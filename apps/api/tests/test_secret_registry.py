"""Central secret registry and file-backed database credentials (WP-3).

Covers MK-SEC-001 v1.2 SEC-093 (one declarative registry for file-backed
secrets), its use of the SEC-017 hardened reader, and SEC-086/086a (database
password from a file, attached to SQLAlchemy's URL object in-process). Every
value is synthetic. Adversarial reader cases (races, FIFOs, devices, bounded
reads) are in test_secret_files.py; the §6.3 matrix is in test_process_roles.py.
"""

import ast
import json
import logging
import os
import re
import subprocess
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any, Union, get_args, get_origin

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import make_url

from mykhaya import process_roles, secret_files, secret_registry
from mykhaya.config import MigrationSettings, Settings
from mykhaya.db_credentials import connection_url, redacted_database_url
from mykhaya.process_roles import CREDENTIALS, PRESENCE_FLAGS, ROLE_GRANTS
from mykhaya.secret_files import SecretFileError
from mykhaya.secret_registry import (
    MIGRATION_SECRET_REGISTRY,
    SECRET_REGISTRY,
    SecretSpec,
    registry_spec,
    resolve_secret_files,
)

API_ROOT = Path(__file__).parents[1]
APP_VALUE = "synthetic-wp3-application-value-0123456789abcdef"
SPECIAL_PASSWORD = "synthetic p@ss:w/rd%20?#&=+;'\"\\ é-ü-✓"
APP_URL_NO_PASSWORD = "postgresql+asyncpg://mykhaya_app@postgres:5432/mykhaya"
MIGRATOR_URL_NO_PASSWORD = "postgresql+asyncpg://mykhaya_migrator@postgres:5432/mykhaya"
APP_URL_WITH_PASSWORD = "postgresql+asyncpg://mykhaya_app:synthetic-url-pass@postgres:5432/mykhaya"

REGISTRY_LOADED = tuple(spec for spec in SECRET_REGISTRY if spec.loader == "registry")
COMPAT_LOADED = tuple(spec for spec in SECRET_REGISTRY if spec.loader != "registry")

# The Phase 1 file-backed credentials MK-SEC-001 lists for this work package.
PHASE_1_FILE_SETTINGS = {
    "MYKHAYA_SECRET_KEY_FILE",
    "MYKHAYA_DATABASE_PASSWORD_FILE",
    "MYKHAYA_SMTP_PASSWORD_FILE",
    "MYKHAYA_VAPID_PRIVATE_KEY_FILE",
    "MYKHAYA_APNS_PRIVATE_KEY_FILE",
    "MYKHAYA_FCM_PRIVATE_KEY_FILE",
    "MYKHAYA_GOOGLE_CLIENT_SECRET_FILE",
    "MYKHAYA_STRIPE_SECRET_KEY_FILE",
    "MYKHAYA_STRIPE_WEBHOOK_SECRET_FILE",
    "MYKHAYA_DVLA_UAT_API_KEY_FILE",
    "MYKHAYA_DVLA_PRODUCTION_API_KEY_FILE",
    "MYKHAYA_DVSA_CLIENT_ID_FILE",
    "MYKHAYA_DVSA_CLIENT_SECRET_FILE",
    "MYKHAYA_DVSA_API_KEY_FILE",
    "MYKHAYA_MONITORING_WATCHDOG_URL_FILE",
}


def _pem(kind: str = "ec") -> str:
    key: Any = (
        ec.generate_private_key(ec.SECP256R1())
        if kind == "ec"
        else rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    return str(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
    )


EC_PEM = _pem("ec")
RSA_PEM = _pem("rsa")
SYNTHETIC: dict[str, str] = {
    "secret_key": APP_VALUE,
    "database_password": SPECIAL_PASSWORD,
    "smtp_password": "synthetic-smtp-value-wp3-0601",
    "vapid_private_key": "synthetic-vapid-value-wp3-0701",
    "apns_private_key": EC_PEM.rstrip("\n"),
    "fcm_private_key": RSA_PEM.rstrip("\n"),
    "google_client_secret": "synthetic-google-value-wp3-1101",
    "stripe_secret_key": "sk_" + "test_synthetic_wp3_1201",  # no literal for scanners
    "stripe_webhook_secret": "whsec_" + "synthetic_wp3_1301",
    "dvla_uat_api_key": "synthetic-dvla-uat-value-wp3-1401",
    "dvla_production_api_key": "synthetic-dvla-prod-value-wp3-1501",
    "dvsa_client_id": "synthetic-dvsa-client-id-wp3-1601",
    "dvsa_client_secret": "synthetic-dvsa-client-secret-wp3-1602",
    "dvsa_api_key": "synthetic-dvsa-value-wp3-1603",
    "monitoring_watchdog_url": "https://watchdog.example.invalid/synthetic-wp3-1701",
}


def _credential_shaped(name: str) -> bool:
    known = {n for spec in CREDENTIALS.values() for n in spec.env}
    return (
        name in known
        or name in PRESENCE_FLAGS
        or name == process_roles.DATABASE_PASSWORD_ENV
        or (name.startswith("MYKHAYA_") and name.endswith(("_FILE", "_PASSWORD", "_SECRET")))
    )


@pytest.fixture
def root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A clean credential environment, with tmp_path standing in for
    /run/secrets (the reader's only approved root)."""
    for name in list(os.environ):
        if _credential_shaped(name) or name in ("MYKHAYA_PROCESS_ROLE", "MYKHAYA_DATABASE_URL"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", APP_VALUE)
    secrets_root = tmp_path / "secrets"
    secrets_root.mkdir()
    monkeypatch.setattr(secret_files, "APPROVED_SECRET_ROOTS", (str(secrets_root),))
    return secrets_root


Writer = Callable[[SecretSpec, str | bytes], Path]


@pytest.fixture
def put(root: Path, monkeypatch: pytest.MonkeyPatch) -> Writer:
    """Write a secret file and point the entry's *_FILE variable at it."""

    def write(spec: SecretSpec, content: str | bytes) -> Path:
        path = root / spec.file_setting
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        if spec.setting == "secret_key":
            monkeypatch.delenv("MYKHAYA_SECRET_KEY", raising=False)
        if spec.setting == "database_password":
            monkeypatch.setenv("MYKHAYA_DATABASE_URL", APP_URL_NO_PASSWORD)
        monkeypatch.setenv(spec.file_env, str(path))
        return path

    return write


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _refused() -> str:
    with pytest.raises(ValidationError) as caught:
        _settings()
    return str(caught.value)


def _file_content(spec: SecretSpec) -> str:
    return SYNTHETIC[spec.setting] + "\n"


def _no_values(text: str, *extra: str) -> None:
    for value in (*SYNTHETIC.values(), *extra):
        assert value not in text
    for fragment in ("BEGIN PRIVATE", "synthetic-url-pass", "p@ss:w"):
        assert fragment not in text
    assert "input_value" not in text


def _annotation_args(annotation: Any) -> tuple[Any, ...]:
    if get_origin(annotation) in (Union, types.UnionType):
        return get_args(annotation)
    return (annotation,)


# --- The registry itself -------------------------------------------------------


def test_registry_covers_every_phase_1_file_backed_credential() -> None:
    registry_files = {spec.file_env for spec in REGISTRY_LOADED}
    assert registry_files == PHASE_1_FILE_SETTINGS


def test_registry_entries_are_unique() -> None:
    for registry in (SECRET_REGISTRY, MIGRATION_SECRET_REGISTRY):
        assert len({spec.setting for spec in registry}) == len(registry)
        assert len({spec.file_setting for spec in registry}) == len(registry)


def test_apple_key_and_keyrings_are_declared_with_their_compatibility_loaders() -> None:
    assert {(s.setting, s.credential, s.format, s.loader) for s in COMPAT_LOADED} == {
        ("apple_private_key", "K-10", "pem", "apple_compat"),
        ("field_encryption_keys", "K-18", "json", "keyring_compat"),
        ("blind_index_keys", "K-19", "json", "keyring_compat"),
    }


@pytest.mark.parametrize("spec", SECRET_REGISTRY, ids=lambda s: s.setting)
def test_every_entry_fills_a_secretstr_field_from_a_declared_file_field(spec: SecretSpec) -> None:
    fields = Settings.model_fields
    assert spec.setting in fields and spec.file_setting in fields
    assert SecretStr in _annotation_args(fields[spec.setting].annotation)
    assert str in _annotation_args(fields[spec.file_setting].annotation)
    assert spec.file_setting == f"{spec.setting}_file"
    assert spec.file_env == f"MYKHAYA_{spec.setting.upper()}_FILE"


@pytest.mark.parametrize("spec", SECRET_REGISTRY, ids=lambda s: s.setting)
def test_only_the_session_secret_is_required_and_nothing_has_a_fallback_value(
    spec: SecretSpec,
) -> None:
    field = Settings.model_fields[spec.setting]
    if spec.required:
        assert spec.setting == "secret_key" and field.is_required()
    else:
        assert field.default is None, "an optional secret must never fall back to a value"
    if spec.loader == "registry":
        assert Settings.model_fields[spec.file_setting].default is None


@pytest.mark.parametrize("spec", (*SECRET_REGISTRY, *MIGRATION_SECRET_REGISTRY))
def test_every_entry_matches_the_section_6_3_credential_policy(spec: SecretSpec) -> None:
    credential = CREDENTIALS[spec.credential]
    if spec.setting == "database_password":
        # One variable, two identities: checked through the URL's user.
        assert spec.file_env == process_roles.DATABASE_PASSWORD_ENV
        assert spec.credential == ("K-03" if spec in MIGRATION_SECRET_REGISTRY else "K-02")
        return
    assert spec.setting in credential.fields
    assert spec.env in credential.env
    assert spec.file_env in credential.env, "the migrate role must refuse the *_FILE variable"


def test_authorised_roles_come_from_the_section_6_3_grants() -> None:
    expected = {
        "secret_key": {"api", "worker", "scheduler", "cli", "test"},
        "database_password": {"api", "worker", "scheduler", "cli", "test"},
        "smtp_password": {"api", "worker", "scheduler", "cli", "test"},
        "vapid_private_key": {"api", "worker", "cli", "test"},
        "apns_private_key": {"worker", "test"},
        "fcm_private_key": {"worker", "test"},
        "apple_private_key": {"api", "cli", "test"},
        "google_client_secret": {"api", "cli", "test"},
        "stripe_secret_key": {"api", "scheduler", "cli", "test"},
        "stripe_webhook_secret": {"api", "cli", "test"},
        "dvla_uat_api_key": {"api", "cli", "test"},
        "dvla_production_api_key": {"api", "cli", "test"},
        "dvsa_client_id": {"api", "cli", "test"},
        "dvsa_client_secret": {"api", "cli", "test"},
        "dvsa_api_key": {"api", "cli", "test"},
        "monitoring_watchdog_url": {"scheduler", "test"},
        "field_encryption_keys": {"api", "worker", "scheduler", "cli", "test"},
        "blind_index_keys": {"api", "worker", "scheduler", "cli", "test"},
    }
    assert {s.setting: set(s.authorised_roles) for s in SECRET_REGISTRY} == expected
    assert MIGRATION_SECRET_REGISTRY[0].authorised_roles == ("migrate", "test")
    assert set(ROLE_GRANTS) | {"test"} == set(process_roles.PROCESS_ROLES)


def test_registry_lookup_by_setting() -> None:
    assert registry_spec("stripe_secret_key").credential == "K-12"
    with pytest.raises(KeyError):
        registry_spec("redis_url")


# --- Static guards: nothing bypasses the registry ------------------------------


def test_every_secretstr_setting_is_declared_in_the_registry() -> None:
    declared = {spec.setting for spec in SECRET_REGISTRY}
    secret_fields = {
        name
        for name, field in Settings.model_fields.items()
        if SecretStr in _annotation_args(field.annotation)
    }
    assert secret_fields == declared, "declare new secrets in mykhaya.secret_registry"
    migration_secret_fields = {
        name
        for name, field in MigrationSettings.model_fields.items()
        if SecretStr in _annotation_args(field.annotation)
    }
    assert migration_secret_fields == {s.setting for s in MIGRATION_SECRET_REGISTRY}


def test_every_file_setting_is_declared_in_the_registry() -> None:
    declared = {spec.file_setting for spec in SECRET_REGISTRY}
    file_fields = {name for name in Settings.model_fields if name.endswith("_file")}
    assert file_fields == declared
    migration_file_fields = {n for n in MigrationSettings.model_fields if n.endswith("_file")}
    assert migration_file_fields == {s.file_setting for s in MIGRATION_SECRET_REGISTRY}


def test_credential_shaped_settings_are_secret_typed() -> None:
    """A credential added as a plain str would bypass masking and the registry.
    (OAuth client IDs other than DVSA's are public identifiers, not credentials.)"""
    shaped = re.compile(r"(password|secret|private_key|api_key|watchdog_url|^dvsa_client_id)$")
    for name, field in Settings.model_fields.items():
        if shaped.search(name):
            assert SecretStr in _annotation_args(field.annotation), name


def test_settings_never_use_pydantic_secrets_dir() -> None:
    for model in (Settings, MigrationSettings):
        assert model.model_config.get("secrets_dir") is None


def _attribute_reads(path: Path, names: set[str]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        f"{path.relative_to(API_ROOT)}:{node.lineno}:{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in names
    ]


def test_only_the_registry_and_compatibility_loaders_read_secret_file_settings() -> None:
    """A registry file is read only by resolve_secret_files (generic, by name).
    The Apple key and keyrings keep their established loaders (WP-3 scope)."""
    file_settings = {spec.file_setting for spec in SECRET_REGISTRY}
    allowed = {
        "mykhaya/config.py": {"apple_private_key_file"},
        "mykhaya/crypto/config.py": {"field_encryption_keys_file", "blind_index_keys_file"},
    }
    found: list[str] = []
    for path in sorted((API_ROOT / "mykhaya").rglob("*.py")):
        relative = path.relative_to(API_ROOT).as_posix()
        for hit in _attribute_reads(path, file_settings):
            if hit.rsplit(":", 1)[1] not in allowed.get(relative, set()):
                found.append(hit)
    assert found == []


def test_only_the_hardened_reader_opens_files_by_descriptor() -> None:
    offenders = [
        path.relative_to(API_ROOT).as_posix()
        for path in (API_ROOT / "mykhaya").rglob("*.py")
        if "os.open(" in path.read_text(encoding="utf-8") and path.name != "secret_files.py"
    ]
    assert offenders == []


# --- Loading each entry from its file ------------------------------------------


@pytest.mark.parametrize("spec", REGISTRY_LOADED, ids=lambda s: s.setting)
def test_each_entry_loads_from_its_file(spec: SecretSpec, put: Writer) -> None:
    put(spec, _file_content(spec))
    settings = _settings()
    value = getattr(settings, spec.setting)
    assert isinstance(value, SecretStr)
    assert value.get_secret_value() == SYNTHETIC[spec.setting]
    assert getattr(settings, spec.file_setting) is not None


@pytest.mark.parametrize("spec", REGISTRY_LOADED, ids=lambda s: s.setting)
def test_each_entry_refuses_a_literal_and_a_file_together(
    spec: SecretSpec, put: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(spec, _file_content(spec))
    monkeypatch.setenv(spec.env, "synthetic-literal-value-wp3-conflict-0000000000")
    text = _refused()
    if spec.literal_allowed:
        assert f"Set {spec.env} or {spec.file_env}, not both" in text
    else:
        assert f"{spec.env} is not supported; use {spec.file_env}" in text
    _no_values(text, "synthetic-literal-value-wp3-conflict")


@pytest.mark.parametrize("spec", REGISTRY_LOADED, ids=lambda s: s.setting)
def test_each_entry_fails_closed_on_a_missing_file(
    spec: SecretSpec, put: Writer, root: Path
) -> None:
    put(spec, _file_content(spec)).unlink()
    text = _refused()
    assert f"{spec.file_env} is missing" in text
    _no_values(text, str(root))


@pytest.mark.parametrize("spec", REGISTRY_LOADED, ids=lambda s: s.setting)
def test_each_entry_refuses_a_file_outside_the_approved_root(
    spec: SecretSpec, monkeypatch: pytest.MonkeyPatch, root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.write_text(_file_content(spec))
    monkeypatch.setenv("MYKHAYA_DATABASE_URL", APP_URL_NO_PASSWORD)
    if spec.setting == "secret_key":
        monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    monkeypatch.setenv(spec.file_env, str(outside))
    text = _refused()
    assert f"{spec.file_env} is outside the approved secret locations" in text
    _no_values(text, str(outside))


@pytest.mark.parametrize("spec", REGISTRY_LOADED, ids=lambda s: s.setting)
def test_each_entry_refuses_a_symlink(
    spec: SecretSpec, put: Writer, monkeypatch: pytest.MonkeyPatch, root: Path
) -> None:
    target = put(spec, _file_content(spec))
    link = root / f"{spec.file_setting}.link"
    link.symlink_to(target)
    monkeypatch.setenv(spec.file_env, str(link))
    text = _refused()
    assert f"{spec.file_env} path contains a symbolic link" in text


@pytest.mark.parametrize("spec", REGISTRY_LOADED, ids=lambda s: s.setting)
@pytest.mark.parametrize(
    ("content", "category"),
    [
        (b"synthetic\x00value", "contains a NUL byte"),
        (b"synthetic-\xff\xfe-value", "is not valid UTF-8"),
    ],
    ids=["nul", "invalid-utf8"],
)
def test_each_entry_refuses_malformed_content(
    spec: SecretSpec, put: Writer, content: bytes, category: str
) -> None:
    put(spec, content)
    text = _refused()
    assert f"{spec.file_env} {category}" in text
    _no_values(text, "synthetic\x00value")


@pytest.mark.parametrize("spec", REGISTRY_LOADED, ids=lambda s: s.setting)
def test_each_entry_refuses_an_empty_file(spec: SecretSpec, put: Writer) -> None:
    put(spec, b"\n")
    expected = "is empty" if spec.format == "single_line" else "must contain exactly one PEM block"
    assert f"{spec.file_env} {expected}" in _refused()


@pytest.mark.parametrize(
    "spec", [s for s in REGISTRY_LOADED if s.format == "single_line"], ids=lambda s: s.setting
)
def test_single_line_entries_refuse_embedded_line_breaks(spec: SecretSpec, put: Writer) -> None:
    put(spec, "synthetic-first-line\nsynthetic-second-line\n")
    text = _refused()
    assert f"{spec.file_env} must contain a single line" in text
    assert "synthetic-first-line" not in text and "synthetic-second-line" not in text


@pytest.mark.parametrize("spec", REGISTRY_LOADED, ids=lambda s: s.setting)
def test_each_entry_bounds_its_read(
    spec: SecretSpec, put: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit = {
        "single_line": secret_files.SINGLE_LINE_MAX_BYTES,
        "pem": secret_files.PEM_MAX_BYTES,
        "json": secret_files.JSON_MAX_BYTES,
    }[spec.format]
    requested: list[int] = []
    real_read = os.read

    def spy(fd: int, n: int) -> bytes:
        requested.append(n)
        return real_read(fd, n)

    put(spec, b"a" * (limit + 1))
    monkeypatch.setattr(secret_files.os, "read", spy)
    text = _refused()
    assert f"{spec.file_env} is too large" in text
    assert requested == [], "an oversized file is refused before anything is read"


def test_blank_file_variables_mean_unset(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for spec in REGISTRY_LOADED:
        monkeypatch.setenv(spec.file_env, "  ")
    settings = _settings()
    assert settings.secret_key.get_secret_value() == APP_VALUE
    assert settings.smtp_password is None and settings.database_password is None


def test_a_role_never_reads_a_credential_it_is_not_granted(
    put: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(registry_spec("apns_private_key"), EC_PEM)
    monkeypatch.setenv("MYKHAYA_PROCESS_ROLE", "api")

    def must_not_read(*_: object, **__: object) -> str:
        raise AssertionError("a forbidden secret file was read")

    monkeypatch.setattr(secret_registry, "read_secret", must_not_read)
    text = _refused()
    assert "MYKHAYA_PROCESS_ROLE=api: must not receive MYKHAYA_APNS_PRIVATE_KEY_FILE (K-08)" in text


@pytest.mark.parametrize(
    ("role", "setting", "granted"),
    [
        ("worker", "apns_private_key", True),
        ("api", "apns_private_key", False),
        ("worker", "fcm_private_key", True),
        ("api", "fcm_private_key", False),
        ("scheduler", "monitoring_watchdog_url", True),
        ("api", "monitoring_watchdog_url", False),
        ("api", "stripe_webhook_secret", True),
        ("scheduler", "stripe_webhook_secret", False),
        ("worker", "stripe_secret_key", False),
        ("api", "dvsa_client_secret", True),
        ("worker", "dvla_production_api_key", False),
        ("cli", "google_client_secret", True),
        ("worker", "google_client_secret", False),
        ("test", "apns_private_key", True),
    ],
)
def test_role_policy_applies_to_file_backed_credentials(
    role: str, setting: str, granted: bool, put: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = registry_spec(setting)
    put(spec, _file_content(spec))
    if role == "test":
        monkeypatch.setenv("MYKHAYA_ENVIRONMENT", "test")
    else:
        monkeypatch.setenv("MYKHAYA_DATABASE_URL", APP_URL_WITH_PASSWORD)
    monkeypatch.setenv("MYKHAYA_PROCESS_ROLE", role)
    if granted:
        assert getattr(_settings(), setting).get_secret_value() == SYNTHETIC[setting]
    else:
        text = _refused()
        assert f"must not receive {spec.file_env} ({spec.credential})" in text
        _no_values(text)


def test_settings_under_the_migrate_role_never_read_the_session_secret_file(
    put: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(registry_spec("secret_key"), APP_VALUE)
    monkeypatch.setenv("MYKHAYA_PROCESS_ROLE", "migrate")
    text = _refused()
    assert "must not receive MYKHAYA_SECRET_KEY_FILE (K-01)" in text


# --- Formats ----------------------------------------------------------------------


@pytest.mark.parametrize("pem", [EC_PEM, RSA_PEM, EC_PEM.replace("\n", "\r\n")])
def test_pem_files_load_with_unix_or_windows_line_endings(root: Path, pem: str) -> None:
    path = root / "key.pem"
    path.write_bytes(pem.encode())
    value = secret_files.read_pem_secret("MYKHAYA_APNS_PRIVATE_KEY_FILE", str(path))
    assert value == pem.rstrip("\r\n")
    serialization.load_pem_private_key(value.encode(), password=None)


@pytest.mark.parametrize(
    "content",
    [
        "Bag Attributes\n" + EC_PEM,
        EC_PEM + EC_PEM,
        EC_PEM.replace("-----END PRIVATE KEY-----", "-----END EC PRIVATE KEY-----"),
        EC_PEM.replace("\n", "\n\n", 1),
        " " + EC_PEM,
        # An empty block, built in pieces so scanners see no key literal.
        "-----BEGIN " + "PRIVATE KEY-----\n" + "-----END " + "PRIVATE KEY-----\n",
        "not a pem key\n",
    ],
    ids=["leading-text", "two-blocks", "mismatched-end", "blank-line", "indent", "empty", "text"],
)
def test_malformed_pem_files_are_refused(root: Path, content: str) -> None:
    path = root / "key.pem"
    path.write_text(content)
    with pytest.raises(SecretFileError) as caught:
        secret_files.read_pem_secret("MYKHAYA_FCM_PRIVATE_KEY_FILE", str(path))
    assert str(caught.value) == "MYKHAYA_FCM_PRIVATE_KEY_FILE must contain exactly one PEM block"


def test_file_backed_fcm_key_has_the_shape_the_production_check_expects(put: Writer) -> None:
    """The production PKCS#8 check (unchanged) sees a file-backed key exactly
    as it sees the environment form."""
    put(registry_spec("fcm_private_key"), RSA_PEM)
    settings = _settings()
    assert settings.fcm_private_key is not None
    pem = settings.fcm_private_key.get_secret_value()
    assert pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert pem.endswith("-----END PRIVATE KEY-----")


def test_json_documents_load_unchanged(root: Path) -> None:
    document = json.dumps({"environment": "test", "keys": [{"id": "synthetic"}]}, indent=2)
    path = root / "keys.json"
    path.write_text(document + "\n")
    value = secret_files.read_json_secret("MYKHAYA_FIELD_ENCRYPTION_KEYS_FILE", str(path))
    assert value == document + "\n"


@pytest.mark.parametrize(
    ("content", "category"),
    [
        ('{"a": 1,', "is not a valid JSON document"),
        ('["not", "an", "object"]', "must contain a JSON object"),
        ('{"a": 1, "a": 2}', "is not a valid JSON document"),
        ("", "is not a valid JSON document"),
    ],
    ids=["truncated", "array", "duplicate-key", "empty"],
)
def test_malformed_json_documents_are_refused(root: Path, content: str, category: str) -> None:
    path = root / "keys.json"
    path.write_text(content)
    with pytest.raises(SecretFileError) as caught:
        secret_files.read_json_secret("MYKHAYA_BLIND_INDEX_KEYS_FILE", str(path))
    assert str(caught.value) == f"MYKHAYA_BLIND_INDEX_KEYS_FILE {category}"


def test_json_reads_are_bounded(root: Path) -> None:
    path = root / "keys.json"
    path.write_text('{"a": "' + "x" * secret_files.JSON_MAX_BYTES + '"}')
    with pytest.raises(SecretFileError, match="is too large"):
        secret_files.read_json_secret("MYKHAYA_BLIND_INDEX_KEYS_FILE", str(path))


def test_the_format_dispatcher_uses_the_declared_reader(root: Path) -> None:
    path = root / "value"
    path.write_text("synthetic-dispatch-value\n")
    assert secret_files.read_secret("X_FILE", str(path), "single_line") == (
        "synthetic-dispatch-value"
    )
    with pytest.raises(SecretFileError, match="must contain exactly one PEM block"):
        secret_files.read_secret("X_FILE", str(path), "pem")
    with pytest.raises(SecretFileError, match="is not a valid JSON document"):
        secret_files.read_secret("X_FILE", str(path), "json")


# --- Legacy compatibility ---------------------------------------------------------


def test_nothing_changes_when_no_file_setting_is_configured(root: Path) -> None:
    data = {spec.setting: SYNTHETIC.get(spec.setting) for spec in REGISTRY_LOADED}
    data.pop("database_password")
    assert resolve_secret_files(data, SECRET_REGISTRY) is data


@pytest.mark.parametrize(
    "spec", [s for s in REGISTRY_LOADED if s.literal_allowed], ids=lambda s: s.setting
)
def test_environment_values_still_load_as_before(
    spec: SecretSpec, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(spec.env, SYNTHETIC[spec.setting])
    value = getattr(_settings(), spec.setting)
    assert value.get_secret_value() == SYNTHETIC[spec.setting]
    assert getattr(_settings(), spec.file_setting) is None


def test_apple_key_file_keeps_its_established_loader(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP-3 does not tighten the Apple key's path rules (deployed layout not yet
    confirmed): a path outside the hardened reader's root still loads as before."""
    outside = tmp_path / "apple-sign-in.p8"
    outside.write_text(EC_PEM)
    monkeypatch.setenv("MYKHAYA_APPLE_PRIVATE_KEY_FILE", str(outside))
    settings = _settings()
    assert settings.apple_private_key is not None
    assert settings.apple_private_key.get_secret_value() == EC_PEM


def test_keyring_files_keep_their_established_loader(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The registry resolver never touches the keyring file settings, which keep
    mykhaya.crypto.config's "missing default file means not provisioned" rule."""
    outside = tmp_path / "field-keys.json"
    monkeypatch.setenv("MYKHAYA_FIELD_ENCRYPTION_KEYS_FILE", str(outside))
    settings = _settings()
    assert settings.field_encryption_keys_file == str(outside)
    assert settings.field_encryption_keys is None


def test_session_secret_from_a_file_keeps_its_existing_checks(
    put: Writer,
) -> None:
    put(registry_spec("secret_key"), "too-short-synthetic\n")
    assert "secret_key" in _refused()
    put(registry_spec("secret_key"), "synthetic-changeme-placeholder-0123456789abcdef\n")
    assert "documented placeholder" in _refused()


# --- No exposure --------------------------------------------------------------


def test_loaded_secrets_never_appear_in_representations_or_serialisation(
    put: Writer, root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    for spec in REGISTRY_LOADED:
        put(spec, _file_content(spec))
    settings = _settings()
    for spec in REGISTRY_LOADED:
        assert getattr(settings, spec.setting).get_secret_value() == SYNTHETIC[spec.setting]
    for text in (
        repr(settings),
        str(settings),
        settings.model_dump_json(),
        str(settings.model_dump()),
        repr(settings.database_connect_url()),
        str(settings.database_connect_url()),
        caplog.text,
    ):
        _no_values(text)
    assert "database_url" not in repr(settings)


def test_file_backed_values_are_never_copied_into_the_environment(put: Writer) -> None:
    for spec in REGISTRY_LOADED:
        put(spec, _file_content(spec))
    _settings()
    environment = "\n".join(os.environ.values())
    for value in SYNTHETIC.values():
        assert value not in environment


def test_errors_never_include_paths_or_values(put: Writer, root: Path) -> None:
    spec = registry_spec("stripe_secret_key")
    put(spec, "synthetic-not-a-stripe-key\nsecond-line\n")
    text = _refused()
    assert str(root) not in text and "synthetic-not-a-stripe-key" not in text


# --- SEC-086 / SEC-086a: database credentials -------------------------------------


def test_legacy_password_bearing_url_is_used_exactly_as_before(root: Path) -> None:
    settings = Settings(database_url=APP_URL_WITH_PASSWORD, _env_file=None)  # type: ignore[call-arg]
    url = settings.database_connect_url()
    assert url == make_url(APP_URL_WITH_PASSWORD)
    assert url.password == "synthetic-url-pass"
    assert settings.database_password is None


def test_legacy_urls_are_not_newly_validated(root: Path) -> None:
    """Without a password file, settings still load with any URL (as before);
    a malformed one fails only when the engine is built, now without quoting it."""
    broken = "::not a url::synthetic-url-pass"
    settings = Settings(database_url=broken, _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(ValueError) as caught:
        settings.database_connect_url()
    assert str(caught.value) == "MYKHAYA_DATABASE_URL is not a valid database URL"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_file_backed_password_is_attached_to_the_url_object(put: Writer) -> None:
    put(registry_spec("database_password"), SPECIAL_PASSWORD + "\n")
    settings = _settings()
    url = settings.database_connect_url()
    assert url.username == "mykhaya_app"
    assert url.password == SPECIAL_PASSWORD
    assert settings.database_url == APP_URL_NO_PASSWORD, "never written back into the URL"
    # The structured URL survives a render/parse round trip unchanged, so no
    # hand-made percent-encoding is involved anywhere.
    assert make_url(url.render_as_string(hide_password=False)).password == SPECIAL_PASSWORD
    assert SPECIAL_PASSWORD not in str(url) and SPECIAL_PASSWORD not in repr(url)


def test_url_with_a_password_is_refused_when_a_password_file_is_set(
    put: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(registry_spec("database_password"), SPECIAL_PASSWORD)
    monkeypatch.setenv("MYKHAYA_DATABASE_URL", APP_URL_WITH_PASSWORD)
    text = _refused()
    assert (
        "MYKHAYA_DATABASE_URL must not contain a password when MYKHAYA_DATABASE_PASSWORD_FILE "
        "is set" in text
    )
    _no_values(text, APP_URL_WITH_PASSWORD)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("postgresql+asyncpg://postgres:5432/mykhaya", "must name a database user"),
        ("::not a url::synthetic-url-pass", "is not a valid database URL"),
    ],
)
def test_password_file_requires_a_usable_url(
    put: Writer, monkeypatch: pytest.MonkeyPatch, url: str, message: str
) -> None:
    put(registry_spec("database_password"), SPECIAL_PASSWORD)
    monkeypatch.setenv("MYKHAYA_DATABASE_URL", url)
    text = _refused()
    assert message in text
    _no_values(text, url)


def test_a_literal_database_password_variable_is_not_accepted(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYKHAYA_DATABASE_PASSWORD", "synthetic-literal-db-password")
    text = _refused()
    assert "MYKHAYA_DATABASE_PASSWORD is not supported; use MYKHAYA_DATABASE_PASSWORD_FILE" in text
    assert "synthetic-literal-db-password" not in text


def test_redacted_diagnostics_mask_the_password() -> None:
    assert "synthetic-url-pass" not in redacted_database_url(APP_URL_WITH_PASSWORD)
    assert "***" in redacted_database_url(APP_URL_WITH_PASSWORD)
    assert redacted_database_url("::bad::synthetic-url-pass") == "<unparseable database URL>"
    assert connection_url(APP_URL_NO_PASSWORD, SecretStr("x")).password == "x"


def test_application_roles_accept_a_file_backed_password(
    put: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(registry_spec("database_password"), SPECIAL_PASSWORD)
    for role in ("api", "worker", "scheduler", "cli"):
        monkeypatch.setenv("MYKHAYA_PROCESS_ROLE", role)
        assert _settings().database_connect_url().password == SPECIAL_PASSWORD


def test_application_roles_still_refuse_the_migrator_identity_with_a_password_file(
    put: Writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(registry_spec("database_password"), SPECIAL_PASSWORD)
    monkeypatch.setenv("MYKHAYA_DATABASE_URL", MIGRATOR_URL_NO_PASSWORD)
    monkeypatch.setenv("MYKHAYA_PROCESS_ROLE", "api")
    text = _refused()
    assert "must not receive MYKHAYA_DATABASE_URL (K-03)" in text
    _no_values(text)


def test_application_roles_still_require_some_database_password(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYKHAYA_DATABASE_URL", APP_URL_NO_PASSWORD)
    monkeypatch.setenv("MYKHAYA_PROCESS_ROLE", "api")
    assert "requires MYKHAYA_DATABASE_URL with the mykhaya_app database role (K-02)" in _refused()


# --- The migrator ----------------------------------------------------------------


@pytest.fixture
def migration_password(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    path = root / "migration_db_password"
    path.write_text(SPECIAL_PASSWORD + "\n")
    monkeypatch.setenv("MYKHAYA_DATABASE_URL", MIGRATOR_URL_NO_PASSWORD)
    monkeypatch.setenv("MYKHAYA_DATABASE_PASSWORD_FILE", str(path))
    return path


def test_migrator_loads_its_own_password_file(migration_password: Path) -> None:
    settings = MigrationSettings()
    assert settings.database_connect_url().username == "mykhaya_migrator"
    assert settings.database_connect_url().password == SPECIAL_PASSWORD
    _no_values(repr(settings))


def test_migrate_role_accepts_a_file_backed_password_and_no_key(
    migration_password: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYKHAYA_PROCESS_ROLE", "migrate")
    assert MigrationSettings().database_connect_url().password == SPECIAL_PASSWORD


def test_migrate_role_still_refuses_the_session_secret_file(
    migration_password: Path, monkeypatch: pytest.MonkeyPatch, root: Path
) -> None:
    monkeypatch.setenv("MYKHAYA_PROCESS_ROLE", "migrate")
    monkeypatch.setenv("MYKHAYA_SECRET_KEY_FILE", str(root / "secret_key"))
    with pytest.raises(ValidationError) as caught:
        MigrationSettings()
    assert "MYKHAYA_SECRET_KEY_FILE (K-01)" in str(caught.value)


@pytest.mark.parametrize("spec", REGISTRY_LOADED[2:], ids=lambda s: s.file_env)
def test_migrate_role_refuses_every_other_credential_file(
    spec: SecretSpec, migration_password: Path, monkeypatch: pytest.MonkeyPatch, root: Path
) -> None:
    monkeypatch.setenv("MYKHAYA_PROCESS_ROLE", "migrate")
    monkeypatch.setenv(spec.file_env, str(root / spec.file_setting))
    with pytest.raises(ValidationError) as caught:
        MigrationSettings()
    assert f"{spec.file_env} ({spec.credential})" in str(caught.value)


def test_migrator_refuses_a_url_password_and_a_file_together(
    migration_password: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "MYKHAYA_DATABASE_URL",
        "postgresql+asyncpg://mykhaya_migrator:synthetic-url-pass@postgres:5432/mykhaya",
    )
    with pytest.raises(ValidationError) as caught:
        MigrationSettings()
    assert "must not contain a password" in str(caught.value)
    _no_values(str(caught.value))


def test_migrate_role_requires_some_database_password(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    monkeypatch.setenv("MYKHAYA_DATABASE_URL", MIGRATOR_URL_NO_PASSWORD)
    monkeypatch.setenv("MYKHAYA_PROCESS_ROLE", "migrate")
    with pytest.raises(ValidationError) as caught:
        MigrationSettings()
    assert "mykhaya_migrator database role (K-03)" in str(caught.value)


def test_migrator_refuses_a_literal_password_variable(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYKHAYA_DATABASE_PASSWORD", "synthetic-literal-db-password")
    with pytest.raises(ValidationError) as caught:
        MigrationSettings()
    assert "MYKHAYA_DATABASE_PASSWORD is not supported" in str(caught.value)
    assert "synthetic-literal-db-password" not in str(caught.value)


ALEMBIC_WITH_PASSWORD_FILE = r"""
import os, sys
from mykhaya import secret_files
secret_files.APPROVED_SECRET_ROOTS = (os.environ["SYNTHETIC_ROOT"],)
from alembic import command
from alembic.config import Config
import mykhaya.config
cfg = Config()
cfg.set_main_option("script_location", "migrations")
command.stamp(cfg, "head", sql=True)  # offline: runs env.py, never connects
assert "mykhaya.db" not in sys.modules, "env.py imported the engine module"
assert mykhaya.config.get_settings.cache_info().currsize == 0, "env.py built Settings"
url = mykhaya.config.get_migration_settings().database_connect_url()
assert url.password == os.environ["EXPECTED"]
print("offline migration with a file-backed password and no key: ok")
"""


def test_alembic_runs_keyless_with_a_file_backed_password(
    migration_password: Path, root: Path
) -> None:
    env = {
        name: value
        for name, value in os.environ.items()
        if not _credential_shaped(name) and name != "MYKHAYA_PROCESS_ROLE"
    }
    env.update(
        MYKHAYA_PROCESS_ROLE="migrate",
        MYKHAYA_DATABASE_URL=MIGRATOR_URL_NO_PASSWORD,
        MYKHAYA_DATABASE_PASSWORD_FILE=str(migration_password),
        SYNTHETIC_ROOT=str(root),
        EXPECTED=SPECIAL_PASSWORD,
    )
    result = subprocess.run(  # noqa: S603 — fixed argv, no external input
        [sys.executable, "-c", ALEMBIC_WITH_PASSWORD_FILE],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "ok" in result.stdout
    assert SPECIAL_PASSWORD not in result.stdout + result.stderr
