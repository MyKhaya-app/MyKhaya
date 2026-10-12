"""Driveway MOT Phase 1 (DVSA MOT History API).

No test reaches the real DVSA or Microsoft Entra ID: every provider call goes
through an httpx.MockTransport that imitates the documented token endpoint
and the ``GET /v1/trade/vehicles/registration/{VRM}`` API. All credentials,
registrations and MOT data here are fabricated test values.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from structlog.testing import capture_logs
from test_driveway_field_encryption import KEYRING, _body, _home
from test_driveway_reminders import ORIGIN, unsafe

import mykhaya.driveway_mot as driveway_mot
import mykhaya.driveway_mot_provider as provider_module
import mykhaya.driveway_sensitive as driveway_sensitive
from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.driveway_mot_provider import (
    DvsaMotHistoryProvider,
    MotAuthFailed,
    MotHistory,
    MotMalformedResponse,
    MotNotConfigured,
    MotRateLimited,
    MotTestRecord,
    MotUnavailable,
    MotVehicleNotFound,
    normalise_mot_response,
)
from mykhaya.main import app
from mykhaya.models import AuditEvent, PlatformSetting, Reminder, Vehicle, VehicleMotTest

TOKEN_URL = "https://login.microsoftonline.com/00000000-test-tenant/oauth2/v2.0/token"
CLIENT_ID = "fake-client-id-0001"
CLIENT_SECRET = "fake-client-secret-DO-NOT-LEAK-0001"
API_KEY = "fake-api-key-DO-NOT-LEAK-0001"
ACCESS_TOKEN = "fake-access-token-DO-NOT-LEAK-0001"
REGISTRATION = "AB12 CDE"
VRM = "AB12CDE"
TODAY = datetime.now(UTC).date()


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def history_payload(**overrides: Any) -> dict[str, Any]:
    """A fabricated DVSA-shaped response: a current pass with an advisory,
    an earlier fail with defects, and an older pass."""
    payload: dict[str, Any] = {
        "registration": VRM,
        "make": "TESTMAKE",
        "model": "TESTMODEL",
        "firstUsedDate": "2018-03-01",
        "fuelType": "Petrol",
        "primaryColour": "Blue",
        "motTests": [
            {
                "completedDate": f"{_iso(-30)}T10:15:00.000Z",
                "testResult": "PASSED",
                "expiryDate": _iso(335),
                "odometerValue": "45210",
                "odometerUnit": "MI",
                "odometerResultType": "READ",
                "motTestNumber": "123456789012",
                "dataSource": "DVSA",
                "defects": [
                    {
                        "text": "Nearside front tyre worn close to legal limit",
                        "type": "ADVISORY",
                        "dangerous": False,
                    }
                ],
            },
            {
                "completedDate": f"{_iso(-32)} 09:00:00",
                "testResult": "FAILED",
                "odometerValue": "45198",
                "odometerUnit": "mi",
                "odometerResultType": "READ",
                "motTestNumber": "123456789011",
                "defects": [
                    {"text": "Offside headlamp aim too high", "type": "MAJOR", "dangerous": False},
                    {
                        "text": "Brake pipe excessively corroded",
                        "type": "DANGEROUS",
                        "dangerous": True,
                    },
                    {"text": "Wiper blade deteriorated", "type": "MINOR", "dangerous": False},
                ],
            },
            {
                "completedDate": "2024.03.01 11:41:11",
                "testResult": "PASSED",
                "expiryDate": "2025.03.10",
                "odometerValue": "30001",
                "odometerUnit": "km",
                "odometerResultType": "READ",
                "motTestNumber": 987654321098,
                "defects": [],
            },
        ],
    }
    payload.update(overrides)
    return payload


class FakeDvsa:
    """A scripted DVSA + Entra ID. ``responses`` is a queue of
    (status, json-or-text) for the vehicle endpoint; when it runs out the
    last entry repeats."""

    def __init__(self) -> None:
        self.responses: list[tuple[int, Any]] = [(200, history_payload())]
        self.token_status = 200
        self.token_calls = 0
        self.api_calls: list[httpx.Request] = []
        self.raise_timeout = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            self.token_calls += 1
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            assert form["grant_type"] == "client_credentials"
            assert form["scope"].startswith("https%3A%2F%2Ftapi.dvsa.gov.uk")
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_client"})
            return httpx.Response(
                200, json={"token_type": "Bearer", "expires_in": 3599, "access_token": ACCESS_TOKEN}
            )
        self.api_calls.append(request)
        if self.raise_timeout:
            self.raise_timeout -= 1
            raise httpx.ReadTimeout("simulated timeout", request=request)
        status, body = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    def provider(self, settings: Settings) -> DvsaMotHistoryProvider:
        async def no_sleep(_: float) -> None:
            return None

        return DvsaMotHistoryProvider(
            settings, transport=httpx.MockTransport(self.handler), sleep=no_sleep
        )


def dvsa_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "dvsa_enabled": True,
        "dvsa_environment": "development",
        "dvsa_token_url": TOKEN_URL,
        "dvsa_client_id": SecretStr(CLIENT_ID),
        "dvsa_client_secret": SecretStr(CLIENT_SECRET),
        "dvsa_api_key": SecretStr(API_KEY),
    }
    values.update(overrides)
    return get_settings().model_copy(update=values)


@pytest.fixture(autouse=True)
def _fresh_token_cache() -> Iterator[None]:
    provider_module.reset_token_cache()
    yield
    provider_module.reset_token_cache()


# =====================================================================================
# Provider unit tests (no database)
# =====================================================================================


@pytest.mark.asyncio
async def test_successful_lookup_is_normalised_and_authenticated_correctly() -> None:
    fake = FakeDvsa()
    history = await fake.provider(dvsa_settings()).fetch(REGISTRATION)
    request = fake.api_calls[0]
    assert (
        str(request.url) == f"https://history.mot.api.gov.uk/v1/trade/vehicles/registration/{VRM}"
    )
    assert request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert request.headers["X-API-Key"] == API_KEY

    assert [t.result for t in history.tests] == ["passed", "failed", "passed"]
    latest, failed, oldest = history.tests
    assert latest.test_number == "123456789012" and latest.expiry_date == TODAY + timedelta(
        days=335
    )
    assert (latest.odometer_value, latest.odometer_unit, latest.odometer_result) == (
        45210,
        "mi",
        "read",
    )
    assert [d.category for d in latest.defects] == ["advisory"]
    assert {(d.category, d.dangerous) for d in failed.defects} == {
        ("major", False),
        ("dangerous", True),
        ("minor", False),
    }
    assert (oldest.test_number, oldest.odometer_unit, oldest.expiry_date) == (
        "987654321098",
        "km",
        date(2025, 3, 10),
    )
    assert oldest.test_date == date(2024, 3, 1)


@pytest.mark.asyncio
async def test_token_is_cached_across_lookups() -> None:
    fake = FakeDvsa()
    provider = fake.provider(dvsa_settings())
    await provider.fetch(REGISTRATION)
    await provider.fetch(REGISTRATION)
    assert fake.token_calls == 1 and len(fake.api_calls) == 2


@pytest.mark.asyncio
async def test_first_mot_not_yet_due_vehicle() -> None:
    fake = FakeDvsa()
    fake.responses = [(200, {"registration": VRM, "motTestDueDate": _iso(400)})]
    history = await fake.provider(dvsa_settings()).fetch(REGISTRATION)
    assert history.tests == () and history.first_mot_due_date == TODAY + timedelta(days=400)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (404, {"errorCode": "MOTH-NF-01", "errorMessage": "not found"}, MotVehicleNotFound),
        (400, {"errorCode": "MOTH-IV-03", "errorMessage": "invalid VRM"}, MotVehicleNotFound),
        (429, {"errorCode": "MOTH-RL-02", "errorMessage": "slow down"}, MotRateLimited),
        (403, {"errorCode": "MOTH-FB-03", "errorMessage": "bad key"}, MotAuthFailed),
        (200, "<html>not json</html>", MotMalformedResponse),
        (200, {"motTests": "nope"}, MotMalformedResponse),
        (200, {"motTests": [{"testResult": "PASSED"}]}, MotMalformedResponse),
        (400, {"errorCode": "MOTH-BR-01"}, MotUnavailable),
    ],
)
async def test_provider_errors_are_translated(status: int, body: Any, error: type) -> None:
    fake = FakeDvsa()
    fake.responses = [(status, body)]
    with pytest.raises(error):
        await fake.provider(dvsa_settings()).fetch(REGISTRATION)
    if error is MotRateLimited:
        assert len(fake.api_calls) == 1  # never retried


@pytest.mark.asyncio
async def test_token_endpoint_rejection_is_an_auth_failure() -> None:
    fake = FakeDvsa()
    fake.token_status = 401
    with pytest.raises(MotAuthFailed):
        await fake.provider(dvsa_settings()).fetch(REGISTRATION)
    assert fake.api_calls == []


@pytest.mark.asyncio
async def test_expired_token_is_refreshed_exactly_once() -> None:
    fake = FakeDvsa()
    fake.responses = [(401, {"errorCode": "MOTH-FB-02"}), (200, history_payload())]
    history = await fake.provider(dvsa_settings()).fetch(REGISTRATION)
    assert len(history.tests) == 3 and fake.token_calls == 2 and len(fake.api_calls) == 2


@pytest.mark.asyncio
async def test_transient_timeout_and_5xx_are_retried_once_then_fail() -> None:
    fake = FakeDvsa()
    fake.raise_timeout = 1
    assert len((await fake.provider(dvsa_settings()).fetch(REGISTRATION)).tests) == 3
    assert len(fake.api_calls) == 2

    fake = FakeDvsa()
    fake.raise_timeout = 5
    with pytest.raises(MotUnavailable):
        await fake.provider(dvsa_settings()).fetch(REGISTRATION)
    assert len(fake.api_calls) == 2

    fake = FakeDvsa()
    fake.responses = [(503, {"errorCode": "MOTH-UN-01"}), (503, {"errorCode": "MOTH-UN-01"})]
    with pytest.raises(MotUnavailable):
        await fake.provider(dvsa_settings()).fetch(REGISTRATION)
    assert len(fake.api_calls) == 2


@pytest.mark.asyncio
async def test_invalid_registration_never_reaches_the_network() -> None:
    fake = FakeDvsa()
    with pytest.raises(MotVehicleNotFound):
        await fake.provider(dvsa_settings()).fetch("AB12/../CDE")
    assert fake.api_calls == [] and fake.token_calls == 0


@pytest.mark.asyncio
async def test_errors_and_repr_never_contain_credentials_or_registration() -> None:
    fake = FakeDvsa()
    fake.token_status = 401
    provider = fake.provider(dvsa_settings())
    with pytest.raises(MotAuthFailed) as raised:
        await provider.fetch(REGISTRATION)
    rendered = repr(provider) + str(raised.value) + repr(raised.value)
    for secret in (CLIENT_ID, CLIENT_SECRET, API_KEY, ACCESS_TOKEN, VRM, REGISTRATION):
        assert secret not in rendered


def test_provider_refuses_to_build_without_full_configuration() -> None:
    with pytest.raises(MotNotConfigured):
        DvsaMotHistoryProvider(dvsa_settings(dvsa_api_key=None))


def test_settings_only_send_credentials_to_expected_https_hosts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MYKHAYA_DVSA_TOKEN_URL", "https://evil.example.com/token")
    with pytest.raises(ValidationError, match="DVSA_TOKEN_URL"):
        Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.setenv("MYKHAYA_DVSA_TOKEN_URL", TOKEN_URL)
    monkeypatch.setenv("MYKHAYA_DVSA_API_BASE_URL", "http://history.mot.api.gov.uk/v1")
    with pytest.raises(ValidationError, match="DVSA_API_BASE_URL"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_dvsa_defaults_are_disabled_and_unconfigured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for key in ("MYKHAYA_DVSA_TOKEN_URL", "MYKHAYA_DVSA_CLIENT_ID", "MYKHAYA_DVSA_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.dvsa_enabled is False and settings.dvsa_configured is False


# --- Status computation ----------------------------------------------------------------


def _test(result: str, days_ago: int, expiry_in: int | None) -> MotTestRecord:
    return MotTestRecord(
        test_number=str(uuid.uuid4().int)[:12],
        completed_at=None,
        test_date=TODAY - timedelta(days=days_ago),
        expiry_date=None if expiry_in is None else TODAY + timedelta(days=expiry_in),
        result=result,
        odometer_value=None,
        odometer_unit=None,
        odometer_result=None,
    )


@pytest.mark.parametrize(
    ("history", "status", "due_offset"),
    [
        (MotHistory(tests=(_test("passed", 10, 355),)), "valid", 355),
        (MotHistory(tests=(_test("passed", 400, -35),)), "expired", -35),
        # A later fail does not cancel the unexpired certificate's dates.
        (MotHistory(tests=(_test("failed", 5, None), _test("passed", 200, 165))), "valid", 165),
        (MotHistory(tests=(), first_mot_due_date=TODAY + timedelta(days=90)), "not_yet_due", 90),
        (MotHistory(tests=(), first_mot_due_date=TODAY - timedelta(days=3)), "expired", -3),
        (MotHistory(tests=(_test("failed", 5, None),)), "expired", None),
        (MotHistory(tests=()), "no_record", None),
    ],
)
def test_compute_summary(history: MotHistory, status: str, due_offset: int | None) -> None:
    summary = driveway_mot.compute_summary(history, today=TODAY)
    assert summary.status == status
    assert summary.due_date == (None if due_offset is None else TODAY + timedelta(days=due_offset))


def test_normaliser_drops_duplicate_test_numbers_and_sorts_newest_first() -> None:
    payload = history_payload()
    payload["motTests"].append(dict(payload["motTests"][0]))
    history = normalise_mot_response(payload)
    numbers = [t.test_number for t in history.tests]
    assert len(numbers) == len(set(numbers)) == 3
    assert history.tests[0].test_date >= history.tests[-1].test_date


# =====================================================================================
# API tests (real router, service, database, Redis lock and reminders)
# =====================================================================================


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


async def _set_platform_toggle(enabled: bool | None) -> Any:
    async with SessionFactory() as db:
        row = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == driveway_mot.DVSA_SETTING_KEY)
        )
        previous = dict(row.value) if row else None
        if enabled is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(PlatformSetting(key=driveway_mot.DVSA_SETTING_KEY, value={"value": enabled}))
        else:
            row.value = {**row.value, "value": enabled}
        await db.commit()
        return previous


@pytest.fixture
async def dvsa(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeDvsa]:
    """DVSA enabled + configured + PCC toggle on, with the fake transport."""
    fake = FakeDvsa()
    settings = dvsa_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(driveway_mot, "build_provider", fake.provider)
    monkeypatch.setattr(driveway_sensitive, "get_field_keyring", lambda: KEYRING)
    previous = await _set_platform_toggle(True)
    yield fake
    app.dependency_overrides.pop(get_settings, None)
    async with SessionFactory() as db:
        row = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == driveway_mot.DVSA_SETTING_KEY)
        )
        if previous is None and row is not None:
            await db.delete(row)
        elif row is not None:
            row.value = previous
        await db.commit()


async def _vehicle(
    client: AsyncClient, prefix: str, **overrides: Any
) -> tuple[uuid.UUID, uuid.UUID, dict]:
    owner_id, home_id = await _home(client, prefix)
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles",
        json=_body(owner_id, registration=REGISTRATION, vin=None, **overrides),
    )
    assert response.status_code == 201, response.text
    return owner_id, home_id, response.json()


def _mot_url(home_id: uuid.UUID, vehicle_id: str) -> str:
    return f"/api/v1/homes/{home_id}/vehicles/{vehicle_id}/mot"


async def _refresh(
    client: AsyncClient, home_id: uuid.UUID, vehicle_id: str, mode: str = "force"
) -> Any:
    return await unsafe(
        client, "POST", f"{_mot_url(home_id, vehicle_id)}/refresh", json={"mode": mode}
    )


async def _row(vehicle_id: str) -> Vehicle:
    async with SessionFactory() as db:
        row = await db.get(Vehicle, uuid.UUID(vehicle_id))
        assert row is not None
        return row


async def _test_count(vehicle_id: str) -> int:
    async with SessionFactory() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(VehicleMotTest)
                .where(VehicleMotTest.vehicle_id == uuid.UUID(vehicle_id))
            )
            or 0
        )


async def _mot_reminders(vehicle_id: str) -> list[Reminder]:
    async with SessionFactory() as db:
        return list(
            (
                await db.scalars(
                    select(Reminder).where(
                        Reminder.source_id == uuid.UUID(vehicle_id),
                        Reminder.source_event == "inspection",
                    )
                )
            ).all()
        )


RAW_DVSA_KEYS = (
    "motTests",
    "testResult",
    "odometerValue",
    "completedDate",
    "motTestNumber",
    "dataSource",
)


@pytest.mark.asyncio
async def test_successful_refresh_persists_and_returns_normalised_data_only(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    _, home_id, vehicle = await _vehicle(client, "mot-ok")
    before = await client.get(_mot_url(home_id, vehicle["id"]))
    assert before.status_code == 200
    assert before.json()["summary"]["status"] is None and before.json()["tests"] == []
    assert dvsa.api_calls == []  # viewing never calls the provider

    response = await _refresh(client, home_id, vehicle["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["refresh"] == {"outcome": "refreshed", "message": None}
    summary = body["summary"]
    assert summary["status"] == "valid" and summary["source"] == "dvsa"
    assert summary["expiry_date"] == _iso(335) and summary["due_date"] == _iso(335)
    assert summary["last_result"] == "passed" and summary["stale"] is False
    assert [t["result"] for t in body["tests"]] == ["passed", "failed", "passed"]
    first = body["tests"][0]
    assert (first["odometer_value"], first["odometer_unit"], first["test_number"]) == (
        45210,
        "mi",
        "123456789012",
    )
    assert body["tests"][1]["defects"][1] == {
        "text": "Brake pipe excessively corroded",
        "category": "dangerous",
        "dangerous": True,
    }
    text = response.text
    for raw in RAW_DVSA_KEYS:
        assert raw not in text
    assert REGISTRATION not in text and VRM not in text and "TESTMAKE" not in text

    row = await _row(vehicle["id"])
    assert row.inspection_status == "valid" and row.inspection_due_date == TODAY + timedelta(
        days=335
    )
    detail = await client.get(f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}")
    assert detail.json()["inspection_status"] == "valid"


@pytest.mark.asyncio
async def test_expired_mot(client: AsyncClient, dvsa: FakeDvsa) -> None:
    payload = history_payload()
    payload["motTests"] = [payload["motTests"][2]]  # only the 2025 pass
    dvsa.responses = [(200, payload)]
    _, home_id, vehicle = await _vehicle(client, "mot-expired")
    body = (await _refresh(client, home_id, vehicle["id"])).json()
    assert body["summary"]["status"] == "expired" and body["summary"]["due_date"] == "2025-03-10"


@pytest.mark.asyncio
async def test_first_mot_not_yet_due_and_its_reminder(client: AsyncClient, dvsa: FakeDvsa) -> None:
    dvsa.responses = [(200, {"registration": VRM, "motTestDueDate": _iso(400)})]
    _, home_id, vehicle = await _vehicle(client, "mot-new")
    body = (await _refresh(client, home_id, vehicle["id"])).json()
    assert body["summary"]["status"] == "not_yet_due"
    assert body["summary"]["first_mot_due_date"] == _iso(400) and body["tests"] == []
    (reminder,) = await _mot_reminders(vehicle["id"])
    assert reminder.title == "First MOT due" and reminder.due_date == TODAY + timedelta(days=400)


@pytest.mark.asyncio
async def test_repeated_refresh_never_duplicates_history_or_reminders(
    client: AsyncClient, dvsa: FakeDvsa, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driveway_mot, "FORCE_COOLDOWN", timedelta(0))
    _, home_id, vehicle = await _vehicle(client, "mot-idem")
    for _ in range(3):
        assert (await _refresh(client, home_id, vehicle["id"])).status_code == 200
    assert await _test_count(vehicle["id"]) == 3
    reminders = await _mot_reminders(vehicle["id"])
    assert len(reminders) == 1 and reminders[0].title == "MOT due"
    reminder_id = reminders[0].id

    # The MOT date changes: the SAME managed reminder moves, no new one.
    payload = history_payload()
    payload["motTests"][0]["expiryDate"] = _iso(500)
    dvsa.responses = [(200, payload)]
    await _refresh(client, home_id, vehicle["id"])
    (moved,) = await _mot_reminders(vehicle["id"])
    assert moved.id == reminder_id and moved.due_date == TODAY + timedelta(days=500)
    assert await _test_count(vehicle["id"]) == 3


@pytest.mark.asyncio
async def test_force_cooldown_and_if_stale_avoid_provider_calls(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    _, home_id, vehicle = await _vehicle(client, "mot-cache")
    await _refresh(client, home_id, vehicle["id"])
    assert len(dvsa.api_calls) == 1
    again = await _refresh(client, home_id, vehicle["id"])  # within the cooldown
    stale_check = await _refresh(client, home_id, vehicle["id"], mode="if_stale")
    assert again.json()["refresh"]["outcome"] == "cached"
    assert stale_check.json()["refresh"]["outcome"] == "cached"
    assert len(dvsa.api_calls) == 1


@pytest.mark.asyncio
async def test_not_found_clears_history_and_says_so(
    client: AsyncClient, dvsa: FakeDvsa, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driveway_mot, "FORCE_COOLDOWN", timedelta(0))
    _, home_id, vehicle = await _vehicle(client, "mot-404")
    await _refresh(client, home_id, vehicle["id"])
    dvsa.responses = [(404, {"errorCode": "MOTH-NF-01"})]
    body = (await _refresh(client, home_id, vehicle["id"])).json()
    assert body["refresh"]["outcome"] == "not_found"
    assert body["refresh"]["message"] == "We couldn't find an MOT record for this registration."
    assert body["summary"]["status"] == "no_record" and body["tests"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "outcome"),
    [
        (503, {"errorCode": "MOTH-UN-01"}, "unavailable"),
        (429, {"errorCode": "MOTH-RL-01"}, "rate_limited"),
        (403, {"errorCode": "MOTH-FB-03"}, "auth_failed"),
        (200, {"motTests": 7}, "malformed"),
    ],
)
async def test_provider_failure_keeps_cached_data_and_records_health(
    client: AsyncClient,
    dvsa: FakeDvsa,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    body: Any,
    outcome: str,
) -> None:
    monkeypatch.setattr(driveway_mot, "FORCE_COOLDOWN", timedelta(0))
    _, home_id, vehicle = await _vehicle(client, f"mot-fail-{outcome.replace('_', '-')}")
    await _refresh(client, home_id, vehicle["id"])
    dvsa.responses = [(status, body)]
    response = await _refresh(client, home_id, vehicle["id"])
    assert response.status_code == 200
    data = response.json()
    assert data["refresh"]["outcome"] == outcome and data["refresh"]["message"]
    assert data["summary"]["status"] == "valid" and len(data["tests"]) == 3  # untouched
    assert data["summary"]["last_attempt_outcome"] == outcome
    async with SessionFactory() as db:
        setting = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == driveway_mot.DVSA_SETTING_KEY)
        )
    assert setting is not None
    assert setting.value["health"]["last_failure_category"] == outcome


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("deployment_enabled", "configured", "platform_toggle"),
    [(False, True, True), (True, False, True), (True, True, False)],
)
async def test_disabled_or_unconfigured_provider_refuses_without_calling(
    client: AsyncClient,
    dvsa: FakeDvsa,
    deployment_enabled: bool,
    configured: bool,
    platform_toggle: bool,
) -> None:
    settings = dvsa_settings(
        dvsa_enabled=deployment_enabled,
        **({} if configured else {"dvsa_client_secret": None}),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    await _set_platform_toggle(platform_toggle)
    _, home_id, vehicle = await _vehicle(client, "mot-disabled")
    response = await _refresh(client, home_id, vehicle["id"])
    assert response.status_code == 503
    assert response.json()["detail"] == "MOT checks aren't available right now."
    view = (await client.get(_mot_url(home_id, vehicle["id"]))).json()
    assert view["provider_available"] is False
    assert dvsa.api_calls == [] and dvsa.token_calls == 0


@pytest.mark.asyncio
async def test_non_gb_vehicle_and_missing_registration_are_refused(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    owner_id, home_id = await _home(client, "mot-za")
    za = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles",
        json=_body(owner_id, country_code="ZA", registration="CA 123-456", vin=None),
    )
    no_reg = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles",
        json=_body(owner_id, registration=None, vin=None),
    )
    za_refresh = await _refresh(client, home_id, za.json()["id"])
    assert za_refresh.status_code == 409 and "UK" in za_refresh.json()["detail"]
    assert (await client.get(_mot_url(home_id, za.json()["id"]))).json()["eligible"] is False
    missing = await _refresh(client, home_id, no_reg.json()["id"])
    assert missing.status_code == 409 and "registration" in missing.json()["detail"]
    assert dvsa.api_calls == []


@pytest.mark.asyncio
async def test_outsider_cannot_read_or_refresh_mot(client: AsyncClient, dvsa: FakeDvsa) -> None:
    _, home_id, vehicle = await _vehicle(client, "mot-owner")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as outsider:
        await _home(outsider, "mot-outsider")
        assert (await outsider.get(_mot_url(home_id, vehicle["id"]))).status_code == 404
        assert (await _refresh(outsider, home_id, vehicle["id"])).status_code == 404
    assert dvsa.api_calls == []


@pytest.mark.asyncio
async def test_provider_receives_the_ciphertext_first_registration(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    """With Phase 2D reads on and plaintext deliberately disagreeing, the
    provider still receives the ciphertext's (authoritative) registration —
    proof the lookup goes through registration_for_provider."""
    settings = dvsa_settings(
        driveway_field_encryption_write=True, driveway_field_encryption_read=True
    )
    app.dependency_overrides[get_settings] = lambda: settings
    _, home_id, vehicle = await _vehicle(client, "mot-cipher")
    async with SessionFactory() as db:
        row = await db.get(Vehicle, uuid.UUID(vehicle["id"]))
        assert row is not None and row.registration_ciphertext
        row.registration = "ZZ99 ZZZ"  # plaintext tampered; ciphertext still AB12 CDE
        await db.commit()
    await _refresh(client, home_id, vehicle["id"])
    assert dvsa.api_calls[0].url.path.endswith(f"/registration/{VRM}")


def test_mot_code_never_reads_the_registration_column_directly() -> None:
    root = Path(__file__).resolve().parents[1] / "mykhaya"
    for name in ("driveway_mot.py", "driveway_mot_provider.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert not re.search(r"\.registration\b(?!_)", source), name
        assert not re.search(r"\.vin\b(?!_)", source), name
    assert "registration_for_provider(" in (root / "driveway_mot.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_registration_and_credentials_never_reach_logs_or_audit(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    _, home_id, vehicle = await _vehicle(client, "mot-logs")
    with capture_logs() as logs:
        await _refresh(client, home_id, vehicle["id"])
    rendered = json.dumps(logs, default=str)
    for secret in (
        REGISTRATION,
        VRM,
        CLIENT_ID,
        CLIENT_SECRET,
        API_KEY,
        ACCESS_TOKEN,
        "Brake pipe",
    ):
        assert secret not in rendered
    refresh_logs = [e for e in logs if e.get("event") == "driveway.dvsa.mot_refresh"]
    assert refresh_logs and refresh_logs[0]["outcome"] == "success"
    assert refresh_logs[0]["test_count"] == 3 and "duration_ms" in refresh_logs[0]
    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.target_id == uuid.UUID(vehicle["id"]),
                    AuditEvent.action == "driveway.vehicle.mot_refreshed",
                )
            )
        ).all()
    assert len(events) == 1
    assert events[0].metadata_ == {"outcome": "success", "test_count": 3, "mode": "force"}


@pytest.mark.asyncio
async def test_persistence_failure_rolls_everything_back(
    client: AsyncClient, dvsa: FakeDvsa, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driveway_mot, "FORCE_COOLDOWN", timedelta(0))
    _, home_id, vehicle = await _vehicle(client, "mot-rollback")
    await _refresh(client, home_id, vehicle["id"])
    before = await _row(vehicle["id"])
    real_replace = driveway_mot._replace_history

    async def explode(db: Any, row: Any, history: Any) -> None:
        await real_replace(db, row, history)  # delete + insert, then fail
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(driveway_mot, "_replace_history", explode)
    payload = history_payload()
    payload["motTests"] = payload["motTests"][:1]
    dvsa.responses = [(200, payload)]
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
        cookies=client.cookies,
    ) as quiet:
        failed = await _refresh(quiet, home_id, vehicle["id"])
    assert failed.status_code == 500
    after = await _row(vehicle["id"])
    assert await _test_count(vehicle["id"]) == 3  # old history intact
    assert after.mot_refreshed_at == before.mot_refreshed_at
    assert after.inspection_status == before.inspection_status

    # The per-vehicle lock was released: the next refresh works.
    monkeypatch.setattr(driveway_mot, "_replace_history", real_replace)
    assert (await _refresh(client, home_id, vehicle["id"])).json()["refresh"][
        "outcome"
    ] == "refreshed"
    assert await _test_count(vehicle["id"]) == 1


@pytest.mark.asyncio
async def test_changing_the_registration_clears_old_mot_data(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    owner_id, home_id, vehicle = await _vehicle(client, "mot-rereg")
    await _refresh(client, home_id, vehicle["id"])
    current = (await client.get(f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}")).json()
    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}",
        json=_body(
            owner_id,
            registration="XY34 ZZZ",
            vin=None,
            nickname=current["nickname"],
            expected_updated_at=current["updated_at"],
        ),
    )
    assert updated.status_code == 200, updated.text
    view = (await client.get(_mot_url(home_id, vehicle["id"]))).json()
    assert view["tests"] == [] and view["summary"]["status"] is None
    # An unrelated edit keeps MOT data.
    await _refresh(client, home_id, vehicle["id"])
    current = (await client.get(f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}")).json()
    await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}",
        json=_body(
            owner_id,
            registration="XY34 ZZZ",
            vin=None,
            nickname="Renamed",
            expected_updated_at=current["updated_at"],
        ),
    )
    assert (await _test_count(vehicle["id"])) == 3


@pytest.mark.asyncio
async def test_moving_a_vehicle_out_of_gb_clears_old_mot_data(
    client: AsyncClient, dvsa: FakeDvsa
) -> None:
    owner_id, home_id, vehicle = await _vehicle(client, "mot-export")
    await _refresh(client, home_id, vehicle["id"])
    assert await _test_count(vehicle["id"]) > 0
    current = (await client.get(f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}")).json()
    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}",
        json=_body(
            owner_id,
            country_code="ZA",
            registration=current["registration"],
            vin=None,
            nickname=current["nickname"],
            expected_updated_at=current["updated_at"],
        ),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["inspection_status"] is None
    assert await _test_count(vehicle["id"]) == 0
    view = (await client.get(_mot_url(home_id, vehicle["id"]))).json()
    assert view["eligible"] is False and view["tests"] == []


def test_home_migration_never_carries_mot_cache() -> None:
    from mykhaya.tools.home_migration import (
        EXCLUDED_TABLES,
        PROVIDER_CACHE_COLUMNS,
        TABLE_ORDER,
        _export_row,
    )

    assert {"vehicle_mot_tests", "vehicle_mot_defects"} <= EXCLUDED_TABLES
    assert not {"vehicle_mot_tests", "vehicle_mot_defects"} & set(TABLE_ORDER)
    exported = _export_row(
        {"id": "x", "nickname": "Car", **dict.fromkeys(PROVIDER_CACHE_COLUMNS, "cached")}
    )
    assert exported == {"id": "x", "nickname": "Car"}


# --- PCC ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pcc_status_reports_state_never_credentials(
    dvsa: FakeDvsa, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_platform_control_centre import TEST_CLIENT_IP, TEST_PROXY_PEER, create_admin, login

    from mykhaya.models import PlatformAdministrator, PlatformSession

    admin = await create_admin()
    origin = get_settings().admin_url
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, client=(TEST_PROXY_PEER, 44000)),
            base_url=origin,
            headers={"Origin": origin, "X-Forwarded-For": TEST_CLIENT_IP},
        ) as admin_client:
            await login(admin_client, admin)
            response = await admin_client.get("/api/v1/platform/integrations/dvsa")
            assert response.status_code == 200
            body = response.json()
            assert body["configured"] is True and body["deployment_enabled"] is True
            assert body["enabled"] is True and body["environment"] == "Development"
            for secret in (CLIENT_ID, CLIENT_SECRET, API_KEY, TOKEN_URL, "00000000-test-tenant"):
                assert secret not in response.text

            csrf = admin_client.cookies.get("mk_admin_csrf")
            tested = await admin_client.post(
                "/api/v1/platform/integrations/dvsa/test",
                json={
                    "registration": REGISTRATION,
                    "reason": "Verify DVSA connection",
                    "confirmed": True,
                },
                headers={"X-CSRF-Token": csrf or ""},
            )
            assert tested.status_code == 200, tested.text
            assert tested.json()["state"] == "Healthy"
            assert REGISTRATION not in tested.text and API_KEY not in tested.text
    finally:
        async with SessionFactory() as db:
            from mykhaya.models import AdministrativeAuditEvent

            events = (
                await db.scalars(
                    select(AdministrativeAuditEvent).where(
                        AdministrativeAuditEvent.administrator_id == admin.id
                    )
                )
            ).all()
            assert REGISTRATION not in json.dumps([e.new_values for e in events], default=str)
            for model, column in (
                (AdministrativeAuditEvent, AdministrativeAuditEvent.administrator_id),
                (PlatformSession, PlatformSession.administrator_id),
            ):
                await db.execute(model.__table__.delete().where(column == admin.id))
            await db.execute(
                PlatformAdministrator.__table__.delete().where(PlatformAdministrator.id == admin.id)
            )
            await db.commit()
