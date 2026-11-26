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
    assert (
        calculate_vehicle_tax(
            vehicle(
                first_registration_date=date(2000, 1, 1), engine_size="1549cc", co2_emissions=None
            ),
            as_of=date(2026, 5, 1),
        )["annual_rate"]
        == 230
    )
    assert (
        calculate_vehicle_tax(
            vehicle(
                first_registration_date=date(2000, 1, 1), engine_size="1550cc", co2_emissions=None
            ),
            as_of=date(2026, 5, 1),
        )["annual_rate"]
        == 375
    )


def test_calculator_does_not_invent_post_2017_expensive_car_data():
    result = calculate_vehicle_tax(
        vehicle(first_registration_date=date(2023, 1, 1), co2_emissions=0),
        as_of=date(2026, 5, 1),
    )
    assert result["status"] == "conditional_estimate"
    assert result["annual_rate"] == 200
    assert result["payment_options"]["monthly_direct_debit_per_month"] == 17.5
    assert result["payment_options"]["six_month_direct_debit_total"] == 210
    assert "original list price" in result["missing_information"]


@pytest.mark.parametrize("registration", [date(2017, 4, 1), date(2024, 1, 1)])
def test_post_2017_first_year_and_expensive_car_inputs_remain_conditional(registration):
    result = calculate_vehicle_tax(
        vehicle(first_registration_date=registration, fuel_type="Electric", co2_emissions=0),
        as_of=date(2026, 5, 1),
    )
    assert result["status"] == "conditional_estimate"
    assert result["annual_rate"] == 200
    assert result["supplement_message"].startswith("For this zero-emission vehicle")
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


def test_2021_electric_vehicle_shows_base_annual_rate_and_no_premium_assumption():
    result = calculate_vehicle_tax(
        vehicle(
            first_registration_date=date(2021, 9, 1),
            first_registration_precision="month",
            fuel_type="Electric",
            co2_emissions=0,
        ),
        as_of=date(2026, 11, 17),
    )
    assert result["annual_rate"] == 200
    assert result["payment_options"]["monthly_direct_debit_per_month"] == 17.5
    assert "zero-emission vehicle" in result["supplement_message"]


def test_calculator_requires_exact_registration_precision_and_category():
    result = calculate_vehicle_tax(vehicle(first_registration_precision="month"))
    assert result["status"] == "insufficient_data"
    assert calculate_vehicle_tax(vehicle(type_approval="N1"))["status"] == "unsupported_category"
    assert calculate_vehicle_tax(vehicle(type_approval=None))["status"] == "insufficient_data"


def test_co2_and_engine_capacity_boundaries_are_inclusive():
    assert (
        calculate_vehicle_tax(vehicle(co2_emissions=110), as_of=date(2026, 5, 1))["annual_rate"]
        == 20
    )
    assert (
        calculate_vehicle_tax(vehicle(co2_emissions=111), as_of=date(2026, 5, 1))["annual_rate"]
        == 35
    )
    assert (
        calculate_vehicle_tax(
            vehicle(
                first_registration_date=date(2000, 1, 1), engine_size="1549cc", co2_emissions=None
            ),
            as_of=date(2026, 5, 1),
        )["annual_rate"]
        == 230
    )


# DVLA V149 "Rates of vehicle tax", rates on or after 1 April 2026: the
# standard rate for cars registered on or after 1 April 2017 (petrol, diesel,
# alternative fuel and zero emission alike).
V149_2026_POST_2017_STANDARD = {
    "single_12_month_total": 200.0,
    "monthly_direct_debit_per_month": 17.5,
    "monthly_direct_debit_total": 210.0,
    "six_month_direct_debit_payment": 105.0,
    "six_month_direct_debit_total": 210.0,
    "six_month_single_payment": 110.0,
    "six_month_single_total": 220.0,
}


@pytest.mark.parametrize("co2", [0, 120])
def test_post_2017_payment_options_match_published_2026_27_rates(co2):
    result = calculate_vehicle_tax(
        vehicle(first_registration_date=date(2021, 3, 1), co2_emissions=co2),
        as_of=date(2026, 11, 18),
    )
    assert result["tax_year"] == "2026-2027"
    assert result["payment_options"] == V149_2026_POST_2017_STANDARD


def test_every_payment_option_total_is_its_own_instalments():
    options = calculate_vehicle_tax(
        vehicle(first_registration_date=date(2019, 9, 27), co2_emissions=108),
        as_of=date(2026, 4, 1),
    )["payment_options"]
    assert options["monthly_direct_debit_per_month"] * 12 == options["monthly_direct_debit_total"]
    assert options["six_month_direct_debit_payment"] * 2 == options["six_month_direct_debit_total"]
    assert options["six_month_single_payment"] * 2 == options["six_month_single_total"]
    # Paying by Direct Debit in two halves is cheaper than two single
    # six-month payments, as on the published table.
    assert options["six_month_direct_debit_total"] < options["six_month_single_total"]


@pytest.mark.parametrize(
    ("co2", "annual"),
    [
        (100, 20),
        (101, 20),
        (110, 20),
        (111, 35),
        (120, 35),
        (121, 170),
        (130, 170),
        (131, 200),
        (140, 200),
        (141, 225),
        (150, 225),
        (151, 275),
        (165, 275),
        (166, 325),
        (175, 325),
        (176, 360),
        (185, 360),
        (186, 410),
        (200, 410),
        (201, 445),
        (225, 445),
        (226, 760),
        (255, 760),
        (256, 790),
    ],
)
def test_2001_to_2017_bands_match_published_2026_27_rates(co2, annual):
    result = calculate_vehicle_tax(vehicle(co2_emissions=co2), as_of=date(2026, 4, 1))
    assert result["annual_rate"] == annual


@pytest.mark.parametrize(("engine", "annual"), [("1549", 230), ("1550", 375)])
def test_pre_2001_rates_match_published_2026_27_rates(engine, annual):
    result = calculate_vehicle_tax(
        vehicle(first_registration_date=date(2000, 6, 1), engine_size=engine),
        as_of=date(2026, 4, 1),
    )
    assert result["annual_rate"] == annual
