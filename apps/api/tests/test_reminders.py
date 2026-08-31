"""Tests for standalone Reminders: personal/household scope + visibility, CRUD
authorization, per-occurrence completion (one-off vs repeating), the cadence-based
due+nag scan (once/hourly/daily/weekly), idempotent delivery, and overdue/restart
behaviour — mirrors tests/test_household_routines.py's structure and helpers.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    FeatureKey,
    FeatureOverride,
    HouseholdRelationship,
    Membership,
    Notification,
    NotificationDelivery,
    OutboxEvent,
    PermissionProfile,
    Reminder,
    ReminderCadence,
    ReminderCompletion,
    ReminderMember,
    ReminderRepeat,
    Role,
    RoutineScope,
    TokenPurpose,
    User,
)
from mykhaya.notifications.reminder_occurrences import is_occurrence_date
from mykhaya.notifications.standalone_reminders import (
    REMINDER_TOPIC,
    deliver_standalone_reminder,
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


async def create_home_with_notifications(client: AsyncClient) -> uuid.UUID:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Reminder Test Home"})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=True)
        )
        await db.commit()
    return home_id


def make_reminder(
    *,
    group_id: uuid.UUID,
    created_by: uuid.UUID,
    due_date: date,
    due_time: time = time(9, 0),
    repeat: ReminderRepeat = ReminderRepeat.never,
    cadence: ReminderCadence = ReminderCadence.once,
    enabled: bool = True,
    scope: RoutineScope = RoutineScope.household,
    owner_user_id: uuid.UUID | None = None,
) -> Reminder:
    return Reminder(
        group_id=group_id,
        title="Call the dentist",
        scope=scope,
        owner_user_id=owner_user_id,
        due_date=due_date,
        due_time=due_time,
        repeat=repeat,
        cadence=cadence,
        enabled=enabled,
        created_by=created_by,
    )


async def reminder_rows(db: AsyncSession, reminder_id: str) -> list[OutboxEvent]:
    rows = (await db.scalars(select(OutboxEvent).where(OutboxEvent.topic == REMINDER_TOPIC))).all()
    return [row for row in rows if row.payload.get("reminder_id") == reminder_id]


# --- CRUD, scope and visibility ---------------------------------------------


@pytest.mark.asyncio
async def test_create_personal_reminder(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("personal"), "Personal Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={
            "title": "Call the dentist",
            "due_date": today,
            "due_time": "09:00:00",
            "scope": "personal",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["scope"] == "personal"
    assert created.json()["owner_user_id"] is not None


@pytest.mark.asyncio
async def test_create_household_reminder_with_assignee(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("hh"), "HH Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={
            "title": "Bring PE kit",
            "due_date": today,
            "due_time": "08:00:00",
            "scope": "household",
            "member_ids": [str(creator_id)],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["member_ids"] == [str(creator_id)]


@pytest.mark.asyncio
async def test_personal_reminder_rejects_explicit_members(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("noassign"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={
            "title": "Should fail",
            "due_date": today,
            "due_time": "09:00:00",
            "scope": "personal",
            "member_ids": [str(uuid.uuid4())],
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cross_home_assignee_is_rejected(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("crosshome"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={
            "title": "Bad assignee",
            "due_date": today,
            "due_time": "09:00:00",
            "scope": "household",
            "member_ids": [str(uuid.uuid4())],
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_personal_reminder_is_isolated_from_other_members(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("iso"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={"title": "Private", "due_date": today, "due_time": "09:00:00", "scope": "personal"},
    )
    reminder_id = created.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_id = await create_verified_user(other_client, unique_email("isoother"), "Other")
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=home_id,
                    user_id=other_id,
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()

        listed = await unsafe(other_client, "GET", f"/api/v1/homes/{home_id}/reminders")
        assert listed.status_code == 200
        assert listed.json()["items"] == []

        forbidden = await unsafe(
            other_client, "DELETE", f"/api/v1/homes/{home_id}/reminders/{reminder_id}"
        )
        assert forbidden.status_code == 404
    assert creator_id


@pytest.mark.asyncio
async def test_household_visibility_shows_reminder_to_other_members(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("visib"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={"title": "Bins out", "due_date": today, "due_time": "09:00:00", "scope": "household"},
    )
    assert created.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_id = await create_verified_user(other_client, unique_email("visother"), "Other")
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=home_id,
                    user_id=other_id,
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()
        listed = await unsafe(other_client, "GET", f"/api/v1/homes/{home_id}/reminders")
        assert listed.status_code == 200, listed.text
        assert len(listed.json()["items"]) == 1
    assert creator_id


@pytest.mark.asyncio
async def test_delete_reminder(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("del"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={"title": "Bins out", "due_date": today, "due_time": "09:00:00"},
    )
    reminder_id = created.json()["id"]
    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/reminders/{reminder_id}")
    assert deleted.status_code == 204
    listed = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/reminders")
    assert listed.json()["items"] == []


# --- completion semantics ---------------------------------------------------


@pytest.mark.asyncio
async def test_complete_one_off_reminder(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("oneoff"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={"title": "One-off", "due_date": today, "due_time": "09:00:00", "repeat": "never"},
    )
    reminder_id = created.json()["id"]

    completed = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders/{reminder_id}/complete",
        json={"occurrence_date": today},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completed_today"] is True
    # A one-off reminder has exactly one occurrence ever — tomorrow is never valid,
    # so there is nothing left to notify about again.
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    retry = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders/{reminder_id}/complete",
        json={"occurrence_date": tomorrow},
    )
    assert retry.status_code == 422


@pytest.mark.asyncio
async def test_complete_repeating_occurrence_leaves_next_scheduled(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("repeat"), "Owner")
    home_id = await create_home_with_notifications(client)
    today_date = datetime.now(UTC).date()
    today = today_date.isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={
            "title": "Daily reminder",
            "due_date": today,
            "due_time": "09:00:00",
            "repeat": "daily",
        },
    )
    reminder_id = created.json()["id"]

    completed = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders/{reminder_id}/complete",
        json={"occurrence_date": today},
    )
    assert completed.status_code == 200
    assert completed.json()["completed_today"] is True
    # The next day's occurrence is still schedulable — completing today's occurrence
    # only ever affects today's, never the whole repeating series.
    tomorrow = (today_date + timedelta(days=1)).isoformat()
    next_day_complete = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders/{reminder_id}/complete",
        json={"occurrence_date": tomorrow},
    )
    assert next_day_complete.status_code == 200, next_day_complete.text


@pytest.mark.asyncio
async def test_complete_invalid_occurrence_date_rejected(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("invocc"), "Owner")
    home_id = await create_home_with_notifications(client)
    today_date = datetime.now(UTC).date()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={
            "title": "Once",
            "due_date": today_date.isoformat(),
            "due_time": "09:00:00",
            "repeat": "never",
        },
    )
    reminder_id = created.json()["id"]
    not_an_occurrence = (today_date + timedelta(days=5)).isoformat()
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders/{reminder_id}/complete",
        json={"occurrence_date": not_an_occurrence},
    )
    assert response.status_code == 422


# --- cadence: once / hourly / daily / weekly until completed ---------------


@pytest.mark.asyncio
async def test_once_cadence_fires_a_single_notification(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("once"), "Owner")
    home_id = await create_home_with_notifications(client)
    now = datetime.now(UTC)
    async with SessionFactory() as db:
        reminder = make_reminder(
            group_id=home_id,
            created_by=creator_id,
            due_date=(now - timedelta(minutes=5)).date(),
            due_time=(now - timedelta(minutes=5)).time().replace(microsecond=0),
            cadence=ReminderCadence.once,
        )
        db.add(reminder)
        await db.commit()
        await db.refresh(reminder)
        reminder_id = str(reminder.id)

        await scan_due_reminders(db, get_settings())
        rows = await reminder_rows(db, reminder_id)
        assert len(rows) == 1
        assert rows[0].payload["slot"] == 0

        # Scanning again must not enqueue a second "once" notification.
        await scan_due_reminders(db, get_settings())
        assert len(await reminder_rows(db, reminder_id)) == 1


@pytest.mark.asyncio
async def test_hourly_cadence_advances_to_the_current_slot_without_replay(
    client: AsyncClient,
) -> None:
    creator_id = await create_verified_user(client, unique_email("hourly"), "Owner")
    home_id = await create_home_with_notifications(client)
    # Due 3.5 hours ago — a scheduler that had been running the whole time would
    # have already sent slots 0, 1, 2; a restart must resume at slot 3 only, not
    # replay the missed ones. due_date/due_time are wall-clock in the home's
    # timezone (no primary calendar set here, so it's config.default_timezone,
    # Europe/London) — the same conversion scan_due_reminders itself performs.
    due_at_utc = datetime.now(UTC) - timedelta(hours=3, minutes=30)
    due_at_local = due_at_utc.astimezone(ZoneInfo(get_settings().default_timezone))
    async with SessionFactory() as db:
        reminder = make_reminder(
            group_id=home_id,
            created_by=creator_id,
            due_date=due_at_local.date(),
            due_time=due_at_local.time().replace(microsecond=0),
            cadence=ReminderCadence.hourly,
        )
        db.add(reminder)
        await db.commit()
        await db.refresh(reminder)
        reminder_id = str(reminder.id)

        await scan_due_reminders(db, get_settings())
        rows = await reminder_rows(db, reminder_id)
        assert len(rows) == 1
        assert rows[0].payload["slot"] == 3


@pytest.mark.asyncio
async def test_completing_the_occurrence_stops_further_nag_scans(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("stopnag"), "Owner")
    home_id = await create_home_with_notifications(client)
    now = datetime.now(UTC)
    async with SessionFactory() as db:
        reminder = make_reminder(
            group_id=home_id,
            created_by=creator_id,
            due_date=(now - timedelta(hours=2)).date(),
            due_time=(now - timedelta(hours=2)).time().replace(microsecond=0),
            cadence=ReminderCadence.hourly,
        )
        db.add(reminder)
        await db.flush()
        db.add(
            ReminderCompletion(
                reminder_id=reminder.id,
                occurrence_date=(now - timedelta(hours=2)).date(),
                completed_by=creator_id,
            )
        )
        await db.commit()
        reminder_id = str(reminder.id)

        await scan_due_reminders(db, get_settings())
        assert await reminder_rows(db, reminder_id) == []


@pytest.mark.asyncio
async def test_deliver_skips_when_occurrence_completed_since_scanned(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("racecomplete"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        reminder = make_reminder(group_id=home_id, created_by=creator_id, due_date=today)
        db.add(reminder)
        await db.flush()
        db.add(
            ReminderCompletion(
                reminder_id=reminder.id, occurrence_date=today, completed_by=creator_id
            )
        )
        await db.commit()
        reminder_id = str(reminder.id)

        await deliver_standalone_reminder(
            db, get_settings(), reminder_id, today.isoformat(), "once", 0
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == creator_id)
        )
        assert notification is None


@pytest.mark.asyncio
async def test_deliver_notifies_explicit_members_only(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("explicit"), "Owner")
    home_id = await create_home_with_notifications(client)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_id = await create_verified_user(other_client, unique_email("explother"), "Other")
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=home_id,
                    user_id=other_id,
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()

    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        reminder = make_reminder(group_id=home_id, created_by=creator_id, due_date=today)
        db.add(reminder)
        await db.flush()
        db.add(ReminderMember(reminder_id=reminder.id, user_id=creator_id))
        await db.commit()
        reminder_id = str(reminder.id)

        await deliver_standalone_reminder(
            db, get_settings(), reminder_id, today.isoformat(), "once", 0
        )
        await db.commit()

        creator_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == creator_id)
        )
        other_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == other_id)
        )
        assert creator_notification is not None
        assert other_notification is None


@pytest.mark.asyncio
async def test_deliver_notifies_whole_household_when_no_explicit_members(
    client: AsyncClient,
) -> None:
    creator_id = await create_verified_user(client, unique_email("wide"), "Owner")
    home_id = await create_home_with_notifications(client)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_id = await create_verified_user(other_client, unique_email("wideother"), "Other")
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=home_id,
                    user_id=other_id,
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()

    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        reminder = make_reminder(group_id=home_id, created_by=creator_id, due_date=today)
        db.add(reminder)
        await db.commit()
        reminder_id = str(reminder.id)

        await deliver_standalone_reminder(
            db, get_settings(), reminder_id, today.isoformat(), "once", 0
        )
        await db.commit()

        creator_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == creator_id)
        )
        other_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == other_id)
        )
        assert creator_notification is not None
        assert other_notification is not None


@pytest.mark.asyncio
async def test_deliver_notifies_only_owner_for_personal_reminder(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("persononly"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        reminder = make_reminder(
            group_id=home_id,
            created_by=creator_id,
            due_date=today,
            scope=RoutineScope.personal,
            owner_user_id=creator_id,
        )
        db.add(reminder)
        await db.commit()
        reminder_id = str(reminder.id)

        await deliver_standalone_reminder(
            db, get_settings(), reminder_id, today.isoformat(), "once", 0
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == creator_id)
        )
        assert notification is not None


@pytest.mark.asyncio
async def test_deliver_is_idempotent_per_recipient(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("idem"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        reminder = make_reminder(group_id=home_id, created_by=creator_id, due_date=today)
        db.add(reminder)
        await db.commit()
        reminder_id = str(reminder.id)

        await deliver_standalone_reminder(
            db, get_settings(), reminder_id, today.isoformat(), "once", 0
        )
        await deliver_standalone_reminder(
            db, get_settings(), reminder_id, today.isoformat(), "once", 0
        )
        await db.commit()

        deliveries = (
            await db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.idempotency_key.like(f"reminder:{reminder_id}:%")
                )
            )
        ).all()
        assert len(deliveries) == 1


@pytest.mark.asyncio
async def test_scan_respects_notifications_feature_flag(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("flagoff"), "Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "No Notif Home"})
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=False)
        )
        await db.commit()

    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        reminder = make_reminder(group_id=home_id, created_by=creator_id, due_date=today)
        db.add(reminder)
        await db.commit()
        reminder_id = str(reminder.id)

        await scan_due_reminders(db, get_settings())
        assert await reminder_rows(db, reminder_id) == []


@pytest.mark.asyncio
async def test_overdue_reminder_is_the_scanned_occurrence_not_todays(client: AsyncClient) -> None:
    """A reminder due 3 days ago and never completed stays "the" overdue occurrence
    — the scan must find that missed date, not silently roll forward to today."""
    creator_id = await create_verified_user(client, unique_email("overdue"), "Owner")
    home_id = await create_home_with_notifications(client)
    overdue_date = (datetime.now(UTC).date()) - timedelta(days=3)
    async with SessionFactory() as db:
        reminder = make_reminder(
            group_id=home_id,
            created_by=creator_id,
            due_date=overdue_date,
            due_time=time(0, 0),
            repeat=ReminderRepeat.never,
            cadence=ReminderCadence.once,
        )
        db.add(reminder)
        await db.commit()
        await db.refresh(reminder)
        reminder_id = str(reminder.id)

        await scan_due_reminders(db, get_settings())
        rows = await reminder_rows(db, reminder_id)
        assert len(rows) == 1
        assert rows[0].payload["occurrence_date"] == overdue_date.isoformat()


@pytest.mark.asyncio
async def test_weekly_repeat_occurrence_math(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("weeklyrepeat"), "Owner")
    home_id = await create_home_with_notifications(client)
    anchor = datetime.now(UTC).date()
    reminder = make_reminder(
        group_id=home_id, created_by=creator_id, due_date=anchor, repeat=ReminderRepeat.weekly
    )
    assert is_occurrence_date(reminder, anchor)
    assert not is_occurrence_date(reminder, anchor + timedelta(days=3))
    assert is_occurrence_date(reminder, anchor + timedelta(weeks=2))
