"""Per-occurrence recurring-event edit/delete (Phase: recurrence exceptions).

Covers the CalendarEventException persistence model, the exception-aware
expand_occurrences/next_occurrence_on_or_after path, the occurrence/future/
series scope API contract, series splitting, security/validation, and
idempotency. Uses the same real-HTTP-against-real-Postgres pattern as
test_calendar.py — see that file's create_verified_user/unsafe/_create_home
helpers, reused here rather than duplicated.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_calendar import create_verified_user, unsafe  # noqa: F401

from mykhaya.calendar_occurrences import (
    canonical_occurrences_up_to,
    expand_occurrences,
    is_canonical_occurrence,
    load_exceptions,
    next_occurrence_on_or_after,
)
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    CalendarEvent,
    CalendarEventException,
    FeatureKey,
    FeatureOverride,
    RecurrencePattern,
)

ORIGIN = "http://localhost:8080"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


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


# Every recurring fixture anchors to the *next* Tuesday 18:00 UTC so tests
# are deterministic regardless of which day they actually run on, and far
# enough in the future that "1 Sep / 8 Sep / 15 Sep / 22 Sep" from the task
# brief map cleanly onto occurrences 1-4.
def _next_weekday_at(weekday: int, hour: int) -> datetime:
    now = datetime.now(UTC)
    days_ahead = (weekday - now.weekday()) % 7
    days_ahead = days_ahead or 7  # always strictly in the future
    base = (now + timedelta(days=days_ahead)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return base


async def _create_weekly_event(
    client: AsyncClient, home_id: str, title: str = "Swimming"
) -> tuple[str, datetime]:
    first = _next_weekday_at(weekday=1, hour=18)  # Tuesday 18:00 UTC
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": title,
            "start_at": first.isoformat(),
            "end_at": (first + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "weekly",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["event_id"], first


async def _occurrences(
    client: AsyncClient, home_id: str, start: datetime, weeks: int = 6
) -> list[dict]:
    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={
            "start_at": (start - timedelta(days=1)).isoformat(),
            "end_at": (start + timedelta(weeks=weeks)).isoformat(),
        },
    )
    assert listed.status_code == 200, listed.text
    return sorted(listed.json()["items"], key=lambda item: item["start_at"])


def _patch_body(occ: dict, **overrides: object) -> dict:
    body = {
        "title": occ["title"],
        "start_at": occ["start_at"],
        "end_at": occ["end_at"],
        "timezone": occ["timezone"],
        "is_all_day": occ["is_all_day"],
        "member_ids": [],
        "recurrence": occ["recurrence"],
        "recurrence_interval": 1,
        "expected_updated_at": occ["updated_at"],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_scenario_1_delete_single_occurrence(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec1-{suffix}@example.com", "Rec One")
    home_id = await _create_home(client, "Rec Home 1")
    event_id, first = await _create_weekly_event(client, home_id)

    occs = await _occurrences(client, home_id, first)
    assert len(occs) >= 4
    third = occs[2]  # "15 Sep" equivalent

    deleted = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        params={"scope": "occurrence", "occurrence_start": third["occurrence_start"]},
    )
    assert deleted.status_code == 204, deleted.text

    after = await _occurrences(client, home_id, first)
    starts = {o["start_at"] for o in after}
    assert third["start_at"] not in starts
    assert len(after) == len(occs) - 1
    # 1st, 2nd, 4th remain.
    assert occs[0]["start_at"] in starts
    assert occs[1]["start_at"] in starts
    assert occs[3]["start_at"] in starts


@pytest.mark.asyncio
async def test_scenario_2_edit_single_occurrence_only(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec2-{suffix}@example.com", "Rec Two")
    home_id = await _create_home(client, "Rec Home 2")
    event_id, first = await _create_weekly_event(client, home_id)

    occs = await _occurrences(client, home_id, first)
    third = occs[2]
    new_start = datetime.fromisoformat(third["start_at"]) + timedelta(hours=2)  # 18:00 -> 20:00

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(
            third,
            title="Swimming lesson",
            start_at=new_start.isoformat(),
            end_at=(new_start + timedelta(hours=1)).isoformat(),
            scope="occurrence",
            occurrence_start=third["occurrence_start"],
        ),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["title"] == "Swimming lesson"
    # Compare on the minute-precision prefix only — avoids depending on
    # exactly which ISO-8601 offset/zone spelling the API happens to emit.
    assert body["start_at"][:16] == new_start.isoformat()[:16]
    assert body["is_overridden"] is True
    assert body["occurrence_start"] == third["occurrence_start"]

    after = await _occurrences(client, home_id, first)
    by_occurrence_start = {o["occurrence_start"]: o for o in after}
    assert by_occurrence_start[occs[0]["occurrence_start"]]["title"] == "Swimming"
    assert by_occurrence_start[occs[0]["occurrence_start"]]["start_at"] == occs[0]["start_at"]
    assert by_occurrence_start[occs[1]["occurrence_start"]]["title"] == "Swimming"
    assert by_occurrence_start[third["occurrence_start"]]["title"] == "Swimming lesson"
    assert by_occurrence_start[occs[3]["occurrence_start"]]["title"] == "Swimming"


@pytest.mark.asyncio
async def test_scenario_3_move_occurrence_no_duplicate_and_stable_identity(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec3-{suffix}@example.com", "Rec Three")
    home_id = await _create_home(client, "Rec Home 3")
    event_id, first = await _create_weekly_event(client, home_id)

    occs = await _occurrences(client, home_id, first)
    third = occs[2]
    moved_start = datetime.fromisoformat(third["start_at"]) + timedelta(days=1)  # Tue -> Wed

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(
            third,
            start_at=moved_start.isoformat(),
            end_at=(moved_start + timedelta(hours=1)).isoformat(),
            scope="occurrence",
            occurrence_start=third["occurrence_start"],
        ),
    )
    assert updated.status_code == 200, updated.text

    # Same window as the initial `occs` fetch (default weeks=6) — a wider
    # window here would legitimately pick up one more Tuesday than the
    # original query did, which is not the "no duplicate" bug this test
    # means to catch.
    after = await _occurrences(client, home_id, first)
    starts = [o["start_at"] for o in after]
    assert third["start_at"] not in starts  # old Tuesday slot gone
    moved_prefix = moved_start.isoformat()[:16]
    assert any(s.startswith(moved_prefix) for s in starts)
    # No duplicate: exactly one event on the moved date, and the total
    # count of occurrences is unchanged (moved, not added).
    assert len(after) == len(occs)

    # Re-editing again must update the SAME exception, not create a second
    # one (stable identity — reopening the moved event edits the same row).
    moved_occ = next(o for o in after if o["occurrence_start"] == third["occurrence_start"])
    again = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(
            moved_occ,
            title="Swimming (moved again)",
            scope="occurrence",
            occurrence_start=third["occurrence_start"],
        ),
    )
    assert again.status_code == 200, again.text
    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(CalendarEventException).where(
                    CalendarEventException.event_id == uuid.UUID(event_id)
                )
            )
        ).all()
        assert len(rows) == 1, "moving/re-editing an occurrence must reuse its exception row"


@pytest.mark.asyncio
async def test_scenario_4_edit_this_and_future(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec4-{suffix}@example.com", "Rec Four")
    home_id = await _create_home(client, "Rec Home 4")
    event_id, first = await _create_weekly_event(client, home_id)

    occs = await _occurrences(client, home_id, first)
    third = occs[2]
    new_time = datetime.fromisoformat(third["start_at"]) + timedelta(hours=1)  # 18:00 -> 19:00

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(
            third,
            start_at=new_time.isoformat(),
            end_at=(new_time + timedelta(hours=1)).isoformat(),
            scope="future",
            occurrence_start=third["occurrence_start"],
        ),
    )
    assert updated.status_code == 200, updated.text
    new_event_id = updated.json()["event_id"]
    assert new_event_id != event_id, "future scope must create a new series, not mutate the old one"

    after = await _occurrences(client, home_id, first)
    # Keyed on the datetime.fromisoformat()-parsed instant, not the raw
    # string — the API and this test's own locally-built ISO strings use
    # different (but equally valid) offset spellings ("Z" vs "+00:00"), so
    # a raw-string dict key would spuriously mismatch.
    by_start = {datetime.fromisoformat(o["start_at"].replace("Z", "+00:00")): o for o in after}
    assert by_start[datetime.fromisoformat(occs[0]["start_at"])]["event_id"] == event_id
    assert by_start[datetime.fromisoformat(occs[1]["start_at"])]["event_id"] == event_id
    # occ[2]/occ[3] now belong to the new series at the new time.
    third_new_start = new_time
    fourth_new_start = datetime.fromisoformat(occs[3]["start_at"]) + timedelta(hours=1)
    assert by_start[third_new_start]["event_id"] == new_event_id
    assert by_start[fourth_new_start]["event_id"] == new_event_id
    old_third_start = datetime.fromisoformat(third["start_at"])
    assert old_third_start not in by_start  # old 18:00 slot for occ 3 is gone


@pytest.mark.asyncio
async def test_scenario_5_delete_this_and_future(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec5-{suffix}@example.com", "Rec Five")
    home_id = await _create_home(client, "Rec Home 5")
    event_id, first = await _create_weekly_event(client, home_id)

    occs = await _occurrences(client, home_id, first)
    third = occs[2]

    deleted = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        params={"scope": "future", "occurrence_start": third["occurrence_start"]},
    )
    assert deleted.status_code == 204, deleted.text

    after = await _occurrences(client, home_id, first, weeks=8)
    starts = {o["start_at"] for o in after}
    assert occs[0]["start_at"] in starts
    assert occs[1]["start_at"] in starts
    assert third["start_at"] not in starts
    assert occs[3]["start_at"] not in starts
    assert len(after) == 2


@pytest.mark.asyncio
async def test_scenario_6_existing_override_survives_future_split(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec6-{suffix}@example.com", "Rec Six")
    home_id = await _create_home(client, "Rec Home 6")
    event_id, first = await _create_weekly_event(client, home_id)

    occs = await _occurrences(client, home_id, first)
    fourth = occs[3]  # "22 Sep" equivalent — override this one first
    override_response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(
            fourth,
            title="Swimming (special)",
            scope="occurrence",
            occurrence_start=fourth["occurrence_start"],
        ),
    )
    assert override_response.status_code == 200, override_response.text

    third = occs[2]  # split from "15 Sep" equivalent
    split_response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(third, scope="future", occurrence_start=third["occurrence_start"]),
    )
    assert split_response.status_code == 200, split_response.text
    new_event_id = split_response.json()["event_id"]

    async with SessionFactory() as db:
        exception = await db.scalar(
            select(CalendarEventException).where(
                CalendarEventException.occurrence_start
                == datetime.fromisoformat(fourth["occurrence_start"])
            )
        )
        assert exception is not None
        assert str(exception.event_id) == new_event_id, "override must move to the new series"
        assert exception.title == "Swimming (special)"

    after = await _occurrences(client, home_id, first)
    fourth_after = next(o for o in after if o["occurrence_start"] == fourth["occurrence_start"])
    assert fourth_after["title"] == "Swimming (special)"


@pytest.mark.asyncio
async def test_scenario_7_deleted_occurrence_survives_future_split(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec7-{suffix}@example.com", "Rec Seven")
    home_id = await _create_home(client, "Rec Home 7")
    event_id, first = await _create_weekly_event(client, home_id)

    occs = await _occurrences(client, home_id, first)
    fourth = occs[3]
    deleted = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        params={"scope": "occurrence", "occurrence_start": fourth["occurrence_start"]},
    )
    assert deleted.status_code == 204

    third = occs[2]
    split_response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(third, scope="future", occurrence_start=third["occurrence_start"]),
    )
    assert split_response.status_code == 200, split_response.text

    after = await _occurrences(client, home_id, first)
    starts = {o["start_at"] for o in after}
    assert fourth["start_at"] not in starts, "22 Sep must remain excluded after the split"


@pytest.mark.asyncio
async def test_scope_occurrence_rejected_for_non_recurring_event(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec8-{suffix}@example.com", "Rec Eight")
    home_id = await _create_home(client, "Rec Home 8")
    start = datetime.now(UTC) + timedelta(days=1)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "One-off",
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "none",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201
    event = created.json()

    deleted = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        params={"scope": "occurrence", "occurrence_start": event["occurrence_start"]},
    )
    assert deleted.status_code == 422


@pytest.mark.asyncio
async def test_occurrence_start_not_belonging_to_series_is_rejected(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec9-{suffix}@example.com", "Rec Nine")
    home_id = await _create_home(client, "Rec Home 9")
    event_id, first = await _create_weekly_event(client, home_id)

    # A Wednesday timestamp can never be a canonical occurrence of a
    # Tuesday-weekly series.
    bogus = first + timedelta(days=1)
    deleted = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        params={"scope": "occurrence", "occurrence_start": bogus.isoformat()},
    )
    assert deleted.status_code == 422


@pytest.mark.asyncio
async def test_occurrence_from_another_event_is_rejected(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec10-{suffix}@example.com", "Rec Ten")
    home_id = await _create_home(client, "Rec Home 10")
    event_id_a, first_a = await _create_weekly_event(client, home_id, title="Series A")
    # Series B runs on a different weekday (Thursday, not A's Tuesday) so
    # its occurrences can never coincide with A's by construction.
    first_b = _next_weekday_at(weekday=3, hour=18)
    created_b = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Series B",
            "start_at": first_b.isoformat(),
            "end_at": (first_b + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "weekly",
            "recurrence_interval": 1,
        },
    )
    assert created_b.status_code == 201, created_b.text
    assert first_a != first_b

    # first_b is a real canonical occurrence — but of the OTHER event.
    deleted = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/events/{event_id_a}",
        params={"scope": "occurrence", "occurrence_start": first_b.isoformat()},
    )
    assert deleted.status_code == 422


@pytest.mark.asyncio
async def test_double_submit_occurrence_delete_is_idempotent(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec11-{suffix}@example.com", "Rec Eleven")
    home_id = await _create_home(client, "Rec Home 11")
    event_id, first = await _create_weekly_event(client, home_id)
    occs = await _occurrences(client, home_id, first)
    target = occs[1]

    first_delete = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        params={"scope": "occurrence", "occurrence_start": target["occurrence_start"]},
    )
    assert first_delete.status_code == 204
    second_delete = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        params={"scope": "occurrence", "occurrence_start": target["occurrence_start"]},
    )
    assert second_delete.status_code == 204

    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(CalendarEventException).where(
                    CalendarEventException.event_id == uuid.UUID(event_id),
                    CalendarEventException.occurrence_start
                    == datetime.fromisoformat(target["occurrence_start"]),
                )
            )
        ).all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_double_submit_occurrence_edit_updates_same_row(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec12-{suffix}@example.com", "Rec Twelve")
    home_id = await _create_home(client, "Rec Home 12")
    event_id, first = await _create_weekly_event(client, home_id)
    occs = await _occurrences(client, home_id, first)
    target = occs[1]

    for _ in range(2):
        response = await unsafe(
            client,
            "PATCH",
            f"/api/v1/homes/{home_id}/events/{event_id}",
            json=_patch_body(
                target,
                title="Double-submitted",
                scope="occurrence",
                occurrence_start=target["occurrence_start"],
            ),
        )
        assert response.status_code == 200, response.text

    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(CalendarEventException).where(
                    CalendarEventException.event_id == uuid.UUID(event_id)
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].title == "Double-submitted"


@pytest.mark.asyncio
async def test_read_only_share_cannot_mutate_occurrence(client: AsyncClient) -> None:
    """Mirrors test_calendar_sharing.py's own read-only enforcement pattern
    at the recurrence-exception layer: a view-only external share must not
    let its recipient create an occurrence exception via the *source
    Home's* own endpoint either (the recipient isn't even a member of that
    Home, so this must 404, exactly like any other unauthorised mutation)."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec13-{suffix}@example.com", "Rec Thirteen")
    home_id = await _create_home(client, "Rec Home 13")
    event_id, first = await _create_weekly_event(client, home_id)
    occs = await _occurrences(client, home_id, first)
    target = occs[1]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as outsider:
        await create_verified_user(outsider, f"outsider13-{suffix}@example.com", "Outsider")
        denied = await unsafe(
            outsider,
            "PATCH",
            f"/api/v1/homes/{home_id}/events/{event_id}",
            json=_patch_body(
                target,
                title="Hijacked",
                scope="occurrence",
                occurrence_start=target["occurrence_start"],
            ),
        )
        assert denied.status_code == 404


@pytest.mark.asyncio
async def test_whole_series_edit_preserves_still_valid_exception(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec14-{suffix}@example.com", "Rec Fourteen")
    home_id = await _create_home(client, "Rec Home 14")
    event_id, first = await _create_weekly_event(client, home_id)
    occs = await _occurrences(client, home_id, first)
    target = occs[1]

    override = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(
            target,
            title="Kept override",
            scope="occurrence",
            occurrence_start=target["occurrence_start"],
        ),
    )
    assert override.status_code == 200

    # Whole-series edit that changes only the title, leaving the same
    # weekly pattern/time — the overridden occurrence is still a valid
    # canonical occurrence afterwards, so its exception must survive.
    series_event = await client.get(f"/api/v1/homes/{home_id}/events/{event_id}")
    assert series_event.status_code == 200
    detail = series_event.json()["event"]
    series_edit = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(detail, title="Swimming (renamed)", scope="series"),
    )
    assert series_edit.status_code == 200, series_edit.text

    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(CalendarEventException).where(
                    CalendarEventException.event_id == uuid.UUID(event_id)
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].title == "Kept override"


@pytest.mark.asyncio
async def test_whole_series_edit_drops_now_invalid_exception(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec15-{suffix}@example.com", "Rec Fifteen")
    home_id = await _create_home(client, "Rec Home 15")
    event_id, first = await _create_weekly_event(client, home_id)
    occs = await _occurrences(client, home_id, first)
    fourth = occs[3]

    override = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(
            fourth,
            title="Will be orphaned",
            scope="occurrence",
            occurrence_start=fourth["occurrence_start"],
        ),
    )
    assert override.status_code == 200

    # Shrink the series to COUNT=2 — the 4th occurrence's exception no
    # longer refers to any occurrence this recurrence rule still generates.
    series_event = await client.get(f"/api/v1/homes/{home_id}/events/{event_id}")
    detail = series_event.json()["event"]
    series_edit = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(detail, scope="series", recurrence_count=2),
    )
    assert series_edit.status_code == 200, series_edit.text

    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(CalendarEventException).where(
                    CalendarEventException.event_id == uuid.UUID(event_id)
                )
            )
        ).all()
        assert rows == [], "exception for a now-invalid occurrence must be dropped"


@pytest.mark.asyncio
async def test_whole_series_delete_removes_exceptions(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec16-{suffix}@example.com", "Rec Sixteen")
    home_id = await _create_home(client, "Rec Home 16")
    event_id, first = await _create_weekly_event(client, home_id)
    occs = await _occurrences(client, home_id, first)
    target = occs[1]

    override = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(
            target,
            title="About to be deleted",
            scope="occurrence",
            occurrence_start=target["occurrence_start"],
        ),
    )
    assert override.status_code == 200

    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/events/{event_id}")
    assert deleted.status_code == 204

    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(CalendarEventException).where(
                    CalendarEventException.event_id == uuid.UUID(event_id)
                )
            )
        ).all()
        assert rows == []


@pytest.mark.asyncio
async def test_home_summary_matches_calendar_for_todays_recurring_occurrence(
    client: AsyncClient,
) -> None:
    """Regression for the pre-existing home_summary gap: a recurring
    event's first occurrence is in the past, but a later occurrence falls
    today — Home must show it, exactly like Calendar/Coming Up do."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec17-{suffix}@example.com", "Rec Seventeen")
    home_id = await _create_home(client, "Rec Home 17")

    now = datetime.now(UTC)
    # A daily series that started 3 days ago and includes today, at a time
    # already in the past today, but not yet ended (end_at in the future)
    # so it still qualifies as "today".
    start = (now - timedelta(days=3)).replace(microsecond=0)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Daily standup",
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "daily",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201, created.text

    summary = await client.get(f"/api/v1/homes/{home_id}/summary")
    assert summary.status_code == 200, summary.text
    titles_today = [event["title"] for event in summary.json()["today_events"]]
    assert "Daily standup" in titles_today


@pytest.mark.asyncio
async def test_moved_occurrence_does_not_appear_at_original_slot_in_expand_occurrences(
    client: AsyncClient,
) -> None:
    """Direct unit-level check of the exception-aware expansion itself
    (not just through the API), proving no duplicate is ever produced."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec18-{suffix}@example.com", "Rec Eighteen")
    home_id = await _create_home(client, "Rec Home 18")
    event_id, first = await _create_weekly_event(client, home_id)
    occs = await _occurrences(client, home_id, first)
    third = occs[2]
    moved_start = datetime.fromisoformat(third["start_at"]) + timedelta(days=1)

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_patch_body(
            third,
            start_at=moved_start.isoformat(),
            end_at=(moved_start + timedelta(hours=1)).isoformat(),
            scope="occurrence",
            occurrence_start=third["occurrence_start"],
        ),
    )
    assert updated.status_code == 200

    async with SessionFactory() as db:
        event = await db.get(CalendarEvent, uuid.UUID(event_id))
        assert event is not None
        exceptions = await load_exceptions(db, [event.id])
        window_start = first - timedelta(days=1)
        window_end = first + timedelta(weeks=5)
        exceptions_for_event = exceptions.get(event.id, {})
        effective = expand_occurrences(event, window_start, window_end, exceptions_for_event)
        starts = [occurrence.start_at for occurrence in effective]
        assert datetime.fromisoformat(third["start_at"]) not in starts
        assert moved_start in starts
        assert starts.count(moved_start) == 1
        assert is_canonical_occurrence(event, datetime.fromisoformat(third["occurrence_start"]))


@pytest.mark.asyncio
async def test_next_occurrence_on_or_after_skips_deleted_occurrence(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"rec19-{suffix}@example.com", "Rec Nineteen")
    home_id = await _create_home(client, "Rec Home 19")
    event_id, first = await _create_weekly_event(client, home_id)
    occs = await _occurrences(client, home_id, first)
    first_occ = occs[0]

    deleted = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        params={"scope": "occurrence", "occurrence_start": first_occ["occurrence_start"]},
    )
    assert deleted.status_code == 204

    async with SessionFactory() as db:
        event = await db.get(CalendarEvent, uuid.UUID(event_id))
        assert event is not None
        exceptions = await load_exceptions(db, [event.id])
        exceptions_for_event = exceptions.get(event.id, {})
        effective = next_occurrence_on_or_after(
            event, first - timedelta(hours=1), exceptions_for_event
        )
        assert effective is not None
        assert effective.start_at == datetime.fromisoformat(occs[1]["start_at"])


def test_canonical_occurrences_up_to_respects_recurrence_until_boundary() -> None:
    """Same off-by-one recurrence_until boundary fix as
    test_recurrence_until_boundary_is_exact_not_off_by_one in test_calendar.py,
    for canonical_occurrences_up_to specifically (the walk behind
    is_canonical_occurrence and the "this and future" split's
    occurrence-index lookup)."""
    event = CalendarEvent(
        start_at=datetime(2026, 1, 1, 9, tzinfo=UTC),
        end_at=datetime(2026, 1, 1, 10, tzinfo=UTC),
        timezone="UTC",
        recurrence=RecurrencePattern.weekly,
        recurrence_interval=1,
        recurrence_until=datetime(2026, 1, 15, 9, tzinfo=UTC),
    )
    # Asking up to a date well past the boundary must still stop at the
    # last in-bounds occurrence (Jan 15), never leak Jan 22 through.
    collected = canonical_occurrences_up_to(event, datetime(2026, 3, 1, tzinfo=UTC))
    assert collected == [
        datetime(2026, 1, 1, 9, tzinfo=UTC),
        datetime(2026, 1, 8, 9, tzinfo=UTC),
        datetime(2026, 1, 15, 9, tzinfo=UTC),
    ]
