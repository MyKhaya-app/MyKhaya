from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx
from pydantic import SecretStr


@dataclass(frozen=True)
class VehicleLookup:
    registration: str
    make: str | None = None
    model: str | None = None
    colour: str | None = None
    year: int | None = None
    fuel_type: str | None = None
    engine_size: str | None = None
    first_registration_date: date | None = None
    tax_status: str | None = None
    tax_due_date: date | None = None
    inspection_status: str | None = None
    inspection_due_date: date | None = None
    co2_emissions: int | None = None
    euro_status: str | None = None
    type_approval: str | None = None
    wheel_plan: str | None = None
    revenue_weight: int | None = None
    marked_for_export: bool | None = None
    marked_as_scrapped: bool | None = None
    date_of_last_v5c_issued: date | None = None
    real_driving_emissions: str | None = None
    vehicle_status: str | None = None
    automated_vehicle: bool | None = None
    art_end_date: date | None = None
    capabilities: tuple[str, ...] = ()


class VehicleLookupNotFound(Exception):
    pass


class VehicleLookupUnavailable(Exception):
    pass


class VehicleLookupAuthFailed(Exception):
    """The provider rejected our credentials (401/403) — distinct from a
    general outage so PCC's Test connection can say "DVLA authentication
    failed." rather than the more general "DVLA service is unavailable.\""""


def normalize_registration(value: str) -> str:
    return "".join(value.upper().split())


class UKDVLAProvider:
    name = "uk_dvla"

    def __init__(
        self, api_key: SecretStr, url: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._api_key = api_key.get_secret_value()
        self._url = url
        self._transport = transport

    async def lookup(self, registration: str) -> VehicleLookup:
        normalized = normalize_registration(registration)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=8.0) as client:
                response = await client.post(
                    self._url,
                    headers={"x-api-key": self._api_key, "Content-Type": "application/json"},
                    json={"registrationNumber": normalized},
                )
        except httpx.HTTPError as exc:
            raise VehicleLookupUnavailable from exc
        if response.status_code == 404:
            raise VehicleLookupNotFound
        if response.status_code in {401, 403}:
            raise VehicleLookupAuthFailed
        if response.status_code in {408, 429} or response.status_code >= 500:
            raise VehicleLookupUnavailable
        if response.status_code >= 400:
            raise VehicleLookupNotFound
        try:
            payload = response.json()
        except ValueError as exc:
            raise VehicleLookupUnavailable from exc

        def parsed_date(*keys: str) -> date | None:
            value = next((payload.get(key) for key in keys if payload.get(key)), None)
            if not value:
                return None
            try:
                return date.fromisoformat(str(value)[:10])
            except ValueError:
                return None

        def parsed_first_registration() -> date | None:
            value = payload.get("monthOfFirstRegistration")
            year = payload.get("yearOfFirstRegistration")
            if isinstance(value, str) and len(value) == 7 and value[4] == "-":
                try:
                    return date.fromisoformat(f"{value}-01")
                except ValueError:
                    return None
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            if isinstance(year, int) and isinstance(value, int) and 1 <= value <= 12:
                try:
                    return date(year, value, 1)
                except ValueError:
                    return None
            return parsed_date("monthOfFirstRegistration")

        capabilities: list[str] = []
        if payload.get("taxStatus") or payload.get("taxDueDate"):
            capabilities.append("tax")
        if payload.get("motStatus") or payload.get("motExpiry") or payload.get("motExpiryDate"):
            capabilities.append("inspection")
        specification_keys = (
            "co2Emissions",
            "euroStatus",
            "typeApproval",
            "wheelPlan",
            "wheelplan",
            "revenueWeight",
        )
        if any(payload.get(key) is not None for key in specification_keys):
            capabilities.append("specifications")
        return VehicleLookup(
            registration=payload.get("registrationNumber") or normalized,
            make=payload.get("make"),
            model=payload.get("model"),
            colour=payload.get("colour"),
            year=payload.get("yearOfManufacture"),
            fuel_type=payload.get("fuelType"),
            engine_size=str(payload["engineCapacity"]) if payload.get("engineCapacity") else None,
            first_registration_date=parsed_first_registration(),
            tax_status=payload.get("taxStatus"),
            tax_due_date=parsed_date("taxDueDate"),
            inspection_status=payload.get("motStatus"),
            inspection_due_date=parsed_date("motExpiry", "motExpiryDate"),
            co2_emissions=payload.get("co2Emissions"),
            euro_status=payload.get("euroStatus"),
            type_approval=payload.get("typeApproval"),
            wheel_plan=payload.get("wheelPlan") or payload.get("wheelplan"),
            revenue_weight=payload.get("revenueWeight"),
            marked_for_export=payload.get("markedForExport"),
            marked_as_scrapped=payload.get("markedAsScrapped"),
            date_of_last_v5c_issued=parsed_date("dateOfLastV5CIssued"),
            real_driving_emissions=payload.get("realDrivingEmissions"),
            vehicle_status=payload.get("vehicleStatus"),
            automated_vehicle=payload.get("automatedVehicle"),
            art_end_date=parsed_date("artEndDate"),
            capabilities=tuple(capabilities),
        )
