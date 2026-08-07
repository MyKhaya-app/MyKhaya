"""Tests for Stage 10: Platform Admin Communications health dashboard, Timeline (what
happened, told chronologically) and Diagnostics (why something failed, filterable).
All three are read-only views over notification_deliveries/operational_heartbeats/
outbox_events — see docs/architecture/notification-engine.md.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    OperationalHeartbeat,
    OutboxEvent,
    PlatformAdministrator,
    PlatformRole,
    User,
)
from mykhaya.notifications.labels import friendly_status, notification_type_label
from mykhaya.security import password_hash

ADMIN_ORIGIN = "http://admin.localhost:8080"
ADMIN_PASSWORD = "A separate operator password!"
AdminFactory = Callable[[PlatformRole], Awaitable[PlatformAdministrator]]


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44240)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    ) as value:
        yield value


@pytest.fixture
async def admin_factory() -> AsyncIterator[AdminFactory]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        suffix = datetime.now(UTC).strftime("%H%M%S%f")
        async with SessionFactory() as db:
            row = PlatformAdministrator(
                email=f"comms-operator-{suffix}@example.com",
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
        "/api/v1/platform/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


async def make_user() -> User:
    async with SessionFactory() as db:
        user = User(email=unique_email("comms"), display_name="Comms Test User")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


def test_notification_type_label_falls_back_to_titlecase() -> None:
    assert notification_type_label("daily_briefing") == "Morning briefing"
    assert notification_type_label("some_new_type") == "Some new type"


def test_friendly_status_covers_all_states() -> None:
    assert friendly_status("sent", "email", retry_pending=False) == "Delivered"
    assert friendly_status("cancelled", "push", retry_pending=False) == "Cancelled"
    assert friendly_status("queued", "email", retry_pending=False) == "Queued"
    assert friendly_status("failed", "push", retry_pending=True) == "Push failed · Retry scheduled"
    assert friendly_status("failed", "push", retry_pending=False) == "Push failed"


@pytest.mark.asyncio
async def test_health_endpoint_reports_service_status(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)

    now = datetime.now(UTC)
    async with SessionFactory() as db:
        await db.merge(
            OperationalHeartbeat(
                service="worker",
                observed_at=now,
                last_success_at=now,
                safe_detail="Worker loop is active.",
            )
        )
        await db.merge(
            OperationalHeartbeat(
                service="scheduler",
                observed_at=now - timedelta(minutes=5),
                last_success_at=now - timedelta(minutes=5),
                safe_detail="Scheduler cycle completed.",
            )
        )
        await db.commit()

    response = await admin_client.get("/api/v1/platform/communications/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["worker"]["status"] == "running"
    assert body["scheduler"]["status"] == "stale"
    assert body["overall"] in {"degraded", "unhealthy"}
    assert "queue_depth" in body
    assert "deliveries_today" in body
    assert "failures_today" in body
    assert "retries_today" in body


@pytest.mark.asyncio
async def test_health_unavailable_when_no_heartbeat_recorded(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    async with SessionFactory() as db:
        await db.execute(delete(OperationalHeartbeat))
        await db.commit()

    response = await admin_client.get("/api/v1/platform/communications/health")
    assert response.status_code == 200
    body = response.json()
    assert body["worker"]["status"] == "unavailable"
    assert body["scheduler"]["status"] == "unavailable"
    assert body["overall"] == "unhealthy"


@pytest.mark.asyncio
async def test_timeline_orders_newest_first_and_labels_entries(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    user = await make_user()

    # Far-future timestamps guarantee these sort ahead of whatever else the full test
    # suite creates in the shared isolated test database around "now" — the timeline
    # endpoint has no recipient filter (that's Diagnostics' job), so this test can't
    # rely on being the only data on page 1.
    far_future = datetime.now(UTC) + timedelta(days=3650)
    async with SessionFactory() as db:
        older = NotificationDelivery(
            channel=NotificationChannel.in_app,
            recipient_user_id=user.id,
            notification_type="daily_briefing",
            idempotency_key=f"timeline-older-{uuid.uuid4()}",
            scheduled_at=far_future - timedelta(minutes=10),
            attempted_at=far_future - timedelta(minutes=10),
            status=NotificationDeliveryStatus.sent,
        )
        newer = NotificationDelivery(
            channel=NotificationChannel.push,
            recipient_user_id=user.id,
            notification_type="event_reminder",
            idempotency_key=f"timeline-newer-{uuid.uuid4()}",
            scheduled_at=far_future,
            attempted_at=far_future,
            status=NotificationDeliveryStatus.sent,
        )
        db.add_all([older, newer])
        await db.commit()

    response = await admin_client.get("/api/v1/platform/communications/timeline")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    matching = [row for row in items if row["recipient_display_name"] == "Comms Test User"]
    assert len(matching) == 2
    assert matching[0]["notification_type"] == "event_reminder"
    assert matching[0]["label"] == "Calendar reminder"
    assert matching[0]["friendly_status"] == "Delivered"
    assert matching[1]["notification_type"] == "daily_briefing"


@pytest.mark.asyncio
async def test_timeline_shows_retry_scheduled_for_pending_failure(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    user = await make_user()

    far_future = datetime.now(UTC) + timedelta(days=3650)
    async with SessionFactory() as db:
        event = OutboxEvent(
            topic="notification.email",
            payload={"recipient_email": user.email},
            processed_at=None,
        )
        db.add(event)
        await db.flush()
        delivery = NotificationDelivery(
            channel=NotificationChannel.email,
            recipient_user_id=user.id,
            notification_type="password_reset",
            idempotency_key=f"timeline-retry-{uuid.uuid4()}",
            outbox_event_id=event.id,
            scheduled_at=far_future,
            attempted_at=far_future,
            status=NotificationDeliveryStatus.failed,
            retry_count=1,
            sanitised_failure_reason="Email delivery temporarily unavailable.",
        )
        db.add(delivery)
        await db.commit()
        delivery_id = str(delivery.id)

    response = await admin_client.get("/api/v1/platform/communications/timeline")
    assert response.status_code == 200
    match = next(row for row in response.json()["items"] if row["id"] == delivery_id)
    assert match["friendly_status"] == "Email failed · Retry scheduled"


@pytest.mark.asyncio
async def test_diagnostics_filters_by_status_and_channel(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    user = await make_user()

    now = datetime.now(UTC)
    async with SessionFactory() as db:
        failed = NotificationDelivery(
            channel=NotificationChannel.push,
            recipient_user_id=user.id,
            notification_type="birthday_reminder",
            idempotency_key=f"diag-failed-{uuid.uuid4()}",
            scheduled_at=now,
            attempted_at=now,
            status=NotificationDeliveryStatus.failed,
            sanitised_failure_reason="Device unsubscribed or expired.",
        )
        sent = NotificationDelivery(
            channel=NotificationChannel.email,
            recipient_user_id=user.id,
            notification_type="birthday_reminder",
            idempotency_key=f"diag-sent-{uuid.uuid4()}",
            scheduled_at=now,
            attempted_at=now,
            status=NotificationDeliveryStatus.sent,
        )
        db.add_all([failed, sent])
        await db.commit()

    failures = await admin_client.get(
        "/api/v1/platform/communications/diagnostics",
        params={"status": "failed", "recipient_email": user.email},
    )
    assert failures.status_code == 200, failures.text
    items = failures.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["sanitised_failure_reason"] == "Device unsubscribed or expired."

    by_channel = await admin_client.get(
        "/api/v1/platform/communications/diagnostics",
        params={"channel": "email", "recipient_email": user.email},
    )
    assert by_channel.status_code == 200
    channel_items = by_channel.json()["items"]
    assert len(channel_items) == 1
    assert channel_items[0]["channel"] == "email"


@pytest.mark.asyncio
async def test_diagnostics_unknown_status_rejected(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await admin_client.get(
        "/api/v1/platform/communications/diagnostics", params={"status": "not-a-status"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_diagnostics_unknown_recipient_returns_empty(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await admin_client.get(
        "/api/v1/platform/communications/diagnostics",
        params={"recipient_email": "nobody-here@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_unauthenticated_communications_requests_are_rejected() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ADMIN_ORIGIN, headers={"Origin": ADMIN_ORIGIN}
    ) as client:
        for path in ("/health", "/timeline", "/diagnostics"):
            response = await client.get(f"/api/v1/platform/communications{path}")
            assert response.status_code in (401, 403, 404)
