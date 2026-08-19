"""POST /api/v1/billing/stripe/webhook — signature verification, durable
idempotency, and the webhook-driven commercial lifecycle. Uses a real HMAC
signature built the same way Stripe itself signs a payload (see
_signed_headers) so signature verification is genuinely exercised end to
end, not mocked away. stripe.Subscription.retrieve is monkeypatched where
the handler needs to refetch current state (invoice events) — no real
Stripe sandbox call is made anywhere in this file.
"""

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator

import pytest
import stripe
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import effective_plan, get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    HomeSubscriptionEvent,
    StripeWebhookEvent,
    SubscriptionPlan,
    SubscriptionStatus,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"
WEBHOOK_SECRET = "whsec_test_secret_abc123"


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
            "stripe_webhook_secret": SecretStr(WEBHOOK_SECRET),
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


async def _make_home(client: AsyncClient, suffix: str) -> uuid.UUID:
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
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Test Home"})
    assert group.status_code == 201
    return uuid.UUID(group.json()["id"])


def _signed_headers(payload: bytes, secret: str = WEBHOOK_SECRET) -> dict[str, str]:
    """Builds a Stripe-Signature header the way Stripe itself signs
    payloads: t=<timestamp>,v1=<hmac_sha256(f"{t}.{payload}", secret)>."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload.decode()}"
    signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={timestamp},v1={signature}"}


def _event(event_type: str, data_object: dict, event_id: str | None = None) -> bytes:
    return json.dumps(
        {
            "id": event_id or f"evt_{uuid.uuid4().hex[:16]}",
            "type": event_type,
            "data": {"object": data_object},
        }
    ).encode()


def _subscription_object(
    group_id: uuid.UUID,
    *,
    status: str = "active",
    sub_id: str | None = None,
    customer: str | None = None,
    price_id: str = "price_month123",
    interval: str = "month",
) -> dict:
    return {
        "id": sub_id or f"sub_{uuid.uuid4().hex[:12]}",
        "status": status,
        "cancel_at_period_end": False,
        "customer": customer or f"cus_{uuid.uuid4().hex[:12]}",
        "current_period_start": 1_700_000_000,
        "current_period_end": 1_702_592_000,
        "metadata": {"mykhaya_group_id": str(group_id)},
        "items": {"data": [{"price": {"id": price_id, "recurring": {"interval": interval}}}]},
    }


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected_and_makes_no_change(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    payload = _event("customer.subscription.created", _subscription_object(home_id))
    response = await client.post(
        "/api/v1/billing/stripe/webhook",
        content=payload,
        headers={"Stripe-Signature": "t=1,v1=deadbeef"},
    )
    assert response.status_code == 400
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.free


@pytest.mark.asyncio
async def test_valid_signature_is_accepted(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    payload = _event("customer.subscription.created", _subscription_object(home_id))
    response = await client.post(
        "/api/v1/billing/stripe/webhook", content=payload, headers=_signed_headers(payload)
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Checkout completion does not activate Family
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_session_completed_records_ids_but_does_not_activate_family(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    session_obj = {
        "id": "cs_test_123",
        "customer": "cus_from_checkout",
        "subscription": "sub_from_checkout",
        "client_reference_id": str(home_id),
        "metadata": {"mykhaya_group_id": str(home_id)},
    }
    payload = _event("checkout.session.completed", session_obj)
    response = await client.post(
        "/api/v1/billing/stripe/webhook", content=payload, headers=_signed_headers(payload)
    )
    assert response.status_code == 200

    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.free
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        assert subscription.external_customer_id == "cus_from_checkout"
        assert subscription.external_subscription_id == "sub_from_checkout"


@pytest.mark.asyncio
async def test_checkout_session_accepts_expanded_customer_and_subscription_objects(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    payload = _event(
        "checkout.session.completed",
        {
            "customer": {"id": "cus_expanded"},
            "subscription": {"id": "sub_expanded"},
            "client_reference_id": str(home_id),
        },
    )
    response = await client.post(
        "/api/v1/billing/stripe/webhook", content=payload, headers=_signed_headers(payload)
    )
    assert response.status_code == 200
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        assert subscription.external_customer_id == "cus_expanded"
        assert subscription.external_subscription_id == "sub_expanded"


@pytest.mark.asyncio
async def test_subscription_created_before_checkout_completed_still_activates_family(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    subscription_payload = _event(
        "customer.subscription.created",
        _subscription_object(home_id, status="active", sub_id=sub_id),
    )
    checkout_payload = _event(
        "checkout.session.completed",
        {
            "customer": "cus_ordered",
            "subscription": sub_id,
            "client_reference_id": str(home_id),
        },
    )
    first = await client.post(
        "/api/v1/billing/stripe/webhook",
        content=subscription_payload,
        headers=_signed_headers(subscription_payload),
    )
    second = await client.post(
        "/api/v1/billing/stripe/webhook",
        content=checkout_payload,
        headers=_signed_headers(checkout_payload),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        assert await effective_plan(db, home_id) == SubscriptionPlan.family
        assert subscription.external_subscription_id == sub_id


# ---------------------------------------------------------------------------
# Activation via confirmed subscription status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_created_active_activates_family(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    payload = _event(
        "customer.subscription.created", _subscription_object(home_id, status="active")
    )
    response = await client.post(
        "/api/v1/billing/stripe/webhook", content=payload, headers=_signed_headers(payload)
    )
    assert response.status_code == 200
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.family


@pytest.mark.asyncio
async def test_confirm_checkout_reconciles_authoritative_active_subscription(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    sub_id = "sub_confirmed_123"
    customer_id = "cus_confirmed_123"
    session = {
        "id": "cs_confirmed_123",
        "mode": "subscription",
        "status": "complete",
        "customer": customer_id,
        "subscription": sub_id,
        "client_reference_id": str(home_id),
        "metadata": {"mykhaya_group_id": str(home_id)},
    }
    subscription = _subscription_object(
        home_id,
        status="active",
        sub_id=sub_id,
        customer=customer_id,
    )
    subscription["customer"] = {"id": customer_id}
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", lambda *args, **kwargs: session)
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda *args, **kwargs: subscription)

    response = await client.post(
        "/api/v1/billing/stripe/confirm-checkout",
        json={"session_id": "cs_confirmed_123"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["confirmed"] is True
    assert response.json()["effective_plan"] == "family"
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.family


@pytest.mark.asyncio
async def test_confirm_checkout_rejects_session_for_another_home(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_home_id = await _make_home(client, uuid.uuid4().hex[:10])
    second_home_id = await _make_home(client, uuid.uuid4().hex[:10])
    session = {
        "id": "cs_other_home",
        "mode": "subscription",
        "status": "complete",
        "customer": "cus_other_home",
        "subscription": "sub_other_home",
        "client_reference_id": str(first_home_id),
        "metadata": {"mykhaya_group_id": str(first_home_id)},
    }
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", lambda *args, **kwargs: session)
    response = await client.post(
        "/api/v1/billing/stripe/confirm-checkout",
        json={"session_id": "cs_other_home"},
    )
    assert response.status_code == 403
    async with SessionFactory() as db:
        assert await effective_plan(db, second_home_id) == SubscriptionPlan.free


@pytest.mark.asyncio
async def test_confirm_checkout_does_not_activate_incomplete_subscription(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    session = {
        "id": "cs_incomplete_sub",
        "mode": "subscription",
        "status": "complete",
        "customer": "cus_incomplete_sub",
        "subscription": "sub_incomplete_sub",
        "client_reference_id": str(home_id),
        "metadata": {"mykhaya_group_id": str(home_id)},
    }
    subscription = _subscription_object(
        home_id,
        status="incomplete",
        sub_id="sub_incomplete_sub",
        customer="cus_incomplete_sub",
    )
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", lambda *args, **kwargs: session)
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda *args, **kwargs: subscription)
    response = await client.post(
        "/api/v1/billing/stripe/confirm-checkout",
        json={"session_id": "cs_incomplete_sub"},
    )
    assert response.status_code == 200
    assert response.json()["confirmed"] is False
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.free


@pytest.mark.asyncio
async def test_subscription_created_incomplete_does_not_activate_family(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    payload = _event(
        "customer.subscription.created", _subscription_object(home_id, status="incomplete")
    )
    response = await client.post(
        "/api/v1/billing/stripe/webhook", content=payload, headers=_signed_headers(payload)
    )
    assert response.status_code == 200
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.free


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_event_delivery_is_idempotent(client: AsyncClient) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    event_id = f"evt_{uuid.uuid4().hex[:16]}"
    payload = _event(
        "customer.subscription.created",
        _subscription_object(home_id, status="active"),
        event_id=event_id,
    )
    first = await client.post(
        "/api/v1/billing/stripe/webhook", content=payload, headers=_signed_headers(payload)
    )
    second = await client.post(
        "/api/v1/billing/stripe/webhook", content=payload, headers=_signed_headers(payload)
    )
    assert first.status_code == 200
    assert second.status_code == 200

    async with SessionFactory() as db:
        stored_events = (
            await db.scalars(
                select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == event_id)
            )
        ).all()
        assert len(stored_events) == 1

        history = (
            await db.scalars(
                select(HomeSubscriptionEvent).where(HomeSubscriptionEvent.group_id == home_id)
            )
        ).all()
        activations = [e for e in history if e.event_type == "stripe_subscription_activated"]
        assert len(activations) == 1


# ---------------------------------------------------------------------------
# Unhandled events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unhandled_event_type_is_acknowledged_and_ignored(client: AsyncClient) -> None:
    payload = _event("customer.updated", {"id": "cus_123"})
    response = await client.post(
        "/api/v1/billing/stripe/webhook", content=payload, headers=_signed_headers(payload)
    )
    assert response.status_code == 200
    event_id = json.loads(payload)["id"]
    async with SessionFactory() as db:
        stored = await db.scalar(
            select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == event_id)
        )
        assert stored is not None
        assert stored.outcome == "ignored"


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_deleted_returns_effective_plan_to_free_without_deleting_home(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    activate_payload = _event(
        "customer.subscription.created",
        _subscription_object(home_id, status="active", sub_id=sub_id),
    )
    await client.post(
        "/api/v1/billing/stripe/webhook",
        content=activate_payload,
        headers=_signed_headers(activate_payload),
    )
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.family

    delete_payload = _event(
        "customer.subscription.deleted",
        _subscription_object(home_id, status="canceled", sub_id=sub_id),
    )
    response = await client.post(
        "/api/v1/billing/stripe/webhook",
        content=delete_payload,
        headers=_signed_headers(delete_payload),
    )
    assert response.status_code == 200

    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.free
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        assert subscription.status == SubscriptionStatus.cancelled
        # Home itself (and its data) is never touched by a Stripe cancellation.
        home = await unsafe(client, "GET", f"/api/v1/groups/{home_id}")
    assert home.status_code == 200


# ---------------------------------------------------------------------------
# Payment failure refetches the current Stripe subscription
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoice_payment_failed_refetches_subscription_and_sets_past_due(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    activate_payload = _event(
        "customer.subscription.created",
        _subscription_object(home_id, status="active", sub_id=sub_id),
    )
    await client.post(
        "/api/v1/billing/stripe/webhook",
        content=activate_payload,
        headers=_signed_headers(activate_payload),
    )

    def fake_retrieve(subscription_id: str, **kwargs: object) -> dict:
        assert subscription_id == sub_id
        return _subscription_object(home_id, status="past_due", sub_id=sub_id)

    monkeypatch.setattr(stripe.Subscription, "retrieve", fake_retrieve)

    invoice_payload = _event("invoice.payment_failed", {"subscription": sub_id})
    response = await client.post(
        "/api/v1/billing/stripe/webhook",
        content=invoice_payload,
        headers=_signed_headers(invoice_payload),
    )
    assert response.status_code == 200

    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        assert subscription.status == SubscriptionStatus.past_due
        # past_due is still honoured — Family access retained during dunning.
        assert await effective_plan(db, home_id) == SubscriptionPlan.family
