"""Phase 4: the household Plan & Billing read model — GET /groups/{id}/billing's
extended fields (price, effective_status_reason, complimentary_expires_at)
and GET /billing/plans (Free vs Family comparison, sourced from
mykhaya.entitlements.PLAN_DEFINITIONS, never hand-duplicated). Checkout/Portal
authorization and Stripe lifecycle are covered in test_billing_checkout.py /
test_billing_webhooks.py — this file covers what's new for the polished
household page. stripe.Price.retrieve is monkeypatched — no real Stripe
sandbox call is made.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import stripe
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from mykhaya.billing import pricing as pricing_module
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import ensure_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    BillingInterval,
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
def _stripe_configured() -> AsyncIterator[None]:
    configured = get_settings().model_copy(
        update={
            "stripe_billing_configured": True,
            "stripe_secret_key": SecretStr("sk_test_abc123"),
            "stripe_webhook_secret": SecretStr("whsec_test_abc123"),
            "stripe_family_monthly_price_id": "price_month123",
            "stripe_family_annual_price_id": "price_year123",
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    yield
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture(autouse=True)
def _clear_pricing_cache() -> Iterator[None]:
    pricing_module.clear_pricing_cache()
    yield
    pricing_module.clear_pricing_cache()


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


def _fake_price(price_id: str, *, unit_amount: int = 399, interval: str = "month") -> dict:
    return {
        "id": price_id,
        "active": True,
        "currency": "gbp",
        "unit_amount": unit_amount,
        "recurring": {"interval": interval},
    }


# ---------------------------------------------------------------------------
# GET /billing/plans
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_comparison_reflects_backend_plan_definitions(client: AsyncClient) -> None:
    response = await client.get("/api/v1/billing/plans")
    assert response.status_code == 200
    rows = response.json()["rows"]
    calendars = next(row for row in rows if row["key"] == "calendar.max_calendars")
    assert calendars["free_display"] == "1 calendar"
    assert calendars["family_display"] == "Unlimited"


@pytest.mark.asyncio
async def test_plan_comparison_never_advertises_unreleased_modules(client: AsyncClient) -> None:
    """lists/chores/notes/wishlists exist in PLAN_DEFINITIONS but have no
    released module behind them (mykhaya.module_registry) — they must never
    be marketed as a Family benefit."""
    response = await client.get("/api/v1/billing/plans")
    keys = {row["key"] for row in response.json()["rows"]}
    assert "lists.enabled" not in keys
    assert "chores.enabled" not in keys
    assert "notes.enabled" not in keys
    assert "wishlists.enabled" not in keys


# ---------------------------------------------------------------------------
# GET /billing/pricing — best value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_annual_best_value_true_when_provider_prices_make_it_cheaper(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_retrieve(price_id: str, **kw: object) -> dict:
        if price_id == "price_month123":
            return _fake_price(price_id, unit_amount=399, interval="month")
        return _fake_price(price_id, unit_amount=3900, interval="year")  # cheaper than 399*12=4788

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    response = await client.get("/api/v1/billing/pricing")
    payload = response.json()
    assert payload["annual_is_best_value"] is True
    assert payload["annual_saving_formatted"] is not None


@pytest.mark.asyncio
async def test_annual_best_value_false_when_not_actually_cheaper(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_retrieve(price_id: str, **kw: object) -> dict:
        if price_id == "price_month123":
            return _fake_price(price_id, unit_amount=399, interval="month")
        return _fake_price(
            price_id, unit_amount=999999, interval="year"
        )  # deliberately not cheaper

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    response = await client.get("/api/v1/billing/pricing")
    payload = response.json()
    assert payload["annual_is_best_value"] is False
    assert payload["annual_saving_formatted"] is None


@pytest.mark.asyncio
async def test_pricing_response_never_exposes_a_stripe_price_id(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_retrieve(price_id: str, **kw: object) -> dict:
        interval = "month" if price_id == "price_month123" else "year"
        return _fake_price(price_id, interval=interval)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    response = await client.get("/api/v1/billing/pricing")
    assert "provider_price_id" not in response.text
    assert "price_month123" not in response.text
    assert "price_year123" not in response.text


# ---------------------------------------------------------------------------
# GET /groups/{id}/billing — extended fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_billing_status_includes_live_price_for_stripe_backed_home(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        stripe.Price,
        "retrieve",
        lambda price_id, **kw: _fake_price(price_id, unit_amount=3900, interval="year"),
    )
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.stripe
        subscription.status = SubscriptionStatus.active
        subscription.billing_interval = BillingInterval.year
        subscription.external_customer_id = f"cus_{uuid.uuid4().hex[:12]}"
        subscription.external_subscription_id = f"sub_{uuid.uuid4().hex[:12]}"
        subscription.external_price_id = "price_year_grandfathered"
        await db.commit()

    response = await unsafe(client, "GET", f"/api/v1/groups/{home_id}/billing")
    assert response.status_code == 200
    payload = response.json()
    assert payload["price"]["unit_amount"] == 3900
    assert payload["price"]["formatted_amount"] == "£39.00"
    assert payload["billing_interval"] == "year"


@pytest.mark.asyncio
async def test_billing_status_has_no_price_for_free_home(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    response = await unsafe(client, "GET", f"/api/v1/groups/{home_id}/billing")
    assert response.status_code == 200
    assert response.json()["price"] is None


@pytest.mark.asyncio
async def test_billing_status_shows_complimentary_expiry(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    expires = datetime.now(UTC) + timedelta(days=30)
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.complimentary
        subscription.status = SubscriptionStatus.active
        subscription.complimentary_expires_at = expires
        await db.commit()

    response = await unsafe(client, "GET", f"/api/v1/groups/{home_id}/billing")
    payload = response.json()
    assert payload["complimentary_expires_at"] is not None
    assert payload["effective_plan"] == "family"
    assert payload["price"] is None


@pytest.mark.asyncio
async def test_billing_status_explains_expired_complimentary_access(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.complimentary
        subscription.status = SubscriptionStatus.active
        subscription.complimentary_expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()

    response = await unsafe(client, "GET", f"/api/v1/groups/{home_id}/billing")
    payload = response.json()
    assert payload["effective_plan"] == "free"
    assert payload["stored_plan"] == "family"
    assert payload["effective_status_reason"] == "Complimentary access expired"


@pytest.mark.asyncio
async def test_billing_status_response_never_exposes_internal_or_secret_fields(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.complimentary
        subscription.complimentary_reason = "Beta tester"
        subscription.complimentary_note = "Internal-only note that must never leak"
        await db.commit()

    response = await unsafe(client, "GET", f"/api/v1/groups/{home_id}/billing")
    text = response.text
    assert "Internal-only note" not in text
    assert "complimentary_note" not in text
    assert "stripe_secret_key" not in text
    assert "webhook" not in text.lower()
    assert "sk_test" not in text
    assert "external_customer_id" not in text
    assert "external_subscription_id" not in text


@pytest.mark.asyncio
async def test_user_cannot_view_another_homes_billing_state(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await _register_and_login(other_client, uuid.uuid4().hex[:10])
        response = await unsafe(other_client, "GET", f"/api/v1/groups/{home_id}/billing")
        assert response.status_code == 404
