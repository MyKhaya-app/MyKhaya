"""Hardened reading of file-backed secrets (MK-SEC-001 SEC-017).

This is the single primitive for reading a secret from a file. It is meant to
be the reader behind the future central secret registry (SEC-093); it is not a
registry itself and knows nothing about which settings exist.

Every protection works on file descriptors, never by checking a path and then
reopening it:

* the path must be absolute, already normalised and strictly inside an
  approved root (``/run/secrets`` by default);
* each directory is opened relative to its parent's descriptor with
  ``O_NOFOLLOW | O_DIRECTORY``, so a symbolic link anywhere in the path,
  including the root itself, is refused;
* the file is opened with ``O_NOFOLLOW | O_NONBLOCK``, so a symlink is refused
  and a FIFO cannot block startup, then validated with ``fstat`` on that same
  descriptor (regular file, size limit) before anything is read;
* at most ``max_bytes + 1`` bytes are ever read, so a file that grows after
  the size check is still refused without an unbounded read.

Errors name only the setting and a failure category. They never include the
path, the contents or any part of a value. Platforms without descriptor-
relative, no-follow opening (Windows) fail closed.
"""

import errno
import os
import posixpath
import stat
from collections.abc import Sequence

APPROVED_SECRET_ROOTS: tuple[str, ...] = ("/run/secrets",)
SINGLE_LINE_MAX_BYTES = 4096


class SecretFileError(ValueError):
    """A secret file was refused. The message is safe to log."""

    def __init__(self, setting: str, category: str) -> None:
        self.setting = setting
        self.category = category
        super().__init__(f"{setting} {category}")


def _required_flags() -> tuple[int, int, int] | None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nofollow is None or directory is None or nonblock is None:
        return None
    if os.open not in os.supports_dir_fd:
        return None
    return int(nofollow), int(directory), int(nonblock)


def _checked_path(setting: str, path_value: str, roots: Sequence[str]) -> list[str]:
    if not path_value or "\x00" in path_value or not path_value.startswith("/"):
        raise SecretFileError(setting, "must be an absolute path")
    if path_value.startswith("//") or posixpath.normpath(path_value) != path_value:
        raise SecretFileError(setting, "must be a normalised path without '.' or '..'")
    for root in roots:
        if path_value.startswith(root.rstrip("/") + "/"):
            break
    else:
        raise SecretFileError(setting, "is outside the approved secret locations")
    parts = path_value.split("/")[1:]
    if not parts or not parts[-1]:
        raise SecretFileError(setting, "must name a file")
    return parts


def _is_symlink(name: str, dir_fd: int) -> bool:
    """Classify a refused component for the error message only; the open has
    already failed, so this never decides whether anything is read."""
    try:
        return stat.S_ISLNK(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _open_error(
    setting: str, exc: OSError, *, final: bool, name: str, dir_fd: int
) -> SecretFileError:
    if exc.errno == errno.ENOENT:
        return SecretFileError(setting, "is missing")
    if exc.errno in (errno.EACCES, errno.EPERM):
        return SecretFileError(setting, "is not readable (permission denied)")
    if exc.errno in (errno.ELOOP, errno.ENOTDIR, getattr(errno, "EMLINK", errno.ELOOP)):
        # Kernels differ on which of these an O_NOFOLLOW symlink produces.
        if exc.errno == errno.ELOOP or _is_symlink(name, dir_fd):
            return SecretFileError(setting, "path contains a symbolic link")
        return SecretFileError(setting, "path contains a non-directory component")
    if final and exc.errno in (errno.ENXIO, errno.EISDIR):
        return SecretFileError(setting, "is not a regular file")
    return SecretFileError(setting, "could not be opened")


def read_secret_file_bytes(
    setting: str,
    path_value: str,
    *,
    max_bytes: int,
    roots: Sequence[str] | None = None,
) -> bytes:
    """Return the raw contents of a secret file, enforcing every path and file check."""
    flags = _required_flags()
    if flags is None:
        raise SecretFileError(setting, "cannot be read safely on this platform")
    nofollow, directory, nonblock = flags
    cloexec = getattr(os, "O_CLOEXEC", 0)
    parts = _checked_path(setting, path_value, APPROVED_SECRET_ROOTS if roots is None else roots)

    dir_fd = os.open("/", os.O_RDONLY | directory | cloexec)
    try:
        for component in parts[:-1]:
            try:
                next_fd = os.open(
                    component, os.O_RDONLY | directory | nofollow | cloexec, dir_fd=dir_fd
                )
            except OSError as exc:
                raise _open_error(
                    setting, exc, final=False, name=component, dir_fd=dir_fd
                ) from None
            os.close(dir_fd)
            dir_fd = next_fd
        try:
            file_fd = os.open(
                parts[-1],
                os.O_RDONLY | nofollow | nonblock | cloexec | getattr(os, "O_NOCTTY", 0),
                dir_fd=dir_fd,
            )
        except OSError as exc:
            raise _open_error(setting, exc, final=True, name=parts[-1], dir_fd=dir_fd) from None
    finally:
        os.close(dir_fd)

    try:
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise SecretFileError(setting, "is not a regular file")
        if info.st_size > max_bytes:
            raise SecretFileError(setting, "is too large")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            try:
                chunk = os.read(file_fd, remaining)
            except OSError:
                raise SecretFileError(setting, "could not be read") from None
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(file_fd)
    data = b"".join(chunks)
    if len(data) > max_bytes:
        raise SecretFileError(setting, "is too large")
    return data


def read_single_line_secret(
    setting: str, path_value: str, *, roots: Sequence[str] | None = None
) -> str:
    """Read a single-line secret (at most 4 KiB) byte for byte.

    Exactly one optional trailing line ending (``\\n`` or ``\\r\\n``) is removed;
    nothing else is changed. Empty values, NUL bytes, invalid UTF-8, embedded
    line breaks and surrounding whitespace are refused.
    """
    data = read_secret_file_bytes(setting, path_value, max_bytes=SINGLE_LINE_MAX_BYTES, roots=roots)
    if b"\x00" in data:
        raise SecretFileError(setting, "contains a NUL byte")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SecretFileError(setting, "is not valid UTF-8") from None
    value = text.removesuffix("\n").removesuffix("\r")
    if "\n" in value or "\r" in value:
        raise SecretFileError(setting, "must contain a single line")
    if not value:
        raise SecretFileError(setting, "is empty")
    if value != value.strip():
        raise SecretFileError(setting, "must not have leading or trailing whitespace")
    return value
