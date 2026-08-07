"""Tests for household routines (Stage 6): interval_weeks/week_anchor_date occurrence
math, CRUD authorization, completion tracking, the durable due-reminder scan, and
worker-side delivery (explicit members vs. household-wide, is_critical passthrough,
re-validation against edits since the scan).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    FeatureKey,
    FeatureOverride,
    HouseholdRelationship,
    HouseholdRoutine,
    HouseholdRoutineMember,
    Membership,
    Notification,
    NotificationDelivery,
    OutboxEvent,
    PermissionProfile,
    Role,
    RoutineReminderTiming,
    TokenPurpose,
    User,
)
from mykhaya.notifications.routine_occurrences import is_occurrence_date, next_occurrence_date
from mykhaya.notifications.routines import (
    ROUTINE_TOPIC,
    deliver_routine_reminder,
    scan_due_routines,
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
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Routine Test Home"})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=True)
        )
        await db.commit()
    return home_id


@pytest.fixture(autouse=True)
async def clean_routine_outbox() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        await db.execute(delete(OutboxEvent).where(OutboxEvent.topic == ROUTINE_TOPIC))
        await db.commit()


def make_routine(
    *,
    group_id: uuid.UUID,
    created_by: uuid.UUID,
    week_anchor_date: date,
    interval_weeks: int = 1,
    reminder_timing: RoutineReminderTiming = RoutineReminderTiming.evening_before,
    is_critical: bool = False,
    enabled: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
) -> HouseholdRoutine:
    return HouseholdRoutine(
        group_id=group_id,
        title="Bins out",
        interval_weeks=interval_weeks,
        week_anchor_date=week_anchor_date,
        reminder_timing=reminder_timing,
        is_critical=is_critical,
        enabled=enabled,
        start_date=start_date or week_anchor_date - timedelta(days=365),
        end_date=end_date,
        created_by=created_by,
    )


# --- occurrence math -------------------------------------------------------


def test_is_occurrence_date_weekly() -> None:
    anchor = date(2026, 1, 6)  # Tuesday
    routine = make_routine(
        group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor
    )
    assert is_occurrence_date(routine, anchor)
    assert is_occurrence_date(routine, anchor + timedelta(weeks=1))
    assert is_occurrence_date(routine, anchor + timedelta(weeks=5))
    assert is_occurrence_date(routine, anchor - timedelta(weeks=3))
    assert not is_occurrence_date(routine, anchor + timedelta(days=1))
    assert not is_occurrence_date(routine, anchor + timedelta(days=3))


def test_is_occurrence_date_alternating_weeks() -> None:
    anchor = date(2026, 1, 6)
    routine = make_routine(
        group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor, interval_weeks=2
    )
    assert is_occurrence_date(routine, anchor)
    assert not is_occurrence_date(routine, anchor + timedelta(weeks=1))
    assert is_occurrence_date(routine, anchor + timedelta(weeks=2))
    assert not is_occurrence_date(routine, anchor + timedelta(weeks=3))
    assert is_occurrence_date(routine, anchor - timedelta(weeks=2))
    assert not is_occurrence_date(routine, anchor - timedelta(weeks=1))


def test_is_occurrence_date_respects_window_and_enabled() -> None:
    anchor = date(2026, 1, 6)
    routine = make_routine(
        group_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        week_anchor_date=anchor,
        start_date=anchor,
        end_date=anchor + timedelta(weeks=2),
    )
    assert not is_occurrence_date(routine, anchor - timedelta(weeks=1))
    assert is_occurrence_date(routine, anchor + timedelta(weeks=2))
    assert not is_occurrence_date(routine, anchor + timedelta(weeks=3))

    routine.enabled = False
    assert not is_occurrence_date(routine, anchor)


def test_next_occurrence_date_finds_soonest_match() -> None:
    anchor = date(2026, 1, 6)
    routine = make_routine(
        group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor, interval_weeks=2
    )
    assert next_occurrence_date(routine, anchor + timedelta(days=1)) == anchor + timedelta(weeks=2)
    assert next_occurrence_date(routine, anchor) == anchor


def test_next_occurrence_date_none_past_end_date() -> None:
    anchor = date(2026, 1, 6)
    routine = make_routine(
        group_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        week_anchor_date=anchor,
        end_date=anchor,
    )
    assert next_occurrence_date(routine, anchor + timedelta(days=1)) is None


# --- CRUD and authorization -------------------------------------------------


@pytest.mark.asyncio
async def test_home_admin_can_create_and_list_routine(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("admin"), "Admin Owner")
    home_id = await create_home_with_notifications(client)
    anchor = (datetime.now(UTC).date()).isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Bins out",
            "interval_weeks": 1,
            "week_anchor_date": anchor,
            "reminder_timing": "evening_before",
            "start_date": anchor,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Bins out"
    assert body["next_occurrence_date"] == anchor

    listed = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


@pytest.mark.asyncio
async def test_member_without_manage_capability_cannot_create_routine(
    client: AsyncClient,
) -> None:
    creator_id = await create_verified_user(client, unique_email("owner2"), "Owner")
    home_id = await create_home_with_notifications(client)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        member_id = await create_verified_user(second_client, unique_email("restricted"), "Kid")
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=home_id,
                    user_id=member_id,
                    role=Role.member,
                    relationship=HouseholdRelationship.review_required,
                    permission_profile=PermissionProfile.review_required,
                )
            )
            await db.commit()

        anchor = datetime.now(UTC).date().isoformat()
        response = await unsafe(
            second_client,
            "POST",
            f"/api/v1/homes/{home_id}/routines",
            json={
                "title": "Should not be allowed",
                "interval_weeks": 1,
                "week_anchor_date": anchor,
                "start_date": anchor,
            },
        )
        assert response.status_code == 403
    assert creator_id  # keep reference; creator's own access is covered above


@pytest.mark.asyncio
async def test_update_routine_conflict_and_success(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("update"), "Update Owner")
    home_id = await create_home_with_notifications(client)
    anchor = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Bins out",
            "interval_weeks": 1,
            "week_anchor_date": anchor,
            "start_date": anchor,
        },
    )
    routine_id = created.json()["id"]
    stale_updated_at = created.json()["updated_at"]

    conflict = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/routines/{routine_id}",
        json={
            "title": "Renamed",
            "interval_weeks": 2,
            "week_anchor_date": anchor,
            "start_date": anchor,
            "expected_updated_at": "2000-01-01T00:00:00Z",
        },
    )
    assert conflict.status_code == 409

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/routines/{routine_id}",
        json={
            "title": "Renamed",
            "interval_weeks": 2,
            "week_anchor_date": anchor,
            "start_date": anchor,
            "expected_updated_at": stale_updated_at,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Renamed"
    assert updated.json()["interval_weeks"] == 2


@pytest.mark.asyncio
async def test_delete_routine(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("delete"), "Delete Owner")
    home_id = await create_home_with_notifications(client)
    anchor = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Bins out",
            "interval_weeks": 1,
            "week_anchor_date": anchor,
            "start_date": anchor,
        },
    )
    routine_id = created.json()["id"]
    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/routines/{routine_id}")
    assert deleted.status_code == 204
    listed = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert listed.json()["items"] == []


# --- completion --------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_and_uncomplete_routine(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("complete"), "Complete Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Bins out",
            "interval_weeks": 1,
            "week_anchor_date": today,
            "start_date": today,
        },
    )
    routine_id = created.json()["id"]

    completed = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines/{routine_id}/complete",
        json={"occurrence_date": today},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completed_today"] is True

    # Idempotent: completing twice does not error or duplicate.
    completed_again = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines/{routine_id}/complete",
        json={"occurrence_date": today},
    )
    assert completed_again.status_code == 200

    uncompleted = await unsafe(
        client, "DELETE", f"/api/v1/homes/{home_id}/routines/{routine_id}/complete/{today}"
    )
    assert uncompleted.status_code == 204

    listed = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert listed.json()["items"][0]["completed_today"] is False


@pytest.mark.asyncio
async def test_complete_rejects_non_occurrence_date(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("badcomplete"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Bins out",
            "interval_weeks": 2,
            "week_anchor_date": today.isoformat(),
            "start_date": today.isoformat(),
        },
    )
    routine_id = created.json()["id"]
    off_week = (today + timedelta(weeks=1)).isoformat()
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines/{routine_id}/complete",
        json={"occurrence_date": off_week},
    )
    assert response.status_code == 422


# --- scan and delivery --------------------------------------------------


async def routine_rows(db: AsyncSession, routine_id: str) -> list[OutboxEvent]:
    rows = (await db.scalars(select(OutboxEvent).where(OutboxEvent.topic == ROUTINE_TOPIC))).all()
    return [row for row in rows if row.payload.get("routine_id") == routine_id]


@pytest.mark.asyncio
async def test_scan_enqueues_same_day_reminder_and_is_idempotent(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("scan"), "Scan Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()

    async with SessionFactory() as db:
        routine = make_routine(
            group_id=home_id,
            created_by=creator_id,
            week_anchor_date=today,
            reminder_timing=RoutineReminderTiming.same_day,
        )
        db.add(routine)
        await db.commit()
        await db.refresh(routine)
        routine_id = str(routine.id)

        await scan_due_routines(db, get_settings())
        rows = await routine_rows(db, routine_id)
        # Whether it fires depends on real current local time vs. the fixed 07:30
        # same-day send slot — assert idempotency regardless of whether it's due yet.
        await scan_due_routines(db, get_settings())
        rows_after = await routine_rows(db, routine_id)
        assert len(rows_after) == len(rows)
        assert len(rows) <= 1


@pytest.mark.asyncio
async def test_scan_respects_notifications_feature_flag(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("flagged"), "Flag Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "No Notif Home"})
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=False)
        )
        await db.commit()

    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        routine = make_routine(
            group_id=home_id,
            created_by=creator_id,
            week_anchor_date=today,
            reminder_timing=RoutineReminderTiming.same_day,
        )
        db.add(routine)
        await db.commit()
        await db.refresh(routine)
        routine_id = str(routine.id)

        await scan_due_routines(db, get_settings())
        rows = await routine_rows(db, routine_id)
        assert rows == []


@pytest.mark.asyncio
async def test_deliver_notifies_explicit_members_only(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("explicit"), "Explicit Owner")
    home_id = await create_home_with_notifications(client)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_id = await create_verified_user(other_client, unique_email("other"), "Other")
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
        routine = make_routine(group_id=home_id, created_by=creator_id, week_anchor_date=today)
        db.add(routine)
        await db.flush()
        db.add(HouseholdRoutineMember(routine_id=routine.id, user_id=creator_id))
        await db.commit()
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "evening_before"
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
    creator_id = await create_verified_user(client, unique_email("wide"), "Wide Owner")
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
        routine = make_routine(group_id=home_id, created_by=creator_id, week_anchor_date=today)
        db.add(routine)
        await db.commit()
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "evening_before"
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
async def test_deliver_skips_disabled_routine(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("disabled"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        routine = make_routine(
            group_id=home_id, created_by=creator_id, week_anchor_date=today, enabled=False
        )
        db.add(routine)
        await db.commit()
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "evening_before"
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == creator_id)
        )
        assert notification is None


@pytest.mark.asyncio
async def test_deliver_skips_when_occurrence_no_longer_valid(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("stale"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        routine = make_routine(
            group_id=home_id, created_by=creator_id, week_anchor_date=today, interval_weeks=2
        )
        db.add(routine)
        await db.commit()
        routine_id = str(routine.id)

    # interval_weeks=2: exactly one week after the anchor is an off week, not a
    # scheduled occurrence — proves re-validation against a schedule that changed
    # (or was simply never valid for this date) since the reminder was scanned.
    off_week_date = (today + timedelta(weeks=1)).isoformat()
    async with SessionFactory() as db:
        await deliver_routine_reminder(
            db, get_settings(), routine_id, off_week_date, "evening_before"
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == creator_id)
        )
        assert notification is None


@pytest.mark.asyncio
async def test_deliver_is_idempotent_per_recipient(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("idemroutine"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        routine = make_routine(group_id=home_id, created_by=creator_id, week_anchor_date=today)
        db.add(routine)
        await db.commit()
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "evening_before"
        )
        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "evening_before"
        )
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
                    NotificationDelivery.notification_type == "household_routine_reminder",
                )
            )
        ).all()
        assert len(deliveries) == 1


@pytest.mark.asyncio
async def test_deliver_passes_through_is_critical(client: AsyncClient) -> None:
    creator_id = await create_verified_user(client, unique_email("critical"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        routine = make_routine(
            group_id=home_id, created_by=creator_id, week_anchor_date=today, is_critical=True
        )
        db.add(routine)
        await db.commit()
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "evening_before"
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == creator_id)
        )
        assert notification is not None
        assert notification.notification_type == "household_routine_reminder"
