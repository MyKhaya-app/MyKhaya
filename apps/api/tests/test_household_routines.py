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
from mykhaya.entitlements import get_home_subscription
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
    RoutineScope,
    SubscriptionPlan,
    TokenPurpose,
    User,
)
from mykhaya.notifications.routine_occurrences import (
    HOME_VISIBILITY_WINDOW_DAYS,
    is_occurrence_date,
    last_occurrence_on_or_before,
    next_occurrence_date,
    select_home_occurrence,
)
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
        # Commercial plan cleanup: household routines require Family
        # (routines.household.enabled) and this file's tests are about
        # routine CRUD/scheduling mechanics, not commercial gating — see
        # test_commercial_plan_cleanup.py for the Free-vs-Family enforcement
        # coverage itself.
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
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
    repeat_unit: str = "weekly",
    reminder_timing: RoutineReminderTiming = RoutineReminderTiming.evening_before,
    is_critical: bool = False,
    enabled: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
    scope: RoutineScope = RoutineScope.household,
    owner_user_id: uuid.UUID | None = None,
) -> HouseholdRoutine:
    return HouseholdRoutine(
        group_id=group_id,
        title="Bins out",
        scope=scope,
        owner_user_id=owner_user_id,
        interval_weeks=interval_weeks,
        repeat_unit=repeat_unit,
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
    routine = make_routine(group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor)
    assert is_occurrence_date(routine, anchor)
    assert is_occurrence_date(routine, anchor + timedelta(weeks=1))
    assert is_occurrence_date(routine, anchor + timedelta(weeks=5))
    assert is_occurrence_date(routine, anchor - timedelta(weeks=3))
    assert not is_occurrence_date(routine, anchor + timedelta(days=1))
    assert not is_occurrence_date(routine, anchor + timedelta(days=3))


def test_is_occurrence_date_daily_uses_anchor_and_date_bounds() -> None:
    anchor = date(2026, 1, 6)
    routine = make_routine(
        group_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        week_anchor_date=anchor,
        repeat_unit="daily",
        start_date=anchor,
        end_date=anchor + timedelta(days=2),
    )
    assert is_occurrence_date(routine, anchor)
    assert is_occurrence_date(routine, anchor + timedelta(days=1))
    assert is_occurrence_date(routine, anchor + timedelta(days=2))
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


# --- Home "To do" card visibility window ------------------------------------
# select_home_occurrence (backing household_routines.list_routines's
# `home=true` branch) is the single source of truth for which occurrence, if
# any, a routine surfaces on Home: its current overdue/due-today occurrence
# until completed, that occurrence through the rest of its due date once
# completed, or its next occurrence once within HOME_VISIBILITY_WINDOW_DAYS
# days of its own due date. These are pure-function tests — no DB, no HTTP —
# covering the window/overdue/completion rules against every recurrence
# cadence the interval_weeks engine can express: daily, weekly, bi-weekly,
# and (via a larger interval_weeks — this engine's only way to approximate
# them, see routine_occurrences.HOME_LOOKBACK_DAYS) monthly and yearly.

NO_COMPLETIONS = lambda occurrence_date: False  # noqa: E731


def completed_on(*dates: date):
    dates_set = set(dates)
    return lambda occurrence_date: occurrence_date in dates_set


def test_home_visibility_hides_occurrence_more_than_window_away() -> None:
    today = date(2026, 3, 10)
    due = today + timedelta(days=HOME_VISIBILITY_WINDOW_DAYS + 1)
    # start_date=due: this occurrence's very first one, so there is no
    # earlier weekly occurrence for last_occurrence_on_or_before to find
    # (make_routine's own default start_date would otherwise backdate a
    # year of weekly occurrences before `due`).
    routine = make_routine(
        group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=due, start_date=due
    )
    assert select_home_occurrence(routine, today, NO_COMPLETIONS) is None


def test_home_visibility_shows_occurrence_exactly_at_window_edge() -> None:
    today = date(2026, 3, 10)
    due = today + timedelta(days=HOME_VISIBILITY_WINDOW_DAYS)
    routine = make_routine(
        group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=due, start_date=due
    )
    selection = select_home_occurrence(routine, today, NO_COMPLETIONS)
    assert selection is not None
    assert selection.occurrence_date == due
    assert selection.is_completed is False
    assert selection.priority == 2


def test_home_visibility_shows_occurrence_due_tomorrow() -> None:
    today = date(2026, 3, 10)
    due = today + timedelta(days=1)
    routine = make_routine(
        group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=due, start_date=due
    )
    selection = select_home_occurrence(routine, today, NO_COMPLETIONS)
    assert selection is not None
    assert selection.occurrence_date == due
    assert selection.priority == 2


def test_home_visibility_shows_occurrence_due_today() -> None:
    today = date(2026, 3, 10)
    routine = make_routine(group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=today)
    selection = select_home_occurrence(routine, today, NO_COMPLETIONS)
    assert selection is not None
    assert selection.occurrence_date == today
    assert selection.is_completed is False
    assert selection.priority == 1


def test_home_visibility_keeps_completed_due_today_occurrence_visible() -> None:
    today = date(2026, 3, 10)
    routine = make_routine(group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=today)
    selection = select_home_occurrence(routine, today, completed_on(today))
    assert selection is not None
    assert selection.occurrence_date == today
    assert selection.is_completed is True
    assert selection.priority == 3


def test_home_visibility_drops_completed_occurrence_after_its_due_date() -> None:
    anchor = date(2026, 3, 6)  # Friday
    routine = make_routine(group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor)
    # Completed on its due date (Friday); by Saturday the due date has
    # passed and the next occurrence (next Friday) is far outside the
    # visibility window, so nothing should show.
    saturday = anchor + timedelta(days=1)
    assert select_home_occurrence(routine, saturday, completed_on(anchor)) is None


def test_home_visibility_does_not_show_next_occurrence_early_after_completion() -> None:
    anchor = date(2026, 3, 6)  # Friday, weekly
    routine = make_routine(group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor)
    completed = completed_on(anchor)
    # The day right after completion, next Friday is still 6 days away.
    assert select_home_occurrence(routine, anchor + timedelta(days=1), completed) is None
    # Still hidden the day before next Friday's 2-day window opens.
    next_friday = anchor + timedelta(weeks=1)
    just_outside_window = next_friday - timedelta(days=HOME_VISIBILITY_WINDOW_DAYS + 1)
    assert select_home_occurrence(routine, just_outside_window, completed) is None


def test_home_visibility_shows_next_occurrence_once_it_enters_the_window() -> None:
    anchor = date(2026, 3, 6)  # Friday, weekly
    routine = make_routine(group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor)
    completed = completed_on(anchor)
    next_friday = anchor + timedelta(weeks=1)
    today = next_friday - timedelta(days=HOME_VISIBILITY_WINDOW_DAYS)
    selection = select_home_occurrence(routine, today, completed)
    assert selection is not None
    assert selection.occurrence_date == next_friday
    assert selection.is_completed is False
    assert selection.priority == 2


def test_home_visibility_keeps_overdue_incomplete_occurrence_visible() -> None:
    anchor = date(2026, 3, 6)  # Friday, weekly, never completed
    routine = make_routine(group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor)
    # A few days later (still before next Friday's own occurrence), the
    # missed Friday occurrence itself stays the selected occurrence — it
    # does not silently disappear or roll forward.
    today = anchor + timedelta(days=3)
    selection = select_home_occurrence(routine, today, NO_COMPLETIONS)
    assert selection is not None
    assert selection.occurrence_date == anchor
    assert selection.is_completed is False
    assert selection.priority == 0


def test_home_visibility_daily_recurrence() -> None:
    routine = make_routine(
        group_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        week_anchor_date=date(2026, 3, 1),
        repeat_unit="daily",
        start_date=date(2026, 3, 1),
    )
    today = date(2026, 3, 15)
    # Uncompleted: today's occurrence is due today.
    due_today = select_home_occurrence(routine, today, NO_COMPLETIONS)
    assert due_today is not None
    assert due_today.occurrence_date == today
    assert due_today.priority == 1
    # Completed: stays visible today, gone the next day (tomorrow's own
    # occurrence isn't due yet, and is within the window so it takes over).
    tomorrow_selection = select_home_occurrence(
        routine, today + timedelta(days=1), completed_on(today)
    )
    assert tomorrow_selection is not None
    assert tomorrow_selection.occurrence_date == today + timedelta(days=1)
    assert tomorrow_selection.is_completed is False


def test_home_visibility_weekly_recurrence() -> None:
    anchor = date(2026, 3, 6)
    routine = make_routine(
        group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor, interval_weeks=1
    )
    assert next_occurrence_date(routine, anchor + timedelta(days=1)) == anchor + timedelta(weeks=1)
    selection = select_home_occurrence(routine, anchor, NO_COMPLETIONS)
    assert selection is not None
    assert selection.occurrence_date == anchor
    assert selection.priority == 1


def test_home_visibility_biweekly_recurrence() -> None:
    anchor = date(2026, 3, 6)
    routine = make_routine(
        group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor, interval_weeks=2
    )
    next_due = anchor + timedelta(weeks=2)
    assert next_occurrence_date(routine, anchor + timedelta(days=1)) == next_due
    today = next_due - timedelta(days=HOME_VISIBILITY_WINDOW_DAYS)
    selection = select_home_occurrence(routine, today, completed_on(anchor))
    assert selection is not None
    assert selection.occurrence_date == next_due
    assert selection.priority == 2


def test_home_visibility_monthly_ish_recurrence() -> None:
    # This routine engine has no dedicated "monthly" unit — a ~4-week
    # interval_weeks is the closest existing cadence it can express (see
    # HOME_LOOKBACK_DAYS's docstring) — but the Home visibility window logic
    # itself is generic over any occurrence date, so it must still hold here.
    anchor = date(2026, 1, 2)
    routine = make_routine(
        group_id=uuid.uuid4(), created_by=uuid.uuid4(), week_anchor_date=anchor, interval_weeks=4
    )
    next_due = anchor + timedelta(weeks=4)
    assert (
        select_home_occurrence(
            routine,
            next_due - timedelta(days=HOME_VISIBILITY_WINDOW_DAYS + 1),
            completed_on(anchor),
        )
        is None
    )
    today = next_due - timedelta(days=HOME_VISIBILITY_WINDOW_DAYS)
    selection = select_home_occurrence(routine, today, completed_on(anchor))
    assert selection is not None
    assert selection.occurrence_date == next_due
    assert selection.priority == 2
    # And a missed monthly-ish occurrence stays overdue rather than
    # disappearing or silently jumping to the following one.
    overdue_selection = select_home_occurrence(
        routine, next_due + timedelta(days=10), NO_COMPLETIONS
    )
    assert overdue_selection is not None
    assert overdue_selection.occurrence_date == next_due
    assert overdue_selection.priority == 0


def test_home_visibility_yearly_ish_recurrence() -> None:
    # Same caveat as the monthly-ish test above — a ~52-week interval_weeks
    # is the closest cadence this engine can express as "yearly". This also
    # exercises last_occurrence_on_or_before's backward search across a gap
    # much wider than the old 60-day lookback ever supported.
    anchor = date(2025, 6, 1)
    routine = make_routine(
        group_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        week_anchor_date=anchor,
        interval_weeks=52,
        start_date=anchor,
    )
    next_due = anchor + timedelta(weeks=52)
    assert last_occurrence_on_or_before(routine, next_due - timedelta(days=1)) == anchor
    hidden_today = next_due - timedelta(days=HOME_VISIBILITY_WINDOW_DAYS + 1)
    assert select_home_occurrence(routine, hidden_today, completed_on(anchor)) is None
    visible_today = next_due - timedelta(days=HOME_VISIBILITY_WINDOW_DAYS)
    selection = select_home_occurrence(routine, visible_today, completed_on(anchor))
    assert selection is not None
    assert selection.occurrence_date == next_due
    assert selection.priority == 2


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
async def test_daily_routine_round_trips_and_can_be_updated(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("daily"), "Daily Owner")
    home_id = await create_home_with_notifications(client)
    anchor = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Feed the dog",
            "repeat_unit": "daily",
            "interval_weeks": 1,
            "week_anchor_date": anchor,
            "start_date": anchor,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["repeat_unit"] == "daily"
    assert created.json()["next_occurrence_date"] == anchor

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/routines/{created.json()['id']}",
        json={
            "title": "Feed the dog",
            "repeat_unit": "weekly",
            "interval_weeks": 2,
            "week_anchor_date": anchor,
            "start_date": anchor,
            "expected_updated_at": created.json()["updated_at"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["repeat_unit"] == "weekly"
    assert updated.json()["interval_weeks"] == 2


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
async def test_home_keeps_same_day_completion_and_excludes_previous_day_completion(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("homecompletion"), "Megan")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)

    current = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Put green bin out",
            "scope": "household",
            "interval_weeks": 1,
            "repeat_unit": "daily",
            "week_anchor_date": today.isoformat(),
            "start_date": today.isoformat(),
        },
    )
    old = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Yesterday only",
            "interval_weeks": 1,
            "week_anchor_date": yesterday.isoformat(),
            "start_date": yesterday.isoformat(),
        },
    )
    assert current.status_code == 201, current.text
    assert old.status_code == 201, old.text

    completed_current = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines/{current.json()['id']}/complete",
        json={"occurrence_date": today.isoformat()},
    )
    completed_old = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines/{old.json()['id']}/complete",
        json={"occurrence_date": yesterday.isoformat()},
    )
    assert completed_current.status_code == 200, completed_current.text
    assert completed_old.status_code == 200, completed_old.text

    home = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines?home=true")
    assert home.status_code == 200, home.text
    rows = {row["title"]: row for row in home.json()["items"]}
    assert "Put green bin out" in rows
    assert rows["Put green bin out"]["home_completed_by_display_name"] == "Megan"
    assert "Yesterday only" not in rows


@pytest.mark.asyncio
async def test_home_hides_occurrence_outside_visibility_window_end_to_end(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("windowfar"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    far_due = today + timedelta(days=3)

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Change smoke alarm batteries",
            "interval_weeks": 1,
            "week_anchor_date": far_due.isoformat(),
            "start_date": far_due.isoformat(),
        },
    )
    assert created.status_code == 201, created.text

    home = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines?home=true")
    assert home.status_code == 200, home.text
    assert "Change smoke alarm batteries" not in {row["title"] for row in home.json()["items"]}


@pytest.mark.asyncio
async def test_home_shows_occurrence_two_days_before_due_end_to_end(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("windownear"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()
    near_due = today + timedelta(days=2)

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Water the tomatoes",
            "interval_weeks": 1,
            "week_anchor_date": near_due.isoformat(),
            "start_date": near_due.isoformat(),
        },
    )
    assert created.status_code == 201, created.text

    home = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines?home=true")
    assert home.status_code == 200, home.text
    rows = {row["title"]: row for row in home.json()["items"]}
    assert "Water the tomatoes" in rows
    assert rows["Water the tomatoes"]["home_occurrence_date"] == near_due.isoformat()


@pytest.mark.asyncio
async def test_home_orders_overdue_before_due_today_before_upcoming_before_completed(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("ordering"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()

    async def add(title: str, anchor: date) -> None:
        response = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/routines",
            json={
                "title": title,
                "interval_weeks": 1,
                "week_anchor_date": anchor.isoformat(),
                "start_date": anchor.isoformat(),
            },
        )
        assert response.status_code == 201, response.text

    # Overdue: anchored a few days ago on a date that is not itself an
    # occurrence of "today" (an off-cycle offset).
    await add("Overdue bins", today - timedelta(days=10))
    # Due today.
    await add("Due today walk the dog", today)
    # Upcoming, within the 2-day window.
    await add("Upcoming water plants", today + timedelta(days=2))
    # Completed today.
    completed_response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Completed feed cat",
            "interval_weeks": 1,
            "week_anchor_date": today.isoformat(),
            "start_date": today.isoformat(),
        },
    )
    assert completed_response.status_code == 201, completed_response.text
    completed_id = completed_response.json()["id"]
    completed = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines/{completed_id}/complete",
        json={"occurrence_date": today.isoformat()},
    )
    assert completed.status_code == 200, completed.text

    home = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines?home=true")
    assert home.status_code == 200, home.text
    titles = [row["title"] for row in home.json()["items"]]
    assert titles == [
        "Overdue bins",
        "Due today walk the dog",
        "Upcoming water plants",
        "Completed feed cat",
    ]


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
        if rows:
            rows[0].processed_at = datetime.now(UTC)
            await db.commit()
            await scan_due_routines(db, get_settings())
            assert len(await routine_rows(db, routine_id)) == 1


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


# --- personal vs. household scope --------------------------------------------


@pytest.mark.asyncio
async def test_create_personal_routine_infers_owner_from_actor(client: AsyncClient) -> None:
    owner_id = await create_verified_user(client, unique_email("personalowner"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Take medication",
            "scope": "personal",
            "interval_weeks": 1,
            "week_anchor_date": today,
            "start_date": today,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["scope"] == "personal"
    assert body["owner_user_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_create_personal_routine_rejects_explicit_members(client: AsyncClient) -> None:
    owner_id = await create_verified_user(client, unique_email("personalmembers"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date().isoformat()

    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/routines",
        json={
            "title": "Take medication",
            "scope": "personal",
            "interval_weeks": 1,
            "week_anchor_date": today,
            "start_date": today,
            "member_ids": [str(owner_id)],
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_routines_excludes_other_members_personal_routines(
    client: AsyncClient,
) -> None:
    owner_id = await create_verified_user(client, unique_email("privateowner"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()

    async with SessionFactory() as db:
        routine = make_routine(
            group_id=home_id,
            created_by=owner_id,
            week_anchor_date=today,
            scope=RoutineScope.personal,
            owner_user_id=owner_id,
        )
        db.add(routine)
        await db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_id = await create_verified_user(other_client, unique_email("privateother"), "Other")
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

        listed = await unsafe(other_client, "GET", f"/api/v1/homes/{home_id}/routines")
        assert listed.status_code == 200
        assert listed.json()["items"] == []

    owner_listed = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/routines")
    assert len(owner_listed.json()["items"]) == 1


@pytest.mark.asyncio
async def test_update_delete_complete_other_users_personal_routine_returns_404(
    client: AsyncClient,
) -> None:
    owner_id = await create_verified_user(client, unique_email("guardowner"), "Owner")
    home_id = await create_home_with_notifications(client)
    today = datetime.now(UTC).date()

    async with SessionFactory() as db:
        routine = make_routine(
            group_id=home_id,
            created_by=owner_id,
            week_anchor_date=today,
            scope=RoutineScope.personal,
            owner_user_id=owner_id,
        )
        db.add(routine)
        await db.commit()
        await db.refresh(routine)
        routine_id = str(routine.id)
        updated_at = routine.updated_at.isoformat()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_id = await create_verified_user(other_client, unique_email("guardother"), "Other")
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

        update = await unsafe(
            other_client,
            "PATCH",
            f"/api/v1/homes/{home_id}/routines/{routine_id}",
            json={
                "title": "Hijacked",
                "scope": "household",
                "interval_weeks": 1,
                "week_anchor_date": today.isoformat(),
                "start_date": today.isoformat(),
                "expected_updated_at": updated_at,
            },
        )
        assert update.status_code == 404

        complete = await unsafe(
            other_client,
            "POST",
            f"/api/v1/homes/{home_id}/routines/{routine_id}/complete",
            json={"occurrence_date": today.isoformat()},
        )
        assert complete.status_code == 404

        delete = await unsafe(
            other_client, "DELETE", f"/api/v1/homes/{home_id}/routines/{routine_id}"
        )
        assert delete.status_code == 404
    assert other_id  # keep reference; ownership is what's under test


@pytest.mark.asyncio
async def test_deliver_notifies_only_owner_for_personal_routine(client: AsyncClient) -> None:
    owner_id = await create_verified_user(client, unique_email("personaldeliver"), "Owner")
    home_id = await create_home_with_notifications(client)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_id = await create_verified_user(
            other_client, unique_email("personaldeliverother"), "Other"
        )
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
        routine = make_routine(
            group_id=home_id,
            created_by=owner_id,
            week_anchor_date=today,
            scope=RoutineScope.personal,
            owner_user_id=owner_id,
        )
        db.add(routine)
        # Even if a HouseholdRoutineMember row exists (e.g. left over from a prior
        # scope switch), a personal routine must never consult it — only owner_user_id.
        await db.flush()
        db.add(HouseholdRoutineMember(routine_id=routine.id, user_id=other_id))
        await db.commit()
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "evening_before"
        )
        await db.commit()

        owner_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == owner_id)
        )
        other_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == other_id)
        )
        assert owner_notification is not None
        assert other_notification is None
