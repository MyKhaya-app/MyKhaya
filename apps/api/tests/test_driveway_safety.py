"""Phase 2A′ Driveway safety fixes: authorization before any vehicle row is
loaded/locked, private photo caching, VRN/VIN-free audit records, and the
read-only nickname==registration count."""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import event, select
from test_driveway_reminders import (
    ORIGIN,
    create_driveway_home,
    create_vehicle,
    create_verified_user,
    unique_email,
    unsafe,
)

from mykhaya.db import SessionFactory, engine
from mykhaya.main import app
from mykhaya.models import AuditEvent, Vehicle
from mykhaya.tools.driveway_nickname_audit import count_nickname_registration_copies

VIN = "WBA8E1C55JA000001"


@pytest.fixture
async def owner_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
async def outsider_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (40, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


async def _vehicle_lock_free(vehicle_id: str) -> bool:
    """True if nothing currently holds a row lock on the vehicle."""
    async with SessionFactory() as db:
        row = await db.scalar(
            select(Vehicle.id)
            .where(Vehicle.id == uuid.UUID(vehicle_id))
            .with_for_update(nowait=True)
        )
        await db.rollback()
        return row is not None


@pytest.mark.asyncio
async def test_outsider_gets_an_identical_404_for_real_and_missing_vehicles(
    owner_client: AsyncClient, outsider_client: AsyncClient
) -> None:
    owner_id = await create_verified_user(owner_client, unique_email("dw-owner"), "Owner")
    home_id = await create_driveway_home(owner_client, "Driveway Owner Home")
    vehicle = await create_vehicle(owner_client, home_id, owner_user_id=owner_id)

    await create_verified_user(outsider_client, unique_email("dw-outsider"), "Outsider")
    await create_driveway_home(outsider_client, "Driveway Outsider Home")

    missing = str(uuid.uuid4())
    update_body = {
        "nickname": "Taken",
        "owner_user_id": str(owner_id),
        "country_code": "GB",
        "registration": "XX11XXX",
        "expected_updated_at": vehicle["updated_at"],
    }
    for vehicle_id in (vehicle["id"], missing):
        base = f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}"
        responses = [
            await unsafe(outsider_client, "PATCH", base, json=update_body),
            await unsafe(outsider_client, "DELETE", base),
            await unsafe(outsider_client, "DELETE", f"{base}/photo"),
            await unsafe(
                outsider_client,
                "POST",
                f"{base}/photo",
                files={"file": ("car.png", _png(), "image/png")},
            ),
            await outsider_client.get(base),
            await outsider_client.get(f"{base}/photo"),
        ]
        for response in responses:
            assert response.status_code == 404, response.text
            assert response.json()["detail"] == "That Home could not be found."

    listing = await outsider_client.get(f"/api/v1/homes/{home_id}/vehicles")
    assert listing.status_code == 404
    assert listing.json()["detail"] == "That Home could not be found."

    # The real vehicle is untouched and not left locked.
    async with SessionFactory() as db:
        row = await db.get(Vehicle, uuid.UUID(vehicle["id"]))
        assert row is not None and row.archived_at is None and row.nickname == "BMW i4"
    assert await _vehicle_lock_free(vehicle["id"])


@pytest.mark.asyncio
async def test_vehicle_photo_is_served_with_private_short_lived_caching(
    owner_client: AsyncClient,
) -> None:
    owner_id = await create_verified_user(owner_client, unique_email("dw-photo"), "Owner")
    home_id = await create_driveway_home(owner_client, "Driveway Photo Home")
    vehicle = await create_vehicle(owner_client, home_id, owner_user_id=owner_id)
    base = f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/photo"

    uploaded = await unsafe(
        owner_client, "POST", base, files={"file": ("car.png", _png(), "image/png")}
    )
    assert uploaded.status_code == 200, uploaded.text
    photo = await owner_client.get(f"{base}?v={uploaded.json()['photo_version']}")
    assert photo.status_code == 200
    cache_control = photo.headers["cache-control"]
    assert cache_control == "private, max-age=300"
    assert "public" not in cache_control and "immutable" not in cache_control


@pytest.mark.asyncio
async def test_vehicle_audit_records_never_contain_registration_or_vin(
    owner_client: AsyncClient,
) -> None:
    owner_id = await create_verified_user(owner_client, unique_email("dw-audit"), "Owner")
    home_id = await create_driveway_home(owner_client, "Driveway Audit Home")
    created = await unsafe(
        owner_client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles",
        json={
            "nickname": "Family car",
            "owner_user_id": str(owner_id),
            "country_code": "GB",
            "registration": "AP22 OOJ",
            "vin": VIN,
        },
    )
    assert created.status_code == 201, created.text
    vehicle = created.json()
    updated = await unsafe(
        owner_client,
        "PATCH",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}",
        json={
            "nickname": "Family car",
            "owner_user_id": str(owner_id),
            "country_code": "GB",
            "registration": "AP22 OOK",
            "vin": VIN,
            "expected_updated_at": vehicle["updated_at"],
        },
    )
    assert updated.status_code == 200, updated.text
    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AuditEvent).where(AuditEvent.target_id == uuid.UUID(vehicle["id"]))
            )
        ).all()
    assert {event.action for event in events} >= {
        "driveway.vehicle.created",
        "driveway.vehicle.updated",
    }
    stored = json.dumps([event.metadata_ for event in events])
    for value in ("AP22", "OOJ", "OOK", VIN):
        assert value not in stored


@pytest.mark.asyncio
async def test_nickname_registration_audit_reports_counts_only(owner_client: AsyncClient) -> None:
    owner_id = await create_verified_user(owner_client, unique_email("dw-nick"), "Owner")
    home_id = await create_driveway_home(owner_client, "Driveway Nickname Home")
    before = await count_nickname_registration_copies()
    # Registration is "AP22 OOJ" (see create_vehicle); differing case and
    # spacing still counts as a copy.
    await create_vehicle(owner_client, home_id, nickname="ap22ooj", owner_user_id=owner_id)
    await create_vehicle(owner_client, home_id, nickname="BMW i4", owner_user_id=owner_id)
    after = await count_nickname_registration_copies()

    assert set(after) == {
        "vehicles_total",
        "nickname_equals_registration_active",
        "nickname_equals_registration_archived",
        "homes_affected",
    }
    assert all(isinstance(value, int) for value in after.values())
    assert after["vehicles_total"] - before["vehicles_total"] == 2
    assert (
        after["nickname_equals_registration_active"] - before["nickname_equals_registration_active"]
        == 1
    )
    assert "AP22" not in json.dumps(after)


@pytest.mark.asyncio
async def test_nickname_audit_issues_only_read_only_aggregate_selects() -> None:
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany) -> None:  # type: ignore[no-untyped-def]
        statements.append(" ".join(statement.split()).upper())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await count_nickname_registration_copies()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    app_statements = [s for s in statements if not s.startswith(("SELECT PG_", "SHOW "))]
    assert app_statements[0] == "SET TRANSACTION READ ONLY"
    assert len(app_statements) == 5
    for statement in app_statements[1:]:
        # Aggregates only — no row values (nickname/registration) are ever selected.
        assert statement.startswith("SELECT COUNT("), statement
        assert not any(word in statement for word in ("INSERT", "UPDATE", "DELETE"))
    assert all(isinstance(value, int) for value in result.values())
