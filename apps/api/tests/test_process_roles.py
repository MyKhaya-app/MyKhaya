"""MYKHAYA_PROCESS_ROLE credential isolation (MK-SEC-001 v1.2 WP-2).

Covers SEC-089 (migrator key denial), SEC-101 (scheduler presence flags),
SEC-102 (role-dependent required and forbidden credentials) and SEC-103 (the
role setting and the unset-role baseline) against the §6.3 matrix. Every
value is synthetic; no real credential, DEV or PROD configuration is used.
"""

import logging
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr, ValidationError

from mykhaya import process_roles, secret_files, secrets_crypto
from mykhaya.billing.config import StripeConfig
from mykhaya.config import MigrationSettings, Settings
from mykhaya.monitoring.checks import stripe_webhook_configured
from mykhaya.process_roles import CREDENTIALS, PRESENCE_FLAGS, ROLE_GRANTS

API_ROOT = Path(__file__).parents[1]
APP_VALUE = "synthetic-wp2-application-value-0123456789abcdef"
APP_URL = "postgresql+asyncpg://mykhaya_app:synthetic-app-db-value@postgres:5432/mykhaya"
MIGRATOR_URL = (
    "postgresql+asyncpg://mykhaya_migrator:synthetic-migrator-db-value@postgres:5432/mykhaya"
)
ADMIN_URL = "postgresql+asyncpg://postgres:synthetic-admin-db-value@postgres:5432/mykhaya"
APPLICATION_ROLES = ("api", "worker", "scheduler", "cli")
SECRET_SUFFIXES = (
    "_PASSWORD",
    "_SECRET",
    "_SECRET_KEY",
    "_PRIVATE_KEY",
    "_API_KEY",
    "_KEY_FILE",
    "_KEYS",
    "_KEYS_FILE",
)


def _apple_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


APPLE_PEM = _apple_pem()

# One synthetic value per credential, keyed by the first env variable that
# carries it. Each value is distinctive so leak checks can search for it.
SYNTHETIC: dict[str, str] = {
    "K-01": APP_VALUE,
    "K-06": "synthetic-smtp-value-0601",
    "K-07": "synthetic-vapid-value-0701",
    "K-08": "synthetic-apns-value-0801",
    "K-09": "synthetic-fcm-value-0901",
    "K-10": APPLE_PEM,
    "K-11": "synthetic-google-value-1101",
    "K-12": "sk_" + "test_synthetic1201",  # built so scanners see no literal
    "K-13": "whsec_synthetic1301",
    "K-14": "synthetic-dvla-uat-value-1401",
    "K-15": "synthetic-dvla-prod-value-1501",
    "K-16": "synthetic-dvsa-value-1601",
    "K-17": "https://watchdog.example.invalid/synthetic-1701",
    "K-18": '{"synthetic": "field-keyring-1801"}',
    "K-19": '{"synthetic": "blind-index-1901"}',
}
SETTINGS_CREDENTIALS = tuple(SYNTHETIC)  # credentials carried by Settings fields


def _credential_shaped(name: str) -> bool:
    known = {n for spec in CREDENTIALS.values() for n in spec.env}
    return (
        name in known
        or name in PRESENCE_FLAGS
        or (name.startswith("MYKHAYA_") and name.endswith(SECRET_SUFFIXES))
    )


_ENV: list[pytest.MonkeyPatch] = []


@pytest.fixture(autouse=True)
def no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start every test from an environment holding no credentials at all,
    whatever the test container inherited, then add exactly what each test
    needs. Every change goes through monkeypatch, so it is undone afterwards."""
    for name in list(os.environ):
        if _credential_shaped(name) or name in ("MYKHAYA_PROCESS_ROLE", "MYKHAYA_DATABASE_URL"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", APP_VALUE)
    _ENV.append(monkeypatch)
    yield
    _ENV.pop()


def _set_env(role: str | None, env: dict[str, str]) -> None:
    if role is not None:
        _ENV[-1].setenv("MYKHAYA_PROCESS_ROLE", role)
    for name, value in env.items():
        _ENV[-1].setenv(name, value)


def _settings(role: str | None = None, **env: str) -> Settings:
    _set_env(role, env)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _refused(role: str | None = None, **env: str) -> str:
    with pytest.raises(ValidationError) as caught:
        _settings(role, **env)
    return str(caught.value)


def _carrier(identifier: str) -> str:
    return CREDENTIALS[identifier].env[0]


def _no_values(text: str) -> None:
    for value in (*SYNTHETIC.values(), APP_URL, MIGRATOR_URL, ADMIN_URL):
        assert value not in text
    for fragment in ("synthetic-app-db-value", "synthetic-migrator-db-value", "BEGIN PRIVATE"):
        assert fragment not in text
    assert "input_value" not in text


# --- SEC-103: the setting and the unset-role baseline --------------------------


def test_supported_roles_are_exactly_those_in_mk_sec_001() -> None:
    assert set(process_roles.PROCESS_ROLES) == {
        "api",
        "worker",
        "scheduler",
        "migrate",
        "test",
        "cli",
    }


def test_unknown_role_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    text = _refused("superuser", MYKHAYA_DATABASE_URL=APP_URL)
    assert "process_role" in text


@pytest.mark.parametrize("blank", ["", "  "])
def test_blank_role_means_unset(blank: str) -> None:
    assert _settings(blank).process_role is None


def test_unset_role_keeps_every_credential_combination_working() -> None:
    """Baseline: with no role, even a configuration violating every row of
    the matrix loads exactly as before WP-2."""
    env = {_carrier(k): v for k, v in SYNTHETIC.items()}
    env.update(
        MYKHAYA_DATABASE_URL=MIGRATOR_URL,
        MYKHAYA_MIGRATION_DB_PASSWORD="synthetic-migrator-db-value",
        POSTGRES_PASSWORD="synthetic-admin-db-value",
    )
    settings = _settings(None, **env)
    assert settings.process_role is None
    assert settings.secret_key.get_secret_value() == APP_VALUE


def test_unset_role_does_not_use_presence_flags() -> None:
    settings = _settings(
        None,
        MYKHAYA_DVLA_ENVIRONMENT="uat",
        MYKHAYA_DVLA_UAT_ENDPOINT="https://uat.example.invalid/vehicles",
        MYKHAYA_DVLA_API_KEY_PRESENT="true",
    )
    assert settings.dvla_configured is False  # no key held, flag ignored


# --- SEC-102: the matrix for every application role ----------------------------


@pytest.mark.parametrize("role", APPLICATION_ROLES)
@pytest.mark.parametrize("identifier", [k for k in SETTINGS_CREDENTIALS if k != "K-01"])
def test_matrix_grants_and_denials(role: str, identifier: str) -> None:
    env = {"MYKHAYA_DATABASE_URL": APP_URL, _carrier(identifier): SYNTHETIC[identifier]}
    if identifier in ROLE_GRANTS[role]:
        assert _settings(role, **env).process_role == role
    else:
        text = _refused(role, **env)
        assert f"{_carrier(identifier)} ({identifier})" in text
        _no_values(text)


def test_matrix_matches_mk_sec_001_section_6_3() -> None:
    assert ROLE_GRANTS["api"] == {
        "K-01", "K-02", "K-06", "K-07", "K-10", "K-11", "K-12", "K-13",
        "K-14", "K-15", "K-16", "K-18", "K-19",
    }  # fmt: skip
    assert ROLE_GRANTS["worker"] == {"K-01", "K-02", "K-06", "K-07", "K-08", "K-09", "K-18", "K-19"}
    assert ROLE_GRANTS["scheduler"] == {"K-01", "K-02", "K-06", "K-12", "K-17", "K-18", "K-19"}
    assert ROLE_GRANTS["migrate"] == {"K-03"}
    assert ROLE_GRANTS["cli"] == ROLE_GRANTS["api"]


@pytest.mark.parametrize("role", APPLICATION_ROLES)
def test_application_roles_load_with_exactly_their_grants(role: str) -> None:
    env = {"MYKHAYA_DATABASE_URL": APP_URL}
    env.update({_carrier(k): SYNTHETIC[k] for k in SETTINGS_CREDENTIALS if k in ROLE_GRANTS[role]})
    settings = _settings(role, **env)
    assert settings.secret_key.get_secret_value() == APP_VALUE


@pytest.mark.parametrize("role", APPLICATION_ROLES)
def test_application_roles_fail_closed_without_the_application_key(
    role: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    text = _refused(role, MYKHAYA_DATABASE_URL=APP_URL)
    assert "secret_key" in text


@pytest.mark.parametrize("role", APPLICATION_ROLES)
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (None, "requires MYKHAYA_DATABASE_URL with the mykhaya_app database role (K-02)"),
        (MIGRATOR_URL, "MYKHAYA_DATABASE_URL (K-03)"),
        (ADMIN_URL, "MYKHAYA_DATABASE_URL (K-04)"),
        (
            "postgresql+asyncpg://mykhaya_app@postgres:5432/mykhaya",
            "requires MYKHAYA_DATABASE_URL with the mykhaya_app database role (K-02)",
        ),
    ],
)
def test_application_roles_require_the_application_database_role(
    role: str, url: str | None, expected: str
) -> None:
    env = {} if url is None else {"MYKHAYA_DATABASE_URL": url}
    text = _refused(role, **env)
    assert expected in text
    _no_values(text)


@pytest.mark.parametrize("role", APPLICATION_ROLES)
@pytest.mark.parametrize(
    ("name", "identifier"),
    [
        ("MYKHAYA_MIGRATION_DB_PASSWORD", "K-03"),
        ("POSTGRES_PASSWORD", "K-04"),
        ("MYKHAYA_POSTGRES_ADMIN_PASSWORD", "K-04"),
    ],
)
def test_application_roles_refuse_migration_and_admin_passwords(
    role: str, name: str, identifier: str
) -> None:
    text = _refused(role, MYKHAYA_DATABASE_URL=APP_URL, **{name: "synthetic-bootstrap-value"})
    assert f"{name} ({identifier})" in text
    assert "synthetic-bootstrap-value" not in text


def test_blank_denied_credentials_are_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose blanks inherited values (e.g. APNs for the API); blank is absent."""
    settings = _settings("api", MYKHAYA_DATABASE_URL=APP_URL, MYKHAYA_APNS_PRIVATE_KEY="")
    assert settings.process_role == "api"


DEVELOPMENT = {
    "MYKHAYA_ENVIRONMENT": "development",
    # The development defaults name these hosts; list them so the existing
    # trusted-host validator accepts the synthetic configuration.
    "MYKHAYA_TRUSTED_HOSTS": (
        '["localhost", "127.0.0.1", "admin.localhost", "status.localhost", "api.localhost"]'
    ),
}


def test_dvla_uat_and_production_keys_are_both_permitted_to_the_api() -> None:
    """DEV is authorised to call the production DVLA API with its own key, so
    the K-14/K-15 environment split is not enforced by role (deployment
    configuration keeps them separate)."""
    settings = _settings(
        "api",
        MYKHAYA_DATABASE_URL=APP_URL,
        **DEVELOPMENT,
        MYKHAYA_DVLA_UAT_API_KEY=SYNTHETIC["K-14"],
        MYKHAYA_DVLA_PRODUCTION_API_KEY=SYNTHETIC["K-15"],
    )
    assert settings.dvla_production_api_key is not None


# --- SEC-102: no role is required to hold another role's credentials ---------


STRIPE_PRICES = {
    "MYKHAYA_STRIPE_BILLING_CONFIGURED": "true",
    "MYKHAYA_STRIPE_FAMILY_MONTHLY_PRICE_ID": "price_synthetic_monthly",
    "MYKHAYA_STRIPE_FAMILY_ANNUAL_PRICE_ID": "price_synthetic_annual",
}


def test_unset_role_still_requires_both_stripe_secrets() -> None:
    text = _refused(None, **STRIPE_PRICES)
    assert "MYKHAYA_STRIPE_SECRET_KEY" in text and "MYKHAYA_STRIPE_WEBHOOK_SECRET" in text


def test_worker_is_not_required_to_hold_stripe_credentials() -> None:
    settings = _settings("worker", MYKHAYA_DATABASE_URL=APP_URL, **STRIPE_PRICES)
    assert settings.stripe_secret_key is None


def test_scheduler_needs_the_stripe_key_but_states_webhook_presence() -> None:
    env = {"MYKHAYA_DATABASE_URL": APP_URL, **STRIPE_PRICES}
    text = _refused("scheduler", **env)
    assert "MYKHAYA_STRIPE_SECRET_KEY" in text and "MYKHAYA_STRIPE_WEBHOOK_SECRET_PRESENT" in text
    # The secret itself is not required of the scheduler (whole name only: the
    # approved presence flag's name begins with the secret's name).
    assert re.search(r"MYKHAYA_STRIPE_WEBHOOK_SECRET\b", text) is None
    settings = _settings(
        "scheduler",
        MYKHAYA_STRIPE_SECRET_KEY=SYNTHETIC["K-12"],
        MYKHAYA_STRIPE_WEBHOOK_SECRET_PRESENT="true",
    )
    assert settings.stripe_webhook_secret is None


def test_api_still_requires_both_stripe_secrets() -> None:
    text = _refused("api", MYKHAYA_DATABASE_URL=APP_URL, **STRIPE_PRICES)
    assert "MYKHAYA_STRIPE_SECRET_KEY" in text and "MYKHAYA_STRIPE_WEBHOOK_SECRET" in text


PRODUCTION: dict[str, Any] = {
    "environment": "production",
    "cookie_secure": True,
    "admin_mfa_required": True,
    "admin_url": "https://admin.mykhaya.app",
    "status_url": "https://status.mykhaya.app",
    "public_web_url": "https://mykhaya.app",
    "native_api_url": "https://api.mykhaya.app",
    "admin_allowed_networks": ["127.0.0.1/32"],
    "trusted_hosts": [
        "localhost",
        "127.0.0.1",
        "admin.mykhaya.app",
        "status.mykhaya.app",
        "mykhaya.app",
        "api.mykhaya.app",
    ],
    "cors_origins": ["https://mykhaya.app", "https://admin.mykhaya.app"],
    "fcm_delivery_configured": True,
    "fcm_project_id": "mykhaya-prod",
    "version": "v9.9.9-synthetic",
}


def test_production_fcm_key_is_required_only_of_roles_granted_it() -> None:
    with pytest.raises(ValidationError, match="requires project ID"):
        Settings(_env_file=None, **PRODUCTION)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="requires project ID"):
        Settings(_env_file=None, process_role="worker", database_url=APP_URL, **PRODUCTION)  # type: ignore[arg-type]
    # The API states the key's presence with a non-secret flag instead.
    with pytest.raises(ValidationError, match="requires MYKHAYA_FCM_PRIVATE_KEY_PRESENT"):
        Settings(_env_file=None, process_role="api", database_url=APP_URL, **PRODUCTION)  # type: ignore[arg-type]
    api = Settings(
        _env_file=None,  # type: ignore[call-arg]
        process_role="api",
        database_url=APP_URL,
        fcm_private_key_present=True,
        **PRODUCTION,  # type: ignore[arg-type]
    )
    assert api.fcm_private_key is None


# --- SEC-101: scheduler presence flags, monitoring outcomes unchanged (T-027) --


DVLA_UAT = {
    "MYKHAYA_DVLA_ENVIRONMENT": "uat",
    "MYKHAYA_DVLA_UAT_ENDPOINT": "https://uat.example.invalid/vehicles",
}
DVSA = {
    "MYKHAYA_DVSA_ENABLED": "true",
    "MYKHAYA_DVSA_TOKEN_URL": "https://login.microsoftonline.com/synthetic-tenant/oauth2/v2.0/token",
}
DVSA_CREDENTIALS = {
    "MYKHAYA_DVSA_CLIENT_ID": "synthetic-dvsa-client",
    "MYKHAYA_DVSA_CLIENT_SECRET": "synthetic-dvsa-secret",
    "MYKHAYA_DVSA_API_KEY": "synthetic-dvsa-api",
}


@pytest.mark.parametrize("configured", [True, False])
def test_dvla_monitoring_outcome_is_unchanged_under_the_scheduler_role(
    configured: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy_env = dict(DVLA_UAT)
    if configured:
        legacy_env["MYKHAYA_DVLA_UAT_API_KEY"] = SYNTHETIC["K-14"]
    legacy = _settings(None, **legacy_env).dvla_configured
    for name in legacy_env:
        monkeypatch.delenv(name, raising=False)
    scheduler = _settings(
        "scheduler",
        MYKHAYA_DATABASE_URL=APP_URL,
        MYKHAYA_DVLA_API_KEY_PRESENT=str(configured).lower(),
        **DVLA_UAT,
    ).dvla_configured
    assert legacy == scheduler == configured


@pytest.mark.parametrize("configured", [True, False])
def test_dvsa_monitoring_outcome_is_unchanged_under_the_scheduler_role(
    configured: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy_env = {**DVSA, **(DVSA_CREDENTIALS if configured else {})}
    legacy = _settings(None, **legacy_env).dvsa_configured
    for name in legacy_env:
        monkeypatch.delenv(name, raising=False)
    scheduler = _settings(
        "scheduler",
        MYKHAYA_DATABASE_URL=APP_URL,
        MYKHAYA_DVSA_CREDENTIALS_PRESENT=str(configured).lower(),
        **DVSA,
    ).dvsa_configured
    assert legacy == scheduler == configured


@pytest.mark.parametrize("configured", [True, False])
def test_stripe_webhook_monitoring_outcome_is_unchanged_under_the_scheduler_role(
    configured: bool,
) -> None:
    legacy_settings = _settings(None)
    legacy_config = StripeConfig(
        source="environment",
        configured=True,
        webhook_secret=SYNTHETIC["K-13"] if configured else None,
    )
    scheduler_settings = _settings(
        "scheduler",
        MYKHAYA_DATABASE_URL=APP_URL,
        MYKHAYA_STRIPE_WEBHOOK_SECRET_PRESENT=str(configured).lower(),
    )
    scheduler_config = StripeConfig(source="environment", configured=True, webhook_secret=None)
    assert (
        stripe_webhook_configured(legacy_settings, legacy_config)
        == stripe_webhook_configured(scheduler_settings, scheduler_config)
        == configured
    )


def test_database_sourced_webhook_secret_is_unaffected_by_presence_flags() -> None:
    settings = _settings(
        "scheduler", MYKHAYA_DATABASE_URL=APP_URL, MYKHAYA_STRIPE_WEBHOOK_SECRET_PRESENT="true"
    )
    unconfigured = StripeConfig(source="database", configured=True, webhook_secret=None)
    assert stripe_webhook_configured(settings, unconfigured) is False


@pytest.mark.parametrize(
    ("env", "flag"),
    [(DVLA_UAT, "MYKHAYA_DVLA_API_KEY_PRESENT"), (DVSA, "MYKHAYA_DVSA_CREDENTIALS_PRESENT")],
)
def test_scheduler_must_state_presence_when_a_provider_is_selected(
    env: dict[str, str], flag: str
) -> None:
    text = _refused("scheduler", MYKHAYA_DATABASE_URL=APP_URL, **env)
    assert flag in text


@pytest.mark.parametrize("identifier", ["K-13", "K-14", "K-15", "K-16"])
def test_scheduler_refuses_provider_credentials_replaced_by_presence_flags(
    identifier: str,
) -> None:
    text = _refused(
        "scheduler", MYKHAYA_DATABASE_URL=APP_URL, **{_carrier(identifier): SYNTHETIC[identifier]}
    )
    assert f"({identifier})" in text


# --- SEC-089: the migrator ------------------------------------------------------


def _migration(role: str | None = "migrate", **env: str) -> MigrationSettings:
    _set_env(role, env)
    return MigrationSettings()


def _migration_refused(role: str | None = "migrate", **env: str) -> str:
    with pytest.raises(ValidationError) as caught:
        _migration(role, **env)
    return str(caught.value)


def test_migrator_runs_with_only_the_migration_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    settings = _migration(MYKHAYA_DATABASE_URL=MIGRATOR_URL)
    assert settings.database_url == MIGRATOR_URL
    assert not hasattr(settings, "secret_key")


def test_legacy_migrator_still_tolerates_the_application_key() -> None:
    """Role unset: existing DEV/PROD contracts still pass the key until cutover."""
    settings = _migration(None, MYKHAYA_DATABASE_URL=MIGRATOR_URL)
    assert settings.process_role is None


def test_enforced_migrator_rejects_the_application_key() -> None:
    text = _migration_refused(MYKHAYA_DATABASE_URL=MIGRATOR_URL)
    assert "MYKHAYA_SECRET_KEY (K-01)" in text
    _no_values(text)


@pytest.mark.parametrize(
    "name",
    sorted(
        {n for k, spec in CREDENTIALS.items() if k != "K-03" for n in spec.env}
        - {"MYKHAYA_SECRET_KEY"}
    ),
)
def test_enforced_migrator_rejects_every_other_credential(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    text = _migration_refused(MYKHAYA_DATABASE_URL=MIGRATOR_URL, **{name: "synthetic-denied"})
    assert name in text
    assert "synthetic-denied" not in text


@pytest.mark.parametrize("flag", PRESENCE_FLAGS)
def test_enforced_migrator_rejects_presence_flags(
    flag: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    text = _migration_refused(MYKHAYA_DATABASE_URL=MIGRATOR_URL, **{flag: "false"})
    assert f"{flag} (presence flag)" in text


def test_enforced_migrator_rejects_unknown_credential_shaped_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    text = _migration_refused(
        MYKHAYA_DATABASE_URL=MIGRATOR_URL, MYKHAYA_FUTURE_PROVIDER_API_KEY="synthetic"
    )
    assert "MYKHAYA_FUTURE_PROVIDER_API_KEY (unrelated credential)" in text


def test_enforced_migrator_allows_the_raw_migration_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    settings = _migration(
        MYKHAYA_DATABASE_URL=MIGRATOR_URL, MYKHAYA_MIGRATION_DB_PASSWORD="synthetic"
    )
    assert settings.process_role == "migrate"


@pytest.mark.parametrize("url", [None, APP_URL, ADMIN_URL])
def test_enforced_migrator_requires_the_migration_database_role(
    url: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    env = {} if url is None else {"MYKHAYA_DATABASE_URL": url}
    text = _migration_refused(**env)
    assert "requires MYKHAYA_DATABASE_URL with the mykhaya_migrator database role (K-03)" in text
    _no_values(text)


def test_blank_inherited_variables_do_not_count_for_the_migrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYKHAYA_SECRET_KEY", "")
    monkeypatch.setenv("MYKHAYA_FIELD_ENCRYPTION_KEYS", "")
    assert _migration(MYKHAYA_DATABASE_URL=MIGRATOR_URL).process_role == "migrate"


@pytest.mark.parametrize("role", ["api", "worker", "scheduler", "cli", "test"])
def test_migration_settings_refuse_non_migrate_roles(role: str) -> None:
    text = _migration_refused(role, MYKHAYA_DATABASE_URL=MIGRATOR_URL)
    assert "migrations run only with the migrate role" in text


def test_application_settings_refuse_the_migrate_role() -> None:
    text = _refused("migrate", MYKHAYA_DATABASE_URL=MIGRATOR_URL)
    assert "must not load the application Settings" in text
    _no_values(text)


# --- File-backed credentials are checked like environment ones ---------------


def test_enforced_migrator_rejects_a_file_backed_application_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    text = _migration_refused(
        MYKHAYA_DATABASE_URL=MIGRATOR_URL, MYKHAYA_SECRET_KEY_FILE="/run/secrets/session_key"
    )
    assert "MYKHAYA_SECRET_KEY_FILE (K-01)" in text


@pytest.mark.parametrize(
    "name", ["MYKHAYA_FIELD_ENCRYPTION_KEYS_FILE", "MYKHAYA_APPLE_PRIVATE_KEY_FILE"]
)
def test_enforced_migrator_rejects_file_backed_credentials(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    text = _migration_refused(MYKHAYA_DATABASE_URL=MIGRATOR_URL, **{name: "/run/secrets/x"})
    assert name in text


def test_file_backed_application_key_satisfies_application_roles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(secret_files, "APPROVED_SECRET_ROOTS", (str(tmp_path),))
    (tmp_path / "session_key").write_text(APP_VALUE + "\n")
    monkeypatch.delenv("MYKHAYA_SECRET_KEY")
    settings = _settings(
        "worker",
        MYKHAYA_DATABASE_URL=APP_URL,
        MYKHAYA_SECRET_KEY_FILE=str(tmp_path / "session_key"),
    )
    assert settings.secret_key.get_secret_value() == APP_VALUE


def test_file_backed_apple_key_is_refused_for_the_worker(tmp_path: Path) -> None:
    key_file = tmp_path / "apple.p8"
    key_file.write_text(APPLE_PEM)
    text = _refused(
        "worker", MYKHAYA_DATABASE_URL=APP_URL, MYKHAYA_APPLE_PRIVATE_KEY_FILE=str(key_file)
    )
    assert "(K-10)" in text
    _no_values(text)


# --- test and cli roles ----------------------------------------------------------


def test_test_role_requires_the_test_environment() -> None:
    assert "MYKHAYA_ENVIRONMENT=test" in _refused("test", **DEVELOPMENT)


def test_test_role_loads_in_the_test_environment() -> None:
    assert _settings("test", MYKHAYA_ENVIRONMENT="test").process_role == "test"


@pytest.mark.parametrize("prefix", ["sk_live_", "rk_live_"])
def test_test_role_refuses_live_stripe_keys(prefix: str) -> None:
    text = _refused(
        "test", MYKHAYA_ENVIRONMENT="test", MYKHAYA_STRIPE_SECRET_KEY=prefix + "synthetic"
    )
    assert "live Stripe key (K-12)" in text
    assert prefix + "synthetic" not in text


def test_cli_follows_the_api_row() -> None:
    assert "(K-17)" in _refused(
        "cli", MYKHAYA_DATABASE_URL=APP_URL, MYKHAYA_MONITORING_WATCHDOG_URL=SYNTHETIC["K-17"]
    )


# --- No disclosure through errors, logs or serialisation ----------------------


def test_violation_errors_never_contain_values(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    env = {_carrier(k): v for k, v in SYNTHETIC.items() if k != "K-01"}
    text = _refused("scheduler", MYKHAYA_DATABASE_URL=MIGRATOR_URL, **env)
    _no_values(text)
    assert not any(
        value in record.getMessage() for record in caplog.records for value in SYNTHETIC.values()
    )


def test_role_settings_serialise_without_secrets() -> None:
    settings = _settings(
        "api", MYKHAYA_DATABASE_URL=APP_URL, MYKHAYA_SMTP_PASSWORD=SYNTHETIC["K-06"]
    )
    for text in (repr(settings), str(settings), settings.model_dump_json()):
        assert APP_VALUE not in text and SYNTHETIC["K-06"] not in text


# --- Encryption, rotation and existing data are unaffected -------------------


def test_roles_do_not_change_key_derivation_or_rotation() -> None:
    legacy = _settings(None)
    api = _settings("api", MYKHAYA_DATABASE_URL=APP_URL)
    ciphertext = secrets_crypto.encrypt_secret(legacy, "synthetic-plaintext")
    assert secrets_crypto.decrypt_secret(api, ciphertext) == "synthetic-plaintext"
    rotated = api.model_copy(
        update={"secret_key": SecretStr("synthetic-rotated-key-0123456789abcdef")}
    )
    assert rotated.process_role == "api"
    with pytest.raises(secrets_crypto.SecretDecryptionError):
        secrets_crypto.decrypt_secret(rotated, ciphertext)


# --- Migrations with and without the legacy key, under the migrate role -------


_ALEMBIC = """
from alembic import command
from alembic.config import Config
cfg = Config()
cfg.set_main_option("script_location", "migrations")
command.stamp(cfg, "head", sql=True)
print("ALEMBIC-OK")
"""


def _alembic(**extra: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "MYKHAYA_SECRET_KEY"}
    env.update(extra)
    # Fixed argv: this interpreter and a constant script, no external input.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", _ALEMBIC],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_enforced_migrator_runs_alembic_without_the_key() -> None:
    result = _alembic(MYKHAYA_PROCESS_ROLE="migrate", MYKHAYA_DATABASE_URL=MIGRATOR_URL)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "ALEMBIC-OK" in result.stdout


def test_enforced_migrator_refuses_alembic_with_the_key() -> None:
    result = _alembic(
        MYKHAYA_PROCESS_ROLE="migrate",
        MYKHAYA_DATABASE_URL=MIGRATOR_URL,
        MYKHAYA_SECRET_KEY=APP_VALUE,
    )
    assert result.returncode != 0
    assert "MYKHAYA_SECRET_KEY (K-01)" in result.stderr
    assert APP_VALUE not in result.stderr and APP_VALUE not in result.stdout


def test_legacy_migrator_runs_alembic_with_the_key() -> None:
    result = _alembic(MYKHAYA_DATABASE_URL=MIGRATOR_URL, MYKHAYA_SECRET_KEY=APP_VALUE)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "ALEMBIC-OK" in result.stdout
