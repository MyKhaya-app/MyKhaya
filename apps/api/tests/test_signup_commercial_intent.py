"""Phase 5 (public pricing and signup/onboarding) — this phase adds no new
commercial-state endpoints, only a public-facing UI in front of the
already-public Phase 3/4 pricing endpoints and the existing registration /
Home-creation / Checkout endpoints. These tests confirm the properties that
make that safe:

- registration and Home creation reject any attempt to inject commercial
  fields (plan/provider/status) — StrictModel's extra="forbid" already
  enforces this; these tests prove it rather than assume it.
- a freshly created Home is always Free/free/active, regardless of query
  string or request body content.
- joining an existing Home via an invitation never creates a second Home or
  touches that Home's existing commercial state.
- GET /billing/pricing and GET /billing/plans (the endpoints the public
  homepage now reads) remain public, rate-limited and free of secret/
  provider-internal data — see test_billing_pricing.py and
  test_billing_plan_page.py for the full existing coverage; this file adds
  only the signup-specific angle.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
import stripe
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from mykhaya.billing import pricing as pricing_module
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
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


@pytest.fixture
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


@pytest.fixture
def _clear_pricing_cache() -> Iterator[None]:
    pricing_module.clear_pricing_cache()
    yield
    pricing_module.clear_pricing_cache()


def _fake_price(price_id: str, *, interval: str, unit_amount: int) -> dict:
    return {
        "id": price_id,
        "active": True,
        "currency": "gbp",
        "unit_amount": unit_amount,
        "recurring": {"interval": interval},
    }


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def _register_and_login(client: AsyncClient, suffix: str) -> User:
    email = f"signup-{suffix}@example.com"
    register = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Signup Test", "password": PASSWORD},
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


def _suffix() -> str:
    return datetime.now(UTC).strftime("%H%M%S%f")


# ---------------------------------------------------------------------------
# Registration cannot be used to inject commercial state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_rejects_commercial_fields(client: AsyncClient) -> None:
    suffix = _suffix()
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={
            "email": f"inject-{suffix}@example.com",
            "display_name": "Injector",
            "password": PASSWORD,
            "plan": "family",
            "provider": "stripe",
            "status": "active",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_group_creation_rejects_commercial_fields(client: AsyncClient) -> None:
    await _register_and_login(client, _suffix())
    response = await unsafe(
        client,
        "POST",
        "/api/v1/groups",
        json={"name": "Injected Home", "plan": "family", "provider": "stripe", "status": "active"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_new_home_is_always_free_regardless_of_query_string(client: AsyncClient) -> None:
    """A public pricing CTA can carry ?plan=family&interval=year into
    /register, but that value never reaches account or Home creation — the
    frontend only ever uses it to pre-fill copy and, later, to call the
    existing authenticated Checkout endpoint. Registration and Home creation
    themselves take no plan parameter at all."""
    await _register_and_login(client, _suffix())
    created = await unsafe(
        client,
        "POST",
        "/api/v1/groups?plan=family&interval=year",
        json={"name": "Query String Home"},
    )
    assert created.status_code == 201
    group_id = uuid.UUID(created.json()["id"])
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, group_id)
        assert subscription is not None
        assert subscription.plan == SubscriptionPlan.free
        assert subscription.provider == SubscriptionProvider.free
        assert subscription.status == SubscriptionStatus.active


# ---------------------------------------------------------------------------
# Invited members never get a commercial-selection surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invited_member_joins_existing_home_without_a_new_home_or_plan_choice(
    client: AsyncClient,
) -> None:
    suffix = _suffix()
    await _register_and_login(client, suffix)
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Existing Home"})
    assert created.status_code == 201
    group_id = created.json()["id"]

    invitee_email = f"invitee-{suffix}@example.com"
    invitation = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": group_id, "email": invitee_email, "role": "adult_member"},
    )
    assert invitation.status_code == 201
    raw_invitation = derived_token(
        uuid.UUID(invitation.json()["id"]),
        "invitation",
        get_settings().secret_key.get_secret_value(),
    )

    async with SessionFactory() as db:
        subscription_before = await get_home_subscription(db, uuid.UUID(group_id))
        assert subscription_before is not None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as invitee_client:
        register = await unsafe(
            invitee_client,
            "POST",
            "/api/v1/auth/register",
            json={
                "email": invitee_email,
                "display_name": "Invited Member",
                "password": PASSWORD,
                "invitation_token": raw_invitation,
            },
        )
        assert register.status_code == 202
        async with SessionFactory() as db:
            invitee = await db.scalar(select(User).where(User.email == invitee_email))
            assert invitee is not None
            token = await db.scalar(
                select(ActionToken)
                .where(
                    ActionToken.user_id == invitee.id,
                    ActionToken.purpose == TokenPurpose.verify_email,
                )
                .order_by(ActionToken.created_at.desc())
            )
            assert token is not None
            raw_verify = derived_token(
                token.id,
                TokenPurpose.verify_email.value,
                get_settings().secret_key.get_secret_value(),
            )
        assert (
            await unsafe(
                invitee_client, "POST", "/api/v1/auth/verify-email", json={"token": raw_verify}
            )
        ).status_code == 200
        assert (
            await unsafe(
                invitee_client,
                "POST",
                "/api/v1/auth/login",
                json={"email": invitee_email, "password": PASSWORD},
            )
        ).status_code == 200

        # Accepting the invitation joins the *existing* Home — no plan
        # purchase surface, no new Home, no Checkout call is ever made here.
        accepted = await unsafe(
            invitee_client, "POST", "/api/v1/invitations/accept", json={"token": raw_invitation}
        )
        assert accepted.status_code == 200

        homes = await invitee_client.get("/api/v1/groups")
        assert homes.status_code == 200
        home_ids = [home["id"] for home in homes.json()]
        assert home_ids == [group_id]

    async with SessionFactory() as db:
        subscription_after = await get_home_subscription(db, uuid.UUID(group_id))
        assert subscription_after is not None
        assert subscription_after.plan == subscription_before.plan
        assert subscription_after.provider == subscription_before.provider
        assert subscription_after.status == subscription_before.status


# ---------------------------------------------------------------------------
# The public homepage reads the exact same pricing the authenticated app does
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_pricing_is_identical_whether_or_not_the_caller_is_signed_in(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    _stripe_configured: None,
    _clear_pricing_cache: None,
) -> None:
    """The public homepage, the direct-signup plan step, and the
    authenticated Settings -> Plan & Billing page all call the same
    GET /billing/pricing endpoint — there is no second amount calculation
    to drift out of sync. This proves an anonymous caller and a signed-in
    caller get byte-identical pricing for the same configured Stripe
    prices."""

    def fake_retrieve(price_id: str, **_: object) -> dict:
        if price_id == "price_month123":
            return _fake_price(price_id, interval="month", unit_amount=399)
        return _fake_price(price_id, interval="year", unit_amount=3900)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)

    anonymous = await client.get("/api/v1/billing/pricing")
    assert anonymous.status_code == 200

    await _register_and_login(client, _suffix())
    signed_in = await client.get("/api/v1/billing/pricing")
    assert signed_in.status_code == 200

    assert anonymous.json() == signed_in.json()
    assert "price_month123" not in anonymous.text
    assert "price_year123" not in anonymous.text
