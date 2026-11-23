"""MYKHAYA_SECRET_KEY loading, migrator isolation and key continuity (WP-1).

Every value here is synthetic. The known-answer digests were produced by the
code before MYKHAYA_SECRET_KEY_FILE and MigrationSettings existed, so they
prove the session secret's derivations (token hashing, derived tokens and
the HKDF keys that encrypt Control Centre credentials) are unchanged.
"""

import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from mykhaya import secret_files, secrets_crypto
from mykhaya.config import MigrationSettings, Settings
from mykhaya.security import derived_token, hash_secret

API_ROOT = Path(__file__).parents[1]
KEY = "synthetic-wp1-known-answer-key-0123456789abcdef"
ROTATED = "synthetic-wp1-rotated-session-secret-0123456789"
RECORD_ID = uuid.UUID("01234567-89ab-7def-8123-456789abcdef")

# SHA-256 of each output for KEY, recorded from the pre-WP-1 implementation.
KNOWN_ANSWER_DIGESTS = {
    "_HKDF_INFO": "dbffa072b83a751ac57c6334220158dff9a2a9c58420bd3f9092464105e6adca",
    "_HOME_JOIN_CODE_HKDF_INFO": "6008d3e33ac9badfb8c9bb1f197fafb19c523e96d7f3f296fb33d63043093dd2",
    "_STRIPE_HKDF_INFO": "24fbb139a72e14eeeb5d79b9831a73c038f94241a80a6772d0b71f29b35e9210",
    "_USER_MFA_TOTP_HKDF_INFO": "549965b7314677c74e147943db8a393ff8e152b8145ac147532782ff458b68cd",
    "hmac_digest": "f991d7b24b65eacd189900bf609869c7d7b8f5101344a05b064258a51b58f7de",
    "derived_link": "78a101797904bdb3a392acfb5d20add37ca34e3cd290c4a36b2f64298f8b3af4",
}
# Encrypted with KEY by the pre-WP-1 encrypt_secret (plaintext below).
PRE_WP1_CIPHERTEXT = (
    "gAAAAABrBAMANvGdM20A2NH426vibg11n093M4PKP5rOkxIm6a3k5HSviFYRSnA6EnIaDeamFExFaR-"
    "2m2-8X7Ak54_WCeSmHoLwZ9SKXnYAj1T0D29pbS0="
)
PRE_WP1_PLAINTEXT = "synthetic-smtp-password"


def _digest(value: str | bytes) -> str:
    data = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _no_leak(text: str, *values: str) -> None:
    for value in values:
        assert value not in text
        assert value[:12] not in text and value[-12:] not in text
    assert "input_value" not in text


KeyFileWriter = Callable[[bytes], Path]


@pytest.fixture
def key_from_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> KeyFileWriter:
    """Stand tmp_path in for /run/secrets (adversarial reader cases are in
    test_secret_files.py)."""
    monkeypatch.setattr(secret_files, "APPROVED_SECRET_ROOTS", (str(tmp_path),))
    monkeypatch.delenv("MYKHAYA_SECRET_KEY", raising=False)

    def write(content: bytes) -> Path:
        path = tmp_path / "secret_key"
        path.write_bytes(content)
        monkeypatch.setenv("MYKHAYA_SECRET_KEY_FILE", str(path))
        return path

    return write


# --- Existing behaviour is preserved ----------------------------------------


def test_environment_key_still_loads_as_secretstr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", KEY)
    settings = _settings()
    assert isinstance(settings.secret_key, SecretStr)
    assert settings.secret_key.get_secret_value() == KEY
    assert settings.secret_key_file is None


def test_application_settings_still_fail_closed_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY", raising=False)
    monkeypatch.delenv("MYKHAYA_SECRET_KEY_FILE", raising=False)
    with pytest.raises(ValidationError) as caught:
        _settings()
    assert "secret_key" in str(caught.value)


def test_known_answers_are_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", KEY)
    settings = _settings()
    raw = settings.secret_key.get_secret_value()
    hkdf_infos = [name for name in KNOWN_ANSWER_DIGESTS if name.endswith("_HKDF_INFO")]
    # Every HKDF purpose in secrets_crypto must be pinned here.
    assert sorted(hkdf_infos) == sorted(n for n in vars(secrets_crypto) if n.endswith("_HKDF_INFO"))
    for name in hkdf_infos:
        derived = secrets_crypto._derive_fernet_key(settings, getattr(secrets_crypto, name))
        assert _digest(derived) == KNOWN_ANSWER_DIGESTS[name], name
    token_hash = hash_secret("synthetic-token-value", raw)
    assert _digest(token_hash) == KNOWN_ANSWER_DIGESTS["hmac_digest"]
    token = derived_token(RECORD_ID, "invitation", raw)
    assert _digest(token) == KNOWN_ANSWER_DIGESTS["derived_link"]


def test_existing_ciphertext_still_decrypts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", KEY)
    assert secrets_crypto.decrypt_secret(_settings(), PRE_WP1_CIPHERTEXT) == PRE_WP1_PLAINTEXT


def test_model_copy_rotation_applies_the_new_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", KEY)
    original = _settings()
    rotated = original.model_copy(update={"secret_key": SecretStr(ROTATED)})
    assert rotated.secret_key.get_secret_value() == ROTATED
    assert original.secret_key.get_secret_value() == KEY
    with pytest.raises(secrets_crypto.SecretDecryptionError) as caught:
        secrets_crypto.decrypt_secret(rotated, PRE_WP1_CIPHERTEXT)
    _no_leak(str(caught.value), KEY, ROTATED)
    assert secrets_crypto.decrypt_secret(original, PRE_WP1_CIPHERTEXT) == PRE_WP1_PLAINTEXT


# --- MYKHAYA_SECRET_KEY_FILE --------------------------------------------------


@pytest.mark.parametrize("terminator", [b"", b"\n", b"\r\n"])
def test_file_key_is_byte_identical_to_the_environment_key(
    key_from_file: KeyFileWriter, terminator: bytes
) -> None:
    key_from_file(KEY.encode() + terminator)
    settings = _settings()
    assert settings.secret_key.get_secret_value() == KEY
    assert secrets_crypto.decrypt_secret(settings, PRE_WP1_CIPHERTEXT) == PRE_WP1_PLAINTEXT


def test_blank_environment_key_with_a_file_uses_the_file(
    key_from_file: KeyFileWriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_from_file(KEY.encode() + b"\n")
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", "  ")
    assert _settings().secret_key.get_secret_value() == KEY


def test_blank_file_variable_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", KEY)
    monkeypatch.setenv("MYKHAYA_SECRET_KEY_FILE", " ")
    assert _settings().secret_key.get_secret_value() == KEY


def test_both_sources_are_rejected(
    key_from_file: KeyFileWriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_from_file(KEY.encode())
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", ROTATED)
    with pytest.raises(ValidationError) as caught:
        _settings()
    assert "not both" in str(caught.value)
    _no_leak(str(caught.value), KEY, ROTATED)


def test_explicit_secret_key_argument_conflicts_with_a_file(
    key_from_file: KeyFileWriter,
) -> None:
    key_from_file(KEY.encode())
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, secret_key=SecretStr(ROTATED))  # type: ignore[call-arg]
    _no_leak(str(caught.value), KEY, ROTATED)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "is empty"),
        (b"\n", "is empty"),
        (b"too-short\n", "at least 32"),
        (b"changeme-" + b"x" * 40 + b"\n", "placeholder"),
        (KEY.encode() + b"\n\n", "single line"),
        (KEY.encode() + b"\nsecond-line\n", "single line"),
        (b" " + KEY.encode() + b"\n", "whitespace"),
        (KEY.encode() + b" \n", "whitespace"),
        (b"\xff" + KEY.encode(), "UTF-8"),
        (b"k" * (secret_files.SINGLE_LINE_MAX_BYTES + 1), "too large"),
    ],
)
def test_malformed_files_fail_closed_without_echoing_contents(
    key_from_file: KeyFileWriter, content: bytes, message: str
) -> None:
    key_from_file(content)
    with pytest.raises(ValidationError) as caught:
        _settings()
    text = str(caught.value)
    assert message in text
    _no_leak(text, KEY)
    assert "second-line" not in text and "changeme-xxxx" not in text


def test_settings_refuse_a_key_file_outside_run_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No root override: the production default (/run/secrets) applies."""
    path = tmp_path / "secret_key"
    path.write_bytes(KEY.encode() + b"\n")
    monkeypatch.delenv("MYKHAYA_SECRET_KEY", raising=False)
    monkeypatch.setenv("MYKHAYA_SECRET_KEY_FILE", str(path))
    with pytest.raises(ValidationError) as caught:
        _settings()
    text = str(caught.value)
    assert "MYKHAYA_SECRET_KEY_FILE is outside the approved secret locations" in text
    assert str(path) not in text
    _no_leak(text, KEY)


def test_settings_refuse_a_symlinked_key_file(
    key_from_file: KeyFileWriter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = key_from_file(KEY.encode() + b"\n")
    link = tmp_path / "linked_key"
    link.symlink_to(target)
    monkeypatch.setenv("MYKHAYA_SECRET_KEY_FILE", str(link))
    with pytest.raises(ValidationError, match="symbolic link"):
        _settings()


# --- No sensitive values in errors or representations ------------------------


def test_model_level_validation_errors_never_echo_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Before WP-1 a failing model validator printed the raw input (input_value)
    into the startup error; depending on its position in the truncated input,
    part of secret_key could appear. Any model-level failure will do."""
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", KEY)
    monkeypatch.setenv("MYKHAYA_APPLE_PRIVATE_KEY", "synthetic-apple-key")
    monkeypatch.setenv("MYKHAYA_APPLE_PRIVATE_KEY_FILE", "/nonexistent/synthetic.p8")
    with pytest.raises(ValidationError) as caught:
        _settings()
    assert "must not both" in str(caught.value)
    _no_leak(str(caught.value), KEY, "synthetic-apple-key")


def test_short_environment_key_error_does_not_echo_it(monkeypatch: pytest.MonkeyPatch) -> None:
    short = "synthetic-short-value"
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", short)
    with pytest.raises(ValidationError) as caught:
        _settings()
    assert short not in str(caught.value)


def test_representations_mask_the_key(key_from_file: KeyFileWriter) -> None:
    key_from_file(KEY.encode() + b"\n")
    settings = _settings()
    for text in (repr(settings), str(settings), settings.model_dump_json()):
        assert KEY not in text


# --- Migrator isolation -------------------------------------------------------


def test_migration_settings_never_hold_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", KEY)
    settings = MigrationSettings(_env_file=None)  # type: ignore[call-arg]
    assert set(MigrationSettings.model_fields) == {"environment", "database_url"}
    assert not hasattr(settings, "secret_key")
    assert KEY not in repr(settings) and KEY not in settings.model_dump_json()


def _keyless_environment() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("MYKHAYA_SECRET_KEY")}


_KEYLESS_ALEMBIC = """
import os, sys
assert not any(k.startswith("MYKHAYA_SECRET_KEY") for k in os.environ)
from alembic import command
from alembic.config import Config
cfg = Config()
cfg.set_main_option("script_location", "migrations")
command.stamp(cfg, "head", sql=True)  # runs migrations/env.py, offline
import mykhaya.config
assert "mykhaya.db" not in sys.modules, "env.py imported the engine module"
assert mykhaya.config.get_settings.cache_info().currsize == 0, "env.py built Settings"
print("KEYLESS-ALEMBIC-OK")
"""


def test_alembic_environment_runs_without_the_secret_key() -> None:
    # Fixed argv: this interpreter and a constant script, no external input.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _KEYLESS_ALEMBIC],
        cwd=API_ROOT,
        env=_keyless_environment(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "KEYLESS-ALEMBIC-OK" in result.stdout
    assert "alembic_version" in result.stdout


def test_application_settings_still_refuse_the_keyless_environment() -> None:
    """Guards the test above: the subprocess environment really has no key."""
    result = subprocess.run(  # noqa: S603 — fixed argv, as above
        [sys.executable, "-c", "from mykhaya.config import Settings; Settings(_env_file=None)"],
        cwd=API_ROOT,
        env=_keyless_environment(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0
    assert "secret_key" in result.stderr
