"""Calendar reminders: explicit per-event reminders, the opt-in default timed reminder and the
opt-in all-day reminder preference, and the defaults those preferences ship with.

Every scan here runs at an exact injected instant (``scan_due_reminders(..., now=...)``) and
every delivery goes through the real ``deliver_event_reminder``, so the assertions cover both
which outbox rows are selected and the notification each recipient finally receives. Events
are inserted directly so start times, recurrence and attendance are fully controlled.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, available_timezones

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    CalendarEvent,
    CalendarEventMember,
    FeatureKey,
    FeatureOverride,
    Group,
    HomeCalendar,
    HouseholdRelationship,
    Membership,
    Notification,
    NotificationPreferences,
    OutboxEvent,
    PermissionProfile,
    RecurrencePattern,
    Role,
    TokenPurpose,
    User,
)
from mykhaya.notifications import reminders
from mykhaya.notifications.engine import get_or_create_preferences
from mykhaya.notifications.reminders import (
    ALL_DAY_DUE_SPREAD,
    ALL_DAY_PREFERENCE_REMINDER,
    DEFAULT_RECURRING_SWEEP_INTERVAL,
    LOOKAHEAD,
    MAX_DEFAULT_REMINDER_MINUTES,
    MAX_EVENT_REMINDER_MINUTES,
    REMINDER_TOPIC,
    deliver_event_reminder,
    due_reminder_candidates,
    scan_due_reminders,
)
from mykhaya.schemas import EventCreate, EventUpdate, NotificationPreferencesUpdate
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"
HALF_MINUTE = timedelta(seconds=30)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture(autouse=True)
async def clean_reminder_outbox() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        await db.execute(delete(OutboxEvent).where(OutboxEvent.topic == REMINDER_TOPIC))
        await db.commit()


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


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


@dataclass
class Home:
    id: uuid.UUID
    calendar_id: uuid.UUID
    owner_id: uuid.UUID
    member_id: uuid.UUID


async def make_home(client: AsyncClient, *, opted_in: bool = True) -> Home:
    """A Home with Calendar and Notifications switched on, its owner (a Home Admin) and one
    further adult member, both in UTC.

    The default timed reminder (30 minutes) and the all-day reminder (09:00) are opt-in, so by
    default both people here have switched them on, as they would in Calendar settings. Pass
    ``opted_in=False`` for people on the shipped defaults, who have not."""
    owner_id = await create_verified_user(client, unique_email("owner"), "Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Reminder Defaults Home"})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        member_id = await create_verified_user(second_client, unique_email("member"), "Member")
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.calendar, group_id=home_id, enabled=True))
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=True)
        )
        db.add(
            Membership(
                group_id=home_id,
                user_id=member_id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        calendar = await db.scalar(
            select(HomeCalendar).where(
                HomeCalendar.group_id == home_id, HomeCalendar.is_primary.is_(True)
            )
        )
        if calendar is None:
            calendar = HomeCalendar(
                group_id=home_id, name="Home", timezone="Europe/London", is_primary=True
            )
            db.add(calendar)
        for user_id in (owner_id, member_id):
            preferences = await get_or_create_preferences(db, user_id)
            if opted_in:
                preferences.default_event_reminder_enabled = True
                preferences.all_day_reminder_enabled = True
            user = await db.get(User, user_id)
            assert user is not None
            user.timezone = "UTC"  # an all-day reminder is a time of day in the user's own zone
        await db.commit()
        return Home(home_id, calendar.id, owner_id, member_id)


async def insert_event(
    home: Home,
    *,
    start_at: datetime,
    end_at: datetime | None = None,
    is_all_day: bool = False,
    reminder_minutes: int | None = None,
    recurrence: RecurrencePattern = RecurrencePattern.none,
    recurrence_until: datetime | None = None,
    recurrence_end_date: date | None = None,
    timezone: str = "Europe/London",
    attendees: tuple[uuid.UUID, ...] | None = None,
    declined: tuple[uuid.UUID, ...] = (),
) -> uuid.UUID:
    """Insert an event and its participants. ``attendees`` defaults to the owner and the
    member, both accepted; ``declined`` are participants who declined."""
    if end_at is None:
        end_at = start_at + (timedelta(days=1) if is_all_day else timedelta(hours=1))
    accepted = attendees if attendees is not None else (home.owner_id, home.member_id)
    async with SessionFactory() as db:
        event = CalendarEvent(
            group_id=home.id,
            calendar_id=home.calendar_id,
            title="Reminder test",
            start_at=start_at,
            end_at=end_at,
            is_all_day=is_all_day,
            timezone=timezone,
            reminder_minutes=reminder_minutes,
            recurrence=recurrence,
            recurrence_until=recurrence_until,
            recurrence_end_date=recurrence_end_date,
            created_by=home.owner_id,
        )
        db.add(event)
        await db.flush()
        for user_id in accepted:
            db.add(CalendarEventMember(group_id=home.id, event_id=event.id, user_id=user_id))
        for user_id in declined:
            db.add(
                CalendarEventMember(
                    group_id=home.id,
                    event_id=event.id,
                    user_id=user_id,
                    attendance_status="declined",
                )
            )
        await db.commit()
        return event.id


async def set_preferences(user_id: uuid.UUID, **fields: object) -> None:
    async with SessionFactory() as db:
        preferences = await get_or_create_preferences(db, user_id)
        for name, value in fields.items():
            setattr(preferences, name, value)
        await db.commit()


async def set_user_timezone(user_id: uuid.UUID, timezone: str) -> None:
    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.timezone = timezone
        await db.commit()


async def scan(now: datetime) -> None:
    async with SessionFactory() as db:
        await scan_due_reminders(db, get_settings(), now=now)


async def outbox_rows(event_id: uuid.UUID) -> list[OutboxEvent]:
    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.topic == REMINDER_TOPIC)
                .order_by(OutboxEvent.created_at, OutboxEvent.dedupe_key)
            )
        ).all()
        return [row for row in rows if row.payload.get("event_id") == str(event_id)]


async def deliver(row: OutboxEvent) -> None:
    """What the worker does with one reminder outbox row."""
    payload = row.payload
    async with SessionFactory() as db:
        await deliver_event_reminder(
            db,
            get_settings(),
            payload["event_id"],
            payload["occurrence_start"],
            payload["reminder_minutes"],
            payload.get("recipient_user_id"),
            payload.get("all_day_reminder_time"),
        )
        await db.commit()


async def deliver_all(event_id: uuid.UUID) -> None:
    for row in await outbox_rows(event_id):
        await deliver(row)


async def reminders_received(user_id: uuid.UUID, event_id: uuid.UUID) -> list[Notification]:
    async with SessionFactory() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.recipient_user_id == user_id,
                        Notification.notification_type == "event_reminder",
                        Notification.related_entity_id == event_id,
                    )
                )
            ).all()
        )


async def candidate_ids(now: datetime, *, include_default_recurring: bool = True) -> set[uuid.UUID]:
    async with SessionFactory() as db:
        events = await due_reminder_candidates(
            db, now, include_default_recurring=include_default_recurring
        )
        return {event.id for event in events}


def a_start() -> datetime:
    """A timed start three days from now at 15:00 UTC — far from any other test's events."""
    return datetime.combine((datetime.now(UTC) + timedelta(days=3)).date(), time(15, 0), tzinfo=UTC)


def payload_of(row: OutboxEvent) -> dict[str, object]:
    return dict(row.payload)


# --- 1. timed event with an explicit reminder --------------------------------------------


@pytest.mark.asyncio
async def test_explicit_reminder_still_enqueues_one_event_level_row_and_notifies_attendees(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    start = a_start()
    event_id = await insert_event(home, start_at=start, reminder_minutes=10)

    await scan(start - timedelta(minutes=10) - HALF_MINUTE)

    rows = await outbox_rows(event_id)
    assert len(rows) == 1
    assert payload_of(rows[0]) == {
        "event_id": str(event_id),
        "occurrence_start": start.isoformat(),
        "reminder_minutes": 10,
    }
    assert rows[0].dedupe_key == f"reminder:{event_id}:{start.isoformat()}:10"

    await deliver(rows[0])
    for user_id in (home.owner_id, home.member_id):
        received = await reminders_received(user_id, event_id)
        assert len(received) == 1
        assert received[0].title == "Reminder test"
        assert f"at {start.astimezone(ZoneInfo('Europe/London')).strftime('%H:%M')}" in (
            received[0].body
        )


# --- 2/3. timed event, no explicit reminder: default timed reminder ----------------------


@pytest.mark.asyncio
async def test_timed_event_without_explicit_reminder_uses_each_attendees_default(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    await set_preferences(home.member_id, default_event_reminder_minutes=15)
    start = a_start()
    event_id = await insert_event(home, start_at=start)

    # 30 minutes before the start: the owner's default (30) is due, the member's (15) is not.
    await scan(start - timedelta(minutes=30) - HALF_MINUTE)
    rows = await outbox_rows(event_id)
    assert [payload_of(r)["recipient_user_id"] for r in rows] == [str(home.owner_id)]
    assert payload_of(rows[0])["reminder_minutes"] == 30
    assert rows[0].dedupe_key == f"reminder:{event_id}:{start.isoformat()}:{home.owner_id}:30"

    # 15 minutes before: now the member's default is due as well.
    await scan(start - timedelta(minutes=15) - HALF_MINUTE)
    rows = await outbox_rows(event_id)
    assert {payload_of(r)["recipient_user_id"] for r in rows} == {
        str(home.owner_id),
        str(home.member_id),
    }

    await deliver_all(event_id)
    for user_id in (home.owner_id, home.member_id):
        received = await reminders_received(user_id, event_id)
        assert len(received) == 1, "each attendee is reminded exactly once"


@pytest.mark.asyncio
async def test_default_timed_reminder_switched_off_is_not_enqueued(client: AsyncClient) -> None:
    home = await make_home(client)
    await set_preferences(home.owner_id, default_event_reminder_enabled=False)
    start = a_start()
    event_id = await insert_event(home, start_at=start)

    await scan(start - timedelta(minutes=30) - HALF_MINUTE)

    rows = await outbox_rows(event_id)
    assert [payload_of(r)["recipient_user_id"] for r in rows] == [str(home.member_id)]
    await deliver_all(event_id)
    assert await reminders_received(home.owner_id, event_id) == []
    assert len(await reminders_received(home.member_id, event_id)) == 1


@pytest.mark.asyncio
async def test_only_accepted_attendees_get_a_default_reminder(client: AsyncClient) -> None:
    home = await make_home(client)
    start = a_start()
    event_id = await insert_event(
        home, start_at=start, attendees=(home.owner_id,), declined=(home.member_id,)
    )

    await scan(start - timedelta(minutes=30) - HALF_MINUTE)

    assert [payload_of(r)["recipient_user_id"] for r in await outbox_rows(event_id)] == [
        str(home.owner_id)
    ]


# --- 4/5. all-day events: the all-day reminder preference --------------------------------


def all_day_start(days_ahead: int = 3) -> datetime:
    """An all-day event's stored start: a pure date at UTC midnight."""
    target = (datetime.now(UTC) + timedelta(days=days_ahead)).date()
    return datetime(target.year, target.month, target.day, tzinfo=UTC)


@pytest.mark.asyncio
async def test_all_day_event_reminds_at_each_attendees_all_day_time(client: AsyncClient) -> None:
    home = await make_home(client)
    await set_preferences(home.owner_id, all_day_reminder_time=time(9, 0))
    # Includes seconds, which the API allows — they must survive the round trip to delivery.
    await set_preferences(home.member_id, all_day_reminder_time=time(18, 30, 15))
    start = all_day_start()
    event_id = await insert_event(home, start_at=start, is_all_day=True)

    owner_due = start.replace(hour=9, minute=0)
    await scan(owner_due - HALF_MINUTE)
    rows = await outbox_rows(event_id)
    assert [payload_of(r)["recipient_user_id"] for r in rows] == [str(home.owner_id)]
    assert payload_of(rows[0])["reminder_minutes"] == ALL_DAY_PREFERENCE_REMINDER
    assert payload_of(rows[0])["all_day_reminder_time"] == "09:00:00"

    member_due = start.replace(hour=18, minute=30, second=15)
    await scan(member_due - HALF_MINUTE)
    rows = await outbox_rows(event_id)
    assert {payload_of(r)["recipient_user_id"] for r in rows} == {
        str(home.owner_id),
        str(home.member_id),
    }

    await deliver_all(event_id)
    for user_id in (home.owner_id, home.member_id):
        received = await reminders_received(user_id, event_id)
        assert len(received) == 1
        assert "today" in received[0].body


@pytest.mark.asyncio
async def test_all_day_reminder_switched_off_is_not_enqueued(client: AsyncClient) -> None:
    home = await make_home(client)
    await set_preferences(home.owner_id, all_day_reminder_enabled=False)
    start = all_day_start()
    event_id = await insert_event(home, start_at=start, is_all_day=True)

    await scan(start.replace(hour=9) - HALF_MINUTE)

    assert [payload_of(r)["recipient_user_id"] for r in await outbox_rows(event_id)] == [
        str(home.member_id)
    ]


@pytest.mark.asyncio
async def test_all_day_reminder_date_is_the_stored_date_in_a_zone_behind_utc(
    client: AsyncClient,
) -> None:
    """An all-day event on 10 Sept is stored as 2026-09-10T00:00Z. For a New York user the
    reminder is 09:00 on the 10th (13:00Z) — not on the 9th, which is what you get by
    converting that midnight into the event's own zone first."""
    home = await make_home(client)
    await set_user_timezone(home.owner_id, "America/New_York")
    start = all_day_start()
    event_id = await insert_event(
        home,
        start_at=start,
        is_all_day=True,
        timezone="America/New_York",
        attendees=(home.owner_id,),
    )
    on_the_day = datetime.combine(start.date(), time(9, 0), tzinfo=ZoneInfo("America/New_York"))
    the_day_before = on_the_day - timedelta(days=1)

    await scan(the_day_before.astimezone(UTC) - HALF_MINUTE)
    assert await outbox_rows(event_id) == []

    await scan(on_the_day.astimezone(UTC) - HALF_MINUTE)
    assert len(await outbox_rows(event_id)) == 1


# --- 6. explicit reminders take precedence over the defaults -----------------------------


@pytest.mark.asyncio
async def test_explicit_reminder_takes_precedence_over_the_default_for_a_timed_event(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    start = a_start()
    event_id = await insert_event(home, start_at=start, reminder_minutes=5)

    # When the default (30 min) would be due, an event with its own reminder does nothing.
    await scan(start - timedelta(minutes=30) - HALF_MINUTE)
    assert await outbox_rows(event_id) == []

    await scan(start - timedelta(minutes=5) - HALF_MINUTE)
    rows = await outbox_rows(event_id)
    assert len(rows) == 1 and "recipient_user_id" not in payload_of(rows[0])

    await deliver_all(event_id)
    for user_id in (home.owner_id, home.member_id):
        assert len(await reminders_received(user_id, event_id)) == 1


@pytest.mark.asyncio
async def test_explicit_reminder_takes_precedence_over_the_all_day_preference(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    start = all_day_start()
    event_id = await insert_event(home, start_at=start, is_all_day=True, reminder_minutes=60)

    await scan(start.replace(hour=9) - HALF_MINUTE)  # the all-day preference moment
    assert await outbox_rows(event_id) == []

    await scan(start - timedelta(minutes=60) - HALF_MINUTE)  # the event's own reminder
    rows = await outbox_rows(event_id)
    assert len(rows) == 1 and payload_of(rows[0])["reminder_minutes"] == 60


# --- 7. preference filtering at delivery -------------------------------------------------


@pytest.mark.asyncio
async def test_default_reminder_switched_off_after_the_scan_is_not_delivered(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    start = a_start()
    event_id = await insert_event(home, start_at=start, attendees=(home.owner_id,))
    await scan(start - timedelta(minutes=30) - HALF_MINUTE)
    assert len(await outbox_rows(event_id)) == 1

    await set_preferences(home.owner_id, default_event_reminder_enabled=False)
    await deliver_all(event_id)

    assert await reminders_received(home.owner_id, event_id) == []


@pytest.mark.asyncio
async def test_a_default_reminder_for_a_time_the_user_has_since_changed_is_dropped(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    start = a_start()
    event_id = await insert_event(home, start_at=start, attendees=(home.owner_id,))
    await scan(start - timedelta(minutes=30) - HALF_MINUTE)

    await set_preferences(home.owner_id, default_event_reminder_minutes=45)
    await deliver_all(event_id)

    assert await reminders_received(home.owner_id, event_id) == []


@pytest.mark.asyncio
async def test_an_all_day_reminder_is_dropped_if_the_preference_changes_after_the_scan(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    start = all_day_start()
    event_id = await insert_event(
        home, start_at=start, is_all_day=True, attendees=(home.owner_id, home.member_id)
    )
    await scan(start.replace(hour=9) - HALF_MINUTE)
    assert len(await outbox_rows(event_id)) == 2

    await set_preferences(home.owner_id, all_day_reminder_enabled=False)
    await set_preferences(home.member_id, all_day_reminder_time=time(10, 0))
    await deliver_all(event_id)

    assert await reminders_received(home.owner_id, event_id) == []
    assert await reminders_received(home.member_id, event_id) == []


@pytest.mark.asyncio
async def test_declining_after_the_scan_drops_the_default_reminder(client: AsyncClient) -> None:
    home = await make_home(client)
    start = a_start()
    event_id = await insert_event(home, start_at=start)
    await scan(start - timedelta(minutes=30) - HALF_MINUTE)

    async with SessionFactory() as db:
        member = await db.scalar(
            select(CalendarEventMember).where(
                CalendarEventMember.event_id == event_id,
                CalendarEventMember.user_id == home.member_id,
            )
        )
        assert member is not None
        member.attendance_status = "declined"
        await db.commit()
    await deliver_all(event_id)

    assert await reminders_received(home.member_id, event_id) == []
    assert len(await reminders_received(home.owner_id, event_id)) == 1


@pytest.mark.asyncio
async def test_the_shared_reminders_toggle_still_silences_an_explicit_reminder(
    client: AsyncClient,
) -> None:
    """Explicit reminders are not governed by the *default* reminder toggle, only by the
    category toggle every reminder shares, which notify() applies."""
    home = await make_home(client)
    await set_preferences(
        home.owner_id, default_event_reminder_enabled=False, event_reminders_enabled=True
    )
    await set_preferences(home.member_id, event_reminders_enabled=False)
    start = a_start()
    event_id = await insert_event(home, start_at=start, reminder_minutes=10)

    await scan(start - timedelta(minutes=10) - HALF_MINUTE)
    await deliver_all(event_id)

    assert len(await reminders_received(home.owner_id, event_id)) == 1  # default toggle is off
    assert await reminders_received(home.member_id, event_id) == []


# --- 8. no duplicate delivery -------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_event_that_gains_an_explicit_reminder_is_not_reminded_twice(
    client: AsyncClient,
) -> None:
    """The event qualifies for the default reminder when scanned, then gets its own reminder
    at the very same lead time before delivery. Both rows exist; each attendee still gets
    exactly one notification."""
    home = await make_home(client)
    start = a_start()
    event_id = await insert_event(home, start_at=start)
    now = start - timedelta(minutes=30) - HALF_MINUTE
    await scan(now)
    assert len(await outbox_rows(event_id)) == 2  # one default row per attendee

    async with SessionFactory() as db:
        event = await db.get(CalendarEvent, event_id)
        assert event is not None
        event.reminder_minutes = 30
        await db.commit()
    await scan(now)
    assert len(await outbox_rows(event_id)) == 3  # plus the new event-level row

    await deliver_all(event_id)

    for user_id in (home.owner_id, home.member_id):
        assert len(await reminders_received(user_id, event_id)) == 1


# --- 9. idempotency across repeated scans -------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_scans_never_duplicate_rows_or_notifications(client: AsyncClient) -> None:
    home = await make_home(client)
    start = a_start()
    default_id = await insert_event(home, start_at=start)
    explicit_id = await insert_event(home, start_at=start + timedelta(hours=3), reminder_minutes=20)
    default_due = start - timedelta(minutes=30)
    explicit_due = start + timedelta(hours=3) - timedelta(minutes=20)

    # The scheduler scans every cycle; the window is LOOKAHEAD wide, so each reminder is seen
    # many times and (for the default) on both sides of its due moment's window boundary.
    instants = [default_due - LOOKAHEAD + timedelta(seconds=s) for s in range(1, 130, 7)]
    instants += [explicit_due - LOOKAHEAD + timedelta(seconds=s) for s in range(1, 130, 7)]
    for instant in instants:
        await scan(instant)
        await scan(instant)  # twice in a row, as two quick cycles would

    assert len(await outbox_rows(default_id)) == 2  # one per attendee
    assert len(await outbox_rows(explicit_id)) == 1

    # A processed row is still a row: scanning again must not re-enqueue it.
    async with SessionFactory() as db:
        for row in await db.scalars(select(OutboxEvent).where(OutboxEvent.topic == REMINDER_TOPIC)):
            row.processed_at = datetime.now(UTC)
        await db.commit()
    await scan(default_due - HALF_MINUTE)
    assert len(await outbox_rows(default_id)) == 2

    # And delivering the same row twice (a retry) still notifies once.
    for row in await outbox_rows(default_id):
        await deliver(row)
        await deliver(row)
    for user_id in (home.owner_id, home.member_id):
        assert len(await reminders_received(user_id, default_id)) == 1


@pytest.mark.asyncio
async def test_consecutive_two_minute_windows_enqueue_a_due_reminder_exactly_once(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    start = a_start()
    event_id = await insert_event(home, start_at=start, attendees=(home.owner_id,))
    due = start - timedelta(minutes=30)

    # Back-to-back windows [t, t+2m): the due instant lies in exactly one of them.
    for offset in range(-6, 3):
        await scan(due + LOOKAHEAD * offset + timedelta(seconds=45))

    assert len(await outbox_rows(event_id)) == 1


# --- 10. events outside the candidate window ----------------------------------------------


@pytest.mark.asyncio
async def test_events_that_cannot_be_due_soon_are_not_candidates_or_enqueued(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    now = a_start()
    near_default = await insert_event(home, start_at=now + timedelta(minutes=31))
    near_explicit = await insert_event(
        home, start_at=now + timedelta(minutes=11), reminder_minutes=10
    )
    near_all_day = await insert_event(home, start_at=all_day_start(0), is_all_day=True)

    # None of these can have a reminder due within the next two minutes.
    default_too_far = await insert_event(home, start_at=now + timedelta(hours=3))
    explicit_too_far = await insert_event(
        home, start_at=now + timedelta(hours=2), reminder_minutes=10
    )
    # Ten days out: still beyond the all-day window from both instants checked below (an
    # all-day event within two days of the scan instant is deliberately a candidate).
    all_day_next_week = await insert_event(
        home, start_at=all_day_start(0) + timedelta(days=10), is_all_day=True
    )
    already_past = await insert_event(home, start_at=now - timedelta(hours=5), reminder_minutes=10)
    long_past_default = await insert_event(home, start_at=now - timedelta(days=200))

    # The "now" that matters for the all-day event: well inside its own date's window.
    candidates = await candidate_ids(now)
    candidates |= await candidate_ids(all_day_start(0) + timedelta(hours=8))
    assert near_default in candidates and near_explicit in candidates and near_all_day in candidates
    for excluded in (
        default_too_far,
        explicit_too_far,
        all_day_next_week,
        already_past,
        long_past_default,
    ):
        assert excluded not in candidates

    await scan(now)
    for excluded in (default_too_far, explicit_too_far, all_day_next_week, already_past):
        assert await outbox_rows(excluded) == []


@pytest.mark.asyncio
async def test_a_long_lead_explicit_reminder_is_a_candidate_exactly_when_it_could_be_due(
    client: AsyncClient,
) -> None:
    """A 7-day reminder (the API maximum) makes an event a candidate a week ahead — but not
    earlier — whereas a 5-minute one is only a candidate minutes ahead."""
    home = await make_home(client)
    start = a_start()
    week_ahead = await insert_event(home, start_at=start, reminder_minutes=10080)

    assert week_ahead in await candidate_ids(start - timedelta(days=7) - HALF_MINUTE)
    assert week_ahead not in await candidate_ids(start - timedelta(days=8))
    await scan(start - timedelta(days=7) - HALF_MINUTE)
    assert len(await outbox_rows(week_ahead)) == 1


@pytest.mark.asyncio
async def test_candidate_query_never_misses_an_event_that_is_due(client: AsyncClient) -> None:
    """Independent of the scan: work out, in plain Python, every instant at which each kind of
    reminder is due and require the event to be a candidate at that instant."""
    home = await make_home(client)
    base = a_start()
    events: list[
        tuple[uuid.UUID, datetime]
    ] = []  # (event id, an instant one of its reminders is due)
    for minutes in (0, 1, 15, 60, 1440, 4000, 10080):
        start = base + timedelta(hours=minutes % 7, minutes=minutes % 53)
        event_id = await insert_event(home, start_at=start, reminder_minutes=minutes)
        events.append((event_id, start - timedelta(minutes=minutes)))
        all_day = await insert_event(
            home, start_at=all_day_start(minutes % 6), is_all_day=True, reminder_minutes=minutes
        )
        events.append((all_day, all_day_start(minutes % 6) - timedelta(minutes=minutes)))
    for lead in (15, 30, 45, 120):
        start = base + timedelta(minutes=lead * 3)
        event_id = await insert_event(home, start_at=start)
        events.append((event_id, start - timedelta(minutes=lead)))
    for offset_days in range(0, 6):
        start = all_day_start(offset_days)
        event_id = await insert_event(home, start_at=start, is_all_day=True)
        events.append((event_id, start.replace(hour=9)))
        events.append((event_id, start + timedelta(hours=23, minutes=59)))
        events.append((event_id, start - timedelta(hours=14)))

    for event_id, due in events:
        assert event_id in await candidate_ids(due - HALF_MINUTE), (event_id, due)


def test_all_day_due_spread_covers_every_time_zone() -> None:
    """The all-day candidate window is expressed in UTC, so it must reach every user's local
    reminder time on the stored date whatever their zone (UTC-12 … UTC+14)."""
    midnight_utc = datetime(2026, 7, 1, tzinfo=UTC)
    midnight_winter = datetime(2026, 1, 1, tzinfo=UTC)
    worst = timedelta(0)
    for stored in (midnight_utc, midnight_winter):
        for name in available_timezones():
            for reminder_time in (time(0, 0), time(23, 59, 59)):
                due = datetime.combine(
                    stored.date(), reminder_time, tzinfo=ZoneInfo(name)
                ).astimezone(UTC)
                worst = max(worst, abs(due - stored))
    assert worst < ALL_DAY_DUE_SPREAD


def _upper_limits(model: type, field_name: str) -> list[int]:
    return [m.le for m in model.model_fields[field_name].metadata if hasattr(m, "le")]  # type: ignore[attr-defined]


def test_default_reminder_bound_matches_the_api_limit() -> None:
    limits = _upper_limits(NotificationPreferencesUpdate, "default_event_reminder_minutes")
    assert limits == [MAX_DEFAULT_REMINDER_MINUTES]


def test_event_reminder_bound_matches_the_api_limit() -> None:
    assert _upper_limits(EventCreate, "reminder_minutes") == [MAX_EVENT_REMINDER_MINUTES]
    assert _upper_limits(EventUpdate, "reminder_minutes") == [MAX_EVENT_REMINDER_MINUTES]


@pytest.mark.asyncio
async def test_events_of_a_disabled_home_are_neither_candidates_nor_reminded(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    start = a_start()
    explicit_id = await insert_event(home, start_at=start, reminder_minutes=10)
    default_id = await insert_event(home, start_at=start)
    now = start - timedelta(minutes=10) - HALF_MINUTE
    assert {explicit_id, default_id} <= await candidate_ids(now)

    async with SessionFactory() as db:
        group = await db.get(Group, home.id)
        assert group is not None
        group.is_active = False
        await db.commit()

    assert not {explicit_id, default_id} & await candidate_ids(now)
    await scan(now)
    assert await outbox_rows(explicit_id) == [] and await outbox_rows(default_id) == []


# --- the defaults the preferences ship with -----------------------------------------------

LEGACY_PREFERENCES_BODY = {
    # What a client that predates the Calendar reminder settings sends: none of the new fields.
    "push_enabled": True,
    "in_app_enabled": True,
    "email_enabled": False,
    "event_reminders_enabled": True,
    "event_invitations_enabled": True,
    "event_changes_enabled": True,
    "household_reminders_enabled": True,
    "daily_briefing_enabled": False,
    "briefing_time": "07:30",
    "briefing_days": "daily",
    "empty_day_briefing_enabled": False,
    "daily_nudge_summary_enabled": True,
    "daily_nudge_summary_time": "07:30",
    "nudges_evening_cleanup_enabled": True,
    "nudges_evening_time": "20:30",
    "nudges_day_complete_enabled": True,
    "lock_screen_preview_level": "title_only",
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
    "quiet_hours_critical_only": False,
}


@pytest.mark.asyncio
async def test_migrated_database_defaults_leave_the_reminder_toggles_off() -> None:
    """ADD COLUMN backfills every existing notification_preferences row with the column's
    server default, so the server default *is* what existing users get on deploy. Read it
    from the migrated database: the two toggles must be false, and a change to the
    explicit-reminder category switch must not have sneaked in alongside them."""
    async with SessionFactory() as db:
        rows = await db.execute(
            text(
                "SELECT column_name, column_default FROM information_schema.columns "
                "WHERE table_name = 'notification_preferences' AND column_name IN "
                "('default_event_reminder_enabled', 'default_event_reminder_minutes', "
                "'all_day_reminder_enabled', 'all_day_reminder_time', 'event_reminders_enabled')"
            )
        )
        defaults = {name: default for name, default in rows.all()}
    assert defaults["default_event_reminder_enabled"] == "false"
    assert defaults["all_day_reminder_enabled"] == "false"
    assert defaults["default_event_reminder_minutes"] == "30"
    assert defaults["all_day_reminder_time"].startswith("'09:00:00'")
    assert defaults["event_reminders_enabled"] == "true"  # explicit reminders: unchanged


@pytest.mark.asyncio
async def test_new_preferences_start_with_default_reminders_off_at_30_minutes(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(client, unique_email("fresh"), "Fresh User")

    response = await client.get("/api/v1/notifications/preferences")
    assert response.status_code == 200
    body = response.json()
    assert body["default_event_reminder_enabled"] is False
    assert body["all_day_reminder_enabled"] is False
    assert body["default_event_reminder_minutes"] == 30  # the interval offered when switched on
    assert body["all_day_reminder_time"] == "09:00"
    assert body["event_reminders_enabled"] is True  # the explicit-reminder switch stays on

    async with SessionFactory() as db:
        stored = await db.scalar(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
        )
        assert stored is not None
        assert stored.default_event_reminder_enabled is False
        assert stored.all_day_reminder_enabled is False


@pytest.mark.asyncio
async def test_enabling_the_default_reminder_persists_the_chosen_interval(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(client, unique_email("optin"), "Opt In User")
    await client.get("/api/v1/notifications/preferences")  # creates the row, off

    response = await unsafe(
        client,
        "PUT",
        "/api/v1/notifications/preferences",
        json={
            **LEGACY_PREFERENCES_BODY,
            "default_event_reminder_enabled": True,
            "default_event_reminder_minutes": 45,
            "all_day_reminder_enabled": True,
            "all_day_reminder_time": "10:00",
        },
    )
    assert response.status_code == 200, response.text

    reread = (await client.get("/api/v1/notifications/preferences")).json()
    assert reread["default_event_reminder_enabled"] is True
    assert reread["default_event_reminder_minutes"] == 45
    assert reread["all_day_reminder_enabled"] is True
    assert reread["all_day_reminder_time"] == "10:00"
    async with SessionFactory() as db:
        stored = await db.scalar(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
        )
        assert stored is not None
        assert stored.default_event_reminder_minutes == 45
        assert stored.default_event_reminder_enabled is True


@pytest.mark.asyncio
async def test_a_client_that_omits_the_reminder_fields_does_not_switch_reminders_on(
    client: AsyncClient,
) -> None:
    """The PUT body is a full replacement, so what an omitted field means matters: it must
    mean "off", never "on" — an older client saving an unrelated setting cannot opt anyone in."""
    await create_verified_user(client, unique_email("legacy"), "Legacy Client User")

    response = await unsafe(
        client, "PUT", "/api/v1/notifications/preferences", json=LEGACY_PREFERENCES_BODY
    )

    assert response.status_code == 200, response.text
    assert response.json()["default_event_reminder_enabled"] is False
    assert response.json()["all_day_reminder_enabled"] is False
    assert (await client.get("/api/v1/notifications/preferences")).json()[
        "default_event_reminder_enabled"
    ] is False


@pytest.mark.asyncio
async def test_a_user_on_the_defaults_still_gets_explicit_reminders_but_no_default_ones(
    client: AsyncClient,
) -> None:
    home = await make_home(client, opted_in=False)
    start = a_start()
    explicit_id = await insert_event(home, start_at=start, reminder_minutes=10)
    timed_id = await insert_event(home, start_at=start)
    all_day = all_day_start()
    all_day_id = await insert_event(home, start_at=all_day, is_all_day=True)

    # An event's own reminder is not governed by the default toggle at all.
    await scan(start - timedelta(minutes=10) - HALF_MINUTE)
    assert len(await outbox_rows(explicit_id)) == 1
    await deliver_all(explicit_id)
    for user_id in (home.owner_id, home.member_id):
        assert len(await reminders_received(user_id, explicit_id)) == 1

    # ...while the opt-in defaults do nothing until someone opts in.
    await scan(start - timedelta(minutes=30) - HALF_MINUTE)
    await scan(all_day.replace(hour=9) - HALF_MINUTE)
    assert await outbox_rows(timed_id) == []
    assert await outbox_rows(all_day_id) == []

    await set_preferences(
        home.owner_id, default_event_reminder_enabled=True, all_day_reminder_enabled=True
    )
    await scan(start - timedelta(minutes=30) - HALF_MINUTE)
    await scan(all_day.replace(hour=9) - HALF_MINUTE)
    assert [payload_of(r)["recipient_user_id"] for r in await outbox_rows(timed_id)] == [
        str(home.owner_id)
    ]
    assert [payload_of(r)["recipient_user_id"] for r in await outbox_rows(all_day_id)] == [
        str(home.owner_id)
    ]


# --- recurring events ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recurring_event_without_an_explicit_reminder_uses_the_default(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    series_start = a_start() - timedelta(days=40)  # a daily 15:00Z series that began long ago
    event_id = await insert_event(
        home,
        start_at=series_start,
        recurrence=RecurrencePattern.daily,
        timezone="UTC",  # no DST shift between the series start and the occurrence under test
        attendees=(home.owner_id,),
    )
    occurrence = a_start()  # three days from now, 15:00Z

    now = occurrence - timedelta(minutes=30) - HALF_MINUTE
    assert event_id in await candidate_ids(now)
    await scan(now)

    rows = await outbox_rows(event_id)
    assert len(rows) == 1
    assert payload_of(rows[0])["occurrence_start"] == occurrence.isoformat()
    assert payload_of(rows[0])["recipient_user_id"] == str(home.owner_id)


@pytest.mark.asyncio
async def test_default_recurring_series_are_left_out_of_a_throttled_sweep(
    client: AsyncClient,
) -> None:
    home = await make_home(client)
    now = a_start()
    default_series = await insert_event(
        home, start_at=now - timedelta(days=40), recurrence=RecurrencePattern.daily
    )
    explicit_series = await insert_event(
        home,
        start_at=now - timedelta(days=40),
        recurrence=RecurrencePattern.daily,
        reminder_minutes=30,
    )

    full = await candidate_ids(now, include_default_recurring=True)
    light = await candidate_ids(now, include_default_recurring=False)
    assert default_series in full and explicit_series in full
    assert default_series not in light, "default-reminder series wait for the next sweep"
    assert explicit_series in light, "explicit-reminder series are scanned on every call"


@pytest.mark.asyncio
async def test_ended_recurring_series_are_not_candidates(client: AsyncClient) -> None:
    home = await make_home(client)
    now = a_start()
    started = now - timedelta(days=60)
    until_last_month = await insert_event(
        home,
        start_at=started,
        recurrence=RecurrencePattern.daily,
        recurrence_until=now - timedelta(days=30),
    )
    end_date_last_month = await insert_event(
        home,
        start_at=started,
        recurrence=RecurrencePattern.weekly,
        recurrence_end_date=(now - timedelta(days=30)).date(),
        reminder_minutes=15,
    )
    not_started_yet = await insert_event(
        home, start_at=now + timedelta(days=30), recurrence=RecurrencePattern.daily
    )
    running = await insert_event(home, start_at=started, recurrence=RecurrencePattern.daily)

    candidates = await candidate_ids(now)
    assert running in candidates
    for excluded in (until_last_month, end_date_last_month, not_started_yet):
        assert excluded not in candidates


# --- throttling ---------------------------------------------------------------------------


def test_default_recurring_sweep_is_throttled_but_never_starved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(reminders, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(reminders, "_last_default_recurring_sweep", None)
    interval = DEFAULT_RECURRING_SWEEP_INTERVAL.total_seconds()

    assert reminders._default_recurring_sweep_due() is True  # the first scan always sweeps
    clock["now"] += 2
    assert reminders._default_recurring_sweep_due() is False
    clock["now"] += interval - 3
    assert reminders._default_recurring_sweep_due() is False
    clock["now"] += 2  # now just over one interval since the sweep
    assert reminders._default_recurring_sweep_due() is True
    # The interval must stay well inside the look-ahead window, or a due reminder could fall
    # between two sweeps and be missed.
    assert DEFAULT_RECURRING_SWEEP_INTERVAL < LOOKAHEAD / 2


@pytest.mark.asyncio
async def test_a_production_scan_throttles_and_an_explicit_now_does_not(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    original = reminders.due_reminder_candidates

    async def spy(db, now, *, include_default_recurring=True):
        seen.append(include_default_recurring)
        return await original(db, now, include_default_recurring=include_default_recurring)

    monkeypatch.setattr(reminders, "due_reminder_candidates", spy)
    monkeypatch.setattr(reminders, "_last_default_recurring_sweep", None)
    async with SessionFactory() as db:
        await scan_due_reminders(db, get_settings())  # production call: first sweep, full
        await scan_due_reminders(db, get_settings())  # immediately after: throttled
        await scan_due_reminders(db, get_settings(), now=datetime.now(UTC))  # explicit: full
    assert seen == [True, False, True]
