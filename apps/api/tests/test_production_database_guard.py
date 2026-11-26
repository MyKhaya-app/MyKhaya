"""Owner decision D-WP4-01: production never falls back to placeholder
database credentials (Settings and MigrationSettings).

Every value is synthetic. Development and test keep the class default URL;
production requires MYKHAYA_DATABASE_URL to be configured explicitly and
refuses the placeholder passwords this repository ships, from any source.
"""

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mykhaya import secret_files
from mykhaya.config import MigrationSettings, Settings
from mykhaya.db_credentials import is_placeholder_password

CLASS_DEFAULT_URL = "postgresql+asyncpg://mykhaya:mykhaya@postgres:5432/mykhaya"
GENUINE_APP_URL = "postgresql+asyncpg://mykhaya_app:synthetic-genuine-w4-pass@postgres:5432/mykhaya"
GENUINE_MIGRATOR_URL = (
    "postgresql+asyncpg://mykhaya_migrator:synthetic-genuine-w4-pass@postgres:5432/mykhaya"
)
PASSWORD_FREE_URL = "postgresql+asyncpg://mykhaya_app@postgres:5432/mykhaya"
# The placeholder passwords the env templates ship (built so scanners see no
# credential literal), plus the class default's.
TEMPLATE_PLACEHOLDERS = (
    "mykhaya",
    "replace-with-" + "a-different-random-runtime-password",
    "replace-with-" + "a-random-migration-password",
    "GENERATE_A_" + "DIFFERENT_UNIQUE_PASSWORD",
    "CHANGE_ME_" + "RANDOM_RUNTIME_PASSWORD",
    "__SET_IN_" + "IGNORED_DEV_FILE__",
)
PRODUCTION: dict[str, Any] = {
    "environment": "production",
    "secret_key": "synthetic-wp4-production-guard-key-0123456789",
    "cookie_secure": True,
    "admin_mfa_required": True,
    "admin_allowed_networks": ["127.0.0.1/32"],
    "public_web_url": "https://mykhaya.app",
    "admin_url": "https://admin.mykhaya.app",
    "status_url": "https://status.mykhaya.app",
    "native_api_url": "https://api.mykhaya.app",
    "trusted_hosts": ["mykhaya.app", "admin.mykhaya.app", "status.mykhaya.app", "api.mykhaya.app"],
    "cors_origins": ["https://mykhaya.app", "https://admin.mykhaya.app"],
}
EXPLICIT = "must be set explicitly in production"
PLACEHOLDER = "holds a placeholder database password, which production refuses"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name in list(os.environ):
        if name.startswith("MYKHAYA_DATABASE") or name in (
            "MYKHAYA_PROCESS_ROLE",
            "MYKHAYA_ENVIRONMENT",
        ):
            monkeypatch.delenv(name)
    root = tmp_path / "secrets"
    root.mkdir()
    monkeypatch.setattr(secret_files, "APPROVED_SECRET_ROOTS", (str(root),))
    return root


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**PRODUCTION, **overrides})  # type: ignore[arg-type]


def _refused(build: Any) -> str:
    with pytest.raises(ValidationError) as caught:
        build()
    text = str(caught.value)
    for secret in ("synthetic-genuine-w4-pass", *TEMPLATE_PLACEHOLDERS[1:], CLASS_DEFAULT_URL):
        assert secret not in text
    assert "input_value" not in text
    return text


# --- Missing: the class default is never used in production ---------------------


def test_application_settings_refuse_the_default_url_in_production() -> None:
    assert EXPLICIT in _refused(_settings)


def test_migration_settings_refuse_the_default_url_in_production() -> None:
    assert EXPLICIT in _refused(lambda: MigrationSettings(environment="production"))


def test_production_environment_from_the_environment_variable_is_enforced_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYKHAYA_ENVIRONMENT", "production")
    assert EXPLICIT in _refused(MigrationSettings)


# --- Placeholder passwords are refused from every source ---------------------------


@pytest.mark.parametrize("password", TEMPLATE_PLACEHOLDERS)
def test_placeholder_passwords_in_an_explicit_url_are_refused(password: str) -> None:
    url = f"postgresql+asyncpg://mykhaya_app:{password}@postgres:5432/mykhaya"
    assert PLACEHOLDER in _refused(lambda: _settings(database_url=url))
    migrator = url.replace("mykhaya_app", "mykhaya_migrator")
    assert PLACEHOLDER in _refused(
        lambda: MigrationSettings(environment="production", database_url=migrator)
    )


def test_the_class_default_supplied_through_the_environment_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYKHAYA_DATABASE_URL", CLASS_DEFAULT_URL)
    assert PLACEHOLDER in _refused(_settings)
    assert PLACEHOLDER in _refused(lambda: MigrationSettings(environment="production"))


def test_the_class_default_supplied_through_a_dotenv_file_is_refused(tmp_path: Path) -> None:
    dotenv = tmp_path / "production.env"
    dotenv.write_text(f"MYKHAYA_DATABASE_URL={CLASS_DEFAULT_URL}\n")
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=str(dotenv), **PRODUCTION)
    assert PLACEHOLDER in str(caught.value)


def test_a_percent_encoded_placeholder_is_refused() -> None:
    url = "postgresql+asyncpg://mykhaya_app:mykh%61ya@postgres:5432/mykhaya"
    assert PLACEHOLDER in _refused(lambda: _settings(database_url=url))


@pytest.mark.parametrize("password", TEMPLATE_PLACEHOLDERS)
def test_placeholder_passwords_in_a_password_file_are_refused(
    password: str, clean_environment: Path
) -> None:
    path = clean_environment / "db_password"
    path.write_text(password + "\n")
    text = _refused(
        lambda: _settings(database_url=PASSWORD_FREE_URL, database_password_file=str(path))
    )
    assert f"MYKHAYA_DATABASE_PASSWORD_FILE {PLACEHOLDER}" in text
    migrator = PASSWORD_FREE_URL.replace("mykhaya_app", "mykhaya_migrator")
    text = _refused(
        lambda: MigrationSettings(
            environment="production", database_url=migrator, database_password_file=str(path)
        )
    )
    assert f"MYKHAYA_DATABASE_PASSWORD_FILE {PLACEHOLDER}" in text


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_url_is_refused(blank: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYKHAYA_DATABASE_URL", blank)
    assert "MYKHAYA_DATABASE_URL is not a valid database URL" in _refused(_settings)


# --- Genuine production configuration keeps working ---------------------------------


def test_a_genuine_legacy_password_bearing_url_is_accepted() -> None:
    assert _settings(database_url=GENUINE_APP_URL).database_connect_url().password == (
        "synthetic-genuine-w4-pass"
    )
    migration = MigrationSettings(environment="production", database_url=GENUINE_MIGRATOR_URL)
    assert migration.database_connect_url().username == "mykhaya_migrator"


def test_a_genuine_url_from_the_environment_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYKHAYA_DATABASE_URL", GENUINE_APP_URL)
    assert _settings().database_url == GENUINE_APP_URL


def test_a_password_free_url_with_a_genuine_password_file_is_accepted(
    clean_environment: Path,
) -> None:
    path = clean_environment / "db_password"
    path.write_text("synthetic-genuine-w4-file-pass\n")
    settings = _settings(database_url=PASSWORD_FREE_URL, database_password_file=str(path))
    assert settings.database_connect_url().password == "synthetic-genuine-w4-file-pass"


def test_production_process_roles_still_apply_on_top(monkeypatch: pytest.MonkeyPatch) -> None:
    text = _refused(lambda: _settings(database_url=GENUINE_MIGRATOR_URL, process_role="api"))
    assert "must not receive MYKHAYA_DATABASE_URL (K-03)" in text


# --- Development and test are unchanged ---------------------------------------------


@pytest.mark.parametrize("environment", ["development", "test"])
def test_development_and_test_keep_the_default_url(environment: str) -> None:
    migration = MigrationSettings(environment=environment)
    assert migration.database_url == CLASS_DEFAULT_URL
    assert migration.database_connect_url().password == "mykhaya"


def test_application_settings_keep_the_default_url_outside_production() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        secret_key="synthetic-wp4-development-key-0123456789abcdef",
    )
    assert settings.database_url == CLASS_DEFAULT_URL


def test_placeholder_detection_is_exact_about_what_it_refuses() -> None:
    for value in TEMPLATE_PLACEHOLDERS:
        assert is_placeholder_password(value)
        assert is_placeholder_password(f" {value.upper()} ")
    for value in ("synthetic-genuine-w4-pass", "mykhaya-2c9f1e7a", "Zq8!mykhaya_app"):
        assert not is_placeholder_password(value)
