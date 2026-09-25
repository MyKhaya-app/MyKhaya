import json

import httpx
import pytest
from pydantic import SecretStr

from mykhaya.driveway_providers import UKDVLAProvider, VehicleLookupNotFound, normalize_registration


def test_registration_normalization() -> None:
    assert normalize_registration(" ap22 oo j ") == "AP22OOJ"


@pytest.mark.asyncio
async def test_dvla_maps_only_supported_vehicle_fields_and_never_logs_key() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
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
        })

    result = await UKDVLAProvider(SecretStr("test-secret"), "https://dvla.test", transport=httpx.MockTransport(handler)).lookup("AP22 OOJ")
    assert result.registration == "AP22OOJ"
    assert result.make == "BMW"
    assert result.model == "i4"
    assert result.inspection_status == "Valid"
    assert not hasattr(result, "keeper_name")
    assert json.loads(requests[0].content) == {"registrationNumber": "AP22OOJ"}
    assert requests[0].headers["x-api-key"] == "test-secret"


@pytest.mark.asyncio
async def test_dvla_not_found_is_safe() -> None:
    provider = UKDVLAProvider(SecretStr("test-secret"), "https://dvla.test", transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    with pytest.raises(VehicleLookupNotFound):
        await provider.lookup("AB12 CDE")
