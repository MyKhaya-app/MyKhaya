"""DEV Docker Secrets: role-scoped Apple and keyring loading, the FCM presence
flag and the encrypted-secret check (MK-SEC-001 v1.2).

Every value is synthetic. With no process role, loading is unchanged.
"""

import base64
import json
import os
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr, ValidationError

from mykhaya import secret_files, secrets_crypto
from mykhaya.config import Settings
from mykhaya.crypto.config import load_sensitive_keyrings
from mykhaya.crypto.errors import KeyConfigurationError
from mykhaya.db import SessionFactory
from mykhaya.models import PlatformSmtpSettings
from mykhaya.notifications.push import fcm_indicated
from mykhaya.tools.encrypted_secrets_check import ENCRYPTED_COLUMNS, check_encrypted_secrets

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the hardened reader needs POSIX")

APP_URL = "postgresql+asyncpg://mykhaya_app:synthetic-roles-db-value@postgres:5432/mykhaya"


def _pem() -> str:
    return (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )


def _ring(purpose: str) -> str:
    return json.dumps(
        {
            "format": "mykhaya-keyring-v1",
            "purpose": purpose,
            "environment": "test",
            "active": "t1",
            "keys": {"t1": base64.b64encode(os.urandom(32)).decode()},
        }
    )


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in list(os.environ):
        if name.startswith("MYKHAYA_"):
            monkeypatch.delenv(name)
    directory = tmp_path / "secrets"
    directory.mkdir()
    monkeypatch.setattr(secret_files, "APPROVED_SECRET_ROOTS", (str(directory),))
    return directory


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "secret_key": "synthetic-roles-application-value-0123456789",
        "database_url": APP_URL,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _refused(**overrides: Any) -> str:
    with pytest.raises(ValidationError) as caught:
        _settings(**overrides)
    return str(caught.value)


# --- Apple sign-in key ----------------------------------------------------------


def test_the_api_role_loads_the_apple_key_with_the_hardened_reader(root: Path) -> None:
    pem = _pem()
    path = root / "apple.p8"
    path.write_text(pem)
    settings = _settings(process_role="api", apple_private_key_file=str(path))
    assert settings.apple_private_key is not None
    assert settings.apple_private_key.get_secret_value() == pem.strip()


@pytest.mark.parametrize("kind", ["link", "outside", "missing", "directory", "text"])
def test_the_api_role_refuses_unsafe_apple_key_files(root: Path, tmp_path: Path, kind: str) -> None:
    pem = _pem()
    path = root / "apple.p8"
    if kind == "link":
        (root / "real.p8").write_text(pem)
        path.symlink_to(root / "real.p8")
    elif kind == "outside":
        path = tmp_path / "apple.p8"
        path.write_text(pem)
    elif kind == "directory":
        path.mkdir()
    elif kind == "text":
        path.write_text("prefix\n" + pem)
    text = _refused(process_role="api", apple_private_key_file=str(path))
    assert "MYKHAYA_APPLE_PRIVATE_KEY_FILE" in text
    assert str(path) not in text and "PRIVATE KEY-----" not in text


def test_a_role_without_the_apple_key_never_opens_it(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = root / "apple.p8"
    path.write_text(_pem())

    def opened(*_: object, **__: object) -> str:
        raise AssertionError("the key file was read")

    monkeypatch.setattr("mykhaya.config.read_secret", opened)
    text = _refused(process_role="worker", apple_private_key_file=str(path))
    assert "must not receive MYKHAYA_APPLE_PRIVATE_KEY_FILE (K-10)" in text


def test_without_a_role_the_apple_key_loader_is_unchanged(root: Path, tmp_path: Path) -> None:
    pem = _pem()
    (tmp_path / "real.p8").write_text(pem)
    link = tmp_path / "apple.p8"
    link.symlink_to(tmp_path / "real.p8")
    settings = _settings(apple_private_key_file=str(link))
    assert settings.apple_private_key is not None
    assert settings.apple_private_key.get_secret_value() == pem


# --- Keyrings -------------------------------------------------------------------


def _keyrings(root: Path, **overrides: Any) -> Settings:
    return _settings(
        **{
            "process_role": "api",
            "field_encryption_keys_file": str(root / "field.json"),
            "blind_index_keys_file": str(root / "blind.json"),
            **overrides,
        }
    )


def test_role_keyrings_load_unchanged_and_match_the_legacy_loader(root: Path) -> None:
    (root / "field.json").write_text(_ring("field-encryption"))
    (root / "blind.json").write_text(_ring("blind-index"))
    field, blind, status = load_sensitive_keyrings(_keyrings(root))
    legacy_field, _, _ = load_sensitive_keyrings(_keyrings(root, process_role=None))
    assert field is not None and blind is not None and legacy_field is not None
    assert status.field_source == status.blind_index_source == "file"
    assert field.active_key_id() == legacy_field.active_key_id()
    assert field.shares_material_with(legacy_field)


def test_missing_keyrings_are_still_unprovisioned_unless_required(root: Path) -> None:
    assert load_sensitive_keyrings(_keyrings(root))[:2] == (None, None)
    with pytest.raises(KeyConfigurationError, match="required but none"):
        load_sensitive_keyrings(_keyrings(root, sensitive_field_keys_required=True))


@pytest.mark.parametrize("dangling", [True, False])
def test_a_linked_keyring_is_an_error_not_a_missing_keyring(root: Path, dangling: bool) -> None:
    if not dangling:
        (root / "real.json").write_text(_ring("field-encryption"))
    (root / "field.json").symlink_to(root / "real.json")
    (root / "blind.json").write_text(_ring("blind-index"))
    with pytest.raises(KeyConfigurationError, match="symbolic link"):
        load_sensitive_keyrings(_keyrings(root))


def test_a_keyring_outside_the_approved_locations_is_refused(root: Path, tmp_path: Path) -> None:
    (tmp_path / "field.json").write_text(_ring("field-encryption"))
    with pytest.raises(KeyConfigurationError, match="outside the approved") as caught:
        load_sensitive_keyrings(
            _keyrings(root, field_encryption_keys_file=str(tmp_path / "field.json"))
        )
    assert str(tmp_path) not in str(caught.value)


def test_a_role_still_refuses_file_and_environment_keyrings_together(root: Path) -> None:
    (root / "field.json").write_text(_ring("field-encryption"))
    with pytest.raises(KeyConfigurationError, match="both as a file"):
        load_sensitive_keyrings(
            _keyrings(root, field_encryption_keys=SecretStr(_ring("field-encryption")))
        )


# --- FCM indicator ----------------------------------------------------------------

FCM: dict[str, Any] = {
    "fcm_delivery_configured": True,
    "fcm_project_id": "mykhaya-dev-faf55",
    "fcm_client_email": "synthetic@example.invalid",
}


@pytest.mark.parametrize("role", ["api", "cli"])
@pytest.mark.parametrize("present", [True, False])
def test_the_api_states_fcm_from_the_presence_flag(root: Path, role: str, present: bool) -> None:
    settings = _settings(process_role=role, fcm_private_key_present=present, **FCM)
    assert settings.fcm_private_key is None
    assert fcm_indicated(settings) is present


def test_the_api_role_requires_the_flag_and_refuses_the_key(root: Path) -> None:
    assert "requires MYKHAYA_FCM_PRIVATE_KEY_PRESENT" in _refused(process_role="api", **FCM)
    text = _refused(
        process_role="api",
        fcm_private_key_present=True,
        fcm_private_key="synthetic-fcm-value",
        **FCM,
    )
    assert "must not receive MYKHAYA_FCM_PRIVATE_KEY (K-09)" in text


@pytest.mark.parametrize("role", [None, "worker"])
def test_holders_of_the_key_ignore_the_flag(root: Path, role: str | None) -> None:
    assert not fcm_indicated(_settings(process_role=role, fcm_private_key_present=True, **FCM))
    assert fcm_indicated(_settings(process_role=role, fcm_private_key="synthetic-fcm-value", **FCM))


def test_the_flag_alone_never_claims_fcm_is_configured(root: Path) -> None:
    assert not fcm_indicated(_settings(process_role="api", fcm_private_key_present=True))


# --- Encrypted-secret check ---------------------------------------------------------


async def test_encrypted_secrets_check_counts_readable_and_failed_rows() -> None:
    from mykhaya.config import get_settings

    before = await check_encrypted_secrets()
    async with SessionFactory() as db:
        row = PlatformSmtpSettings(
            encrypted_password=secrets_crypto.encrypt_secret(get_settings(), "synthetic")
        )
        db.add(row)
        await db.commit()
        try:
            good = await check_encrypted_secrets()
            row.encrypted_password = "not-a-valid-ciphertext"  # noqa: S105 — synthetic
            await db.commit()
            bad = await check_encrypted_secrets()
        finally:
            await db.delete(row)
            await db.commit()
    assert good["smtp_password_readable"] == before["smtp_password_readable"] + 1
    assert bad["smtp_password_failed"] == before["smtp_password_failed"] + 1
    assert await check_encrypted_secrets() == before


def test_every_application_key_encrypted_column_is_covered() -> None:
    from mykhaya.models import Base

    covered = {column.key for _, column, _ in ENCRYPTED_COLUMNS}
    found = {
        column.name
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name.startswith("encrypted_") or column.name.endswith("_encrypted")
    }
    assert found == covered
