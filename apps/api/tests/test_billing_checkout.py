"""POST /groups/{id}/billing/checkout-session, /portal-session, and
GET /groups/{id}/billing — authorization (billing_manage capability, i.e.
home_admin only), the client's constrained intent (interval only, never a
Price ID/amount/currency), duplicate-subscription protection, and Stripe
Customer reuse. stripe.Customer.create / stripe.checkout.Session.create /
stripe.billing_portal.Session.create are monkeypatched — no real Stripe
sandbox call is made.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import stripe
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import ensure_home_subscription, get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
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


async def _add_standard_partner(group_id: uuid.UUID, user: User) -> None:
    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=group_id,
                user_id=user.id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()


def _fake_customer(email: str) -> dict:
    return {"id": f"cus_{uuid.uuid4().hex[:12]}", "email": email}


def _fake_checkout_session(**kwargs: object) -> dict:
    return {"id": f"cs_{uuid.uuid4().hex[:12]}", "url": "https://checkout.stripe.com/test/session"}


def _fake_portal_session(**kwargs: object) -> dict:
    return {"id": f"bps_{uuid.uuid4().hex[:12]}", "url": "https://billing.stripe.com/test/session"}


# ---------------------------------------------------------------------------
# Client intent is constrained
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_cannot_supply_a_price_id_or_amount(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stripe.Customer, "create", lambda **kw: _fake_customer(kw.get("email", "")))
    monkeypatch.setattr(
        stripe.checkout.Session, "create", lambda **kw: _fake_checkout_session(**kw)
    )
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/billing/checkout-session",
        json={
            "interval": "month",
            "price_id": "price_attacker_controlled",
            "unit_amount": 1,
            "currency": "usd",
        },
    )
    assert response.status_code == 422  # StrictModel rejects the extra fields


@pytest.mark.asyncio
async def test_invalid_interval_is_rejected(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/billing/checkout-session",
        json={"interval": "fortnightly"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_admin_can_create_checkout_session(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stripe.Customer, "create", lambda **kw: _fake_customer(kw.get("email", "")))
    monkeypatch.setattr(
        stripe.checkout.Session, "create", lambda **kw: _fake_checkout_session(**kw)
    )
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/billing/checkout-session",
        json={"interval": "month"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["checkout_url"].startswith("https://checkout.stripe.com")


@pytest.mark.asyncio
async def test_standard_partner_cannot_create_checkout_session(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        partner = await _register_and_login(second_client, uuid.uuid4().hex[:10])
        await _add_standard_partner(home_id, partner)
        response = await unsafe(
            second_client,
            "POST",
            f"/api/v1/groups/{home_id}/billing/checkout-session",
            json={"interval": "month"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_standard_partner_cannot_open_portal_session(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        partner = await _register_and_login(second_client, uuid.uuid4().hex[:10])
        await _add_standard_partner(home_id, partner)
        response = await unsafe(
            second_client, "POST", f"/api/v1/groups/{home_id}/billing/portal-session"
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Duplicate protection / customer reuse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_checkout_reuses_the_same_stripe_customer(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"customer": 0}

    def fake_customer_create(**kw: object) -> dict:
        calls["customer"] += 1
        return _fake_customer(str(kw.get("email", "")))

    monkeypatch.setattr(stripe.Customer, "create", fake_customer_create)
    monkeypatch.setattr(
        stripe.checkout.Session, "create", lambda **kw: _fake_checkout_session(**kw)
    )
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    first = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/billing/checkout-session",
        json={"interval": "month"},
    )
    assert first.status_code == 200
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.status = SubscriptionStatus.cancelled  # allow a second attempt
        await db.commit()
    second = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/billing/checkout-session",
        json={"interval": "year"},
    )
    assert second.status_code == 200
    assert calls["customer"] == 1


@pytest.mark.asyncio
async def test_existing_live_stripe_subscription_rejects_a_new_checkout(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stripe_call_made = {"value": False}

    def fail_if_called(**kw: object) -> dict:
        stripe_call_made["value"] = True
        return _fake_checkout_session(**kw)

    monkeypatch.setattr(stripe.Customer, "create", lambda **kw: _fake_customer(""))
    monkeypatch.setattr(stripe.checkout.Session, "create", fail_if_called)
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.provider = SubscriptionProvider.stripe
        subscription.status = SubscriptionStatus.active
        subscription.external_subscription_id = "sub_existing"
        await db.commit()

    response = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/billing/checkout-session",
        json={"interval": "month"},
    )
    assert response.status_code == 409
    assert stripe_call_made["value"] is False


@pytest.mark.asyncio
async def test_complimentary_home_can_still_start_checkout(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checkout may be created while complimentary access exists — only
    verified Stripe activation later flips the provider (see
    docs/architecture/commercial-entitlements.md#complimentary-stripe-transitions)."""
    monkeypatch.setattr(stripe.Customer, "create", lambda **kw: _fake_customer(""))
    monkeypatch.setattr(
        stripe.checkout.Session, "create", lambda **kw: _fake_checkout_session(**kw)
    )
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.provider = SubscriptionProvider.complimentary
        from mykhaya.models import SubscriptionPlan

        subscription.plan = SubscriptionPlan.family
        await db.commit()

    response = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/billing/checkout-session",
        json={"interval": "month"},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Portal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_portal_session_requires_an_existing_stripe_customer(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    response = await unsafe(client, "POST", f"/api/v1/groups/{home_id}/billing/portal-session")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_portal_session_opens_for_the_billing_manager(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        stripe.billing_portal.Session, "create", lambda **kw: _fake_portal_session(**kw)
    )
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.external_customer_id = "cus_existing"
        await db.commit()
    response = await unsafe(client, "POST", f"/api/v1/groups/{home_id}/billing/portal-session")
    assert response.status_code == 200
    assert response.json()["portal_url"].startswith("https://billing.stripe.com")


# ---------------------------------------------------------------------------
# Minimal billing status surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_billing_status_reflects_capability_and_stripe_availability(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    response = await unsafe(client, "GET", f"/api/v1/groups/{home_id}/billing")
    assert response.status_code == 200
    payload = response.json()
    assert payload["stored_plan"] == "free"
    assert payload["effective_plan"] == "free"
    assert payload["can_manage_billing"] is True
    assert payload["stripe_billing_available"] is True
    assert payload["has_stripe_customer"] is False


@pytest.mark.asyncio
async def test_billing_status_forbids_non_member(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await _register_and_login(other_client, uuid.uuid4().hex[:10])
        response = await unsafe(other_client, "GET", f"/api/v1/groups/{home_id}/billing")
        assert response.status_code == 404
