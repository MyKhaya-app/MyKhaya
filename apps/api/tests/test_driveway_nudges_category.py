"""MOT nudges in Nudges: visibility, the system "Driveway" category, and
deleting plan nudges (see mykhaya.driveway_mot_nudges and
mykhaya.driveway_reminders). Uses the fabricated DVSA transport from
test_driveway_mot — nothing here reaches a real provider."""

from __future__ import annotations

import uuid
from datetime import date, time, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from test_driveway_mot import (  # noqa: F401  (fixtures)
    TODAY,
    FakeDvsa,
    _iso,
    _refresh,
    _row,
    _vehicle,
    client,
    dvsa,
    history_payload,
)
from test_driveway_mot_nudges import _nudges_url, _reminders, _save
from test_driveway_reminders import unsafe

import mykhaya.driveway_mot as driveway_mot
from mykhaya.db import SessionFactory
from mykhaya.models import Reminder, ReminderRepeat, RoutineScope, TodoCategory
from mykhaya.notifications.reminder_occurrences import next_occurrence_date


def _reminder(**overrides: Any) -> Reminder:
    values: dict[str, Any] = {
        "title": "x",
        "due_date": TODAY + timedelta(days=300),
        "due_time": time(9, 0),
        "repeat": ReminderRepeat.never,
        "enabled": True,
    }
    values.update(overrides)
    return Reminder(**values)


def test_one_off_reminders_report_their_due_date_however_far_ahead() -> None:
    far = _reminder()
    assert next_occurrence_date(far, TODAY) == TODAY + timedelta(days=300)
    assert next_occurrence_date(_reminder(enabled=False), TODAY) is None
    assert next_occurrence_date(_reminder(due_date=TODAY - timedelta(days=1)), TODAY) is None
    assert next_occurrence_date(_reminder(due_date=TODAY), TODAY) == TODAY
    # Repeating reminders keep the bounded look-ahead.
    weekly = _reminder(repeat=ReminderRepeat.weekly, due_date=TODAY + timedelta(days=200))
    assert next_occurrence_date(weekly, TODAY) is None
    weekly_soon = _reminder(repeat=ReminderRepeat.weekly, due_date=TODAY + timedelta(days=3))
    assert next_occurrence_date(weekly_soon, TODAY) == TODAY + timedelta(days=3)


async def _list(client: AsyncClient, home_id: uuid.UUID) -> list[dict[str, Any]]:
    response = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/reminders")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _search(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """The Nudges page's client-side search: title, description, category."""
    needle = query.lower()
    return [
        item
        for item in items
        if needle in item["title"].lower()
        or needle in (item["description"] or "").lower()
        or needle in ((item["category"] or {}).get("name") or "").lower()
    ]


@pytest.mark.asyncio
async def test_mot_nudges_are_returned_by_the_nudges_list_and_found_by_search(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    owner_id, home_id, vehicle = await _vehicle(client, "nc-list")
    assert (await _save(client, home_id, vehicle["id"])).status_code == 200

    items = await _list(client, home_id)
    nudges = [item for item in items if item["vehicle"] and item["vehicle"]["mot_plan_lead_days"]]
    assert sorted(item["next_occurrence_date"] for item in nudges) == [_iso(305), _iso(328)]
    for item in nudges:
        assert item["title"] == "Book MOT – Family car"
        assert item["scope"] == "personal" and item["owner_user_id"] == str(owner_id)
        assert item["category"]["name"] == "Driveway"
        assert item["category"]["system"] == "driveway"
        assert item["vehicle"]["vehicle_id"] == vehicle["id"]
        assert item["vehicle"]["registration"] == "AB12 CDE"
        assert item["vehicle"]["nickname"] == "Family car"
    assert {item["vehicle"]["mot_plan_lead_days"] for item in nudges} == {30, 7}
    found = _search(items, "MOT")
    assert {item["id"] for item in nudges} <= {item["id"] for item in found}


@pytest.mark.asyncio
async def test_every_home_has_a_driveway_category_that_cannot_be_renamed_or_deleted(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    _, home_id, vehicle = await _vehicle(client, "nc-system")
    categories = (await unsafe(client, "GET", f"/api/v1/homes/{home_id}/todo-categories")).json()[
        "items"
    ]
    (system,) = [c for c in categories if c["system"] == "driveway"]
    assert system["name"] == "Driveway"
    url = f"/api/v1/homes/{home_id}/todo-categories/{system['id']}"

    renamed = await unsafe(
        client, "PATCH", url, json={"name": "Cars", "expected_updated_at": system["updated_at"]}
    )
    assert renamed.status_code == 409
    # Refused even while empty.
    assert (await unsafe(client, "DELETE", url)).status_code == 409
    duplicate = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/todo-categories", json={"name": "driveway"}
    )
    assert duplicate.status_code == 409
    # It can't be picked for an ordinary reminder.
    ordinary = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={
            "title": "Bins",
            "scope": "personal",
            "due_date": _iso(1),
            "due_time": "09:00",
            "category_id": system["id"],
        },
    )
    assert ordinary.status_code == 422

    # Vehicle reminders land in it, and editing one keeps it there.
    await _save(client, home_id, vehicle["id"])
    reminders = await _reminders(vehicle["id"])
    assert {str(r.category_id) for r in reminders.values()} == {system["id"]}
    nudge = next(i for i in await _list(client, home_id) if i["vehicle"])
    edited = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/reminders/{nudge['id']}",
        json={
            "title": nudge["title"],
            "scope": "personal",
            "due_date": nudge["due_date"],
            "due_time": nudge["due_time"][:5],
            "repeat": "never",
            "cadence": "once",
            "enabled": True,
            "member_ids": [],
            "category_id": None,
            "expected_updated_at": nudge["updated_at"],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["category"]["system"] == "driveway"


@pytest.mark.asyncio
async def test_deleting_one_plan_nudge_drops_that_day_and_a_refresh_does_not_recreate_it(
    client: AsyncClient, dvsa: FakeDvsa, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driveway_mot, "FORCE_COOLDOWN", timedelta(0))
    _, home_id, vehicle = await _vehicle(client, "nc-del-one")
    await _refresh(client, home_id, vehicle["id"])
    await _save(client, home_id, vehicle["id"])
    seven = (await _reminders(vehicle["id"]))["inspection_lead_7"]

    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/reminders/{seven.id}")
    assert deleted.status_code == 204
    plan = (await unsafe(client, "GET", _nudges_url(home_id, vehicle["id"]))).json()["plan"]
    assert plan["offsets"] == [30]

    payload = history_payload()
    payload["motTests"][0]["expiryDate"] = _iso(700)
    dvsa.responses = [(200, payload)]
    await _refresh(client, home_id, vehicle["id"])
    after = await _reminders(vehicle["id"])
    assert set(after) == {"inspection_lead_30"}
    assert after["inspection_lead_30"].due_date == TODAY + timedelta(days=670)


@pytest.mark.asyncio
async def test_removing_the_plan_deletes_its_nudges_and_a_refresh_recreates_nothing(
    client: AsyncClient, dvsa: FakeDvsa, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driveway_mot, "FORCE_COOLDOWN", timedelta(0))
    _, home_id, vehicle = await _vehicle(client, "nc-del-plan")
    await _refresh(client, home_id, vehicle["id"])
    await _save(client, home_id, vehicle["id"])

    removed = await unsafe(client, "DELETE", _nudges_url(home_id, vehicle["id"]))
    assert removed.status_code == 204
    assert await _reminders(vehicle["id"]) == {}
    assert (await unsafe(client, "GET", _nudges_url(home_id, vehicle["id"]))).json() == {
        "plan": None
    }

    payload = history_payload()
    payload["motTests"][0]["expiryDate"] = _iso(700)
    dvsa.responses = [(200, payload)]
    await _refresh(client, home_id, vehicle["id"])
    assert await _reminders(vehicle["id"]) == {}
    assert (await _row(vehicle["id"])).mot_nudge_plan == {"off": True}

    # Saving a new plan turns MOT nudges back on.
    assert (await _save(client, home_id, vehicle["id"], due_date=_iso(700))).status_code == 200
    assert set(await _reminders(vehicle["id"])) == {"inspection_lead_30", "inspection_lead_7"}


@pytest.mark.asyncio
async def test_deleting_the_last_plan_nudge_turns_mot_nudges_off(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    _, home_id, vehicle = await _vehicle(client, "nc-del-last")
    await _save(client, home_id, vehicle["id"], offsets=[7])
    seven = (await _reminders(vehicle["id"]))["inspection_lead_7"]
    await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/reminders/{seven.id}")
    assert (await _row(vehicle["id"])).mot_nudge_plan == {"off": True}


@pytest.mark.asyncio
async def test_the_newest_reminders_are_never_cut_off_by_the_list_cap(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    owner_id, home_id, _ = await _vehicle(client, "nc-cap")
    async with SessionFactory() as db:
        for index in range(1005):
            db.add(
                Reminder(
                    group_id=home_id,
                    title=f"Old {index}",
                    scope=RoutineScope.personal,
                    owner_user_id=owner_id,
                    due_date=date(2026, 1, 1),
                    due_time=time(9, 0),
                    created_by=owner_id,
                )
            )
        await db.commit()
    newest = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={"title": "Newest", "scope": "personal", "due_date": _iso(1), "due_time": "09:00"},
    )
    assert newest.status_code == 201, newest.text
    items = await _list(client, home_id)
    assert len(items) == 1000
    assert items[-1]["title"] == "Newest"


@pytest.mark.asyncio
async def test_a_new_home_is_seeded_with_the_driveway_category(client: AsyncClient) -> None:
    from test_driveway_field_encryption import _home

    _, home_id = await _home(client, "nc-seed")
    async with SessionFactory() as db:
        rows = (
            await db.scalars(select(TodoCategory).where(TodoCategory.group_id == home_id))
        ).all()
    assert [(row.name, row.managed_source) for row in rows] == [("Driveway", "driveway")]


@pytest.mark.asyncio
async def test_home_migration_carries_the_driveway_category_plan_and_nudges(
    client: AsyncClient, dvsa: FakeDvsa, tmp_path: Any
) -> None:
    from mykhaya.config import get_settings
    from mykhaya.tools.home_migration import export_home, import_home

    owner_id, home_id, vehicle = await _vehicle(client, "nc-migrate")
    await _save(client, home_id, vehicle["id"])

    source = get_settings().model_copy(update={"environment": "development"})
    package = await export_home(home_id, tmp_path / "package.json", source)
    target = get_settings().model_copy(update={"environment": "production"})
    report = await import_home(
        package, target, dry_run=False, target_environment="production", confirm=True
    )
    imported_home = uuid.UUID(report["target_home_id"])
    async with SessionFactory() as db:
        categories = (
            await db.scalars(select(TodoCategory).where(TodoCategory.group_id == imported_home))
        ).all()
        nudges = (
            await db.scalars(
                select(Reminder).where(
                    Reminder.group_id == imported_home, Reminder.source_type == "driveway"
                )
            )
        ).all()
    (category,) = categories
    assert (category.name, category.managed_source) == ("Driveway", "driveway")
    assert sorted(r.source_event or "" for r in nudges) == [
        "inspection_lead_30",
        "inspection_lead_7",
    ]
    assert {r.category_id for r in nudges} == {category.id}
    assert all(r.created_by is not None for r in nudges)
