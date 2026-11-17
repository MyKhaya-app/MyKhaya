from datetime import date
from types import SimpleNamespace

import pytest

from mykhaya.driveway_tax import calculate_vehicle_tax


def vehicle(**overrides):
    values = {
        "country_code": "GB",
        "lookup_provider": "uk_dvla",
        "first_registration_date": date(2015, 5, 1),
        "first_registration_precision": "day",
        "type_approval": "M1",
        "engine_size": None,
        "co2_emissions": 120,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_calculator_is_local_and_maps_2001_to_2017_rate():
    result = calculate_vehicle_tax(vehicle(), as_of=date(2026, 5, 1))
    assert result["status"] == "calculated"
    assert result["annual_rate"] == 35
    assert result["tax_year"] == "2026-2027"


def test_tax_year_boundary_uses_the_new_schedule_from_6_april():
    before = calculate_vehicle_tax(vehicle(), as_of=date(2026, 3, 31))
    on_boundary = calculate_vehicle_tax(vehicle(), as_of=date(2026, 4, 6))
    assert before["tax_year"] == "2025-2026"
    assert on_boundary["tax_year"] == "2026-2027"
    assert before["annual_rate"] == 35
    assert on_boundary["annual_rate"] == 35


def test_calculator_handles_pre_2001_engine_capacity_boundary():
    assert calculate_vehicle_tax(
        vehicle(first_registration_date=date(2000, 1, 1), engine_size="1549cc", co2_emissions=None),
        as_of=date(2026, 5, 1),
    )["annual_rate"] == 230
    assert calculate_vehicle_tax(
        vehicle(first_registration_date=date(2000, 1, 1), engine_size="1550cc", co2_emissions=None),
        as_of=date(2026, 5, 1),
    )["annual_rate"] == 375


def test_calculator_does_not_invent_post_2017_expensive_car_data():
    result = calculate_vehicle_tax(
        vehicle(first_registration_date=date(2023, 1, 1), co2_emissions=0),
        as_of=date(2026, 5, 1),
    )
    assert result["status"] == "conditional_estimate"
    assert result["annual_rate"] is None
    assert "original list price" in result["missing_information"]


@pytest.mark.parametrize("registration", [date(2017, 4, 1), date(2024, 1, 1)])
def test_post_2017_first_year_and_expensive_car_inputs_remain_conditional(registration):
    result = calculate_vehicle_tax(
        vehicle(first_registration_date=registration, fuel_type="Electric", co2_emissions=0),
        as_of=date(2026, 5, 1),
    )
    assert result["status"] == "conditional_estimate"
    assert result["annual_rate"] is None
    assert "first-licence versus subsequent-licence state" in result["missing_information"]


def test_electric_car_before_2017_uses_zero_emissions_band_without_network_access():
    result = calculate_vehicle_tax(
        vehicle(
            first_registration_date=date(2016, 6, 1),
            fuel_type="Electric",
            co2_emissions=0,
        ),
        as_of=date(2026, 4, 6),
    )
    assert result["status"] == "calculated"
    assert result["annual_rate"] == 20
    assert result["source"].startswith("https://www.gov.uk/")


def test_calculator_requires_exact_registration_precision_and_category():
    result = calculate_vehicle_tax(vehicle(first_registration_precision="month"))
    assert result["status"] == "insufficient_data"
    assert calculate_vehicle_tax(vehicle(type_approval="N1"))["status"] == "unsupported_category"
    assert calculate_vehicle_tax(vehicle(type_approval=None))["status"] == "insufficient_data"


def test_co2_and_engine_capacity_boundaries_are_inclusive():
    assert calculate_vehicle_tax(
        vehicle(co2_emissions=110), as_of=date(2026, 5, 1)
    )["annual_rate"] == 20
    assert calculate_vehicle_tax(
        vehicle(co2_emissions=111), as_of=date(2026, 5, 1)
    )["annual_rate"] == 35
    assert calculate_vehicle_tax(
        vehicle(first_registration_date=date(2000, 1, 1), engine_size="1549cc", co2_emissions=None),
        as_of=date(2026, 5, 1),
    )["annual_rate"] == 230
