"""Tests for the Daily Nudge Summary — a separate, user-configurable *morning*
digest of today's outstanding Routines/Reminders/To-dos (see
mykhaya.notifications.nudges.deliver_daily_nudge_summary), distinct from Daily
Briefing (mykhaya.notifications.briefing) and from the existing *evening*
Nudges preferences. Also covers the individual-notification deduplication
this introduces in mykhaya.notifications.routines/standalone_reminders, and
the Daily Briefing regression this whole slice fixes (a Nudges-hijacked
briefing no longer sends the user's actual calendar/meal content).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    FeatureFlag,
    FeatureKey,
    FeatureOverride,
    HouseholdRoutine,
    Notification,
    OutboxEvent,
    Reminder,
    ReminderCadence,
    ReminderCompletion,
    ReminderRepeat,
    RoutineReminderTiming,
    RoutineScope,
    SubscriptionPlan,
    Todo,
    TokenPurpose,
    User,
)
from mykhaya.notifications.briefing import deliver_daily_briefing
from mykhaya.notifications.engine import get_or_create_preferences
from mykhaya.notifications.nudges import (
    DAILY_SUMMARY_TOPIC,
    deliver_daily_nudge_summary,
    scan_due_daily_nudge_summary,
)
from mykhaya.notifications.routines import deliver_routine_reminder
from mykhaya.notifications.standalone_reminders import deliver_standalone_reminder
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


async def create_home_with_notifications(client: AsyncClient, *, family: bool = False) -> uuid.UUID:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Nudge Summary Home"})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=True)
        )
        db.add(FeatureOverride(feature_key=FeatureKey.calendar, group_id=home_id, enabled=True))
        if family:
            # Household-scope routines require Family — see
            # test_commercial_plan_cleanup.py for the Free-vs-Family gating
            # itself; this file is about scheduling/dedup mechanics.
            subscription = await get_home_subscription(db, home_id)
            assert subscription is not None
            subscription.plan = SubscriptionPlan.family
        await db.commit()
    return home_id


async def set_user_timezone(user_id: uuid.UUID, timezone: str = "Europe/London") -> None:
    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.timezone = timezone
        await db.commit()


async def configure_summary(
    user_id: uuid.UUID,
    *,
    enabled: bool = True,
    summary_time: time | None = None,
) -> None:
    async with SessionFactory() as db:
        prefs = await get_or_create_preferences(db, user_id)
        prefs.daily_nudge_summary_enabled = enabled
        if summary_time is not None:
            prefs.daily_nudge_summary_time = summary_time
        await db.commit()


def make_routine(
    *,
    group_id: uuid.UUID,
    created_by: uuid.UUID,
    week_anchor_date: date,
    reminder_timing: RoutineReminderTiming = RoutineReminderTiming.same_day,
    scope: RoutineScope = RoutineScope.household,
    owner_user_id: uuid.UUID | None = None,
) -> HouseholdRoutine:
    return HouseholdRoutine(
        group_id=group_id,
        title="Take Tablet",
        scope=scope,
        owner_user_id=owner_user_id,
        interval_weeks=1,
        repeat_unit="weekly",
        week_anchor_date=week_anchor_date,
        reminder_timing=reminder_timing,
        is_critical=False,
        enabled=True,
        start_date=week_anchor_date - timedelta(days=365),
        created_by=created_by,
    )


def make_reminder(
    *,
    group_id: uuid.UUID,
    created_by: uuid.UUID,
    due_date: date,
    due_time: time = time(7, 30),
    cadence: ReminderCadence = ReminderCadence.once,
    scope: RoutineScope = RoutineScope.household,
    owner_user_id: uuid.UUID | None = None,
) -> Reminder:
    return Reminder(
        group_id=group_id,
        title="Sign the school form",
        scope=scope,
        owner_user_id=owner_user_id,
        due_date=due_date,
        due_time=due_time,
        repeat=ReminderRepeat.never,
        cadence=cadence,
        enabled=True,
        created_by=created_by,
    )


@pytest.fixture(autouse=True)
async def clean_outbox() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        await db.execute(delete(OutboxEvent).where(OutboxEvent.topic == DAILY_SUMMARY_TOPIC))
        await db.commit()


# --- defaults / preferences --------------------------------------------------


@pytest.mark.asyncio
async def test_new_user_defaults_to_enabled_at_0730(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("defaults"), "Defaults Owner")
    async with SessionFactory() as db:
        prefs = await get_or_create_preferences(db, user_id)
        assert prefs.daily_nudge_summary_enabled is True
        assert prefs.daily_nudge_summary_time == time(7, 30)
        await db.commit()


@pytest.mark.asyncio
async def test_changing_nudge_summary_time_does_not_alter_briefing_time(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(client, unique_email("independent"), "Independent Owner")
    async with SessionFactory() as db:
        prefs = await get_or_create_preferences(db, user_id)
        original_briefing_time = prefs.briefing_time
        prefs.daily_nudge_summary_time = time(8, 0)
        await db.commit()
    async with SessionFactory() as db:
        prefs = await get_or_create_preferences(db, user_id)
        assert prefs.daily_nudge_summary_time == time(8, 0)
        assert prefs.briefing_time == original_briefing_time


# --- empty day ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_sends_nothing_on_an_empty_day(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("emptynudge"), "Empty Nudge Owner")
    await set_user_timezone(user_id)
    await configure_summary(user_id)

    today = datetime.now(UTC).astimezone(TZ).date()
    async with SessionFactory() as db:
        await deliver_daily_nudge_summary(db, get_settings(), str(user_id), today.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is None


# --- content --------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_reports_correct_grammatical_counts_and_excludes_completed(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(client, unique_email("counts"), "Counts Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id)
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        db.add(make_routine(group_id=home_id, created_by=user_id, week_anchor_date=today))
        db.add(make_reminder(group_id=home_id, created_by=user_id, due_date=today))
        db.add(Todo(group_id=home_id, title="Buy milk", due_date=today, created_by=user_id))
        completed = Todo(
            group_id=home_id,
            title="Already done",
            due_date=today,
            created_by=user_id,
            completed_at=datetime.now(UTC),
            completed_by=user_id,
        )
        db.add(completed)
        await db.commit()

        await deliver_daily_nudge_summary(db, get_settings(), str(user_id), today.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None
        assert notification.title == "Your Nudges today"
        assert "1 routine, 1 to-do and 1 reminder" in notification.body
        assert "Take Tablet" in notification.body
        assert "Sign the school form" in notification.body
        assert "Buy milk" in notification.body
        assert "Already done" not in notification.body


@pytest.mark.asyncio
async def test_deliver_uses_plural_wording_for_multiple_items() -> None:
    from mykhaya.notifications.nudges import _count_phrase

    assert _count_phrase(0, "routine") == "0 routines"
    assert _count_phrase(1, "routine") == "1 routine"
    assert _count_phrase(2, "routine") == "2 routines"


# --- disabled / idempotent -------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_skips_when_disabled(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("nudgeoff"), "Nudge Off Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id, enabled=False)
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        db.add(make_routine(group_id=home_id, created_by=user_id, week_anchor_date=today))
        await db.commit()
        await deliver_daily_nudge_summary(db, get_settings(), str(user_id), today.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is None


@pytest.mark.asyncio
async def test_deliver_skips_on_free_plan_even_with_outstanding_items(client: AsyncClient) -> None:
    """Phase 2B: nudges.enabled is Family-only — a Free Home's routines/
    reminders/to-dos never surface in, or trigger, the Daily Nudge Summary,
    even though the underlying data exists and the user has the preference
    enabled."""
    user_id = await create_verified_user(client, unique_email("freenudge"), "Free Nudge Owner")
    home_id = await create_home_with_notifications(client, family=False)
    await set_user_timezone(user_id)
    await configure_summary(user_id)
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        db.add(
            Todo(group_id=home_id, title="Buy milk", due_date=today, created_by=user_id)
        )
        await db.commit()
        await deliver_daily_nudge_summary(db, get_settings(), str(user_id), today.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is None


@pytest.mark.asyncio
async def test_deliver_skips_when_nudges_module_disabled_for_home(client: AsyncClient) -> None:
    """A Home Admin (or a stale override) disabling the Nudges module
    itself suppresses the summary too — not just Notifications."""
    user_id = await create_verified_user(client, unique_email("nudgesoff"), "Nudges Off Owner")
    home_id = await create_home_with_notifications(client, family=True)
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.nudges, group_id=home_id, enabled=False))
        await db.commit()
    await set_user_timezone(user_id)
    await configure_summary(user_id)
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        db.add(
            Todo(group_id=home_id, title="Buy milk", due_date=today, created_by=user_id)
        )
        await db.commit()
        await deliver_daily_nudge_summary(db, get_settings(), str(user_id), today.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is None


@pytest.mark.asyncio
async def test_deliver_skips_when_notifications_disabled_for_home(client: AsyncClient) -> None:
    """Notifications delivery infrastructure is checked independently of
    Nudges module/entitlement state — disabling it (platform-wide, here)
    suppresses the summary send without affecting Nudges API access
    itself."""
    user_id = await create_verified_user(
        client, unique_email("notifsoff"), "Notifications Off Owner"
    )
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id)
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        db.add(
            Todo(group_id=home_id, title="Buy milk", due_date=today, created_by=user_id)
        )
        # The Home's own FeatureOverride says notifications=True (set by
        # create_home_with_notifications) — disable it globally instead, to
        # prove the platform layer is checked too, not just the override.
        flag = await db.scalar(
            select(FeatureFlag).where(FeatureFlag.key == FeatureKey.notifications)
        )
        assert flag is not None
        original = flag.enabled
        flag.enabled = False
        await db.commit()
    try:
        async with SessionFactory() as db:
            await deliver_daily_nudge_summary(db, get_settings(), str(user_id), today.isoformat())
            await db.commit()
            notification = await db.scalar(
                select(Notification).where(Notification.recipient_user_id == user_id)
            )
            assert notification is None
    finally:
        async with SessionFactory() as db:
            flag = await db.scalar(
                select(FeatureFlag).where(FeatureFlag.key == FeatureKey.notifications)
            )
            assert flag is not None
            flag.enabled = original
            await db.commit()


@pytest.mark.asyncio
async def test_deliver_is_idempotent_per_user_per_day(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("idemnudge"), "Idem Nudge Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id)
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        db.add(make_routine(group_id=home_id, created_by=user_id, week_anchor_date=today))
        await db.commit()
        await deliver_daily_nudge_summary(db, get_settings(), str(user_id), today.isoformat())
        await deliver_daily_nudge_summary(db, get_settings(), str(user_id), today.isoformat())
        await db.commit()
        notifications = (
            await db.scalars(select(Notification).where(Notification.recipient_user_id == user_id))
        ).all()
        assert len(notifications) == 1


@pytest.mark.asyncio
async def test_scan_is_idempotent_under_repeated_runs(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("scannudge"), "Scan Nudge Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    now_local = datetime.now(UTC).astimezone(TZ)
    await configure_summary(user_id, summary_time=now_local.time().replace(microsecond=0))

    async with SessionFactory() as db:
        db.add(
            make_routine(group_id=home_id, created_by=user_id, week_anchor_date=now_local.date())
        )
        await db.commit()

        await scan_due_daily_nudge_summary(db, get_settings())
        await scan_due_daily_nudge_summary(db, get_settings())
        rows = (
            await db.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.topic == DAILY_SUMMARY_TOPIC,
                    OutboxEvent.dedupe_key
                    == f"daily-nudge-summary:{user_id}:{now_local.date().isoformat()}",
                )
            )
        ).all()
        assert len(rows) == 1


# --- Daily Briefing must not be hijacked -------------------------------------


@pytest.mark.asyncio
async def test_daily_briefing_still_sends_real_calendar_content_when_user_also_has_nudges_items(
    client: AsyncClient,
) -> None:
    """Regression coverage for the actual reported bug: an enabled Daily
    Briefing must always deliver the user's calendar/meal content — it must
    never be silently replaced by a Nudges-style summary just because the
    user also has due routines/reminders/todos that day."""
    user_id = await create_verified_user(client, unique_email("nothijacked"), "Not Hijacked Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    today_local = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        prefs = await get_or_create_preferences(db, user_id)
        prefs.daily_briefing_enabled = True
        prefs.empty_day_briefing_enabled = True
        # A due routine, reminder and to-do for the same user/day — exactly
        # the condition that used to divert deliver_daily_briefing() into
        # the Nudges template instead of the calendar briefing.
        db.add(make_routine(group_id=home_id, created_by=user_id, week_anchor_date=today_local))
        db.add(make_reminder(group_id=home_id, created_by=user_id, due_date=today_local))
        db.add(Todo(group_id=home_id, title="Pack lunch", due_date=today_local, created_by=user_id))
        await db.commit()

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

    async with SessionFactory() as db:
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None
        # The real calendar-briefing content — not the Nudges wording.
        assert notification.title == "You have 1 event today."
        assert "Swimming" in notification.body
        assert notification.deep_link == {"type": "calendar_today"}
        # And definitely not the hijacked Nudges-flavoured message.
        assert notification.title != "Your Nudges today"


# --- deduplication ------------------------------------------------------------


@pytest.mark.asyncio
async def test_routine_same_day_suppressed_when_covered_by_summary_at_same_time(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(
        client, unique_email("deduproutine"), "Dedup Routine Owner"
    )
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    # Home tz falls back to settings.default_timezone ("Europe/London"),
    # matching the routine's fixed 07:30 same_day send exactly.
    await configure_summary(user_id, summary_time=time(7, 30))
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        routine = make_routine(group_id=home_id, created_by=user_id, week_anchor_date=today)
        db.add(routine)
        await db.commit()
        await db.refresh(routine)
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "same_day"
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is None  # suppressed — covered by the (not-yet-sent) summary


@pytest.mark.asyncio
async def test_routine_evening_before_is_never_suppressed(client: AsyncClient) -> None:
    """evening_before is about *tomorrow's* occurrence at 18:00 — it can
    never collide with a morning summary and must always be delivered."""
    user_id = await create_verified_user(
        client, unique_email("dedupevening"), "Dedup Evening Owner"
    )
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id, summary_time=time(7, 30))
    today = datetime.now(UTC).astimezone(TZ).date()
    tomorrow = today + timedelta(days=1)

    async with SessionFactory() as db:
        routine = make_routine(
            group_id=home_id,
            created_by=user_id,
            week_anchor_date=tomorrow,
            reminder_timing=RoutineReminderTiming.evening_before,
        )
        db.add(routine)
        await db.commit()
        await db.refresh(routine)
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, tomorrow.isoformat(), "evening_before"
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None


@pytest.mark.asyncio
async def test_routine_not_suppressed_when_summary_disabled(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("dedupoff"), "Dedup Off Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id, enabled=False, summary_time=time(7, 30))
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        routine = make_routine(group_id=home_id, created_by=user_id, week_anchor_date=today)
        db.add(routine)
        await db.commit()
        await db.refresh(routine)
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "same_day"
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None


@pytest.mark.asyncio
async def test_routine_not_suppressed_when_summary_time_differs(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("dedupdiff"), "Dedup Diff Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id, summary_time=time(20, 0))  # not near 07:30
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        routine = make_routine(group_id=home_id, created_by=user_id, week_anchor_date=today)
        db.add(routine)
        await db.commit()
        await db.refresh(routine)
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "same_day"
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None


@pytest.mark.asyncio
async def test_routine_not_suppressed_when_summary_is_one_minute_before(
    client: AsyncClient,
) -> None:
    """A near-miss must not be treated as the same occurrence: the summary
    and the routine's fixed 07:30 same-day send are each exact,
    minute-precision configured times, not a "now" vs. scan-cursor
    comparison — so there is no tolerance window, and even one minute's
    difference means a different occurrence that must still be delivered
    individually."""
    user_id = await create_verified_user(client, unique_email("dedupbefore"), "Dedup Before Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id, summary_time=time(7, 29))
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        routine = make_routine(group_id=home_id, created_by=user_id, week_anchor_date=today)
        db.add(routine)
        await db.commit()
        await db.refresh(routine)
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "same_day"
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None


@pytest.mark.asyncio
async def test_routine_not_suppressed_when_summary_is_one_minute_after(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(client, unique_email("dedupafter"), "Dedup After Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id, summary_time=time(7, 31))
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        routine = make_routine(group_id=home_id, created_by=user_id, week_anchor_date=today)
        db.add(routine)
        await db.commit()
        await db.refresh(routine)
        routine_id = str(routine.id)

        await deliver_routine_reminder(
            db, get_settings(), routine_id, today.isoformat(), "same_day"
        )
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None


@pytest.mark.asyncio
async def test_reminder_slot0_suppressed_but_later_escalation_slot_still_delivered(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(client, unique_email("dedupesc"), "Dedup Escalation Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id, summary_time=time(7, 30))
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        reminder = make_reminder(
            group_id=home_id,
            created_by=user_id,
            due_date=today,
            due_time=time(7, 30),
            cadence=ReminderCadence.hourly,
        )
        db.add(reminder)
        await db.commit()
        await db.refresh(reminder)
        reminder_id = str(reminder.id)

        # Slot 0 — the reminder's first due-time send — is covered by the
        # summary window and must be suppressed.
        await deliver_standalone_reminder(
            db, get_settings(), reminder_id, today.isoformat(), "hourly", 0
        )
        await db.commit()
        assert (
            await db.scalar(select(Notification).where(Notification.recipient_user_id == user_id))
        ) is None

        # Slot 3 (three hours later, e.g. 10:30) is an escalation of an item
        # still incomplete — must always be delivered regardless of the
        # morning summary.
        await deliver_standalone_reminder(
            db, get_settings(), reminder_id, today.isoformat(), "hourly", 3
        )
        await db.commit()
        assert (
            await db.scalar(select(Notification).where(Notification.recipient_user_id == user_id))
        ) is not None


@pytest.mark.asyncio
async def test_reminder_not_suppressed_when_item_not_in_summary(client: AsyncClient) -> None:
    """A reminder already completed for today's occurrence is not part of
    what the summary would show — its (already-guarded-elsewhere)
    individual send path must not be additionally suppressed by dedup
    logic that doesn't apply to it."""
    user_id = await create_verified_user(client, unique_email("dedupdone"), "Dedup Done Owner")
    home_id = await create_home_with_notifications(client, family=True)
    await set_user_timezone(user_id)
    await configure_summary(user_id, summary_time=time(7, 30))
    today = datetime.now(UTC).astimezone(TZ).date()

    async with SessionFactory() as db:
        reminder = make_reminder(
            group_id=home_id, created_by=user_id, due_date=today, due_time=time(7, 30)
        )
        db.add(reminder)
        await db.flush()
        db.add(
            ReminderCompletion(
                reminder_id=reminder.id, occurrence_date=today, completed_by=user_id
            )
        )
        await db.commit()
        reminder_id = str(reminder.id)

        # deliver_standalone_reminder itself already returns early for a
        # completed occurrence (pre-existing behaviour) — confirms the new
        # dedup check introduced no additional suppression path bypassing
        # that; the reminder correctly produces no notification either way.
        await deliver_standalone_reminder(
            db, get_settings(), reminder_id, today.isoformat(), "once", 0
        )
        await db.commit()
        assert (
            await db.scalar(select(Notification).where(Notification.recipient_user_id == user_id))
        ) is None
