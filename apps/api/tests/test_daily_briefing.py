"""Tests for the daily morning briefing (Stage 5): the durable due-briefing scan,
once-only delivery, weekdays-only scheduling, empty-day suppression, natural-sentence
composition, and visibility-safe content across homes. No fake clock exists, so
scan tests set `briefing_time` to the current real local time.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    BriefingDays,
    FeatureKey,
    FeatureOverride,
    Notification,
    NotificationPreferences,
    OutboxEvent,
    TokenPurpose,
    User,
)
from mykhaya.notifications.briefing import (
    BriefingOccurrence,
    deliver_daily_briefing,
    empty_day_message,
    format_daily_briefing,
    oxford_join,
    scan_due_briefings,
)
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"
TZ = ZoneInfo("Europe/London")
TEST_BRIEFING_USER_IDS: set[str] = set()


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
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Briefing Test Home"})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.calendar, group_id=home_id, enabled=True))
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=True)
        )
        await db.commit()
    return home_id


async def enable_briefing(
    user_id: uuid.UUID,
    *,
    briefing_time: time | None = None,
    briefing_days: BriefingDays = BriefingDays.daily,
    empty_day_briefing_enabled: bool = True,
    timezone: str | None = "Europe/London",
) -> None:
    now_local = datetime.now(UTC).astimezone(TZ)
    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.timezone = timezone
        # A preferences row may already exist — e.g. registration's verification email
        # now goes through notify(), which lazily creates one — so update in place
        # rather than assuming this is the first row for this user.
        prefs = await db.scalar(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
        )
        if prefs is None:
            prefs = NotificationPreferences(user_id=user_id)
            db.add(prefs)
        prefs.daily_briefing_enabled = True
        prefs.briefing_time = briefing_time or now_local.time().replace(microsecond=0)
        prefs.briefing_days = briefing_days
        prefs.empty_day_briefing_enabled = empty_day_briefing_enabled
        await db.commit()


@pytest.fixture(autouse=True)
async def clean_briefing_outbox() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        for user_id in TEST_BRIEFING_USER_IDS:
            await db.execute(
                delete(OutboxEvent).where(
                    OutboxEvent.dedupe_key.like(f"daily-briefing:{user_id}:%")
                )
            )
        await db.commit()
    TEST_BRIEFING_USER_IDS.clear()


async def briefing_rows_for_user(db: AsyncSession, user_id: str) -> list[OutboxEvent]:
    TEST_BRIEFING_USER_IDS.add(user_id)
    rows = (
        await db.scalars(
            select(OutboxEvent).where(OutboxEvent.dedupe_key.like(f"daily-briefing:{user_id}:%"))
        )
    ).all()
    return list(rows)


def test_oxford_join_composes_natural_sentences() -> None:
    assert oxford_join([]) == ""
    assert oxford_join(["Swimming at 09:30"]) == "Swimming at 09:30"
    assert (
        oxford_join(["Swimming at 09:30", "Dentist at 14:00"])
        == "Swimming at 09:30 and Dentist at 14:00"
    )
    assert (
        oxford_join(["Swimming at 09:30", "Dentist at 14:00", "Bins out"])
        == "Swimming at 09:30, Dentist at 14:00, and Bins out"
    )


def test_empty_day_message_is_stable_within_a_day_but_varies_across_days() -> None:
    day_one = date(2026, 1, 1)
    day_two = date(2026, 1, 2)
    assert empty_day_message(day_one) == empty_day_message(day_one)
    assert empty_day_message(day_one) != empty_day_message(day_two) or day_one == day_two


def briefing_occurrence(
    title: str,
    start: str,
    *,
    all_day: bool = False,
    event_id: str | None = None,
) -> BriefingOccurrence:
    return BriefingOccurrence(
        event_id=uuid.UUID(event_id or uuid.uuid4().hex),
        title=title,
        start_at=datetime.fromisoformat(start),
        is_all_day=all_day,
    )


def test_format_daily_briefing_uses_bullets_and_singular_title() -> None:
    title, body = format_daily_briefing(
        [briefing_occurrence("Contact Lens Check", "2026-08-17T08:50:00+01:00")],
        local_date=date(2026, 8, 17),
        tz=TZ,
    )
    assert title == "You have 1 event today."
    assert body == "Please take care of yourself!\n• 08:50 Contact Lens Check"


def test_format_daily_briefing_sorts_events_in_recipient_timezone() -> None:
    title, body = format_daily_briefing(
        [
            briefing_occurrence("Later", "2026-08-17T17:30:00+01:00"),
            briefing_occurrence("Earlier", "2026-08-17T09:50:00+01:00"),
            briefing_occurrence("Middle", "2026-08-17T11:20:00+01:00"),
        ],
        local_date=date(2026, 8, 17),
        tz=TZ,
    )
    assert title == "You have 3 events today."
    assert body == (
        "Please take care of yourself!\n"
        "• 09:50 Earlier\n"
        "• 11:20 Middle\n"
        "• 17:30 Later"
    )


def test_format_daily_briefing_formats_all_day_and_local_timezone() -> None:
    title, body = format_daily_briefing(
        [
            briefing_occurrence("All-day thing", "2026-08-17T00:00:00+00:00", all_day=True),
            briefing_occurrence("Local appointment", "2026-08-17T08:50:00+00:00"),
        ],
        local_date=date(2026, 8, 17),
        tz=TZ,
    )
    assert title == "You have 2 events today."
    assert body == (
        "Please take care of yourself!\n"
        "• All day – All-day thing\n"
        "• 09:50 Local appointment"
    )


def test_format_daily_briefing_limits_visible_events_and_reports_remainder() -> None:
    occurrences = [
        briefing_occurrence(
            f"Event {index}",
            f"2026-08-17T{index + 8:02d}:00:00+00:00",
            event_id=f"00000000-0000-0000-0000-{index + 1:012d}",
        )
        for index in range(6)
    ]
    title, body = format_daily_briefing(occurrences, local_date=date(2026, 8, 17), tz=UTC)
    assert title == "You have 6 events today."
    assert body.count("\n• ") == 6
    assert body.endswith("• +1 more events")


def test_format_daily_briefing_sanitises_control_characters_and_zero_events() -> None:
    title, body = format_daily_briefing(
        [briefing_occurrence("Bad\nTitle\r\t\x00", "2026-08-17T09:00:00+00:00")],
        local_date=date(2026, 8, 17),
        tz=UTC,
    )
    assert title == "You have 1 event today."
    assert body == "Please take care of yourself!\n• 09:00 Bad Title"

    empty_title, empty_body = format_daily_briefing(
        [], local_date=date(2026, 8, 17), tz=UTC, birthday_phrases=[]
    )
    assert empty_title == "You have 0 events today."
    assert "\n• " not in empty_body


@pytest.mark.asyncio
async def test_scan_enqueues_a_due_briefing_and_is_idempotent(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("briefscan"), "Briefing Owner")
    await enable_briefing(user_id)

    async with SessionFactory() as db:
        await scan_due_briefings(db, get_settings())
        rows = await briefing_rows_for_user(db, str(user_id))
        assert len(rows) == 1

        # A second scan pass before delivery must not enqueue a duplicate.
        await scan_due_briefings(db, get_settings())
        rows_after = await briefing_rows_for_user(db, str(user_id))
        assert len(rows_after) == 1


@pytest.mark.asyncio
async def test_processed_occurrence_is_not_recreated_on_later_scan(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("briefprocessed"), "Processed Owner")
    await enable_briefing(user_id)

    async with SessionFactory() as db:
        await scan_due_briefings(db, get_settings())
        row = (await briefing_rows_for_user(db, str(user_id)))[0]
        row.processed_at = datetime.now(UTC)
        await db.commit()
        await scan_due_briefings(db, get_settings())
        assert len(await briefing_rows_for_user(db, str(user_id))) == 1


@pytest.mark.asyncio
async def test_concurrent_scans_share_one_durable_occurrence(client: AsyncClient) -> None:
    user_id = await create_verified_user(
        client, unique_email("briefconcurrent"), "Concurrent Owner"
    )
    await enable_briefing(user_id)

    async def scan_once() -> None:
        async with SessionFactory() as db:
            await scan_due_briefings(db, get_settings())

    await asyncio.gather(scan_once(), scan_once())
    async with SessionFactory() as db:
        assert len(await briefing_rows_for_user(db, str(user_id))) == 1


@pytest.mark.asyncio
async def test_scan_skips_when_briefing_time_not_yet_reached(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("notyet"), "Not Yet Owner")
    # Keep the future time on the same local date; a time-only preference cannot
    # represent tomorrow, and adding six hours can wrap past midnight.
    far_future_time = (datetime.now(UTC).astimezone(TZ) + timedelta(minutes=30)).time()
    await enable_briefing(user_id, briefing_time=far_future_time)

    async with SessionFactory() as db:
        await scan_due_briefings(db, get_settings())
        rows = await briefing_rows_for_user(db, str(user_id))
        assert rows == []


@pytest.mark.asyncio
async def test_scan_respects_weekdays_only_preference(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("weekday"), "Weekday Owner")
    now_local = datetime.now(UTC).astimezone(TZ)
    await enable_briefing(user_id, briefing_days=BriefingDays.weekdays)

    async with SessionFactory() as db:
        await scan_due_briefings(db, get_settings())
        rows = await briefing_rows_for_user(db, str(user_id))
        if now_local.weekday() > 4:
            assert rows == []
        else:
            assert len(rows) == 1


@pytest.mark.asyncio
async def test_deliver_composes_events_into_bullets_and_is_visibility_safe(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(client, unique_email("content"), "Content Owner")
    home_id = await create_home_with_calendar(client)
    await enable_briefing(user_id)

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

    async with SessionFactory() as db:
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None
        assert notification.title == "You have 1 event today."
        assert notification.body == "Please take care of yourself!\n• 09:30 Swimming"
        assert notification.deep_link == {"type": "calendar_today"}


@pytest.mark.asyncio
async def test_deliver_skips_other_homes_events_not_visible_to_user(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("outsider"), "Outsider")
    await enable_briefing(user_id)

    other_client_home_id: uuid.UUID
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await create_verified_user(other_client, unique_email("otherowner"), "Other Owner")
        other_client_home_id = await create_home_with_calendar(other_client)
        today_local = datetime.now(UTC).astimezone(TZ).date()
        event_start = datetime.combine(today_local, datetime.min.time(), tzinfo=TZ) + timedelta(
            hours=9
        )
        created = await unsafe(
            other_client,
            "POST",
            f"/api/v1/homes/{other_client_home_id}/events",
            json={
                "title": "Not visible to outsider",
                "start_at": event_start.isoformat(),
                "end_at": (event_start + timedelta(hours=1)).isoformat(),
                "timezone": "Europe/London",
            },
        )
        assert created.status_code == 201

    today_local = datetime.now(UTC).astimezone(TZ).date()
    async with SessionFactory() as db:
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        # Empty-day briefing is enabled by default, so a notification is still sent —
        # but it must not mention the other home's event.
        assert notification is not None
        assert "Not visible to outsider" not in notification.body


@pytest.mark.asyncio
async def test_deliver_suppresses_send_when_empty_day_briefing_disabled(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(client, unique_email("nosend"), "No Send Owner")
    await enable_briefing(user_id, empty_day_briefing_enabled=False)

    today_local = datetime.now(UTC).astimezone(TZ).date()
    async with SessionFactory() as db:
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is None


@pytest.mark.asyncio
async def test_deliver_sends_empty_day_message_when_no_events(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("empty"), "Empty Day Owner")
    await enable_briefing(user_id)

    today_local = datetime.now(UTC).astimezone(TZ).date()
    async with SessionFactory() as db:
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is not None
        assert notification.body == (
            f"Please take care of yourself!\n{empty_day_message(today_local)}"
        )


@pytest.mark.asyncio
async def test_deliver_is_idempotent_per_user_per_day(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("idembrief"), "Idem Owner")
    await enable_briefing(user_id)

    today_local = datetime.now(UTC).astimezone(TZ).date()
    async with SessionFactory() as db:
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await db.commit()
        notifications = (
            await db.scalars(select(Notification).where(Notification.recipient_user_id == user_id))
        ).all()
        assert len(notifications) == 1


@pytest.mark.asyncio
async def test_deliver_skips_when_disabled_since_scan(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("disabled"), "Disabled Owner")
    await enable_briefing(user_id)

    async with SessionFactory() as db:
        prefs = await db.scalar(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
        )
        assert prefs is not None
        prefs.daily_briefing_enabled = False
        await db.commit()

    today_local = datetime.now(UTC).astimezone(TZ).date()
    async with SessionFactory() as db:
        await deliver_daily_briefing(db, get_settings(), str(user_id), today_local.isoformat())
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == user_id)
        )
        assert notification is None
