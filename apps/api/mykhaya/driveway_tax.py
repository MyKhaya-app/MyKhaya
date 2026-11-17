"""Local, versioned VED estimates for verified Driveway vehicle data.

This module is intentionally pure: it never contacts DVLA, DVSA or GOV.UK.
Rates are reviewed application data, not provider responses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from mykhaya.models import Vehicle

TaxCalculationStatus = Literal[
    "calculated", "conditional_estimate", "insufficient_data", "unsupported_category"
]

SOURCE = "https://www.gov.uk/vehicle-tax-rate-tables"
# Schedule sources: the GOV.UK current tables and DVLA V149 rate publication.
# Rates are copied into this versioned module so calculation never performs I/O.
RATE_PUBLICATION = "https://www.gov.uk/government/publications/rates-of-vehicle-tax-v149"
TAX_YEAR_2025_START = date(2025, 4, 1)
TAX_YEAR_2026_START = date(2026, 4, 1)


@dataclass(frozen=True)
class VedSchedule:
    tax_year: str
    effective_from: date
    pre_2001: tuple[int, int]
    bands_2001_2017: tuple[tuple[int, int], ...]
    post_2017_standard: int
    post_2017_monthly: int | None
    post_2017_six_month: int | None


SCHEDULES = (
    VedSchedule(
        "2025-2026",
        TAX_YEAR_2025_START,
        (220, 360),
        ((100, 20), (110, 20), (120, 35), (130, 165), (140, 195), (150, 215),
         (165, 265), (175, 315), (185, 345), (200, 395), (225, 430), (255, 735),
         (10_000, 760)),
        195,
        None,
        None,
    ),
    VedSchedule(
        "2026-2027",
        TAX_YEAR_2026_START,
        (230, 375),
        ((100, 20), (110, 20), (120, 35), (130, 170), (140, 200), (150, 225),
         (165, 275), (175, 325), (185, 360), (200, 410), (225, 445), (255, 760),
         (10_000, 790)),
        200,
        210,
        110,
    ),
)


def _schedule_for(as_of: date) -> VedSchedule:
    selected = SCHEDULES[0]
    for schedule in SCHEDULES:
        if schedule.effective_from <= as_of:
            selected = schedule
    return selected


def _result(
    status: TaxCalculationStatus,
    schedule: VedSchedule,
    *,
    annual_rate: int | None = None,
    payment_options: dict[str, float] | None = None,
    category: str | None = None,
    assumptions: list[str] | None = None,
    missing: list[str] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "annual_rate": annual_rate,
        "payment_options": payment_options or {},
        "tax_year": schedule.tax_year,
        "category": category,
        "assumptions": assumptions or [],
        "missing_information": missing or [],
        "source": SOURCE,
        "calculated_at": datetime.now().astimezone(),
    }


def calculate_vehicle_tax(vehicle: Vehicle, *, as_of: date | None = None) -> dict[str, object]:
    """Return a qualified estimate from stored fields without network access."""
    today = as_of or date.today()
    schedule = _schedule_for(today)
    if vehicle.country_code.upper() != "GB":
        return _result("unsupported_category", schedule, missing=["UK vehicle data"])
    if vehicle.lookup_provider != "uk_dvla":
        return _result(
            "insufficient_data", schedule, missing=["DVLA-verified vehicle details"]
        )
    if vehicle.first_registration_date is None or vehicle.first_registration_precision != "day":
        return _result(
            "insufficient_data",
            schedule,
            missing=["exact first registration date (day precision)"],
        )
    if vehicle.type_approval is None:
        return _result("insufficient_data", schedule, missing=["verified vehicle category"])
    if vehicle.type_approval.upper() not in {"M1", "M1G"}:
        return _result("unsupported_category", schedule, category=vehicle.type_approval)

    registered = vehicle.first_registration_date
    if registered < date(2001, 3, 1):
        try:
            match = re.search(r"\d+", str(vehicle.engine_size or ""))
            engine_cc = int(match.group()) if match else 0
        except ValueError:
            engine_cc = 0
        if engine_cc <= 0:
            return _result("insufficient_data", schedule, missing=["engine capacity"])
        annual = schedule.pre_2001[0 if engine_cc <= 1549 else 1]
        return _result(
            "calculated", schedule, annual_rate=annual,
            payment_options={"single_12_month": float(annual)},
            category="pre-2001 car",
            assumptions=["M1/M1G vehicle", "rate based on engine capacity"],
        )

    if registered < date(2017, 4, 1):
        if vehicle.co2_emissions is None:
            return _result("insufficient_data", schedule, missing=["CO₂ emissions"])
        for upper, annual in schedule.bands_2001_2017:
            if vehicle.co2_emissions <= upper:
                return _result(
                    "calculated", schedule, annual_rate=annual,
                    payment_options={"single_12_month": float(annual)},
                    category="2001-2017 car",
                    assumptions=[
                        "M1/M1G vehicle",
                        "fuel type falls within the published standard car table",
                    ],
                )

    # Post-2017 rates cannot be made exact from this model. It does not store
    # original list price, RDE2 status or whether the first licence rate still
    # applies, so never infer any of those values.
    if registered >= date(2017, 4, 1):
        return _result(
            "conditional_estimate", schedule,
            category="post-2017 car",
            assumptions=[
                f"base subsequent-licence rate is £{schedule.post_2017_standard}",
                "an expensive-car supplement may apply",
            ],
            missing=[
                "original list price",
                "RDE2 status where relevant",
                "first-licence versus subsequent-licence state",
            ],
        )

    return _result("unsupported_category", schedule)
