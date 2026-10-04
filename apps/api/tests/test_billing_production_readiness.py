"""Phase 7: production billing readiness hardening.

Covers the billing acquisition gate (separate from "Stripe configured"),
Checkout/Portal IDOR protection across Homes, Stripe provider-ID uniqueness,
reconciliation's ownership-mismatch defence, and Stripe-outage safety for
existing paid Homes. stripe.* calls are monkeypatched throughout — no real
Stripe sandbox call is made. See
docs/architecture/commercial-entitlements.md#billing-acquisition-gate.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
import stripe
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mykhaya.billing import pricing as pricing_module
from mykhaya.billing.client import StripeUnavailableError
from mykhaya.billing.state import (
    SubscriptionOwnershipMismatchError,
    apply_stripe_subscription_state,
)
from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import ensure_home_subscription, get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    FeatureKey,
    FeatureOverride,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture(autouse=True)
def _clear_pricing_cache() -> Iterator[None]:
    pricing_module.clear_pricing_cache()
    yield
    pricing_module.clear_pricing_cache()


def _configured_settings(**overrides: object) -> Settings:
    return get_settings().model_copy(
        update={
            "stripe_billing_configured": True,
            "stripe_billing_acquisition_enabled": True,
            "stripe_secret_key": SecretStr("sk_test_abc123"),
            "stripe_webhook_secret": SecretStr("whsec_test_abc123"),
            "stripe_family_monthly_price_id": "price_month123",
            "stripe_family_annual_price_id": "price_year123",
            **overrides,
        }
    )


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def _register_and_login(client: AsyncClient, suffix: str) -> User:
    email = f"member-{suffix}@example.com"
    register = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Member", "password": PASSWORD},
    )
    assert register.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        token = await db.scalar(
            select(ActionToken)
            .where(
                ActionToken.user_id == user.id,
                ActionToken.purpose == TokenPurpose.verify_email,
            )
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    return user


async def _make_home(client: AsyncClient, suffix: str) -> uuid.UUID:
    await _register_and_login(client, suffix)
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Test Home"})
    assert group.status_code == 201
    return uuid.UUID(group.json()["id"])


def _suffix() -> str:
    return datetime.now(UTC).strftime("%H%M%S%f")


# ---------------------------------------------------------------------------
# The acquisition gate — separate from "Stripe configured"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_is_refused_while_acquisition_is_disabled(client: AsyncClient) -> None:
    app.dependency_overrides[get_settings] = lambda: _configured_settings(
        stripe_billing_acquisition_enabled=False
    )
    try:
        home_id = await _make_home(client, _suffix())
        response = await unsafe(
            client,
            "POST",
            f"/api/v1/groups/{home_id}/billing/checkout-session",
            json={"interval": "month"},
        )
        assert response.status_code == 503
        assert "temporarily unavailable" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_free_signup_and_home_creation_unaffected_by_acquisition_disabled(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: _configured_settings(
        stripe_billing_acquisition_enabled=False
    )
    try:
        home_id = await _make_home(client, _suffix())
        async with SessionFactory() as db:
            subscription = await get_home_subscription(db, home_id)
            assert subscription is not None
            assert subscription.plan == SubscriptionPlan.free
            assert subscription.provider == SubscriptionProvider.free
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_pricing_stays_informational_while_acquisition_is_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Public pricing keeps showing the real price — only Checkout itself is
    blocked. The frontend uses acquisition_enabled to decide whether to
    offer Checkout, not by hiding the price."""
    monkeypatch.setattr(
        stripe.Price,
        "retrieve",
        lambda price_id, **kw: {
            "id": price_id,
            "active": True,
            "currency": "gbp",
            "unit_amount": 399 if price_id == "price_month123" else 3900,
            "recurring": {"interval": "month" if price_id == "price_month123" else "year"},
        },
    )
    app.dependency_overrides[get_settings] = lambda: _configured_settings(
        stripe_billing_acquisition_enabled=False
    )
    try:
        response = await client.get("/api/v1/billing/pricing")
        assert response.status_code == 200
        body = response.json()
        assert body["acquisition_enabled"] is False
        assert body["options"][0]["formatted_amount"]
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_webhook_processing_unaffected_by_acquisition_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kill switch must never be wired to webhook acceptance — existing
    subscribers' renewals/cancellations must keep processing regardless."""
    home_id = await _make_home(client, _suffix())
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.provider = SubscriptionProvider.stripe
        subscription.plan = SubscriptionPlan.family
        subscription.status = SubscriptionStatus.active
        subscription.external_customer_id = "cus_existing123"
        subscription.external_subscription_id = "sub_existing123"
        await db.commit()

    def fake_construct_event(payload, sig_header, secret):
        import json

        return json.loads(payload)

    monkeypatch.setattr(stripe.Webhook, "construct_event", fake_construct_event)
    app.dependency_overrides[get_settings] = lambda: _configured_settings(
        stripe_billing_acquisition_enabled=False
    )
    try:
        event = {
            "id": f"evt_{uuid.uuid4().hex[:12]}",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_existing123",
                    "customer": "cus_existing123",
                    "status": "past_due",
                    "cancel_at_period_end": False,
                    "items": {
                        "data": [
                            {"price": {"id": "price_month123", "recurring": {"interval": "month"}}}
                        ]
                    },
                }
            },
        }
        response = await client.post(
            "/api/v1/billing/stripe/webhook",
            json=event,
            headers={"stripe-signature": "test"},
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.pop(get_settings, None)
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        assert subscription.status == SubscriptionStatus.past_due


# ---------------------------------------------------------------------------
# Checkout/Portal IDOR — cannot act on another Home
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_start_checkout_for_a_home_you_do_not_belong_to(client: AsyncClient) -> None:
    app.dependency_overrides[get_settings] = lambda: _configured_settings()
    try:
        other_home_id = await _make_home(client, _suffix())

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as attacker_client:
            await _register_and_login(attacker_client, _suffix())
            response = await unsafe(
                attacker_client,
                "POST",
                f"/api/v1/groups/{other_home_id}/billing/checkout-session",
                json={"interval": "month"},
            )
            assert response.status_code in (403, 404)
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_cannot_open_portal_for_a_home_you_do_not_belong_to(client: AsyncClient) -> None:
    app.dependency_overrides[get_settings] = lambda: _configured_settings()
    try:
        other_home_id = await _make_home(client, _suffix())

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as attacker_client:
            await _register_and_login(attacker_client, _suffix())
            response = await unsafe(
                attacker_client,
                "POST",
                f"/api/v1/groups/{other_home_id}/billing/portal-session",
                json={},
            )
            assert response.status_code in (403, 404)
    finally:
        app.dependency_overrides.pop(get_settings, None)


# ---------------------------------------------------------------------------
# Stripe provider-ID uniqueness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stripe_customer_id_cannot_resolve_to_two_homes(client: AsyncClient) -> None:
    home_a = await _make_home(client, _suffix())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        home_b = await _make_home(second_client, _suffix())

    async with SessionFactory() as db:
        subscription_a = await ensure_home_subscription(db, home_a)
        subscription_a.external_customer_id = "cus_shared123"
        await db.commit()

    async with SessionFactory() as db:
        subscription_b = await ensure_home_subscription(db, home_b)
        subscription_b.external_customer_id = "cus_shared123"
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


@pytest.mark.asyncio
async def test_a_stripe_subscription_id_cannot_resolve_to_two_homes(client: AsyncClient) -> None:
    home_a = await _make_home(client, _suffix())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        home_b = await _make_home(second_client, _suffix())

    async with SessionFactory() as db:
        subscription_a = await ensure_home_subscription(db, home_a)
        subscription_a.external_subscription_id = "sub_shared123"
        await db.commit()

    async with SessionFactory() as db:
        subscription_b = await ensure_home_subscription(db, home_b)
        subscription_b.external_subscription_id = "sub_shared123"
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


# ---------------------------------------------------------------------------
# Reconciliation authority: never trust a mismatched Stripe object
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_stripe_state_rejects_a_subscription_whose_metadata_points_elsewhere() -> None:
    async with SessionFactory() as db:
        home_id = uuid.uuid4()
        other_home_id = uuid.uuid4()
        stripe_subscription = {
            "id": "sub_mismatch123",
            "customer": "cus_mismatch123",
            "status": "active",
            "cancel_at_period_end": False,
            "metadata": {"mykhaya_group_id": str(other_home_id)},
            "items": {
                "data": [{"price": {"id": "price_month123", "recurring": {"interval": "month"}}}]
            },
        }
        with pytest.raises(SubscriptionOwnershipMismatchError):
            await apply_stripe_subscription_state(
                db,
                group_id=home_id,
                stripe_subscription=stripe_subscription,
                actor_administrator_id=None,
                reason="test",
                event_type_hint="stripe_reconciled",
            )


@pytest.mark.asyncio
async def test_apply_stripe_state_allows_matching_metadata(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    async with SessionFactory() as db:
        stripe_subscription = {
            "id": "sub_match123",
            "customer": "cus_match123",
            "status": "active",
            "cancel_at_period_end": False,
            "metadata": {"mykhaya_group_id": str(home_id)},
            "items": {
                "data": [{"price": {"id": "price_month123", "recurring": {"interval": "month"}}}]
            },
        }
        updated = await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=stripe_subscription,
            actor_administrator_id=None,
            reason="test",
            event_type_hint="stripe_subscription_activated",
        )
        assert updated is not None
        assert updated.plan == SubscriptionPlan.family


# ---------------------------------------------------------------------------
# Stripe outage safety: existing entitlements never call Stripe, never
# downgrade merely because the API is unreachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_family_entitlement_survives_stripe_being_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordinary feature authorization (here: creating a second calendar,
    which only a Family-entitled Home may do) must never call Stripe at
    all — resolving entitlement is purely local. Simulate total Stripe
    outage by making any Stripe SDK call raise, then prove the Family
    action still succeeds."""

    def stripe_call_forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Ordinary feature authorization must never call Stripe.")

    monkeypatch.setattr(stripe.Price, "retrieve", stripe_call_forbidden)
    monkeypatch.setattr(stripe.Subscription, "retrieve", stripe_call_forbidden)
    monkeypatch.setattr(stripe.Customer, "create", stripe_call_forbidden)

    home_id = await _make_home(client, _suffix())
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.stripe
        subscription.status = SubscriptionStatus.active
        subscription.external_customer_id = "cus_outage123"
        subscription.external_subscription_id = "sub_outage123"
        await db.commit()

    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.calendar, group_id=home_id, enabled=True))
        await db.commit()

    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second calendar"}
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_checkout_fails_safely_when_stripe_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_unavailable(**kwargs: object):
        raise StripeUnavailableError("Simulated Stripe outage")

    monkeypatch.setattr(stripe.Customer, "create", lambda **kw: raise_unavailable())
    app.dependency_overrides[get_settings] = lambda: _configured_settings()
    try:
        home_id = await _make_home(client, _suffix())
        response = await unsafe(
            client,
            "POST",
            f"/api/v1/groups/{home_id}/billing/checkout-session",
            json={"interval": "month"},
        )
        assert response.status_code == 503
        async with SessionFactory() as db:
            subscription = await get_home_subscription(db, home_id)
            assert subscription is not None
            assert subscription.plan == SubscriptionPlan.free
    finally:
        app.dependency_overrides.pop(get_settings, None)
