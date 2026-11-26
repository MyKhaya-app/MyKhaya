import json

import httpx
import pytest
from pydantic import SecretStr

from mykhaya.driveway_dvla_controls import DvlaBudgetExceeded
from mykhaya.driveway_providers import (
    UKDVLAProvider,
    VehicleLookupNotFound,
    normalize_fuel_type,
    normalize_registration,
)


def test_registration_normalization() -> None:
    assert normalize_registration(" ap22 oo j ") == "AP22OOJ"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("DIESEL", "Diesel"),
        ("ELECTRICITY", "Electric"),
        ("Hybrid Electric (Clean)", "Hybrid"),
        ("Gas Bi-Fuel", "Gas Bi-Fuel"),
    ],
)
def test_fuel_type_normalisation_preserves_supported_and_unknown_values(
    value: str, expected: str
) -> None:
    assert normalize_fuel_type(value) == expected


@pytest.mark.asyncio
async def test_dvla_maps_only_supported_vehicle_fields_and_never_logs_key() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "registrationNumber": "AP22OOJ",
                "make": "BMW",
                "model": "i4",
                "colour": "Black",
                "yearOfManufacture": 2022,
                "fuelType": "Electric",
                "taxStatus": "Taxed",
                "taxDueDate": "2027-01-01",
                "motStatus": "Valid",
                "motExpiryDate": "2026-12-01",
                "keeperName": "Should never be mapped",
            },
        )

    result = await UKDVLAProvider(
        SecretStr("test-secret"), "https://dvla.test", transport=httpx.MockTransport(handler)
    ).lookup("AP22 OOJ")
    assert result.registration == "AP22OOJ"
    assert result.make == "BMW"
    assert result.model == "i4"
    assert result.inspection_status == "Valid"
    assert not hasattr(result, "keeper_name")
    assert json.loads(requests[0].content) == {"registrationNumber": "AP22OOJ"}
    assert requests[0].headers["x-api-key"] == "test-secret"


@pytest.mark.asyncio
async def test_dvla_maps_v12_specifications_and_year_month_registration() -> None:
    provider = UKDVLAProvider(
        SecretStr("test-secret"),
        "https://dvla.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "registrationNumber": "AA19AAA",
                    "yearOfManufacture": 2019,
                    "yearOfFirstRegistration": 2019,
                    "monthOfFirstRegistration": 3,
                    "co2Emissions": 120,
                    "euroStatus": "Euro 6",
                    "typeApproval": "M1",
                    "wheelPlan": "2 AXLE RIGID BODY",
                    "revenueWeight": 1800,
                    "markedForExport": False,
                    "markedAsScrapped": False,
                    "dateOfLastV5CIssued": "2024-01-02",
                    "realDrivingEmissions": "2",
                    "vehicleStatus": "Taxed",
                    "automatedVehicle": False,
                    "artEndDate": "2025-03-30",
                    "motExpiry": "2026-03-30",
                },
            )
        ),
    )
    result = await provider.lookup("AA19 AAA")
    assert result.first_registration_date.isoformat() == "2019-03-01"
    assert result.first_registration_precision == "month"
    assert result.co2_emissions == 120
    assert result.wheel_plan == "2 AXLE RIGID BODY"
    assert result.inspection_due_date.isoformat() == "2026-03-30"


@pytest.mark.asyncio
async def test_dvla_not_found_is_safe() -> None:
    provider = UKDVLAProvider(
        SecretStr("test-secret"),
        "https://dvla.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(404)),
    )
    with pytest.raises(VehicleLookupNotFound):
        await provider.lookup("AB12 CDE")


@pytest.mark.asyncio
async def test_production_provider_consumes_shared_budget_before_http(monkeypatch) -> None:
    budget_calls = 0

    async def budget(settings) -> None:
        nonlocal budget_calls
        budget_calls += 1

    monkeypatch.setattr("mykhaya.driveway_providers.enforce_request_budget", budget)
    provider = UKDVLAProvider(
        SecretStr("test-secret"),
        "https://dvla.test",
        settings=object(),
        transport=httpx.MockTransport(lambda _: httpx.Response(404)),
    )
    with pytest.raises(VehicleLookupNotFound):
        await provider.lookup("AB12 CDE")
    assert budget_calls == 1


@pytest.mark.asyncio
async def test_provider_does_not_contact_dvla_when_budget_is_exhausted(monkeypatch) -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"registrationNumber": "AB12CDE"})

    async def exhausted(settings) -> None:
        raise DvlaBudgetExceeded

    monkeypatch.setattr("mykhaya.driveway_providers.enforce_request_budget", exhausted)
    provider = UKDVLAProvider(
        SecretStr("test-secret"),
        "https://dvla.test",
        settings=object(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DvlaBudgetExceeded):
        await provider.lookup("AB12 CDE")
    assert requests == 0
