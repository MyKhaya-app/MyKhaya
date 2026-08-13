"""Settings.validate_admin_and_status_url_configuration — the startup check that
catches MYKHAYA_ADMIN_URL/MYKHAYA_STATUS_URL drifting out of sync with
MYKHAYA_TRUSTED_HOSTS/MYKHAYA_CORS_ORIGINS (the exact class of bug found during
live Control Centre verification), instead of failing silently at request time.

Settings is built via model_validate() directly here (not via
get_settings().model_copy(), which does not re-run pydantic validators, and not
via Settings(**kwargs), whose pydantic-settings __init__ overload mypy can't
match against a generic dict) so these tests exercise real validation.
"""

import pytest
from pydantic import ValidationError

from mykhaya.config import Settings

SECRET_KEY = "a" * 40


def _base_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "secret_key": SECRET_KEY,
        "environment": "development",
        "public_web_url": "http://localhost:8089",
        "admin_url": "http://admin.localhost:8089",
        "status_url": "http://status.localhost:8089",
        "trusted_hosts": ["localhost", "127.0.0.1", "admin.localhost", "status.localhost"],
        "cors_origins": ["http://localhost:8089", "http://admin.localhost:8089"],
    }
    kwargs.update(overrides)
    return kwargs


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate(_base_kwargs(**overrides))


def test_valid_development_localhost_configuration_is_accepted() -> None:
    settings = _settings()
    assert settings.admin_webauthn_rp_id == "admin.localhost"
    assert settings.admin_webauthn_origin == "http://admin.localhost:8089"


def test_valid_production_https_configuration_is_accepted() -> None:
    settings = _settings(
        environment="production",
        public_web_url="https://mykhaya.example.com",
        admin_url="https://admin.mykhaya.example.com",
        status_url="https://status.mykhaya.example.com",
        trusted_hosts=[
            "mykhaya.example.com",
            "admin.mykhaya.example.com",
            "status.mykhaya.example.com",
        ],
        cors_origins=["https://admin.mykhaya.example.com"],
        cookie_secure=True,
        cookie_domain=None,
        admin_allowed_networks=["10.0.0.0/8"],
        admin_mfa_required=True,
    )
    assert settings.admin_webauthn_origin == "https://admin.mykhaya.example.com"


def test_malformed_admin_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not a valid http"):
        _settings(admin_url="not-a-url")


def test_admin_url_missing_scheme_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not a valid http"):
        _settings(admin_url="admin.localhost:8089")


def test_production_admin_url_using_http_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must use https in production"):
        _settings(
            environment="production",
            public_web_url="https://mykhaya.example.com",
            admin_url="http://admin.mykhaya.example.com",
            status_url="https://status.mykhaya.example.com",
            trusted_hosts=[
                "mykhaya.example.com",
                "admin.mykhaya.example.com",
                "status.mykhaya.example.com",
            ],
            cors_origins=["http://admin.mykhaya.example.com"],
            cookie_secure=True,
            admin_allowed_networks=["10.0.0.0/8"],
            admin_mfa_required=True,
        )


def test_admin_url_host_not_in_trusted_hosts_is_rejected() -> None:
    with pytest.raises(ValidationError, match="MYKHAYA_TRUSTED_HOSTS"):
        _settings(
            admin_url="http://admin.localhost:8089",
            trusted_hosts=["localhost", "127.0.0.1", "status.localhost"],
        )


def test_admin_url_origin_not_in_cors_origins_is_rejected() -> None:
    with pytest.raises(ValidationError, match="MYKHAYA_CORS_ORIGINS"):
        _settings(cors_origins=["http://localhost:8089"])


def test_stale_admin_url_port_mismatch_with_cors_origins_is_rejected() -> None:
    """The exact real-world bug this validator was added to catch: admin_url
    moved to a new port but cors_origins still lists the old one."""
    with pytest.raises(ValidationError, match="MYKHAYA_CORS_ORIGINS"):
        _settings(
            admin_url="http://admin.localhost:8089",
            cors_origins=["http://localhost:8089", "http://admin.localhost:8080"],
        )


def test_validation_is_skipped_in_test_environment_even_when_urls_are_incoherent() -> None:
    settings = _settings(
        environment="test",
        admin_url="http://admin.localhost:8089",
        trusted_hosts=[],
        cors_origins=[],
    )
    assert settings.environment == "test"


def test_webauthn_rp_id_and_origin_are_derived_from_admin_url() -> None:
    settings = _settings(
        admin_url="http://admin.localhost:9999",
        status_url="http://status.localhost:9999",
        public_web_url="http://localhost:9999",
        trusted_hosts=["localhost", "admin.localhost", "status.localhost"],
        cors_origins=["http://admin.localhost:9999"],
    )
    assert settings.admin_webauthn_rp_id == "admin.localhost"
    assert settings.admin_webauthn_origin == "http://admin.localhost:9999"
