"""Hardened reading of file-backed secrets (MK-SEC-001 SEC-017).

This is the single primitive for reading a secret from a file, and the reader
behind the central secret registry (SEC-093, mykhaya.secret_registry). It is
not a registry itself and knows nothing about which settings exist; it offers
one bounded reader per declared format (single line, PEM, JSON).

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
import json
import os
import posixpath
import stat
from collections.abc import Callable, Sequence
from typing import Literal

APPROVED_SECRET_ROOTS: tuple[str, ...] = ("/run/secrets",)
SINGLE_LINE_MAX_BYTES = 4096
PEM_MAX_BYTES = 16384
JSON_MAX_BYTES = 65536

SecretFormat = Literal["single_line", "pem", "json"]


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


def _decode_text(setting: str, data: bytes) -> str:
    if b"\x00" in data:
        raise SecretFileError(setting, "contains a NUL byte")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise SecretFileError(setting, "is not valid UTF-8") from None


def read_pem_secret(setting: str, path_value: str, *, roots: Sequence[str] | None = None) -> str:
    """Read exactly one PEM block (at most 16 KiB), such as an APNs or FCM key.

    The file must start with ``-----BEGIN <label>-----`` and end with the
    matching ``-----END <label>-----`` line; only trailing line endings are
    removed. Blank lines, stray whitespace, text around the block (for example
    OpenSSL "Bag Attributes") and a second block are refused. Whether the key
    is the right type for its provider stays with that provider's validation.
    """
    data = read_secret_file_bytes(setting, path_value, max_bytes=PEM_MAX_BYTES, roots=roots)
    text = _decode_text(setting, data).rstrip("\r\n")
    lines = text.replace("\r\n", "\n").split("\n")
    first, last = lines[0], lines[-1]
    if (
        len(lines) < 3
        or not (first.startswith("-----BEGIN ") and first.endswith("-----"))
        or last != "-----END " + first.removeprefix("-----BEGIN ")
        or any(line.startswith("-----") for line in lines[1:-1])
        or any(not line or line != line.strip() for line in lines)
    ):
        raise SecretFileError(setting, "must contain exactly one PEM block")
    return text


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def read_json_secret(setting: str, path_value: str, *, roots: Sequence[str] | None = None) -> str:
    """Read a JSON object document (at most 64 KiB), such as a keyring.

    The text is returned unchanged for its consumer's own parser. It is parsed
    here only to refuse malformed documents, non-object documents and duplicate
    keys; the parsed copy is discarded.
    """
    data = read_secret_file_bytes(setting, path_value, max_bytes=JSON_MAX_BYTES, roots=roots)
    text = _decode_text(setting, data)
    try:
        document = json.loads(text, object_pairs_hook=_unique_object)
    except ValueError:
        raise SecretFileError(setting, "is not a valid JSON document") from None
    if not isinstance(document, dict):
        raise SecretFileError(setting, "must contain a JSON object")
    return text


_READERS: dict[str, Callable[..., str]] = {
    "single_line": read_single_line_secret,
    "pem": read_pem_secret,
    "json": read_json_secret,
}


def read_secret(
    setting: str,
    path_value: str,
    secret_format: SecretFormat,
    *,
    roots: Sequence[str] | None = None,
) -> str:
    """Read a secret file in its declared format (the registry's entry point)."""
    return _READERS[secret_format](setting, path_value, roots=roots)
