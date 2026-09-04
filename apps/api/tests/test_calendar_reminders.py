"""Tests for calendar event reminders (Stage 4): the durable due-reminder scan,
idempotency, recurring-series correctness, edit/delete safety, visibility, and the
feature-flag gate. No fake clock exists, so due-reminder tests construct events whose
start time is a few minutes in the future relative to real `datetime.now(UTC)`.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    CalendarEvent,
    FeatureKey,
    FeatureOverride,
    HouseholdRelationship,
    Membership,
    Notification,
    NotificationDelivery,
    OutboxEvent,
    PermissionProfile,
    Role,
    SubscriptionPlan,
    TokenPurpose,
    User,
)
from mykhaya.notifications.reminders import (
    REMINDER_TOPIC,
    deliver_event_reminder,
    scan_due_reminders,
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
            .where(
                ActionToken.user_id == user.id,
                ActionToken.purpose == TokenPurpose.verify_email,
            )
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id,
            TokenPurpose.verify_email.value,
            get_settings().secret_key.get_secret_value(),
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    return user_id


async def create_home_with_calendar(client: AsyncClient) -> uuid.UUID:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Reminder Test Home"})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.calendar, group_id=home_id, enabled=True))
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=True)
        )
        # test_deliver_reminder_notifies_all_event_members assigns a second
        # member to an event (events.shared.enabled); Family here so that
        # keeps working without affecting the other, single-member tests in
        # this file.
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    return home_id


@pytest.fixture(autouse=True)
async def clean_reminder_outbox() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        await db.execute(delete(OutboxEvent).where(OutboxEvent.topic == REMINDER_TOPIC))
        await db.commit()


async def reminder_rows_for_event(db: AsyncSession, event_id: str) -> list[OutboxEvent]:
    """OutboxEvent.payload is a generic JSON column (not JSONB), so it has no `.astext`
    SQL comparator — filter by topic at the SQL level and by event_id in Python."""
    rows = (await db.scalars(select(OutboxEvent).where(OutboxEvent.topic == REMINDER_TOPIC))).all()
    return [row for row in rows if row.payload.get("event_id") == event_id]


@pytest.mark.asyncio
async def test_scan_enqueues_a_due_reminder_and_is_idempotent(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("scan"), "Scan Owner")
    home_id = await create_home_with_calendar(client)
    start_at = datetime.now(UTC) + timedelta(minutes=5, seconds=30)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Swimming",
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "reminder_minutes": 5,
        },
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]

    async with SessionFactory() as db:
        await scan_due_reminders(db, get_settings())
        rows = await reminder_rows_for_event(db, event_id)
        assert len(rows) == 1

        # Running the scan again before the row is processed must not duplicate it.
        await scan_due_reminders(db, get_settings())
        rows_after = await reminder_rows_for_event(db, event_id)
        assert len(rows_after) == 1
        rows_after[0].processed_at = datetime.now(UTC)
        await db.commit()
        await scan_due_reminders(db, get_settings())
        assert len(await reminder_rows_for_event(db, event_id)) == 1


@pytest.mark.asyncio
async def test_scan_does_not_enqueue_when_not_yet_due_or_already_passed(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("notdue"), "Not Due Owner")
    home_id = await create_home_with_calendar(client)
    far_future = datetime.now(UTC) + timedelta(days=10)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Far away event",
            "start_at": far_future.isoformat(),
            "end_at": (far_future + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "reminder_minutes": 5,
        },
    )
    assert created.status_code == 201
    event_id = created.json()["event_id"]

    async with SessionFactory() as db:
        await scan_due_reminders(db, get_settings())
        rows = await reminder_rows_for_event(db, event_id)
        assert rows == []


@pytest.mark.asyncio
async def test_scan_respects_notifications_feature_flag(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("flagged"), "Flag Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "No Notifications Home"})
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.calendar, group_id=home_id, enabled=True))
        # Explicit override=False, rather than relying on the absence of an override
        # plus an assumed-disabled global default — the global flag's live state isn't
        # this test's concern and shouldn't make the test's outcome depend on it.
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=False)
        )
        await db.commit()
    start_at = datetime.now(UTC) + timedelta(minutes=5, seconds=30)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Should not remind",
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "reminder_minutes": 5,
        },
    )
    assert created.status_code == 201
    event_id = created.json()["event_id"]

    async with SessionFactory() as db:
        await scan_due_reminders(db, get_settings())
        rows = await reminder_rows_for_event(db, event_id)
        assert rows == []


@pytest.mark.asyncio
async def test_deliver_reminder_notifies_all_event_members(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("creator"), "Creator")
    home_id = await create_home_with_calendar(client)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        member_email = unique_email("member")
        member_id = await create_verified_user(second_client, member_email, "Member")

    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=home_id,
                user_id=member_id,
                role=Role.adult_member,
                # Both fields default to "review_required" (zero capabilities) at the
                # model level — a real invitation-acceptance flow sets these; this test
                # bypasses that flow, so it must set them explicitly to grant calendar
                # visibility, otherwise can_view_event correctly (and silently) denies
                # the reminder.
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()

    start_at = datetime.now(UTC) + timedelta(minutes=10)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Family dinner",
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "reminder_minutes": 10,
            "member_ids": [str(member_id)],
        },
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]

    async with SessionFactory() as db:
        await deliver_event_reminder(db, get_settings(), event_id, start_at.isoformat(), 10)
        await db.commit()

    async with SessionFactory() as db:
        creator_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == creator_id)
        )
        member_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == member_id)
        )
        assert creator_notification is not None
        assert "Family dinner" in creator_notification.title
        assert member_notification is not None


@pytest.mark.asyncio
async def test_deliver_reminder_skips_deleted_event(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("del"), "Delete Owner")
    home_id = await create_home_with_calendar(client)
    start_at = datetime.now(UTC) + timedelta(minutes=10)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Will be deleted",
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "reminder_minutes": 10,
        },
    )
    event_id = created.json()["event_id"]
    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/events/{event_id}")
    assert deleted.status_code == 204

    async with SessionFactory() as db:
        await deliver_event_reminder(db, get_settings(), event_id, start_at.isoformat(), 10)
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == creator_id)
        )
        assert notification is None


@pytest.mark.asyncio
async def test_deliver_reminder_skips_stale_occurrence_after_reschedule(
    client: AsyncClient,
) -> None:
    creator_id = await create_verified_user(client, unique_email("resched"), "Reschedule Owner")
    home_id = await create_home_with_calendar(client)
    original_start = datetime.now(UTC) + timedelta(minutes=10)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Dentist",
            "start_at": original_start.isoformat(),
            "end_at": (original_start + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "reminder_minutes": 10,
        },
    )
    event_id = created.json()["event_id"]

    # Reschedule directly at the data layer — this test's purpose is proving
    # deliver_event_reminder's staleness check, not re-testing the PATCH endpoint's own
    # optimistic-concurrency behaviour (already covered by test_calendar.py).
    new_start = original_start + timedelta(hours=3)
    async with SessionFactory() as db:
        event_row = await db.get(CalendarEvent, uuid.UUID(event_id))
        assert event_row is not None
        event_row.start_at = new_start
        event_row.end_at = new_start + timedelta(hours=1)
        await db.commit()

    # A reminder scanned against the *original* time must not fire once the event has
    # moved — the worker re-validates against current data before sending.
    async with SessionFactory() as db:
        await deliver_event_reminder(db, get_settings(), event_id, original_start.isoformat(), 10)
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == creator_id)
        )
        assert notification is None


@pytest.mark.asyncio
async def test_deliver_reminder_is_idempotent_per_recipient(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("idem"), "Idempotent Owner")
    home_id = await create_home_with_calendar(client)
    start_at = datetime.now(UTC) + timedelta(minutes=10)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Once only",
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "reminder_minutes": 10,
        },
    )
    event_id = created.json()["event_id"]

    async with SessionFactory() as db:
        await deliver_event_reminder(db, get_settings(), event_id, start_at.isoformat(), 10)
        await deliver_event_reminder(db, get_settings(), event_id, start_at.isoformat(), 10)
        await db.commit()
        notifications = (
            await db.scalars(
                select(Notification).where(Notification.recipient_user_id == creator_id)
            )
        ).all()
        assert len(notifications) == 1
        deliveries = (
            await db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.recipient_user_id == creator_id,
                    # Excludes the registration email_verification delivery this same
                    # user's create_verified_user() call also generated for creator_id.
                    NotificationDelivery.notification_type == "event_reminder",
                )
            )
        ).all()
        assert len(deliveries) == 1


@pytest.mark.asyncio
async def test_recurring_weekly_event_reminder_uses_future_occurrence(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("recur"), "Recurring Owner")
    home_id = await create_home_with_calendar(client)
    # Base occurrence is far in the past; the scan must find the *next future*
    # occurrence's reminder, not miss the series because the base row is stale.
    # Exact weekly alignment: base_start is precisely 6 whole weeks before the target
    # occurrence, so expanding a weekly series from it lands exactly on next_occurrence.
    next_occurrence = datetime.now(UTC) + timedelta(minutes=5, seconds=30)
    base_start = next_occurrence - timedelta(weeks=6)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Weekly swim",
            "start_at": base_start.isoformat(),
            "end_at": (base_start + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "reminder_minutes": 5,
            "recurrence": "weekly",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]

    async with SessionFactory() as db:
        await scan_due_reminders(db, get_settings())
        rows = await reminder_rows_for_event(db, event_id)
        assert len(rows) == 1
        occurrence_start = datetime.fromisoformat(rows[0].payload["occurrence_start"])
        assert occurrence_start > datetime.now(UTC)


@pytest.mark.asyncio
async def test_occurrence_level_member_override_changes_reminder_recipients(
    client: AsyncClient,
) -> None:
    """A member added to just one occurrence (scope=occurrence, member_ids)
    must change who is reminded about *that* occurrence, without adding them
    to any other occurrence of the same series — see
    EffectiveOccurrence.member_ids_override and
    notifications.visibility.viewer_ids_for_event's member_ids_override
    parameter."""
    creator_id = await create_verified_user(client, unique_email("recur-owner"), "Recur Owner")
    home_id = await create_home_with_calendar(client)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as buddy_client:
        buddy_id = await create_verified_user(buddy_client, unique_email("buddy"), "Swim Buddy")

    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=home_id,
                user_id=buddy_id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()

    first_start = datetime.now(UTC) + timedelta(minutes=10)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Weekly swim",
            "start_at": first_start.isoformat(),
            "end_at": (first_start + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "reminder_minutes": 10,
            "member_ids": [],
            "recurrence": "weekly",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]
    second_start = first_start + timedelta(weeks=1)

    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={
            "start_at": first_start.isoformat(),
            "end_at": (second_start + timedelta(hours=1)).isoformat(),
        },
    )
    assert listed.status_code == 200, listed.text
    occurrences = sorted(listed.json()["items"], key=lambda item: item["start_at"])
    assert len(occurrences) == 2
    second_occ = occurrences[1]

    patched = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json={
            "title": second_occ["title"],
            "start_at": second_occ["start_at"],
            "end_at": second_occ["end_at"],
            "timezone": second_occ["timezone"],
            "is_all_day": second_occ["is_all_day"],
            "member_ids": [str(buddy_id)],
            "recurrence": second_occ["recurrence"],
            "recurrence_interval": 1,
            "expected_updated_at": second_occ["updated_at"],
            "scope": "occurrence",
            "occurrence_start": second_occ["occurrence_start"],
        },
    )
    assert patched.status_code == 200, patched.text

    async with SessionFactory() as db:
        await deliver_event_reminder(db, get_settings(), event_id, first_start.isoformat(), 10)
        await db.commit()

    async with SessionFactory() as db:
        # The unmodified first occurrence has no override — its recipient
        # set is the base event's own membership, which (like every
        # event/occurrence edit — see _validated_requested_members) always
        # implicitly includes its creator. The buddy, added only to
        # occurrence 2, must not leak into occurrence 1's reminder.
        recipients = (
            await db.scalars(
                select(Notification.recipient_user_id).where(
                    Notification.related_entity_id == uuid.UUID(event_id),
                    Notification.notification_type == "event_reminder",
                )
            )
        ).all()
        assert buddy_id not in recipients
        assert creator_id in recipients

    async with SessionFactory() as db:
        await deliver_event_reminder(db, get_settings(), event_id, second_start.isoformat(), 10)
        await db.commit()

    async with SessionFactory() as db:
        recipients = (
            await db.scalars(
                select(Notification.recipient_user_id).where(
                    Notification.related_entity_id == uuid.UUID(event_id),
                    Notification.notification_type == "event_reminder",
                )
            )
        ).all()
        # Occurrence 2's override adds the buddy on top of the (always
        # implicitly included) creator — the override changes who is
        # reminded about *this* occurrence without erasing the standing
        # "creator is always a participant" rule.
        assert buddy_id in recipients
        assert creator_id in recipients


@pytest.mark.asyncio
async def test_visibility_check_still_reflects_current_capabilities_for_test_module() -> None:
    """Sanity check that the visibility module exists and is importable independently —
    full capability-matrix coverage already lives in test_household_controls.py."""
    from mykhaya.notifications.visibility import can_view_event, viewer_ids_for_event

    assert callable(can_view_event)
    assert callable(viewer_ids_for_event)
