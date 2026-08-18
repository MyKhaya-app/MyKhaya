"""Settings.validate_stripe_configuration — Stripe billing (Phase 3) must be
either fully unconfigured (the default, all Free/Complimentary features
work) or fully and consistently configured; it must never boot in a
half-configured or test/live-mismatched state. Also covers
mykhaya.billing.config.resolve_stripe_config's environment fallback and
fail-safe unconfigured result — Platform Control Centre-managed
(database-sourced) precedence is covered in test_platform_stripe_settings.py.
"""

import pytest
from pydantic import ValidationError

from mykhaya.billing.config import resolve_stripe_config
from mykhaya.config import Settings
from mykhaya.db import SessionFactory

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


def _stripe_test_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "stripe_billing_configured": True,
        "stripe_secret_key": "sk_test_abc123",
        "stripe_webhook_secret": "whsec_abc123",
        "stripe_family_monthly_price_id": "price_month123",
        "stripe_family_annual_price_id": "price_year123",
    }
    kwargs.update(overrides)
    return kwargs


@pytest.mark.asyncio
async def test_stripe_disabled_by_default_and_needs_no_other_setting() -> None:
    settings = _settings()
    assert settings.stripe_billing_configured is False
    async with SessionFactory() as db:
        config = await resolve_stripe_config(settings, db)
    assert config.configured is False
    assert config.source == "unconfigured"
    assert config.secret_key is None


@pytest.mark.asyncio
async def test_fully_configured_test_mode_is_accepted_in_development() -> None:
    settings = _settings(**_stripe_test_kwargs())
    assert settings.stripe_billing_configured is True
    async with SessionFactory() as db:
        config = await resolve_stripe_config(settings, db)
    assert config.configured is True
    assert config.source == "environment"
    assert config.mode == "test"
    assert config.secret_key == "sk_test_abc123"
    assert config.family_monthly_price_id == "price_month123"
    assert config.family_annual_price_id == "price_year123"


@pytest.mark.asyncio
async def test_database_configuration_uses_pcc_acquisition_switch() -> None:
    from mykhaya.models import PlatformStripeSettings
    from mykhaya.secrets_crypto import encrypt_stripe_secret

    settings = _settings(**_stripe_test_kwargs(stripe_billing_acquisition_enabled=True))
    async with SessionFactory() as db:
        row = PlatformStripeSettings(
            enabled=True,
            acquisition_enabled=False,
            test_publishable_key="pk_test_db123",
            encrypted_test_secret_key=encrypt_stripe_secret(settings, "sk_test_db123"),
            encrypted_test_webhook_secret=encrypt_stripe_secret(settings, "whsec_db123"),
            test_family_monthly_price_id="price_month_db",
            test_family_annual_price_id="price_year_db",
        )
        db.add(row)
        await db.commit()
        config = await resolve_stripe_config(settings, db)
    assert config.source == "database"
    assert config.configured is True
    assert config.acquisition_enabled is False


@pytest.mark.parametrize(
    "missing_field",
    [
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_family_monthly_price_id",
        "stripe_family_annual_price_id",
    ],
)
def test_half_configured_stripe_fails_startup(missing_field: str) -> None:
    kwargs = _stripe_test_kwargs()
    kwargs[missing_field] = None
    with pytest.raises(ValidationError, match="MYKHAYA_STRIPE_BILLING_CONFIGURED"):
        _settings(**kwargs)


def test_secret_key_not_shaped_like_a_stripe_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not look like a Stripe secret key"):
        _settings(**_stripe_test_kwargs(stripe_secret_key="not-a-real-key"))


def test_live_key_outside_production_is_rejected() -> None:
    with pytest.raises(ValidationError, match="live-mode key"):
        _settings(
            environment="development", **_stripe_test_kwargs(stripe_secret_key="sk_live_abc123")
        )


def test_test_key_in_production_is_rejected() -> None:
    kwargs = _stripe_test_kwargs()
    with pytest.raises(ValidationError, match="test-mode key"):
        _settings(
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
            **kwargs,
        )


def test_live_key_in_production_is_accepted() -> None:
    kwargs = _stripe_test_kwargs(stripe_secret_key="sk_live_abc123")
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
        **kwargs,
    )
    assert settings.stripe_billing_configured is True
