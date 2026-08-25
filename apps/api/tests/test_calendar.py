import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mykhaya.calendar_occurrences import expand_occurrences, next_occurrence_on_or_after
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
    Invitation,
    Membership,
    PermissionProfile,
    RecurrencePattern,
    Role,
    SubscriptionPlan,
    TokenPurpose,
    User,
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


async def create_verified_user(client: AsyncClient, email: str, name: str) -> None:
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
        client,
        "POST",
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_calendar_crud_and_conflict(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"owner-{suffix}@example.com", "Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Pilot Home"})
    assert group.status_code == 201
    home_id = group.json()["id"]

    disabled = await client.get(f"/api/v1/homes/{home_id}/event-labels")
    assert disabled.status_code == 404
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.calendar,
                group_id=uuid.UUID(home_id),
                enabled=True,
            )
        )
        await db.commit()
    evaluation = await client.get(f"/api/v1/features/{home_id}/calendar")
    assert evaluation.status_code == 200
    assert evaluation.json() == {"feature": "calendar", "enabled": True}

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "School run",
            "start_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(hours=3)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "weekly",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201
    event = created.json()

    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={
            "start_at": datetime.now(UTC).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
    )
    assert listed.status_code == 200
    assert listed.json()["items"]

    conflict = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json={
            "title": "School run updated",
            "start_at": event["start_at"],
            "end_at": event["end_at"],
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "weekly",
            "recurrence_interval": 1,
            "expected_updated_at": "2000-01-01T00:00:00+00:00",
        },
    )
    assert conflict.status_code == 409

    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/events/{event['event_id']}")
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_cross_home_event_access_denied(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"owner2-{suffix}@example.com", "Owner Two")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Private Home"})
    assert group.status_code == 201
    home_id = group.json()["id"]

    async with SessionFactory() as db:
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.calendar,
                group_id=uuid.UUID(home_id),
                enabled=True,
            )
        )
        await db.commit()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Private Event",
            "start_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "none",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as outsider:
        await create_verified_user(outsider, f"outsider-{suffix}@example.com", "Outsider")
        denied = await outsider.get(
            f"/api/v1/homes/{home_id}/events",
            params={
                "start_at": datetime.now(UTC).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            },
        )
        assert denied.status_code == 404


@pytest.mark.asyncio
async def test_invitation_only_registration_mode_requires_valid_invitation(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    owner_email = f"owner3-{suffix}@example.com"
    invitee_email = f"invitee3-{suffix}@example.com"

    await create_verified_user(client, owner_email, "Owner Three")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Invitation Home"})
    assert group.status_code == 201
    home_id = group.json()["id"]
    # home.max_members restricts Free to a single person — this test is
    # about registration-mode validation, not commercial gating, so upgrade
    # to Family to be able to invite at all.
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()

    invitation = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": home_id, "email": invitee_email, "role": "adult_member"},
    )
    assert invitation.status_code == 201

    async with SessionFactory() as db:
        row = await db.scalar(
            select(Invitation).where(
                Invitation.group_id == uuid.UUID(home_id),
                Invitation.email == invitee_email,
            )
        )
        assert row is not None
        token = derived_token(row.id, "invitation", get_settings().secret_key.get_secret_value())

    invitation_only = get_settings().model_copy(update={"registration_mode": "invitation_only"})
    app.dependency_overrides[get_settings] = lambda: invitation_only
    try:
        rejected = await unsafe(
            client,
            "POST",
            "/api/v1/auth/register",
            json={
                "email": f"other-{suffix}@example.com",
                "display_name": "Other",
                "password": PASSWORD,
            },
        )
        assert rejected.status_code == 403

        accepted = await unsafe(
            client,
            "POST",
            "/api/v1/auth/register",
            json={
                "email": invitee_email,
                "display_name": "Invited",
                "password": PASSWORD,
                "invitation_token": token,
            },
        )
        assert accepted.status_code == 202
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_weekly_recurrence_survives_dst_transition(client: AsyncClient) -> None:
    """A weekly 09:00 Europe/London event must still show 09:00 local time
    after the clocks change, not 08:00 or 10:00. UK clocks moved forward on
    2026-03-29. Regression test for the UTC-timedelta recurrence bug fixed
    in _expand_occurrences — see docs/design/visual-identity.md context and
    the fix itself in routers/calendar.py."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"dst-{suffix}@example.com", "DST Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "DST Home"})
    assert group.status_code == 201
    home_id = group.json()["id"]

    async with SessionFactory() as db:
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.calendar,
                group_id=uuid.UUID(home_id),
                enabled=True,
            )
        )
        await db.commit()

    # First occurrence: Tuesday 2026-03-24 09:00 Europe/London, still GMT
    # (UTC+0) — before the 2026-03-29 spring-forward.
    tz = ZoneInfo("Europe/London")
    first_local = datetime(2026, 3, 24, 9, 0, tzinfo=tz)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Weekly team call",
            "start_at": first_local.astimezone(UTC).isoformat(),
            "end_at": (first_local + timedelta(hours=1)).astimezone(UTC).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "weekly",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201

    # Query a range spanning three weeks after the spring-forward, so the
    # occurrence on 2026-04-14 falls after clocks moved to BST (UTC+1).
    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={
            "start_at": datetime(2026, 4, 13, tzinfo=UTC).isoformat(),
            "end_at": datetime(2026, 4, 16, tzinfo=UTC).isoformat(),
        },
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items, "expected an occurrence in the post-DST week"
    occurrence_start = datetime.fromisoformat(items[0]["start_at"])
    local_start = occurrence_start.astimezone(tz)
    assert local_start.hour == 9, (
        f"expected 09:00 local time after DST, got {local_start.isoformat()} "
        "— weekly recurrence is drifting across the clock change"
    )


def test_recurrence_end_date_is_inclusive() -> None:
    event = CalendarEvent(
        start_at=datetime(2026, 8, 21, 9, tzinfo=UTC),
        end_at=datetime(2026, 8, 21, 10, tzinfo=UTC),
        timezone="UTC",
        recurrence=RecurrencePattern.weekly,
        recurrence_interval=1,
        recurrence_end_date=date(2026, 9, 18),
    )
    occurrences = expand_occurrences(
        event,
        datetime(2026, 8, 20, tzinfo=UTC),
        datetime(2026, 9, 26, tzinfo=UTC),
    )
    assert [start.date() for start, _end in occurrences] == [
        date(2026, 8, 21),
        date(2026, 8, 28),
        date(2026, 9, 4),
        date(2026, 9, 11),
        date(2026, 9, 18),
    ]


def test_next_occurrence_on_or_after_one_off_event_in_the_past_has_none() -> None:
    event = CalendarEvent(
        start_at=datetime(2026, 1, 1, 9, tzinfo=UTC),
        end_at=datetime(2026, 1, 1, 10, tzinfo=UTC),
        timezone="UTC",
        recurrence=RecurrencePattern.none,
        recurrence_interval=1,
    )
    assert next_occurrence_on_or_after(event, datetime(2026, 6, 1, tzinfo=UTC)) is None


def test_next_occurrence_on_or_after_finds_a_weekly_occurrence_months_out() -> None:
    """No arbitrary future horizon: a weekly series' next occurrence, found by
    stepping in memory rather than expanding a bounded date range, must
    resolve correctly even many months past MAX_RANGE_DAYS (93 days)."""
    event = CalendarEvent(
        start_at=datetime(2026, 1, 6, 9, tzinfo=UTC),  # a Tuesday
        end_at=datetime(2026, 1, 6, 10, tzinfo=UTC),
        timezone="UTC",
        recurrence=RecurrencePattern.weekly,
        recurrence_interval=1,
    )
    cursor = datetime(2026, 9, 1, tzinfo=UTC)  # ~8 months after start_at
    result = next_occurrence_on_or_after(event, cursor)
    assert result is not None
    start, end = result
    assert start >= cursor
    assert start.weekday() == 1  # still a Tuesday
    assert (start - datetime(2026, 1, 6, 9, tzinfo=UTC)).days % 7 == 0
    assert end - start == timedelta(hours=1)


def test_next_occurrence_on_or_after_respects_recurrence_until() -> None:
    event = CalendarEvent(
        start_at=datetime(2026, 1, 1, 9, tzinfo=UTC),
        end_at=datetime(2026, 1, 1, 10, tzinfo=UTC),
        timezone="UTC",
        recurrence=RecurrencePattern.monthly,
        recurrence_interval=1,
        recurrence_until=datetime(2026, 3, 1, tzinfo=UTC),
    )
    # The series ends before ever reaching a cursor this far out.
    assert next_occurrence_on_or_after(event, datetime(2026, 6, 1, tzinfo=UTC)) is None
    # But a cursor within the series' lifetime finds the right occurrence.
    found = next_occurrence_on_or_after(event, datetime(2026, 2, 1, tzinfo=UTC))
    assert found is not None
    assert found[0].date() == date(2026, 2, 1)


def test_next_occurrence_on_or_after_respects_recurrence_count() -> None:
    event = CalendarEvent(
        start_at=datetime(2026, 1, 1, 9, tzinfo=UTC),
        end_at=datetime(2026, 1, 1, 10, tzinfo=UTC),
        timezone="UTC",
        recurrence=RecurrencePattern.daily,
        recurrence_interval=1,
        recurrence_count=3,
    )
    # Occurrences exist for Jan 1/2/3 only — a cursor past that has none.
    assert next_occurrence_on_or_after(event, datetime(2026, 1, 4, tzinfo=UTC)) is None
    found = next_occurrence_on_or_after(event, datetime(2026, 1, 2, 12, tzinfo=UTC))
    assert found is not None
    assert found[0].date() == date(2026, 1, 3)


def test_next_occurrence_on_or_after_parent_start_date_does_not_win_ordering() -> None:
    """Regression: the parent CalendarEvent row's own start_at (its very
    first occurrence, possibly long past) must never be mistaken for "the
    next occurrence" — callers that sort candidates by the returned
    occurrence's start must see the actual next one, not the series' origin
    date."""
    event = CalendarEvent(
        start_at=datetime(2020, 1, 1, 9, tzinfo=UTC),
        end_at=datetime(2020, 1, 1, 10, tzinfo=UTC),
        timezone="UTC",
        recurrence=RecurrencePattern.yearly,
        recurrence_interval=1,
    )
    cursor = datetime(2026, 6, 1, tzinfo=UTC)
    found = next_occurrence_on_or_after(event, cursor)
    assert found is not None
    assert found[0].date() == date(2027, 1, 1)
    assert found[0] > event.start_at


async def _enable_calendar(home_id: str) -> None:
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.calendar, group_id=uuid.UUID(home_id), enabled=True
            )
        )
        await db.commit()


async def _create_home(client: AsyncClient, name: str) -> str:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201, group.text
    home_id = group.json()["id"]
    await _enable_calendar(home_id)
    return home_id


async def _create_upcoming_event(
    client: AsyncClient,
    home_id: str,
    title: str,
    start: datetime,
    *,
    is_all_day: bool = False,
    recurrence: str = "none",
) -> None:
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": title,
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "is_all_day": is_all_day,
            "member_ids": [],
            "recurrence": recurrence,
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201, created.text


@pytest.mark.asyncio
async def test_upcoming_events_endpoint_shows_next_three_events_tomorrow(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"upcoming1-{suffix}@example.com", "Owner")
    home_id = await _create_home(client, "Upcoming Home One")
    now = datetime.now(UTC)
    await _create_upcoming_event(client, home_id, "Breakfast", now + timedelta(days=1, hours=1))
    await _create_upcoming_event(client, home_id, "Lunch", now + timedelta(days=1, hours=5))
    await _create_upcoming_event(client, home_id, "Dinner", now + timedelta(days=1, hours=9))

    response = await client.get(
        f"/api/v1/homes/{home_id}/events/upcoming",
        params={"after": (now - timedelta(hours=1)).isoformat(), "limit": 3},
    )
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert titles == ["Breakfast", "Lunch", "Dinner"]


@pytest.mark.asyncio
async def test_upcoming_events_endpoint_has_no_future_horizon_and_trims_to_limit(
    client: AsyncClient,
) -> None:
    """Unlike list_events (capped at MAX_RANGE_DAYS = 93 days), the upcoming
    endpoint must find an occurrence 8 months out with no fixed window, while
    still trimming a larger candidate set down to `limit`, earliest first."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"upcoming2-{suffix}@example.com", "Owner")
    home_id = await _create_home(client, "Upcoming Home Two")
    now = datetime.now(UTC)
    await _create_upcoming_event(client, home_id, "Yesterday", now - timedelta(days=1))
    await _create_upcoming_event(client, home_id, "Tomorrow", now + timedelta(days=1))
    await _create_upcoming_event(client, home_id, "Five days", now + timedelta(days=5))
    await _create_upcoming_event(client, home_id, "Fourteen days", now + timedelta(days=14))
    await _create_upcoming_event(client, home_id, "Eight months", now + timedelta(days=240))

    after = (now - timedelta(hours=1)).isoformat()
    limited = await client.get(
        f"/api/v1/homes/{home_id}/events/upcoming", params={"after": after, "limit": 3}
    )
    assert limited.status_code == 200
    assert [item["title"] for item in limited.json()["items"]] == [
        "Tomorrow",
        "Five days",
        "Fourteen days",
    ]

    unlimited = await client.get(
        f"/api/v1/homes/{home_id}/events/upcoming", params={"after": after, "limit": 10}
    )
    assert unlimited.status_code == 200
    assert [item["title"] for item in unlimited.json()["items"]] == [
        "Tomorrow",
        "Five days",
        "Fourteen days",
        "Eight months",
    ]
    # The Yesterday event never appears — the endpoint only ever returns
    # occurrences on/after `after`.
    assert "Yesterday" not in [item["title"] for item in unlimited.json()["items"]]


@pytest.mark.asyncio
async def test_upcoming_events_endpoint_single_and_zero_future_events(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"upcoming3-{suffix}@example.com", "Owner")
    home_id = await _create_home(client, "Upcoming Home Three")
    now = datetime.now(UTC)
    after = (now - timedelta(hours=1)).isoformat()

    # No future events at all yet.
    empty = await client.get(
        f"/api/v1/homes/{home_id}/events/upcoming", params={"after": after, "limit": 3}
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []

    await _create_upcoming_event(client, home_id, "Only one", now + timedelta(days=2))
    single = await client.get(
        f"/api/v1/homes/{home_id}/events/upcoming", params={"after": after, "limit": 3}
    )
    assert single.status_code == 200
    assert [item["title"] for item in single.json()["items"]] == ["Only one"]


@pytest.mark.asyncio
async def test_upcoming_events_endpoint_recurring_and_all_day_ordering(
    client: AsyncClient,
) -> None:
    """A recurring event's long-past parent start_at must never win ordering
    over its actual next occurrence (see the pure-function regression above),
    and an all-day event must still take part in the same ordering as timed
    events."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"upcoming4-{suffix}@example.com", "Owner")
    home_id = await _create_home(client, "Upcoming Home Four")
    now = datetime.now(UTC)

    # A weekly series that started long ago — its next real occurrence must
    # sort by that actual date, never by its 400-day-old parent start_at.
    old_start = (now - timedelta(days=400)).replace(hour=9, minute=0, second=0, microsecond=0)
    one_off_start = now + timedelta(days=3)
    all_day_start = (now + timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    await _create_upcoming_event(
        client, home_id, "Weekly standup", old_start, recurrence="weekly"
    )
    await _create_upcoming_event(client, home_id, "One-off soon", one_off_start)
    await _create_upcoming_event(
        client, home_id, "All-day trip", all_day_start, is_all_day=True
    )

    after = now - timedelta(hours=1)
    response = await client.get(
        f"/api/v1/homes/{home_id}/events/upcoming",
        params={"after": after.isoformat(), "limit": 3},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["title"] for item in items} == {"Weekly standup", "One-off soon", "All-day trip"}
    for item in items:
        assert datetime.fromisoformat(item["start_at"]) >= after

    # The response is sorted by each occurrence's actual (computed) start —
    # verify independently against the pure recurrence math rather than
    # hardcoding which title lands first, since that depends on exactly
    # where `now` falls in the weekly cycle.
    weekly_event = CalendarEvent(
        start_at=old_start,
        end_at=old_start + timedelta(hours=1),
        timezone="UTC",
        recurrence=RecurrencePattern.weekly,
        recurrence_interval=1,
    )
    weekly_next = next_occurrence_on_or_after(weekly_event, after)
    assert weekly_next is not None
    starts_by_title = {
        "Weekly standup": weekly_next[0],
        "One-off soon": one_off_start,
        "All-day trip": all_day_start,
    }
    expected_order = [
        title for title, _ in sorted(starts_by_title.items(), key=lambda pair: pair[1])
    ]
    assert [item["title"] for item in items] == expected_order


@pytest.mark.asyncio
async def test_event_recurrence_end_date_create_update_remove_and_validation(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"recur-end-{suffix}@example.com", "Recurrence Owner")
    home_id = await _home_with_calendar(client, "Recurrence End Home")
    start = datetime(2026, 8, 21, 9, tzinfo=UTC)
    end = datetime(2026, 8, 21, 10, tzinfo=UTC)
    body = {
        "title": "Weekly series",
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "timezone": "UTC",
        "recurrence": "weekly",
        "recurrence_interval": 1,
        "recurrence_end_date": "2026-09-18",
    }
    created = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/events", json=body)
    assert created.status_code == 201, created.text
    assert created.json()["recurrence_end_date"] == "2026-09-18"

    updated_body = {
        **body,
        "recurrence_end_date": "2026-09-25",
        "expected_updated_at": created.json()["updated_at"],
    }
    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{created.json()['event_id']}",
        json=updated_body,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["recurrence_end_date"] == "2026-09-25"

    cleared_body = {
        **updated_body,
        "recurrence": "none",
        "recurrence_end_date": None,
        "expected_updated_at": updated.json()["updated_at"],
    }
    cleared = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{created.json()['event_id']}",
        json=cleared_body,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["recurrence"] == "none"
    assert cleared.json()["recurrence_end_date"] is None

    invalid = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={**body, "recurrence_end_date": "2026-08-20"},
    )
    assert invalid.status_code == 422


async def _home_with_calendar(client: AsyncClient, name: str) -> str:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = group.json()["id"]
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.calendar, group_id=uuid.UUID(home_id), enabled=True
            )
        )
        # The label-management tests using this helper create a second
        # event-category label (calendar.max_categories) — Free seeds only
        # one active by default (see routers.groups' DEFAULT_LABELS
        # seeding), so this needs Family.
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    return home_id


@pytest.mark.asyncio
async def test_event_label_create_update_rename_recolour_and_duplicate_name(
    client: AsyncClient,
) -> None:
    """Calendar/category colour, not who created the event, is what an event
    shows — see docs/design/visual-identity.md. Labels are created and later
    renamed, recoloured and disabled through the same colour_token palette
    used for member colours."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"labeladmin-{suffix}@example.com", "Label Admin")
    home_id = await _home_with_calendar(client, "Label Home")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Sport", "color": "emerald"},
    )
    assert created.status_code == 201
    label = created.json()
    assert label["color"] == "emerald"
    assert label["is_active"] is True

    # An unrecognised colour token is rejected at the schema, not stored.
    invalid_colour = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Bad Colour", "color": "not-a-real-colour"},
    )
    assert invalid_colour.status_code == 422

    # Duplicate name within the same home is rejected, not silently accepted
    # as a second identical category.
    duplicate = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Sport", "color": "blue"},
    )
    assert duplicate.status_code == 409

    # Rename and recolour independently.
    renamed = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{label['id']}",
        json={"name": "Football"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Football"
    assert renamed.json()["color"] == "emerald"  # unchanged by a name-only update

    recoloured = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{label['id']}",
        json={"color": "sky"},
    )
    assert recoloured.status_code == 200
    assert recoloured.json()["color"] == "sky"
    assert recoloured.json()["name"] == "Football"  # unchanged by a colour-only update

    # Two different labels may share the same colour — not blocked.
    second = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Athletics", "color": "sky"},
    )
    assert second.status_code == 201

    # Disable, then confirm it drops out of the active listing.
    disabled = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{label['id']}",
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    listed = await client.get(f"/api/v1/homes/{home_id}/event-labels")
    assert label["id"] not in {row["id"] for row in listed.json()}


@pytest.mark.asyncio
async def test_event_label_update_requires_calendar_edit_all(client: AsyncClient) -> None:
    """A household member without calendar.edit_all (e.g. an explicit-sharing
    friend/extended-family profile) cannot rename or recolour a shared
    calendar/category — that's shared household structure, gated the same
    way label creation already is."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"labelowner-{suffix}@example.com", "Label Owner")
    home_id = await _home_with_calendar(client, "Label Perms Home")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Outing", "color": "coral"},
    )
    assert created.status_code == 201
    label_id = created.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as friend_client:
        friend_email = f"labelfriend-{suffix}@example.com"
        await create_verified_user(friend_client, friend_email, "Label Friend")
        async with SessionFactory() as db:
            user = await db.scalar(select(User).where(User.email == friend_email))
            assert user is not None
            db.add(
                Membership(
                    group_id=uuid.UUID(home_id),
                    user_id=user.id,
                    role=Role.guest,
                    relationship=HouseholdRelationship.friend,
                    permission_profile=PermissionProfile.explicit_sharing,
                )
            )
            await db.commit()

        blocked = await unsafe(
            friend_client,
            "PATCH",
            f"/api/v1/homes/{home_id}/event-labels/{label_id}",
            json={"color": "rose"},
        )
        assert blocked.status_code == 403

    unchanged = await client.get(f"/api/v1/homes/{home_id}/event-labels")
    assert next(row for row in unchanged.json() if row["id"] == label_id)["color"] == "coral"


@pytest.mark.asyncio
async def test_home_calendar_colour_can_be_changed_but_never_its_name(client: AsyncClient) -> None:
    """The synthetic `label_id: null` option is presented to users as "Home
    calendar" — a fixed product concept, never user-renamable, but its
    colour (the fallback uncategorised events render with) is. StrictModel's
    extra="forbid" on HomeCalendarUpdate means a client-supplied `name` is
    rejected outright (422), not merely ignored."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"homecolour-{suffix}@example.com", "Home Colour Owner")
    home_id = await _home_with_calendar(client, "Home Colour Home")

    calendars = await client.get(f"/api/v1/homes/{home_id}/calendars")
    assert calendars.status_code == 200
    primary = next(row for row in calendars.json()["items"] if row["is_primary"])
    assert primary["name"] == "Home Calendar"
    assert primary["color"] == "teal"

    recoloured = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/calendars/{primary['id']}",
        json={"color": "amber"},
    )
    assert recoloured.status_code == 200, recoloured.text
    assert recoloured.json()["color"] == "amber"
    assert recoloured.json()["name"] == "Home Calendar"  # unchanged

    # A client-supplied `name` is rejected structurally, not just ignored.
    rename_attempt = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/calendars/{primary['id']}",
        json={"name": "Renamed Calendar", "color": "sky"},
    )
    assert rename_attempt.status_code == 422

    unchanged = await client.get(f"/api/v1/homes/{home_id}/calendars")
    persisted = next(row for row in unchanged.json()["items"] if row["is_primary"])
    assert persisted["name"] == "Home Calendar"
    assert persisted["color"] == "amber"  # the earlier colour-only update still stands


@pytest.mark.asyncio
async def test_home_calendar_colour_update_requires_calendar_edit_all(client: AsyncClient) -> None:
    """Same capability as event-category rename/recolour — a shared
    calendar's colour is Home-administered structure, not any one member's
    content."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"calcolourowner-{suffix}@example.com", "Cal Colour Owner")
    home_id = await _home_with_calendar(client, "Cal Colour Perms Home")

    calendars = await client.get(f"/api/v1/homes/{home_id}/calendars")
    primary = next(row for row in calendars.json()["items"] if row["is_primary"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as friend_client:
        friend_email = f"calcolourfriend-{suffix}@example.com"
        await create_verified_user(friend_client, friend_email, "Cal Colour Friend")
        async with SessionFactory() as db:
            user = await db.scalar(select(User).where(User.email == friend_email))
            assert user is not None
            db.add(
                Membership(
                    group_id=uuid.UUID(home_id),
                    user_id=user.id,
                    role=Role.guest,
                    relationship=HouseholdRelationship.friend,
                    permission_profile=PermissionProfile.explicit_sharing,
                )
            )
            await db.commit()

        blocked = await unsafe(
            friend_client,
            "PATCH",
            f"/api/v1/homes/{home_id}/calendars/{primary['id']}",
            json={"color": "rose"},
        )
        assert blocked.status_code == 403

    unchanged = await client.get(f"/api/v1/homes/{home_id}/calendars")
    persisted = next(row for row in unchanged.json()["items"] if row["is_primary"])
    assert persisted["color"] == "teal"  # unchanged


@pytest.mark.asyncio
async def test_uncategorised_events_use_home_calendar_colour_and_category_still_overrides(
    client: AsyncClient,
) -> None:
    """`calendar_color` (the Home calendar's own colour) is what a
    `label_id: null` event should render as; a category's own colour always
    takes precedence once one is assigned."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rendercolour-{suffix}@example.com", "Render Colour")
    home_id = await _home_with_calendar(client, "Render Colour Home")

    calendars = await client.get(f"/api/v1/homes/{home_id}/calendars")
    primary = next(row for row in calendars.json()["items"] if row["is_primary"])
    recoloured = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/calendars/{primary['id']}",
        json={"color": "violet"},
    )
    assert recoloured.status_code == 200

    label = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Chores", "color": "emerald"},
    )
    assert label.status_code == 201
    label_id = label.json()["id"]

    uncategorised = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "No category",
            "start_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "none",
        },
    )
    assert uncategorised.status_code == 201
    assert uncategorised.json()["calendar_color"] == "violet"
    assert uncategorised.json()["label"] is None

    categorised = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "With category",
            "start_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "none",
            "label_id": label_id,
        },
    )
    assert categorised.status_code == 201
    # The Home calendar colour is still populated for a categorised event
    # (uniform shape for the frontend) but its label colour takes precedence.
    assert categorised.json()["calendar_color"] == "violet"
    assert categorised.json()["label"]["color"] == "emerald"

    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={
            "start_at": datetime.now(UTC).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert listed.status_code == 200
    items = {row["title"]: row for row in listed.json()["items"]}
    assert items["No category"]["calendar_color"] == "violet"
    assert items["With category"]["calendar_color"] == "violet"
    assert items["With category"]["label"]["color"] == "emerald"


@pytest.mark.asyncio
async def test_recurring_event_occurrences_keep_consistent_label_colour(
    client: AsyncClient,
) -> None:
    """One event, one colour — every expanded occurrence of a recurring
    event must carry the same label colour, the same identity every week,
    matching the continuity the month view relies on for multi-day/
    cross-week spans."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"recurcolour-{suffix}@example.com", "Recur Colour")
    home_id = await _home_with_calendar(client, "Recur Colour Home")

    label = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Practice", "color": "violet"},
    )
    assert label.status_code == 201
    label_id = label.json()["id"]

    start_at = datetime.now(UTC) + timedelta(days=1)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Weekly practice",
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "label_id": label_id,
            "recurrence": "weekly",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201

    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(days=35)).isoformat(),
        },
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) >= 4, "expected multiple weekly occurrences in a 5-week window"
    assert all(item["label"]["color"] == "violet" for item in items)
    assert all(item["label"]["id"] == label_id for item in items)


@pytest.mark.asyncio
async def test_create_event_rejects_naive_datetime(client: AsyncClient) -> None:
    """A start_at/end_at with no UTC offset is ambiguous about which instant
    it names — the API must reject it (422) rather than silently guessing
    server-local or UTC intent. Regression test for the calendar timezone
    architecture fix: every timed boundary must be an explicit instant."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"naive-{suffix}@example.com", "Naive Owner")
    home_id = await _home_with_calendar(client, "Naive Home")

    naive_start = (datetime.now(UTC) + timedelta(hours=2)).replace(tzinfo=None)
    naive_end = (datetime.now(UTC) + timedelta(hours=3)).replace(tzinfo=None)
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Ambiguous event",
            "start_at": naive_start.isoformat(),
            "end_at": naive_end.isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "none",
            "recurrence_interval": 1,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_all_day_event_normalized_to_utc_midnight_on_create(client: AsyncClient) -> None:
    """An all-day event names calendar dates, not a wall-clock instant — even
    if a client submits a non-midnight start/end (e.g. a stray time-of-day
    left over from a timed picker), the stored instant must be normalized to
    literal UTC midnight so the exclusive-end-date contract every calendar
    view relies on always holds. Regression test for all-day events silently
    landing on the wrong day when converted through a non-UTC timezone."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"allday-{suffix}@example.com", "All Day Owner")
    home_id = await _home_with_calendar(client, "All Day Home")

    # Deliberately submit a non-midnight time-of-day and a same-day end (as
    # the old frontend picker used to for a "same day" all-day event) to
    # prove the backend normalizes regardless of what was sent.
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Sports Day",
            "start_at": "2026-08-14T09:00:00+01:00",
            "end_at": "2026-08-14T10:00:00+01:00",
            "timezone": "Europe/London",
            "is_all_day": True,
            "member_ids": [],
            "recurrence": "none",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201
    event = created.json()
    assert event["start_at"] in ("2026-08-14T00:00:00Z", "2026-08-14T00:00:00+00:00")
    # Exclusive end: the day *after* the single covered calendar date.
    assert event["end_at"] in ("2026-08-15T00:00:00Z", "2026-08-15T00:00:00+00:00")


@pytest.mark.asyncio
async def test_all_day_event_normalized_to_utc_midnight_on_update(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"alldayedit-{suffix}@example.com", "All Day Editor")
    home_id = await _home_with_calendar(client, "All Day Edit Home")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Bank Holiday",
            "start_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "none",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201
    event = created.json()

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json={
            "title": "Bank Holiday",
            # A three-day all-day event (28-30 Aug inclusive), submitted with
            # a stray afternoon time-of-day on both ends. end_at is the
            # exclusive boundary (the day after the last covered date, per
            # the existing convention), same as Month/Schedule already
            # expect and the same as the frontend picker now constructs.
            "start_at": "2026-08-28T14:30:00+01:00",
            "end_at": "2026-08-31T14:30:00+01:00",
            "timezone": "Europe/London",
            "is_all_day": True,
            "member_ids": [],
            "recurrence": "none",
            "recurrence_interval": 1,
            "expected_updated_at": event["updated_at"],
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["start_at"] in ("2026-08-28T00:00:00Z", "2026-08-28T00:00:00+00:00")
    # Exclusive end: the day after the last covered date (30 Aug).
    assert body["end_at"] in ("2026-08-31T00:00:00Z", "2026-08-31T00:00:00+00:00")


# ---------------------------------------------------------------------------
# Regression: editing an event 422ing on every field (calendar_id in the
# PATCH body) — the frontend's EventForm builds one payload shape shared by
# create and edit, but EventUpdate (unlike EventCreate) has no `calendar_id`
# field: an event's calendar assignment is fixed at creation and always
# resolved server-side from the existing row (see update_event). StrictModel
# rejects any unrecognised field with 422 `extra_forbidden`, so sending
# `calendar_id` (even null) broke *every* edit, regardless of what changed.
# ---------------------------------------------------------------------------


def _update_body(event: dict, **overrides: object) -> dict:
    """A full EventUpdate body seeded from an existing event's own current
    values — mirrors what the frontend's EventForm actually submits (every
    schema field present, since EventUpdate is not a partial/PATCH-semantics
    schema), deliberately excluding `calendar_id`."""
    body = {
        "title": event["title"],
        "start_at": event["start_at"],
        "end_at": event["end_at"],
        "timezone": event["timezone"],
        "is_all_day": event["is_all_day"],
        "member_ids": list(event.get("member_ids", [])),
        "label_id": event["label"]["id"] if event.get("label") else None,
        "location_text": event.get("location_text"),
        "reminder_minutes": event.get("reminder_minutes"),
        "recurrence": event.get("recurrence", "none"),
        "recurrence_interval": 1,
        "recurrence_until": None,
        "recurrence_count": None,
        "expected_updated_at": event["updated_at"],
    }
    body.update(overrides)
    return body


async def _create_event(client: AsyncClient, home_id: str, **overrides: object) -> dict:
    body = {
        "title": "Original title",
        "start_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "end_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "timezone": "Europe/London",
        "is_all_day": False,
        "member_ids": [],
        "recurrence": "none",
    }
    body.update(overrides)
    created = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/events", json=body)
    assert created.status_code == 201, created.text
    return created.json()


@pytest.mark.asyncio
async def test_editing_only_the_title_succeeds(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"edittitle-{suffix}@example.com", "Edit Title")
    home_id = await _home_with_calendar(client, "Edit Title Home")
    event = await _create_event(client, home_id)

    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_update_body(event, title="Updated title"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Updated title"


@pytest.mark.asyncio
async def test_editing_start_and_end_time_succeeds(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"edittime-{suffix}@example.com", "Edit Time")
    home_id = await _home_with_calendar(client, "Edit Time Home")
    event = await _create_event(client, home_id)

    new_start = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    new_end = (datetime.now(UTC) + timedelta(days=1, hours=1)).isoformat()
    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_update_body(event, start_at=new_start, end_at=new_end),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # Compare as instants rather than string formats (the API may normalise offset notation).
    assert datetime.fromisoformat(body["start_at"]) == datetime.fromisoformat(new_start)
    assert datetime.fromisoformat(body["end_at"]) == datetime.fromisoformat(new_end)


@pytest.mark.asyncio
async def test_changing_category_on_an_existing_event_succeeds(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"editcat-{suffix}@example.com", "Edit Category")
    home_id = await _home_with_calendar(client, "Edit Category Home")
    event = await _create_event(client, home_id)

    label = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Sport", "color": "emerald"},
    )
    assert label.status_code == 201
    label_id = label.json()["id"]

    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_update_body(event, label_id=label_id),
    )
    assert response.status_code == 200, response.text
    assert response.json()["label"]["id"] == label_id


@pytest.mark.asyncio
async def test_changing_participants_succeeds_where_entitled(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    owner_email = f"editmembers-{suffix}@example.com"
    await create_verified_user(client, owner_email, "Edit Members Owner")
    home_id = await _home_with_calendar(client, "Edit Members Home")
    event = await _create_event(client, home_id)

    friend_email = f"editmembersfriend-{suffix}@example.com"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as friend_client:
        await create_verified_user(friend_client, friend_email, "Edit Members Friend")
    async with SessionFactory() as db:
        owner = await db.scalar(select(User).where(User.email == owner_email))
        friend = await db.scalar(select(User).where(User.email == friend_email))
        assert owner is not None
        assert friend is not None
        db.add(
            Membership(
                group_id=uuid.UUID(home_id),
                user_id=friend.id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()
        owner_id, friend_id = owner.id, friend.id

    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_update_body(event, member_ids=[str(friend_id)]),
    )
    assert response.status_code == 200, response.text
    assert str(friend_id) in response.json()["member_ids"]
    assert str(owner_id) in response.json()["member_ids"]  # creator is always kept


@pytest.mark.asyncio
async def test_event_can_be_edited_without_setting_every_optional_field(
    client: AsyncClient,
) -> None:
    """EventUpdate is not a partial/PATCH-semantics schema — but every field
    beyond the handful of true requireds (title/start/end/timezone/is_all_day/
    expected_updated_at) is still optional with a sensible default, so a
    minimal body omitting description/location/label/members/reminder/
    recurrence entirely must still succeed."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"editminimal-{suffix}@example.com", "Edit Minimal")
    home_id = await _home_with_calendar(client, "Edit Minimal Home")
    event = await _create_event(
        client, home_id, location_text="Kitchen", description="Weekly catch-up"
    )

    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json={
            "title": "Still weekly catch-up",
            "start_at": event["start_at"],
            "end_at": event["end_at"],
            "timezone": event["timezone"],
            "is_all_day": False,
            "expected_updated_at": event["updated_at"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Still weekly catch-up"


@pytest.mark.asyncio
async def test_home_calendar_event_label_id_null_can_be_edited(client: AsyncClient) -> None:
    """An uncategorised event (label_id null — presented to users as "Home
    calendar") must be editable exactly like a categorised one."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"edithomecal-{suffix}@example.com", "Edit Home Cal")
    home_id = await _home_with_calendar(client, "Edit Home Cal Home")
    event = await _create_event(client, home_id)
    assert event["label"] is None
    assert event["calendar_color"]  # always populated

    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_update_body(event, location_text="Living room"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["label"] is None
    assert response.json()["location_text"] == "Living room"


@pytest.mark.asyncio
async def test_legacy_event_created_before_recent_calendar_changes_can_still_be_updated(
    client: AsyncClient,
) -> None:
    """Simulates an event whose row predates the newer optional fields ever
    being touched (reminder_minutes/recurrence_until/recurrence_count all
    left at their original None/default) — editing it must not require the
    caller to first "upgrade" it by supplying values for fields it never had."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"editlegacy-{suffix}@example.com", "Edit Legacy")
    home_id = await _home_with_calendar(client, "Edit Legacy Home")
    event = await _create_event(client, home_id)
    assert event["reminder_minutes"] is None

    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_update_body(event, title="Legacy event, updated"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Legacy event, updated"
    assert response.json()["reminder_minutes"] is None


@pytest.mark.asyncio
async def test_update_still_rejects_a_calendar_id_field_and_other_invalid_input(
    client: AsyncClient,
) -> None:
    """Confirms the fix was made on the frontend contract, not by loosening
    backend validation: `calendar_id` (an event's calendar is fixed at
    creation, never editable) and a nonsensical end-before-start range must
    both still be rejected."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"editinvalid-{suffix}@example.com", "Edit Invalid")
    home_id = await _home_with_calendar(client, "Edit Invalid Home")
    event = await _create_event(client, home_id)

    with_calendar_id = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_update_body(event, calendar_id=None),
    )
    assert with_calendar_id.status_code == 422
    detail = with_calendar_id.json()["detail"]
    assert detail[0]["type"] == "extra_forbidden"
    assert detail[0]["loc"] == ["body", "calendar_id"]

    end_before_start = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_update_body(event, end_at=event["start_at"], start_at=event["end_at"]),
    )
    assert end_before_start.status_code == 422
    assert end_before_start.json()["detail"] == "End must be after start"
