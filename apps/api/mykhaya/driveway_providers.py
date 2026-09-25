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
    capabilities: tuple[str, ...] = ()


class VehicleLookupNotFound(Exception):
    pass


class VehicleLookupUnavailable(Exception):
    pass


def normalize_registration(value: str) -> str:
    return "".join(value.upper().split())


class UKDVLAProvider:
    name = "uk_dvla"

    def __init__(self, api_key: SecretStr, url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
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
        if response.status_code in {401, 403, 408, 429} or response.status_code >= 500:
            raise VehicleLookupUnavailable
        if response.status_code >= 400:
            raise VehicleLookupNotFound
        try:
            payload = response.json()
        except ValueError as exc:
            raise VehicleLookupUnavailable from exc

        def parsed_date(key: str) -> date | None:
            value = payload.get(key)
            if not value:
                return None
            try:
                return date.fromisoformat(str(value))
            except ValueError:
                return None

        capabilities: list[str] = []
        if payload.get("taxStatus") or payload.get("taxDueDate"):
            capabilities.append("tax")
        if payload.get("motStatus") or payload.get("motExpiryDate"):
            capabilities.append("inspection")
        return VehicleLookup(
            registration=payload.get("registrationNumber") or normalized,
            make=payload.get("make"),
            model=payload.get("model"),
            colour=payload.get("colour"),
            year=payload.get("yearOfManufacture"),
            fuel_type=payload.get("fuelType"),
            engine_size=str(payload["engineCapacity"]) if payload.get("engineCapacity") else None,
            first_registration_date=parsed_date("monthOfFirstRegistration"),
            tax_status=payload.get("taxStatus"),
            tax_due_date=parsed_date("taxDueDate"),
            inspection_status=payload.get("motStatus"),
            inspection_due_date=parsed_date("motExpiryDate"),
            capabilities=tuple(capabilities),
        )
