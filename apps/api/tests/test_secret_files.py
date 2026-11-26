"""Adversarial tests for mykhaya.secret_files (MK-SEC-001 SEC-017).

All values are synthetic. Race conditions are reproduced deterministically by
intercepting os.open/os.fstat/os.read at the exact point the reader calls
them; thread timeouts are only a safety net so a regression to blocking I/O
fails the test instead of hanging the suite.
"""

import errno
import logging
import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from mykhaya import secret_files
from mykhaya.secret_files import (
    SINGLE_LINE_MAX_BYTES,
    SecretFileError,
    read_secret_file_bytes,
    read_single_line_secret,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the reader fails closed off POSIX")

SETTING = "MYKHAYA_SYNTHETIC_SECRET_FILE"
SYNTHETIC = "synthetic-sec017-value-0123456789abcdefghijkl"
NON_ROOT = hasattr(os, "geteuid") and os.geteuid() != 0


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Stands in for /run/secrets. tmp_path itself contains no symlinks."""
    directory = tmp_path / "run-secrets"
    directory.mkdir()
    return directory


def read(root: Path, path: Path | str) -> str:
    return read_single_line_secret(SETTING, str(path), roots=(str(root),))


def refused(root: Path, path: Path | str) -> SecretFileError:
    with pytest.raises(SecretFileError) as caught:
        read(root, path)
    return caught.value


def write(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def finishes(action: Callable[[], Any], timeout: float = 10.0) -> Any:
    """Run action in a thread; fail (rather than hang) if it blocks."""
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["value"] = action()
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "the reader blocked"
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def opens(path: Path, fd: int) -> bool:
    """True when fd is the reader's descriptor for path (Linux /proc)."""
    try:
        return os.readlink(f"/proc/self/fd/{fd}") == str(path)
    except OSError:
        return False


@pytest.fixture
def intercept(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """Wrap an os function; the hook runs before (or after) the real call.

    Other code in the process (the coverage tracer, for example) calls the
    same os functions, so every hook checks that the call is the reader's.
    """

    def install(name: str, hook: Callable[..., None], *, after: bool = False) -> None:
        real = getattr(os, name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not after:
                hook(*args, **kwargs)
            result = real(*args, **kwargs)
            if after:
                hook(*args, **kwargs)
            return result

        monkeypatch.setattr(os, name, wrapper)
        if name == "open":
            # The reader fails closed unless os.open supports dir_fd.
            monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {wrapper})

    yield install


# 11. A legitimate Docker Compose file secret --------------------------------


@pytest.mark.parametrize("terminator", [b"", b"\n", b"\r\n"])
def test_compose_style_secret_file_loads_byte_for_byte(root: Path, terminator: bytes) -> None:
    secret = write(root / "session_key", SYNTHETIC.encode() + terminator)
    secret.chmod(0o444)
    assert read(root, secret) == SYNTHETIC


def test_nested_directory_under_the_root_is_allowed(root: Path) -> None:
    (root / "mykhaya").mkdir()
    assert (
        read(root, write(root / "mykhaya" / "session_key", SYNTHETIC.encode() + b"\n")) == SYNTHETIC
    )


def test_exactly_the_size_limit_is_accepted(root: Path) -> None:
    value = "k" * SINGLE_LINE_MAX_BYTES
    assert read(root, write(root / "key", value.encode())) == value


# 1. Relative and non-normalised paths -----------------------------------------


@pytest.mark.parametrize("path", ["session_key", "run/secrets/session_key", "./key", ""])
def test_relative_paths_are_refused(root: Path, path: str) -> None:
    assert refused(root, path).category == "must be an absolute path"


@pytest.mark.parametrize("suffix", ["/../escape", "/./key", "//key", "/key/"])
def test_non_normalised_paths_are_refused(root: Path, suffix: str) -> None:
    error = refused(root, f"{root}{suffix}")
    assert error.category == "must be a normalised path without '.' or '..'"


def test_double_slash_prefix_is_refused(root: Path) -> None:
    assert refused(root, "/" + str(root) + "/key").category.startswith("must be a normalised")


def test_nul_byte_in_path_is_refused(root: Path) -> None:
    assert refused(root, f"{root}/key\x00.txt").category == "must be an absolute path"


# 2. Paths outside the approved roots ------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "/app/mykhaya/config.py",
        "/tmp/session_key",  # noqa: S108 — a refused path literal; never opened
        "/run/secretsX/session_key",  # prefix trick
        "/run/session_key",
    ],
)
def test_default_root_refuses_everything_outside_run_secrets(path: str) -> None:
    with pytest.raises(SecretFileError) as caught:
        read_single_line_secret(SETTING, path)
    assert caught.value.category == "is outside the approved secret locations"


def test_the_root_itself_is_not_a_secret_file() -> None:
    with pytest.raises(SecretFileError):
        read_single_line_secret(SETTING, "/run/secrets")


def test_default_roots_are_run_secrets_only() -> None:
    assert secret_files.APPROVED_SECRET_ROOTS == ("/run/secrets",)


# 3. /proc/self/environ and other special files -------------------------------


def test_proc_self_environ_is_refused_by_default() -> None:
    with pytest.raises(SecretFileError) as caught:
        read_single_line_secret(SETTING, "/proc/self/environ")
    assert caught.value.category == "is outside the approved secret locations"


def test_proc_self_is_refused_even_under_an_approved_proc_root() -> None:
    """/proc/self is a symlink, so even a wrongly approved /proc root fails."""
    with pytest.raises(SecretFileError) as caught:
        read_single_line_secret(SETTING, "/proc/self/environ", roots=("/proc",))
    assert caught.value.category == "path contains a symbolic link"


def test_character_device_is_refused_without_blocking() -> None:
    with pytest.raises(SecretFileError) as caught:
        finishes(lambda: read_single_line_secret(SETTING, "/dev/zero", roots=("/dev",)))
    assert caught.value.category == "is not a regular file"


def test_directory_is_not_a_regular_file(root: Path) -> None:
    (root / "directory").mkdir()
    assert refused(root, root / "directory").category == "is not a regular file"


# 4 and 5. Symlinks in the final component and in parent directories ---------


def test_symlinked_final_file_is_refused(root: Path) -> None:
    target = write(root / "real_key", SYNTHETIC.encode())
    (root / "session_key").symlink_to(target)
    assert refused(root, root / "session_key").category == "path contains a symbolic link"


def test_symlink_to_a_file_outside_the_root_is_refused(root: Path, tmp_path: Path) -> None:
    outside = write(tmp_path / "outside_key", SYNTHETIC.encode())
    (root / "session_key").symlink_to(outside)
    assert refused(root, root / "session_key").category == "path contains a symbolic link"


def test_symlinked_parent_directory_is_refused(root: Path) -> None:
    (root / "real").mkdir()
    write(root / "real" / "session_key", SYNTHETIC.encode())
    (root / "linked").symlink_to(root / "real")
    error = refused(root, root / "linked" / "session_key")
    assert error.category == "path contains a symbolic link"


def test_symlinked_root_is_refused(root: Path, tmp_path: Path) -> None:
    write(root / "session_key", SYNTHETIC.encode())
    alias = tmp_path / "alias-root"
    alias.symlink_to(root)
    with pytest.raises(SecretFileError) as caught:
        read_single_line_secret(SETTING, str(alias / "session_key"), roots=(str(alias),))
    assert caught.value.category == "path contains a symbolic link"


def test_file_used_as_a_directory_is_refused(root: Path) -> None:
    write(root / "plain", SYNTHETIC.encode())
    error = refused(root, root / "plain" / "session_key")
    assert error.category == "path contains a non-directory component"


# 6. FIFOs, including a regular file swapped for a FIFO -----------------------


def test_fifo_is_refused_without_blocking(root: Path) -> None:
    os.mkfifo(root / "session_key")
    with pytest.raises(SecretFileError) as caught:
        finishes(lambda: read(root, root / "session_key"))
    assert caught.value.category == "is not a regular file"


def test_regular_file_swapped_for_a_fifo_at_open_is_refused(
    root: Path, intercept: Callable[..., None]
) -> None:
    """The swap happens immediately before the reader opens the file: the
    worst possible moment for a check-then-open implementation."""
    write(root / "session_key", SYNTHETIC.encode())

    def swap(path: Any, *args: Any, **kwargs: Any) -> None:
        if path == "session_key" and "dir_fd" in kwargs:
            os.unlink(path, dir_fd=kwargs["dir_fd"])
            os.mkfifo(path, dir_fd=kwargs["dir_fd"])

    intercept("open", swap)
    with pytest.raises(SecretFileError) as caught:
        finishes(lambda: read(root, root / "session_key"))
    assert caught.value.category == "is not a regular file"


def test_regular_file_swapped_for_a_symlink_at_open_is_refused(
    root: Path, intercept: Callable[..., None], tmp_path: Path
) -> None:
    write(root / "session_key", SYNTHETIC.encode())
    outside = write(tmp_path / "attacker_key", b"synthetic-attacker-controlled-value-0123456789")

    def swap(path: Any, *args: Any, **kwargs: Any) -> None:
        if path == "session_key" and "dir_fd" in kwargs:
            os.unlink(path, dir_fd=kwargs["dir_fd"])
            os.symlink(outside, path, dir_fd=kwargs["dir_fd"])

    intercept("open", swap)
    assert refused(root, root / "session_key").category == "path contains a symbolic link"


def test_parent_directory_swapped_for_a_symlink_mid_walk_is_refused(
    root: Path, intercept: Callable[..., None], tmp_path: Path
) -> None:
    (root / "mykhaya").mkdir()
    write(root / "mykhaya" / "session_key", SYNTHETIC.encode())
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    write(decoy / "session_key", b"synthetic-attacker-controlled-value-0123456789")

    def swap(path: Any, *args: Any, **kwargs: Any) -> None:
        if path == "mykhaya" and "dir_fd" in kwargs:
            os.rename(
                "mykhaya", "mykhaya-moved", src_dir_fd=kwargs["dir_fd"], dst_dir_fd=kwargs["dir_fd"]
            )
            os.symlink(decoy, "mykhaya", dir_fd=kwargs["dir_fd"])

    intercept("open", swap)
    error = refused(root, root / "mykhaya" / "session_key")
    assert error.category == "path contains a symbolic link"


# 7. Oversized files and bounded reads ------------------------------------------


@pytest.fixture
def read_sizes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    sizes: list[int] = []
    real = os.read

    def spy(fd: int, n: int) -> bytes:
        sizes.append(n)
        return real(fd, n)

    monkeypatch.setattr(os, "read", spy)
    return sizes


def test_oversized_file_is_refused_before_any_read(root: Path, read_sizes: list[int]) -> None:
    big = root / "session_key"
    with open(big, "wb") as handle:
        handle.truncate(512 * 1024 * 1024)  # sparse: no disk or memory used
    assert refused(root, big).category == "is too large"
    assert read_sizes == []


def test_one_byte_over_the_limit_is_refused(root: Path) -> None:
    path = write(root / "session_key", b"k" * (SINGLE_LINE_MAX_BYTES + 1))
    assert refused(root, path).category == "is too large"


def test_file_growing_after_the_size_check_is_refused_with_a_bounded_read(
    root: Path, intercept: Callable[..., None], read_sizes: list[int]
) -> None:
    path = write(root / "session_key", SYNTHETIC.encode())

    def grow(fd: int) -> None:
        if opens(path, fd):
            with open(path, "ab") as handle:
                handle.write(b"k" * (64 * 1024))

    intercept("fstat", grow, after=True)
    assert refused(root, path).category == "is too large"
    assert sum(read_sizes) <= SINGLE_LINE_MAX_BYTES + 1
    assert max(read_sizes) <= SINGLE_LINE_MAX_BYTES + 1


def test_reads_never_request_more_than_the_limit_plus_one(
    root: Path, read_sizes: list[int]
) -> None:
    read(root, write(root / "session_key", SYNTHETIC.encode()))
    assert read_sizes and max(read_sizes) <= SINGLE_LINE_MAX_BYTES + 1


# 8. Empty, malformed and invalid-encoding secrets -----------------------------


@pytest.mark.parametrize(
    ("content", "category"),
    [
        (b"", "is empty"),
        (b"\n", "is empty"),
        (b"\r\n", "is empty"),
        (SYNTHETIC.encode() + b"\x00", "contains a NUL byte"),
        (b"\x00" + SYNTHETIC.encode(), "contains a NUL byte"),
        (b"\xff\xfe" + SYNTHETIC.encode(), "is not valid UTF-8"),
        (SYNTHETIC.encode()[:10] + b"\xc3", "is not valid UTF-8"),
        (SYNTHETIC.encode() + b"\n\n", "must contain a single line"),
        (SYNTHETIC.encode() + b"\nsecond-line", "must contain a single line"),
        (SYNTHETIC.encode() + b"\rsecond-line", "must contain a single line"),
        (b" " + SYNTHETIC.encode(), "must not have leading or trailing whitespace"),
        (SYNTHETIC.encode() + b"\t\n", "must not have leading or trailing whitespace"),
    ],
)
def test_malformed_secrets_are_refused(root: Path, content: bytes, category: str) -> None:
    error = refused(root, write(root / "session_key", content))
    assert error.category == category
    assert SYNTHETIC not in str(error) and "second-line" not in str(error)


def test_non_ascii_utf8_secret_is_preserved(root: Path) -> None:
    value = "synthetic-ключ-秘密-0123456789abcdefghijklmnop"
    assert read(root, write(root / "session_key", value.encode() + b"\n")) == value


# 9. Unreadable files and permission failures ----------------------------------


@pytest.mark.skipif(not NON_ROOT, reason="root bypasses file modes")
def test_unreadable_file_is_refused(root: Path) -> None:
    path = write(root / "session_key", SYNTHETIC.encode())
    path.chmod(0)
    try:
        assert refused(root, path).category == "is not readable (permission denied)"
    finally:
        path.chmod(0o600)


@pytest.mark.skipif(not NON_ROOT, reason="root bypasses file modes")
def test_unsearchable_parent_directory_is_refused(root: Path) -> None:
    (root / "locked").mkdir()
    write(root / "locked" / "session_key", SYNTHETIC.encode())
    (root / "locked").chmod(0)
    try:
        error = refused(root, root / "locked" / "session_key")
        assert error.category == "is not readable (permission denied)"
    finally:
        (root / "locked").chmod(0o700)


def test_read_error_after_open_is_refused(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(root / "session_key", SYNTHETIC.encode())

    def failing_read(fd: int, n: int) -> bytes:
        raise OSError(errno.EIO, "synthetic I/O error", str(path))

    monkeypatch.setattr(os, "read", failing_read)
    assert refused(root, path).category == "could not be read"


# 10. Files changing or disappearing during access ----------------------------


def test_file_removed_just_before_open_is_reported_missing(
    root: Path, intercept: Callable[..., None]
) -> None:
    write(root / "session_key", SYNTHETIC.encode())

    def remove(path: Any, *args: Any, **kwargs: Any) -> None:
        if path == "session_key" and "dir_fd" in kwargs:
            os.unlink(path, dir_fd=kwargs["dir_fd"])

    intercept("open", remove)
    assert refused(root, root / "session_key").category == "is missing"


def test_file_removed_after_open_is_read_from_the_open_descriptor(
    root: Path, intercept: Callable[..., None]
) -> None:
    """Proves the reader never reopens the path after validating it."""
    path = write(root / "session_key", SYNTHETIC.encode() + b"\n")

    def remove(fd: int) -> None:
        if opens(path, fd):
            path.unlink()

    intercept("fstat", remove, after=True)
    assert read(root, path) == SYNTHETIC
    assert not path.exists()


def test_file_replaced_after_open_still_yields_the_validated_file(
    root: Path, intercept: Callable[..., None]
) -> None:
    path = write(root / "session_key", SYNTHETIC.encode() + b"\n")
    replacement = write(root / "replacement", b"synthetic-attacker-controlled-value-0123456789")

    def replace(fd: int) -> None:
        if opens(path, fd):
            os.replace(replacement, path)

    intercept("fstat", replace, after=True)
    assert read(root, path) == SYNTHETIC
    # The swap really happened: the path now holds the attacker's file.
    assert path.read_bytes() == b"synthetic-attacker-controlled-value-0123456789"


def test_missing_file_is_refused(root: Path) -> None:
    assert refused(root, root / "absent").category == "is missing"


def test_missing_parent_directory_is_refused(root: Path) -> None:
    assert refused(root, root / "absent" / "session_key").category == "is missing"


# 12. No disclosure through exceptions, logs or representations --------------


def test_errors_name_only_the_setting_and_a_category(
    root: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    leaky = write(root / "session_key", SYNTHETIC.encode() + b"\nsecond-line")
    (root / "linked").symlink_to(leaky)
    cases = [
        root / "session_key",
        root / "linked",
        root / "absent",
        tmp_path / "outside",
        "relative/session_key",
    ]
    for path in cases:
        error = refused(root, path)
        for text in (str(error), repr(error), " ".join(map(str, error.args))):
            assert text.startswith(SETTING) or text.startswith("SecretFileError")
            assert SYNTHETIC not in text and "second-line" not in text
            assert str(root) not in text and str(tmp_path) not in text
        assert error.__cause__ is None
        assert error.__context__ is None or error.__suppress_context__
    assert not any(SYNTHETIC in record.getMessage() for record in caplog.records)
    assert not any(str(root) in record.getMessage() for record in caplog.records)


def test_os_errors_carrying_the_path_are_never_chained(root: Path) -> None:
    error = refused(root, root / "absent")
    assert error.__cause__ is None and error.__suppress_context__


# Platforms without the required protections fail closed --------------------


@pytest.mark.parametrize("flag", ["O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK"])
def test_missing_platform_protection_fails_closed(
    root: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    path = write(root / "session_key", SYNTHETIC.encode())
    monkeypatch.delattr(os, flag)
    assert refused(root, path).category == "cannot be read safely on this platform"


def test_missing_descriptor_relative_open_fails_closed(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(root / "session_key", SYNTHETIC.encode())
    monkeypatch.setattr(os, "supports_dir_fd", set())
    assert refused(root, path).category == "cannot be read safely on this platform"


def test_raw_reader_enforces_the_same_rules(root: Path) -> None:
    path = write(root / "doc.json", b"{}")
    assert read_secret_file_bytes(SETTING, str(path), max_bytes=16, roots=(str(root),)) == b"{}"
    with pytest.raises(SecretFileError):
        read_secret_file_bytes(SETTING, str(path), max_bytes=1, roots=(str(root),))
