"""Platform Control Centre Stripe configuration (Payments page): reading
metadata, saving/replacing/removing Test and Live credentials, precedence
against the MYKHAYA_STRIPE_* environment variables, mode safety, the
connection-test action, and audit behaviour. See
docs/architecture/platform-control-centre.md#stripe-configuration-precedence.

stripe.Account.retrieve is monkeypatched where used — no real Stripe sandbox
call is made.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
import stripe
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    PlatformAdministrator,
    PlatformRole,
    PlatformStripeSettings,
    StripeMode,
)
from mykhaya.security import password_hash

ADMIN_ORIGIN = "http://admin.localhost:8080"
ADMIN_PASSWORD = "A separate operator password!"

VALID_TEST_SETTINGS = {
    "enabled": True,
    "mode": "test",
    "test_publishable_key": "pk_test_abc123",
    "test_secret_key": "sk_test_abc123",
    "test_webhook_secret": "whsec_test_abc123",
    "test_family_monthly_price_id": "price_month_test",
    "test_family_annual_price_id": "price_year_test",
    "live_publishable_key": None,
    "live_secret_key": None,
    "live_webhook_secret": None,
    "live_family_monthly_price_id": None,
    "live_family_annual_price_id": None,
    "reason": "Initial sandbox configuration for QA",
    "confirmed": True,
}


@pytest.fixture(autouse=True)
async def _clean_stripe_settings() -> AsyncIterator[None]:
    async with SessionFactory() as db:
        await db.execute(delete(PlatformStripeSettings))
        await db.commit()
    yield
    async with SessionFactory() as db:
        await db.execute(delete(PlatformStripeSettings))
        await db.commit()


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44301)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    ) as value:
        yield value


@pytest.fixture
async def admin_factory() -> AsyncIterator[
    Callable[[PlatformRole], Awaitable[PlatformAdministrator]]
]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        suffix = datetime.now(UTC).strftime("%H%M%S%f")
        async with SessionFactory() as db:
            row = PlatformAdministrator(
                email=f"stripe-operator-{suffix}@example.com",
                display_name="Test Operator",
                password_hash=password_hash.hash(ADMIN_PASSWORD),
                role=role,
                mfa_enrolled=True,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
        identifiers.append(row.id)
        return row

    yield factory
    if identifiers:
        async with SessionFactory() as db:
            await db.execute(
                delete(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id.in_(identifiers)
                )
            )
            await db.execute(
                delete(PlatformAdministrator).where(PlatformAdministrator.id.in_(identifiers))
            )
            await db.commit()


async def admin_login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login",
        json={"email": admin.email, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_admin_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def _save_settings(admin_client: AsyncClient, overrides: dict | None = None) -> object:
    body = dict(VALID_TEST_SETTINGS)
    if overrides:
        body.update(overrides)
    return await unsafe(admin_client, "PUT", "/api/v1/platform/payments/stripe/settings", json=body)


# ---------------------------------------------------------------------------
# Read access / privilege
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_support_can_read_stripe_configuration(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, operator)
    response = await admin_client.get("/api/v1/platform/payments/stripe")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["configured"] is False
    assert payload["source"] == "unconfigured"
    assert payload["test"]["secret_key_configured"] is False


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/v1/platform/payments/stripe")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_household_users_cannot_reach_the_platform_endpoint() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8080"
    ) as client:
        response = await client.get("/api/v1/platform/payments/stripe")
        assert response.status_code in (401, 403, 404)


# ---------------------------------------------------------------------------
# Writing settings: role, secrets never returned, encryption at rest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_support_role_cannot_write_settings(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, operator)
    response = await _save_settings(admin_client)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_operator_can_save_test_settings_and_secrets_are_never_returned(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.administrator)
    await admin_login(admin_client, operator)
    save = await _save_settings(admin_client)
    assert save.status_code == 200, save.text
    assert "sk_test_abc123" not in save.text
    assert "whsec_test_abc123" not in save.text

    read = await admin_client.get("/api/v1/platform/payments/stripe")
    payload = read.json()
    assert payload["configured"] is True
    assert payload["source"] == "database"
    assert payload["test"]["secret_key_configured"] is True
    assert payload["test"]["secret_key_last4"] == "c123"
    assert payload["test"]["webhook_secret_configured"] is True
    assert "sk_test_abc123" not in read.text
    assert "whsec_test_abc123" not in read.text


@pytest.mark.asyncio
async def test_secret_is_encrypted_at_rest(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    await _save_settings(admin_client)
    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformStripeSettings).limit(1))
        assert row is not None
        assert row.encrypted_test_secret_key is not None
        assert "sk_test_abc123" not in row.encrypted_test_secret_key
        assert row.encrypted_test_webhook_secret is not None
        assert "whsec_test_abc123" not in row.encrypted_test_webhook_secret


@pytest.mark.asyncio
async def test_malformed_secret_key_is_rejected(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    response = await _save_settings(admin_client, {"test_secret_key": "not-a-real-key"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_malformed_price_id_is_rejected(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    response = await _save_settings(
        admin_client, {"test_family_monthly_price_id": "not-a-price-id"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_enabling_incomplete_mode_is_rejected(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    response = await _save_settings(admin_client, {"test_family_annual_price_id": None})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test/Live isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saving_test_mode_never_touches_live_columns(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    await _save_settings(
        admin_client,
        {
            "mode": "live",
            "live_publishable_key": "pk_live_xyz",
            "live_secret_key": "sk_live_xyz123",
            "live_webhook_secret": "whsec_live_xyz123",
            "live_family_monthly_price_id": "price_month_live",
            "live_family_annual_price_id": "price_year_live",
        },
    )
    read = (await admin_client.get("/api/v1/platform/payments/stripe")).json()
    assert read["test"]["secret_key_configured"] is True
    assert read["test"]["secret_key_last4"] == "c123"
    assert read["live"]["secret_key_configured"] is True
    assert read["live"]["secret_key_last4"] == "z123"
    assert read["mode"] == "live"

    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformStripeSettings).limit(1))
        assert row is not None
        assert row.encrypted_test_secret_key is not None
        assert row.encrypted_live_secret_key is not None
        assert row.encrypted_test_secret_key != row.encrypted_live_secret_key


@pytest.mark.asyncio
async def test_incomplete_live_mode_does_not_fall_back_to_test_credentials(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """Selecting Live mode with no Live credentials stored must report
    configured=False — never silently use the Test secret key while Stripe
    is claimed to be operating in Live mode."""
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    await _save_settings(admin_client)  # Test mode, fully configured

    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformStripeSettings).limit(1))
        assert row is not None
        row.mode = StripeMode.live
        await db.commit()

    read = (await admin_client.get("/api/v1/platform/payments/stripe")).json()
    assert read["mode"] == "live"
    assert read["configured"] is False
    assert read["incomplete_reason"] is not None
    assert "Live" in read["incomplete_reason"]


# ---------------------------------------------------------------------------
# Clearing secrets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_secret_removes_only_the_named_field(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    await _save_settings(admin_client)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/payments/stripe/settings/clear-secret",
        json={
            "field": "test_webhook_secret",
            "reason": "Rotating the webhook signing secret",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    read = (await admin_client.get("/api/v1/platform/payments/stripe")).json()
    assert read["test"]["webhook_secret_configured"] is False
    assert read["test"]["secret_key_configured"] is True


@pytest.mark.asyncio
async def test_clear_secret_with_nothing_stored_conflicts(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/payments/stripe/settings/clear-secret",
        json={"field": "live_secret_key", "reason": "Nothing to clear yet", "confirmed": True},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Environment precedence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_environment_fallback_when_no_stored_row(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    configured = get_settings().model_copy(
        update={
            "stripe_billing_configured": True,
            "stripe_secret_key": SecretStr("sk_test_env123"),
            "stripe_webhook_secret": SecretStr("whsec_env123"),
            "stripe_family_monthly_price_id": "price_month_env",
            "stripe_family_annual_price_id": "price_year_env",
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        operator = await admin_factory(PlatformRole.support)
        await admin_login(admin_client, operator)
        response = await admin_client.get("/api/v1/platform/payments/stripe")
        payload = response.json()
        assert payload["configured"] is True
        assert payload["source"] == "environment"
        assert payload["editable"] is False
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_stored_configuration_takes_precedence_over_environment(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """Unlike SMTP/push, Stripe's Platform-Admin-managed row wins over the
    environment once enabled — this is a deliberate, task-specific reversal
    of the usual precedence. See
    docs/architecture/platform-control-centre.md#stripe-configuration-precedence."""
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)

    async with SessionFactory() as db:
        row = PlatformStripeSettings(
            enabled=True,
            test_publishable_key="pk_test_db123",
            test_family_monthly_price_id="price_month_db",
            test_family_annual_price_id="price_year_db",
        )
        from mykhaya.secrets_crypto import encrypt_stripe_secret

        settings = get_settings()
        row.encrypted_test_secret_key = encrypt_stripe_secret(settings, "sk_test_db123")
        row.encrypted_test_webhook_secret = encrypt_stripe_secret(settings, "whsec_db123")
        db.add(row)
        await db.commit()

    configured = get_settings().model_copy(
        update={
            "stripe_billing_configured": True,
            "stripe_secret_key": SecretStr("sk_test_env123"),
            "stripe_webhook_secret": SecretStr("whsec_env123"),
            "stripe_family_monthly_price_id": "price_month_env",
            "stripe_family_annual_price_id": "price_year_env",
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        response = await admin_client.get("/api/v1/platform/payments/stripe")
        payload = response.json()
        assert payload["source"] == "database"
        assert payload["test"]["publishable_key"] == "pk_test_db123"
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_environment_managed_stripe_rejects_writes(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    configured = get_settings().model_copy(
        update={
            "stripe_billing_configured": True,
            "stripe_secret_key": SecretStr("sk_test_env123"),
            "stripe_webhook_secret": SecretStr("whsec_env123"),
            "stripe_family_monthly_price_id": "price_month_env",
            "stripe_family_annual_price_id": "price_year_env",
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        operator = await admin_factory(PlatformRole.owner)
        await admin_login(admin_client, operator)
        response = await _save_settings(admin_client)
        assert response.status_code == 409
    finally:
        app.dependency_overrides.pop(get_settings, None)


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_test_reports_configuration_incomplete(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/payments/stripe/test-connection",
        json={"reason": "Checking before go-live", "confirmed": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"] == "configuration_incomplete"


@pytest.mark.asyncio
async def test_connection_test_success_never_creates_stripe_objects(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_retrieve(**kw: object) -> dict:
        calls.append("account.retrieve")
        return {"id": "acct_1"}

    monkeypatch.setattr(stripe.Account, "retrieve", fake_retrieve)
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    await _save_settings(admin_client)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/payments/stripe/test-connection",
        json={"reason": "Verifying sandbox connectivity", "confirmed": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"] == "connected"
    assert calls == ["account.retrieve"]


@pytest.mark.asyncio
async def test_connection_test_is_rate_limited(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    body = {"reason": "Repeated connection checks", "confirmed": True}
    statuses = []
    for _ in range(5):
        response = await unsafe(
            admin_client, "POST", "/api/v1/platform/payments/stripe/test-connection", json=body
        )
        statuses.append(response.status_code)
    assert 429 in statuses


# ---------------------------------------------------------------------------
# Audit behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_change_is_audited_without_secret_values(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    operator = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, operator)
    await _save_settings(admin_client)

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == operator.id,
                    AdministrativeAuditEvent.target_type == "stripe_settings",
                )
            )
        ).all()
        actions = {event.action for event in events}
        assert "stripe.settings_changed" in actions
        assert "stripe.test_secret_key_replaced" in actions
        assert "stripe.test_webhook_secret_replaced" in actions
        for event in events:
            blob = f"{event.previous_values} {event.new_values} {event.reason}"
            assert "sk_test_abc123" not in blob
            assert "whsec_test_abc123" not in blob
