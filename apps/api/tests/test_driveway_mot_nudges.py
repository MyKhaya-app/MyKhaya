"""Driveway MOT nudges: the owner's MOT reminder plan (see
mykhaya.driveway_mot_nudges). Uses the fabricated DVSA transport from
test_driveway_mot — nothing here reaches a real provider."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_driveway_field_encryption import _body
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
from test_driveway_reminders import ORIGIN, create_verified_user, unique_email, unsafe

import mykhaya.driveway_mot as driveway_mot
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AuditEvent,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Reminder,
    Role,
    RoutineScope,
)


def _nudges_url(home_id: uuid.UUID, vehicle_id: str) -> str:
    return f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}/mot/nudges"


async def _save(client: AsyncClient, home_id: uuid.UUID, vehicle_id: str, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "title": "Book MOT – Family car",
        "due_date": _iso(335),
        "offsets": [30, 7],
        "repeat": True,
    }
    body.update(overrides)
    return await unsafe(client, "PUT", _nudges_url(home_id, vehicle_id), json=body)


async def _reminders(vehicle_id: str) -> dict[str, Reminder]:
    async with SessionFactory() as db:
        rows = (
            await db.scalars(select(Reminder).where(Reminder.source_id == uuid.UUID(vehicle_id)))
        ).all()
    return {row.source_event or "": row for row in rows}


@pytest.mark.asyncio
async def test_saving_a_plan_creates_owner_reminders_and_replaces_the_automatic_one(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    owner_id, home_id, vehicle = await _vehicle(client, "nudge-save")
    await _refresh(client, home_id, vehicle["id"])
    assert set(await _reminders(vehicle["id"])) == {"inspection"}

    response = await _save(client, home_id, vehicle["id"])
    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    assert plan["offsets"] == [30, 7] and plan["repeat"] is True
    assert plan["scheduled"] == [_iso(305), _iso(328)]

    reminders = await _reminders(vehicle["id"])
    assert set(reminders) == {"inspection_lead_30", "inspection_lead_7"}
    for reminder in reminders.values():
        assert reminder.title == "Book MOT – Family car"
        assert reminder.scope == RoutineScope.personal
        assert reminder.owner_user_id == owner_id
        assert reminder.source_type == "driveway"
    assert reminders["inspection_lead_30"].due_date == TODAY + timedelta(days=305)

    fetched = (await unsafe(client, "GET", _nudges_url(home_id, vehicle["id"]))).json()
    assert fetched["plan"] == plan

    # The reminders are ordinary Nudges reminders.
    listing = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/reminders")
    titles = [item["title"] for item in listing.json()["items"]]
    assert titles.count("Book MOT – Family car") == 2


@pytest.mark.asyncio
async def test_resaving_updates_in_place_and_drops_unchosen_days(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    _, home_id, vehicle = await _vehicle(client, "nudge-resave")
    await _save(client, home_id, vehicle["id"])
    before = await _reminders(vehicle["id"])

    response = await _save(client, home_id, vehicle["id"], offsets=[7, 0], title="MOT soon")
    assert response.status_code == 200
    after = await _reminders(vehicle["id"])
    assert set(after) == {"inspection_lead_7", "inspection_lead_0"}
    assert after["inspection_lead_7"].id == before["inspection_lead_7"].id
    assert after["inspection_lead_7"].title == "MOT soon"


@pytest.mark.asyncio
async def test_lead_days_already_in_the_past_are_skipped(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    _, home_id, vehicle = await _vehicle(client, "nudge-past")
    response = await _save(client, home_id, vehicle["id"], due_date=_iso(10), offsets=[30, 7])
    assert response.json()["plan"]["scheduled"] == [_iso(3)]
    assert set(await _reminders(vehicle["id"])) == {"inspection_lead_7"}


@pytest.mark.asyncio
async def test_a_repeating_plan_moves_on_after_the_next_pass(
    client: AsyncClient, dvsa: FakeDvsa, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driveway_mot, "FORCE_COOLDOWN", timedelta(0))
    _, home_id, vehicle = await _vehicle(client, "nudge-repeat")
    await _refresh(client, home_id, vehicle["id"])
    await _save(client, home_id, vehicle["id"])
    ids = {event: row.id for event, row in (await _reminders(vehicle["id"])).items()}

    # Same MOT again: nothing moves, and no automatic reminder comes back.
    await _refresh(client, home_id, vehicle["id"])
    assert {e: r.id for e, r in (await _reminders(vehicle["id"])).items()} == ids

    payload = history_payload()
    payload["motTests"][0]["expiryDate"] = _iso(700)
    dvsa.responses = [(200, payload)]
    await _refresh(client, home_id, vehicle["id"])
    moved = await _reminders(vehicle["id"])
    assert set(moved) == {"inspection_lead_30", "inspection_lead_7"}
    assert moved["inspection_lead_30"].id == ids["inspection_lead_30"]
    assert moved["inspection_lead_30"].due_date == TODAY + timedelta(days=670)
    assert (await _row(vehicle["id"])).mot_nudge_plan["due_date"] == _iso(700)


@pytest.mark.asyncio
async def test_a_one_off_plan_is_used_up_by_the_next_pass(
    client: AsyncClient, dvsa: FakeDvsa, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driveway_mot, "FORCE_COOLDOWN", timedelta(0))
    _, home_id, vehicle = await _vehicle(client, "nudge-once")
    await _refresh(client, home_id, vehicle["id"])
    await _save(client, home_id, vehicle["id"], repeat=False)

    payload = history_payload()
    payload["motTests"][0]["expiryDate"] = _iso(700)
    dvsa.responses = [(200, payload)]
    await _refresh(client, home_id, vehicle["id"])

    reminders = await _reminders(vehicle["id"])
    # The old nudges stay where they were; the automatic reminder resumes.
    assert reminders["inspection_lead_30"].due_date == TODAY + timedelta(days=305)
    assert reminders["inspection"].due_date == TODAY + timedelta(days=700)
    assert (await _row(vehicle["id"])).mot_nudge_plan is None
    assert (await unsafe(client, "GET", _nudges_url(home_id, vehicle["id"]))).json() == {
        "plan": None
    }


@pytest.mark.asyncio
async def test_plans_are_as_private_as_the_vehicles_reminders(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    _, home_id, vehicle = await _vehicle(client, "nudge-private")
    await _save(client, home_id, vehicle["id"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as partner:
        partner_id = await create_verified_user(partner, unique_email("nudge-p"), "Partner")
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=home_id,
                    user_id=partner_id,
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()
        url = _nudges_url(home_id, vehicle["id"])
        assert (await unsafe(partner, "GET", url)).status_code == 404
        assert (await _save(partner, home_id, vehicle["id"])).status_code == 404


@pytest.mark.asyncio
async def test_recipients_cannot_be_chosen_and_bad_input_is_refused(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    owner_id, home_id, vehicle = await _vehicle(client, "nudge-input")
    url = vehicle["id"]
    assert (await _save(client, home_id, url, recipients=[str(owner_id)])).status_code == 422
    assert (await _save(client, home_id, url, offsets=[5])).status_code == 422
    assert (await _save(client, home_id, url, offsets=[])).status_code == 422
    assert (await _save(client, home_id, url, title="   ")).status_code == 422
    assert (await _save(client, home_id, url, due_date=_iso(366 * 6))).status_code == 422

    other = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles",
        json=_body(owner_id, country_code="ZA", registration="CA 123-456", vin=None),
    )
    refused = await _save(client, home_id, other.json()["id"])
    assert refused.status_code == 409


@pytest.mark.asyncio
async def test_saving_is_audited_without_the_title_or_registration(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    _, home_id, vehicle = await _vehicle(client, "nudge-audit")
    await _save(client, home_id, vehicle["id"])
    async with SessionFactory() as db:
        event = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "driveway.vehicle.mot_nudges_saved",
                AuditEvent.group_id == home_id,
            )
        )
    assert event is not None
    assert event.metadata_ == {"offsets": [30, 7], "repeat": True}
