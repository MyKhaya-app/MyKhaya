"""Slice 4.5 — lifecycle enforcement for scheduled work and notifications.

Covers both layers: creation-side (notify() refuses to enqueue/deliver
anything for an inactive User or Group, and the scan/content queries in
briefing.py/birthdays.py/meal_plans.py exclude inactive Homes) and
delivery-side (worker.py re-verifies eligibility for an already-queued
push/email at dispatch time, terminally — never retried as a failure).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya import worker
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    CalendarEvent,
    FeatureKey,
    FeatureOverride,
    Group,
    HouseholdRelationship,
    Membership,
    Notification,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationPreferences,
    OutboxEvent,
    PermissionProfile,
    PushSubscription,
    Role,
    SubscriptionPlan,
    TokenPurpose,
    User,
    WorkerJobRecord,
)
from mykhaya.notifications.briefing import deliver_daily_briefing
from mykhaya.notifications.engine import notify
from mykhaya.notifications.reminders import deliver_event_reminder
from mykhaya.notifications.visibility import active_membership
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"
TZ = ZoneInfo("Europe/London")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


async def create_verified_user(client: AsyncClient, email: str, name: str) -> uuid.UUID:
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": PASSWORD},
    )
    assert response.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        user_id = user.id
        token = await db.scalar(
            select(ActionToken)
            .where(ActionToken.user_id == user.id, ActionToken.purpose == TokenPurpose.verify_email)
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
    return user_id


async def create_home(client: AsyncClient, name: str = "Lifecycle Test Home") -> uuid.UUID:
    response = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert response.status_code == 201, response.text
    home_id = uuid.UUID(response.json()["id"])
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.calendar, group_id=home_id, enabled=True))
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=True)
        )
        await db.commit()
    return home_id


async def set_home_active(group_id: uuid.UUID, active: bool) -> None:
    async with SessionFactory() as db:
        group = await db.get(Group, group_id)
        assert group is not None
        group.is_active = active
        group.suspended_at = None if active else datetime.now(UTC)
        await db.commit()


async def set_user_active(user_id: uuid.UUID, active: bool, *, archived: bool = False) -> None:
    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.is_active = active
        user.suspended_at = None if active else datetime.now(UTC)
        user.archived_at = datetime.now(UTC) if archived else None
        await db.commit()


async def enable_push(user_id: uuid.UUID) -> None:
    async with SessionFactory() as db:
        db.add(
            PushSubscription(
                user_id=user_id,
                endpoint=f"https://push.example/{uuid.uuid4()}",
                p256dh_key="abc",
                auth_key="def",
            )
        )
        await db.commit()


async def enable_email(user_id: uuid.UUID) -> None:
    async with SessionFactory() as db:
        prefs = await db.scalar(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
        )
        if prefs is None:
            prefs = NotificationPreferences(user_id=user_id)
            db.add(prefs)
        prefs.email_enabled = True
        await db.commit()


async def join_home(home_id: uuid.UUID, email: str) -> uuid.UUID:
    """Registers a second user and joins them to home_id as a standard adult
    member directly (bypassing the invitation-acceptance HTTP flow, which is
    orthogonal to what's under test here) — mirrors test_calendar_
    notifications.py's own _join_home helper."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        user_id = await create_verified_user(second_client, email, "Second Member")
    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=home_id,
                user_id=user_id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()
    return user_id


async def enable_briefing(user_id: uuid.UUID, *, timezone: str = "Europe/London") -> None:
    """Registration's own verification email already runs through notify(),
    which lazily creates a NotificationPreferences row — so this updates
    in place rather than inserting a second row and violating the
    one-row-per-user unique constraint."""
    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.timezone = timezone
        prefs = await db.scalar(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
        )
        if prefs is None:
            prefs = NotificationPreferences(user_id=user_id)
            db.add(prefs)
        prefs.daily_briefing_enabled = True
        prefs.empty_day_briefing_enabled = True
        await db.commit()


async def outbox_event_for_key(
    db: AsyncSession, idempotency_key: str, *, channel: str
) -> OutboxEvent:
    """Locates the OutboxEvent this test's own notify() call produced, via
    the NotificationDelivery.idempotency_key it was given — never a bare
    `topic ==` query, which would also match unrelated events already in
    the database from registration's own verification email or from
    earlier tests sharing this container's database."""
    pattern = f"{idempotency_key}:email" if channel == "email" else f"{idempotency_key}:{channel}:%"
    if channel == "email":
        delivery = await db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.idempotency_key == pattern)
        )
    else:
        delivery = await db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.idempotency_key.like(pattern))
        )
    assert delivery is not None, f"no queued {channel} delivery found for key {idempotency_key}"
    assert delivery.outbox_event_id is not None
    event = await db.get(OutboxEvent, delivery.outbox_event_id)
    assert event is not None
    return event


# ---------------------------------------------------------------------------
# notify() — creation-side lifecycle enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_suppresses_disabled_user(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("disabled"), "Disabled User")
    await set_user_active(user_id, False)

    async with SessionFactory() as db:
        result = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Time to take the bins out.",
            idempotency_key=f"test:disabled-user:{user_id}",
        )
        await db.commit()
        assert result is None
        assert (
            await db.scalar(select(Notification).where(Notification.recipient_user_id == user_id))
        ) is None


@pytest.mark.asyncio
async def test_notify_suppresses_archived_user(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("archived"), "Archived User")
    await set_user_active(user_id, False, archived=True)

    async with SessionFactory() as db:
        result = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Time to take the bins out.",
            idempotency_key=f"test:archived-user:{user_id}",
        )
        await db.commit()
        assert result is None


@pytest.mark.asyncio
async def test_notify_suppresses_disabled_home(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("homeuser"), "Home User")
    home_id = await create_home(client)
    await set_home_active(home_id, False)

    async with SessionFactory() as db:
        result = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Time to take the bins out.",
            idempotency_key=f"test:disabled-home:{user_id}",
            group_id=home_id,
        )
        await db.commit()
        assert result is None
        assert (
            await db.scalar(select(Notification).where(Notification.recipient_user_id == user_id))
        ) is None


@pytest.mark.asyncio
async def test_notify_suppresses_archived_home(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("archhomeuser"), "Home User")
    home_id = await create_home(client)
    async with SessionFactory() as db:
        group = await db.get(Group, home_id)
        assert group is not None
        group.is_active = False
        group.archived_at = datetime.now(UTC)
        await db.commit()

    async with SessionFactory() as db:
        result = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Time to take the bins out.",
            idempotency_key=f"test:archived-home:{user_id}",
            group_id=home_id,
        )
        await db.commit()
        assert result is None


@pytest.mark.asyncio
async def test_notify_inactive_home_a_does_not_suppress_active_home_b(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("multihome"), "Multi Home User")
    home_a = await create_home(client, "Home A")
    home_b = await create_home(client, "Home B")
    await set_home_active(home_a, False)

    async with SessionFactory() as db:
        suppressed = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="From Home A",
            body="Should be suppressed.",
            idempotency_key=f"test:multihome-a:{user_id}",
            group_id=home_a,
        )
        allowed = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="From Home B",
            body="Should be delivered.",
            idempotency_key=f"test:multihome-b:{user_id}",
            group_id=home_b,
        )
        await db.commit()
        assert suppressed is None
        assert allowed is not None


@pytest.mark.asyncio
async def test_notify_mandatory_email_type_still_sends_for_an_inactive_user(
    client: AsyncClient,
) -> None:
    """Account-security messages (MANDATORY_EMAIL_TYPES) are the one
    documented exemption — an inactive user can still receive e.g. a
    password reset, matching the existing always-deliver architecture."""
    user_id = await create_verified_user(client, unique_email("mandatory"), "Mandatory User")
    await set_user_active(user_id, False)

    async with SessionFactory() as db:
        key = f"test:mandatory-inactive-user:{user_id}"
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="password_reset",
            title="Reset your password",
            body="Use this link.",
            idempotency_key=key,
        )
        await db.commit()
        delivery = await db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.idempotency_key == f"{key}:email"
            )
        )
        assert delivery is not None


@pytest.mark.asyncio
async def test_notify_mandatory_email_type_still_blocked_for_an_inactive_home(
    client: AsyncClient,
) -> None:
    """The Home check has no MANDATORY_EMAIL_TYPES exemption — a household
    invitation must never go out for an archived/disabled Home."""
    user_id = await create_verified_user(client, unique_email("invitee"), "Invitee")
    home_id = await create_home(client)
    await set_home_active(home_id, False)

    async with SessionFactory() as db:
        key = f"test:mandatory-inactive-home:{user_id}"
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_invitation",
            title="You're invited",
            body="Join the Home.",
            idempotency_key=key,
            group_id=home_id,
        )
        await db.commit()
        delivery = await db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.idempotency_key == f"{key}:email"
            )
        )
        assert delivery is None


@pytest.mark.asyncio
async def test_restored_user_receives_notifications_normally(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("restored"), "Restored User")
    await set_user_active(user_id, False)
    await set_user_active(user_id, True)

    async with SessionFactory() as db:
        result = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Time to take the bins out.",
            idempotency_key=f"test:restored-user:{user_id}",
        )
        await db.commit()
        assert result is not None


@pytest.mark.asyncio
async def test_restored_home_generates_notifications_normally(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("restoredhome"), "Home User")
    home_id = await create_home(client)
    await set_home_active(home_id, False)
    await set_home_active(home_id, True)

    async with SessionFactory() as db:
        result = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Time to take the bins out.",
            idempotency_key=f"test:restored-home:{user_id}",
            group_id=home_id,
        )
        await db.commit()
        assert result is not None


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_removed_membership_is_not_operationally_active(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("removed"), "Removed Member")
    home_id = await create_home(client)
    async with SessionFactory() as db:
        membership = await db.scalar(
            select(Membership).where(
                Membership.group_id == home_id, Membership.user_id == user_id
            )
        )
        assert membership is not None
        membership.removed_at = datetime.now(UTC)
        await db.commit()

    async with SessionFactory() as db:
        assert await active_membership(db, home_id, user_id) is None


# ---------------------------------------------------------------------------
# Outbox / worker delivery-time suppression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_skips_queued_push_after_user_disabled(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("queuedpush"), "Queued Push User")
    await enable_push(user_id)

    async with SessionFactory() as db:
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Time to take the bins out.",
            idempotency_key=f"test:queued-push:{user_id}",
        )
        await db.commit()
        event = await outbox_event_for_key(db, "test:queued-push:" + str(user_id), channel="push")
        event_id = event.id

    await set_user_active(user_id, False)
    await worker.process(event_id)

    async with SessionFactory() as db:
        event = await db.get(OutboxEvent, event_id)
        job = await db.get(WorkerJobRecord, event_id)
        delivery = await db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.outbox_event_id == event_id)
        )
        assert event is not None and event.processed_at is not None
        assert event.attempts == 0  # never counted as a failed attempt
        assert job is not None and job.status == "completed"  # not "failed"
        assert delivery is not None
        assert delivery.status == NotificationDeliveryStatus.skipped
        assert delivery.sanitised_failure_reason == "Recipient is no longer active."


@pytest.mark.asyncio
async def test_worker_skips_queued_email_after_user_disabled(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("queuedemail"), "Queued Email User")
    await enable_email(user_id)

    async with SessionFactory() as db:
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Time to take the bins out.",
            idempotency_key=f"test:queued-email:{user_id}",
        )
        await db.commit()
        event = await outbox_event_for_key(db, "test:queued-email:" + str(user_id), channel="email")
        event_id = event.id

    await set_user_active(user_id, False)
    await worker.process(event_id)

    async with SessionFactory() as db:
        event = await db.get(OutboxEvent, event_id)
        job = await db.get(WorkerJobRecord, event_id)
        delivery = await db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.outbox_event_id == event_id)
        )
        assert event is not None and event.processed_at is not None
        assert event.attempts == 0
        assert job is not None and job.status == "completed"
        assert delivery is not None
        assert delivery.status == NotificationDeliveryStatus.skipped


@pytest.mark.asyncio
async def test_worker_skips_queued_push_after_home_disabled(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("homepush"), "Home Push User")
    home_id = await create_home(client)
    await enable_push(user_id)

    async with SessionFactory() as db:
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Time to take the bins out.",
            idempotency_key=f"test:home-push:{user_id}",
            group_id=home_id,
        )
        await db.commit()
        event = await outbox_event_for_key(db, "test:home-push:" + str(user_id), channel="push")
        event_id = event.id

    await set_home_active(home_id, False)
    await worker.process(event_id)

    async with SessionFactory() as db:
        event = await db.get(OutboxEvent, event_id)
        delivery = await db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.outbox_event_id == event_id)
        )
        assert event is not None and event.processed_at is not None
        assert event.attempts == 0
        assert delivery is not None
        assert delivery.status == NotificationDeliveryStatus.skipped
        assert delivery.sanitised_failure_reason == "Home is no longer active."


@pytest.mark.asyncio
async def test_worker_does_not_skip_push_for_a_still_active_recipient(client: AsyncClient) -> None:
    """Control case: confirms the skip logic is conditional, not a blanket
    suppression — an unrelated failure (no push service configured in
    tests) still results in a normal cancelled/failed outcome, not skipped."""
    user_id = await create_verified_user(client, unique_email("stillactive"), "Still Active")
    await enable_push(user_id)

    async with SessionFactory() as db:
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Time to take the bins out.",
            idempotency_key=f"test:still-active:{user_id}",
        )
        await db.commit()
        event = await outbox_event_for_key(db, "test:still-active:" + str(user_id), channel="push")
        event_id = event.id

    await worker.process(event_id)

    async with SessionFactory() as db:
        delivery = await db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.outbox_event_id == event_id)
        )
        assert delivery is not None
        assert delivery.status != NotificationDeliveryStatus.skipped


# ---------------------------------------------------------------------------
# Daily briefing content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_briefing_excludes_events_from_an_inactive_home(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("briefinactive"), "Briefing User")
    home_id = await create_home(client)

    today_local = datetime.now(UTC).astimezone(TZ).date()
    event_start = datetime.combine(today_local, datetime.min.time(), tzinfo=TZ) + timedelta(
        hours=9, minutes=30
    )
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Swimming",
            "start_at": event_start.isoformat(),
            "end_at": (event_start + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
        },
    )
    assert created.status_code == 201, created.text

    await enable_briefing(user_id)

    await set_home_active(home_id, False)

    async with SessionFactory() as db:
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None
        assert "Swimming" not in notification.body


@pytest.mark.asyncio
async def test_briefing_includes_events_from_a_still_active_second_home(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(client, unique_email("briefactive"), "Briefing User")
    home_a = await create_home(client, "Home A")
    home_b = await create_home(client, "Home B")

    today_local = datetime.now(UTC).astimezone(TZ).date()
    event_start = datetime.combine(today_local, datetime.min.time(), tzinfo=TZ) + timedelta(
        hours=10
    )
    for home_id, title in ((home_a, "Home A Event"), (home_b, "Home B Event")):
        created = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/events",
            json={
                "title": title,
                "start_at": event_start.isoformat(),
                "end_at": (event_start + timedelta(hours=1)).isoformat(),
                "timezone": "Europe/London",
            },
        )
        assert created.status_code == 201, created.text

    await enable_briefing(user_id)

    await set_home_active(home_a, False)

    async with SessionFactory() as db:
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None
        assert "Home A Event" not in notification.body
        assert "Home B Event" in notification.body


@pytest.mark.asyncio
async def test_briefing_sends_nothing_for_an_inactive_user(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("briefinactuser"), "Briefing User")
    await enable_briefing(user_id)

    await set_user_active(user_id, False)
    today_local = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is None


# ---------------------------------------------------------------------------
# Event reminders
# ---------------------------------------------------------------------------


async def create_reminder_event(
    client: AsyncClient, home_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> tuple[str, str]:
    # Assigning specific members to an event needs events.shared.enabled,
    # a Family-plan entitlement — unrelated to lifecycle, but required for
    # member_ids to be accepted at all.
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()

    start_at = datetime(2027, 6, 1, 18, 0, tzinfo=UTC)
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Family dinner",
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "member_ids": [str(m) for m in member_ids],
            "reminder_minutes": 30,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["event_id"], start_at.isoformat()


@pytest.mark.asyncio
async def test_event_reminder_suppressed_for_an_inactive_home(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("evthome"), "Event Creator")
    home_id = await create_home(client)
    member_id = await join_home(home_id, unique_email("evtmember"))
    event_id, occurrence_start = await create_reminder_event(client, home_id, [member_id])

    await set_home_active(home_id, False)

    async with SessionFactory() as db:
        await deliver_event_reminder(db, get_settings(), event_id, occurrence_start, 30)
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(
                Notification.recipient_user_id == member_id,
                Notification.notification_type == "event_reminder",
            )
        )
        assert notification is None
        # The event itself is untouched — only delivery was suppressed.
        event = await db.get(CalendarEvent, uuid.UUID(event_id))
        assert event is not None and event.deleted_at is None


@pytest.mark.asyncio
async def test_event_reminder_suppressed_for_an_inactive_recipient_only(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("evtcreator"), "Event Creator")
    home_id = await create_home(client)
    inactive_member_id = await join_home(home_id, unique_email("evtinactive"))
    active_member_id = await join_home(home_id, unique_email("evtactive"))
    event_id, occurrence_start = await create_reminder_event(
        client, home_id, [inactive_member_id, active_member_id]
    )

    await set_user_active(inactive_member_id, False)

    async with SessionFactory() as db:
        await deliver_event_reminder(db, get_settings(), event_id, occurrence_start, 30)
        await db.commit()
        inactive_notification = await db.scalar(
            select(Notification).where(
                Notification.recipient_user_id == inactive_member_id,
                Notification.notification_type == "event_reminder",
            )
        )
        active_notification = await db.scalar(
            select(Notification).where(
                Notification.recipient_user_id == active_member_id,
                Notification.notification_type == "event_reminder",
            )
        )
        assert inactive_notification is None
        assert active_notification is not None
