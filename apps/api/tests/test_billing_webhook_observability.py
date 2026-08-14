"""Phase 7: webhook processing observability — a failed webhook attempt is
recorded (StripeWebhookFailure) without ever blocking Stripe's own retry of
that same event, and Platform Control Centre can see both per-Home and
deployment-wide webhook health. Reuses test_billing_webhooks.py's real
HMAC-signature helper (no monkeypatched signature verification) — see
docs/architecture/commercial-entitlements.md#webhook-observability.
"""

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    PlatformAdministrator,
    PlatformRole,
    StripeWebhookEvent,
    StripeWebhookFailure,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token, password_hash

ORIGIN = "http://localhost:8080"
ADMIN_ORIGIN = "http://admin.localhost:8080"
PASSWORD = "Correct horse battery staple!"
ADMIN_PASSWORD = "A separate operator password!"
WEBHOOK_SECRET = "whsec_test_secret_abc123"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44201)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
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
    csrf_cookie_name = "mk_admin_csrf" if "admin" in str(client.base_url) else "mk_csrf"
    csrf = client.cookies.get(csrf_cookie_name)
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


async def _make_admin() -> PlatformAdministrator:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with SessionFactory() as db:
        row = PlatformAdministrator(
            email=f"operator-{suffix}@example.com",
            display_name="Test Operator",
            password_hash=password_hash.hash(ADMIN_PASSWORD),
            role=PlatformRole.owner,
            mfa_enrolled=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def _admin_login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text


def _signed_headers(payload: bytes, secret: str = WEBHOOK_SECRET) -> dict[str, str]:
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload.decode()}"
    signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={timestamp},v1={signature}"}


def _malformed_period_event(group_id: uuid.UUID, event_id: str) -> bytes:
    """A structurally valid, correctly signed event whose current_period_end
    is not a number — datetime.fromtimestamp raises inside
    apply_stripe_subscription_state, so this genuinely fails processing
    rather than simulating a failure by monkeypatching internals."""
    return json.dumps(
        {
            "id": event_id,
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": f"sub_{uuid.uuid4().hex[:12]}",
                    "status": "active",
                    "cancel_at_period_end": False,
                    "customer": f"cus_{uuid.uuid4().hex[:12]}",
                    "current_period_start": "not-a-timestamp",
                    "current_period_end": "not-a-timestamp",
                    "metadata": {"mykhaya_group_id": str(group_id)},
                    "items": {
                        "data": [
                            {"price": {"id": "price_month123", "recurring": {"interval": "month"}}}
                        ]
                    },
                }
            },
        }
    ).encode()


def _valid_subscription_event(group_id: uuid.UUID, event_id: str) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": f"sub_{uuid.uuid4().hex[:12]}",
                    "status": "active",
                    "cancel_at_period_end": False,
                    "customer": f"cus_{uuid.uuid4().hex[:12]}",
                    "current_period_start": 1_700_000_000,
                    "current_period_end": 1_702_592_000,
                    "metadata": {"mykhaya_group_id": str(group_id)},
                    "items": {
                        "data": [
                            {"price": {"id": "price_month123", "recurring": {"interval": "month"}}}
                        ]
                    },
                }
            },
        }
    ).encode()


# ---------------------------------------------------------------------------
# A failure is observable, but never dedupes away Stripe's retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_processing_failure_is_recorded_without_blocking_retry(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    event_id = f"evt_{uuid.uuid4().hex[:16]}"

    failing_payload = _malformed_period_event(home_id, event_id)
    response = await client.post(
        "/api/v1/billing/stripe/webhook",
        content=failing_payload,
        headers=_signed_headers(failing_payload),
    )
    assert response.status_code == 500

    async with SessionFactory() as db:
        dedup_row = await db.scalar(
            select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == event_id)
        )
        assert dedup_row is None, "a failed attempt must never commit a dedup row"
        failure_row = await db.scalar(
            select(StripeWebhookFailure).where(StripeWebhookFailure.stripe_event_id == event_id)
        )
        assert failure_row is not None
        assert "stripe" not in failure_row.error_message.lower()  # no raw provider payload

    # Stripe's own retry, same event ID, this time with a well-formed payload.
    retry_payload = _valid_subscription_event(home_id, event_id)
    retry_response = await client.post(
        "/api/v1/billing/stripe/webhook",
        content=retry_payload,
        headers=_signed_headers(retry_payload),
    )
    assert retry_response.status_code == 200
    async with SessionFactory() as db:
        dedup_row = await db.scalar(
            select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == event_id)
        )
        assert dedup_row is not None
        assert dedup_row.outcome == "processed"


# ---------------------------------------------------------------------------
# Platform Control Centre visibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_health_endpoint_reflects_recent_failures(
    client: AsyncClient, admin_client: AsyncClient
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    for _ in range(3):
        payload = _malformed_period_event(home_id, f"evt_{uuid.uuid4().hex[:16]}")
        response = await client.post(
            "/api/v1/billing/stripe/webhook", content=payload, headers=_signed_headers(payload)
        )
        assert response.status_code == 500

    admin = await _make_admin()
    await _admin_login(admin_client, admin)
    health = await unsafe(admin_client, "GET", "/api/v1/platform/subscriptions/webhook-health")
    assert health.status_code == 200
    body = health.json()
    assert body["configured"] is True
    assert body["state"] == "warning"
    assert body["recent_failure_count"] >= 3
    assert len(body["recent_failures"]) >= 3


@pytest.mark.asyncio
async def test_subscription_detail_shows_recent_webhook_events_for_that_home(
    client: AsyncClient, admin_client: AsyncClient
) -> None:
    home_id = await _make_home(client, uuid.uuid4().hex[:10])
    event_id = f"evt_{uuid.uuid4().hex[:16]}"
    payload = _valid_subscription_event(home_id, event_id)
    response = await client.post(
        "/api/v1/billing/stripe/webhook", content=payload, headers=_signed_headers(payload)
    )
    assert response.status_code == 200

    admin = await _make_admin()
    await _admin_login(admin_client, admin)
    detail = await unsafe(admin_client, "GET", f"/api/v1/platform/subscriptions/{home_id}")
    assert detail.status_code == 200
    events = detail.json()["recent_webhook_events"]
    assert any(event["stripe_event_id"] == event_id for event in events)
