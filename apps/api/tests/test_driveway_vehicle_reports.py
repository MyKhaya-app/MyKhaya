"""Vehicle Report endpoints: authorisation, HMAC lookup tokens, the approved
30-per-user-per-hour download budget, household-detail opt-out and the
server-side email kill switch. Database- and Redis-backed."""

from __future__ import annotations

import base64
import io
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select
from test_driveway_reminders import (
    ORIGIN,
    create_driveway_home,
    create_vehicle,
    create_verified_user,
    unique_email,
    unsafe,
)

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.driveway_schemas import VehicleLookupResult
from mykhaya.main import app
from mykhaya.models import AuditEvent, NotificationDelivery
from mykhaya.routers import driveway as driveway_router


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
async def outsider() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


class RenderSpy:
    """Stands in for the WeasyPrint renderer where only routing is under test."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> bytes:
        self.calls.append(kwargs)
        return b"%PDF-1.7 stub"


@pytest.fixture
def render_spy(monkeypatch: pytest.MonkeyPatch) -> RenderSpy:
    spy = RenderSpy()
    monkeypatch.setattr(driveway_router, "render_vehicle_report_pdf", spy)
    return spy


async def _home_with_vehicle(client: AsyncClient, prefix: str) -> tuple[uuid.UUID, uuid.UUID, str]:
    user_id = await create_verified_user(client, unique_email(prefix), "Report Owner")
    home_id = await create_driveway_home(client, "Report Home")
    vehicle = await create_vehicle(client, home_id, nickname="Pebble")
    return user_id, home_id, vehicle["id"]


def _lookup_token(home_id: uuid.UUID, user_id: uuid.UUID) -> str:
    result = VehicleLookupResult(found=True, registration="LB19 NEW", make="VAUXHALL")
    return driveway_router._sign_lookup_report(result, home_id, user_id, get_settings())


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (40, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_saved_report_renders_a_real_pdf_and_is_audited(client: AsyncClient) -> None:
    _, home_id, vehicle_id = await _home_with_vehicle(client, "dw-report-real")
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}/report/pdf",
        json={"format": "essential"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content_type"] == "application/pdf"
    assert base64.b64decode(body["pdf_base64"]).startswith(b"%PDF-")
    assert body["filename"].startswith("MyKhaya-Vehicle-Report-AP22-OOJ-")
    async with SessionFactory() as db:
        event = await db.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "driveway.vehicle.report.generated")
            .where(AuditEvent.group_id == home_id)
        )
    assert event is not None
    assert event.metadata_ == {"format": "essential", "household_details": True}


async def test_outsider_cannot_download_another_homes_report(
    client: AsyncClient, outsider: AsyncClient, render_spy: RenderSpy
) -> None:
    owner_id, home_id, vehicle_id = await _home_with_vehicle(client, "dw-report-owner")
    await create_verified_user(outsider, unique_email("dw-report-outsider"), "Outsider")
    await create_driveway_home(outsider, "Outsider Home")
    saved = await unsafe(
        outsider,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}/report/pdf",
        json={"format": "full"},
    )
    lookup = await unsafe(
        outsider,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/lookup/report/pdf",
        json={"format": "full", "report_token": _lookup_token(home_id, owner_id)},
    )
    assert saved.status_code in {403, 404}
    assert lookup.status_code in {403, 404}
    assert render_spy.calls == []


async def test_lookup_report_token_is_bound_and_tamper_proof(
    client: AsyncClient, render_spy: RenderSpy
) -> None:
    user_id, home_id, _ = await _home_with_vehicle(client, "dw-report-token")
    url = f"/api/v1/homes/{home_id}/vehicles/lookup/report/pdf"
    good = _lookup_token(home_id, user_id)
    ok = await unsafe(client, "POST", url, json={"format": "full", "report_token": good})
    assert ok.status_code == 200, ok.text
    assert render_spy.calls[-1]["source"] == "lookup"
    assert "photo" not in render_spy.calls[-1]
    tampered = good[:-4] + ("0000" if not good.endswith("0000") else "1111")
    other_user = _lookup_token(home_id, uuid.uuid4())
    for token in (tampered, other_user):
        response = await unsafe(client, "POST", url, json={"format": "full", "report_token": token})
        assert response.status_code == 410
    assert len(render_spy.calls) == 1


async def test_household_details_toggle_controls_nickname_and_photo(
    client: AsyncClient, render_spy: RenderSpy
) -> None:
    _, home_id, vehicle_id = await _home_with_vehicle(client, "dw-report-household")
    upload = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}/photo",
        files={"file": ("car.png", _png(), "image/png")},
    )
    assert upload.status_code == 200, upload.text
    url = f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}/report/pdf"

    assert (await unsafe(client, "POST", url, json={"format": "full"})).status_code == 200
    included = render_spy.calls[-1]
    assert included["include_household_details"] is True
    assert included["photo"]  # stored photo bytes, loaded after authorisation
    assert included["vehicle"]["nickname"] == "Pebble"

    shared = await unsafe(
        client, "POST", url, json={"format": "full", "include_household_details": False}
    )
    assert shared.status_code == 200
    excluded = render_spy.calls[-1]
    assert excluded["include_household_details"] is False
    assert excluded["photo"] is None  # never even read from storage


async def test_download_budget_is_30_per_user_across_services_formats_and_networks(
    client: AsyncClient, render_spy: RenderSpy
) -> None:
    user_id, home_id, vehicle_id = await _home_with_vehicle(client, "dw-report-limit")
    saved_url = f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}/report/pdf"
    lookup_url = f"/api/v1/homes/{home_id}/vehicles/lookup/report/pdf"
    token = _lookup_token(home_id, user_id)
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("198.51.100.7", 40000)),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
        cookies=client.cookies,
    ) as other_network:
        for index in range(30):
            sender = client if index % 2 else other_network
            fmt = "full" if index % 3 else "essential"
            if index % 4:
                response = await unsafe(sender, "POST", saved_url, json={"format": fmt})
            else:
                response = await unsafe(
                    sender, "POST", lookup_url, json={"format": fmt, "report_token": token}
                )
            assert response.status_code == 200, (index, response.text)
        blocked_saved = await unsafe(client, "POST", saved_url, json={"format": "full"})
        blocked_lookup = await unsafe(
            other_network, "POST", lookup_url, json={"format": "essential", "report_token": token}
        )
    assert blocked_saved.status_code == 429
    assert blocked_lookup.status_code == 429
    assert len(render_spy.calls) == 30


async def test_report_email_is_switched_off_server_side(
    client: AsyncClient, render_spy: RenderSpy
) -> None:
    assert get_settings().vehicle_report_email_enabled is False
    user_id, home_id, vehicle_id = await _home_with_vehicle(client, "dw-report-email-off")
    saved = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}/report/email",
        json={"format": "full"},
    )
    lookup = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/lookup/report/email",
        json={"format": "full", "report_token": _lookup_token(home_id, user_id)},
    )
    assert saved.status_code == 403 and lookup.status_code == 403
    assert render_spy.calls == []  # nothing is rendered for a refused email
    async with SessionFactory() as db:
        deliveries = await db.scalar(
            select(NotificationDelivery.id).where(
                NotificationDelivery.idempotency_key.like(f"driveway-vehicle-report:{user_id}:%")
            )
        )
    assert deliveries is None


async def test_email_limit_is_checked_before_rendering_when_enabled(
    client: AsyncClient, render_spy: RenderSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "vehicle_report_email_enabled", True)
    queued: list[dict[str, Any]] = []

    async def fake_queue(**kwargs: Any) -> None:  # no real notification is sent
        queued.append(kwargs)

    monkeypatch.setattr(driveway_router, "_queue_vehicle_report_email", fake_queue)
    _, home_id, vehicle_id = await _home_with_vehicle(client, "dw-report-email-limit")
    url = f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}/report/email"
    statuses = [
        (await unsafe(client, "POST", url, json={"format": "essential"})).status_code
        for _ in range(4)
    ]
    assert statuses == [202, 202, 202, 429]
    assert len(render_spy.calls) == 3 and len(queued) == 3


async def test_release_switches_fail_closed_by_default() -> None:
    """DEV needs no extra configuration: absent settings mean email is off and
    arbitrary DVSA lookup is off."""
    from mykhaya.config import Settings

    defaults = Settings.model_fields
    assert defaults["vehicle_report_email_enabled"].default is False
    assert defaults["dvsa_arbitrary_lookup_enabled"].default is False
    assert get_settings().vehicle_report_email_enabled is False
    assert get_settings().dvsa_arbitrary_lookup_enabled is False


async def test_missing_brand_assets_fail_closed_with_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from mykhaya import vehicle_report_pdf

    monkeypatch.setattr(get_settings(), "vehicle_report_assets_dir", str(tmp_path / "none"))
    monkeypatch.setattr(vehicle_report_pdf, "_IMAGE_ASSETS_DIR", tmp_path / "none")
    monkeypatch.setattr(vehicle_report_pdf, "_REPO_PUBLIC_DIR", tmp_path / "none")
    _, home_id, vehicle_id = await _home_with_vehicle(client, "dw-report-no-assets")
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}/report/pdf",
        json={"format": "essential"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Vehicle Reports are temporarily unavailable."
