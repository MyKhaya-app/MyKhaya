"""Synthetic QA scenarios for the Vehicle Report prototype.

Every value here is invented. Registrations use the reserved-looking MK21 HYA /
YK12 RTX / LB19 NEW / ZZ99 ZZZ marks and do not identify real vehicles. The
dict shapes mirror the real report payload: ``VehicleResponse`` /
``VehicleLookupResult`` (vehicle) and ``VehicleMotResponse`` (mot).
"""

from __future__ import annotations

GENERATED_AT = "2026-11-17T09:12:00+00:00"

# 2026-2027 post-2017 standard-rate payment options. The six-month figures
# follow DVLA's published pattern (Direct Debit = 2 x half of the 5% surcharged
# total; single six-month payment carries the 10% surcharge). See README:
# driveway_tax.py currently emits these two six-month values the other way round.
_POST_2017_OPTIONS = {
    "single_12_month_total": 200.0,
    "monthly_direct_debit_per_month": 17.5,
    "monthly_direct_debit_total": 210.0,
    "six_month_direct_debit_payment": 105.0,
    "six_month_direct_debit_total": 210.0,
    "six_month_single_payment": 110.0,
    "six_month_single_total": 220.0,
}

_E208 = {
    "nickname": "Pebble",
    "make": "PEUGEOT",
    "model": "e-208",
    "colour": "GREY",
    "year": 2021,
    "fuel_type": "ELECTRICITY",
    "engine_size": None,
    "country_code": "GB",
    "registration": "MK21 HYA",
    "first_registration_date": "2021-03-01",
    "first_registration_precision": "month",
    "first_registration_with_dvla_date": None,
    "tax_status": "Taxed",
    "tax_due_date": "2027-03-01",
    "co2_emissions": 0,
    "euro_status": None,
    "type_approval": "M1",
    "wheel_plan": "2 AXLE RIGID BODY",
    "revenue_weight": 1980,
    "marked_for_export": False,
    "marked_as_scrapped": False,
    "date_of_last_v5c_issued": "2024-06-12",
    "real_driving_emissions": None,
    "vehicle_status": None,
    "automated_vehicle": None,
    "art_end_date": None,
    "last_successful_lookup": "2026-11-17T08:30:00+00:00",
    "tax_calculation": {
        "status": "conditional_estimate",
        "annual_rate": 200,
        "payment_options": _POST_2017_OPTIONS,
        "tax_year": "2026-2027",
        "category": "post-2017 car",
        "assumptions": [
            "base subsequent-licence rate is £200",
            "the first-year versus standard-rate distinction is not inferred",
        ],
        "missing_information": [
            "original list price",
            "first-licence versus subsequent-licence state",
        ],
        "supplement_message": (
            "For this zero-emission vehicle, the premium supplement is not applied in this estimate."
        ),
        "source": "mykhaya",
        "calculated_at": "2026-11-17T09:12:00+00:00",
    },
}


def _test(date, result, miles, expiry=None, defects=()):
    return {
        "test_date": date,
        "result": result,
        "odometer_value": miles,
        "odometer_unit": "mi",
        "odometer_result": "read",
        "expiry_date": expiry,
        "defects": [
            {"category": c, "text": t, "dangerous": c == "dangerous"} for c, t in defects
        ],
    }


_E208_MOT = {
    "eligible": True,
    "provider_available": True,
    "has_registration": True,
    "summary": {
        "status": "valid",
        "due_date": "2027-03-14",
        "expiry_date": "2027-03-14",
        "last_test_date": "2026-03-15",
        "last_result": "passed",
        "refreshed_at": "2026-11-17T08:31:00+00:00",
        "stale": False,
    },
    "tests": [
        _test("2026-03-15", "passed", 30599, "2027-03-14", [
            ("advisory", "Nearside front tyre worn close to legal limit (5.2.3 (e))"),
            ("advisory", "Offside rear brake disc slightly worn (1.1.14 (a) (ii))"),
        ]),
        _test("2025-03-20", "passed", 21410, "2026-03-19"),
        _test("2025-03-18", "failed", 21402, None, [
            ("major", "Offside front tyre tread depth below requirements of 1.6mm (5.2.3 (e))"),
            ("advisory", "Nearside front tyre worn close to legal limit (5.2.3 (e))"),
        ]),
        _test("2024-03-01", "passed", 11834, "2025-02-28", [
            ("minor", "Front windscreen wiper blade deteriorated (3.4 (b))"),
        ]),
    ],
}

_FOCUS_DEFECT_POOL = [
    ("advisory", "Nearside rear tyre worn close to legal limit (5.2.3 (e))"),
    ("advisory", "Front brake discs worn, pitted or scored, but not seriously weakened (1.1.14 (a) (ii))"),
    ("advisory", "Underside of vehicle has slight corrosion on sub-frame, not seriously weakened"),
    ("minor", "Exhaust has a minor leak of exhaust gases (6.1.2 (a))"),
    ("advisory", "Oil leak from engine, but not excessive"),
    ("major", "Offside front coil spring fractured or seriously weakened (5.3.1 (b) (i))"),
    ("advisory", "Nearside front anti-roll bar linkage ball joint has slight play"),
    ("dangerous", "Nearside rear brake hose damaged so that it is likely to fail (1.1.11 (c))"),
    ("prs", "Offside headlamp aim too high (4.1.2 (a))"),
]

_FOCUS_TESTS = []
_miles = 98412
for i, year in enumerate(range(2026, 2014, -1)):
    result = "failed" if year in (2023, 2019) else "passed"
    defects = [_FOCUS_DEFECT_POOL[(i + k) % len(_FOCUS_DEFECT_POOL)] for k in range(1 + i % 4)]
    # A pass can only carry advisories, minor defects or items repaired at test.
    defects = [d for d in defects if d[0] in {"advisory", "minor", "prs"}] or [_FOCUS_DEFECT_POOL[0]]
    if result == "failed":
        defects = [("dangerous" if year == 2023 else "major", _FOCUS_DEFECT_POOL[7 if year == 2023 else 5][1])] + defects
    _FOCUS_TESTS.append(_test(f"{year}-06-0{1 + i % 8}", result, _miles,
                              None if result == "failed" else f"{year + 1}-05-31", defects))
    if result == "failed":
        _FOCUS_TESTS.append(_test(f"{year}-06-1{i % 8}", "passed", _miles + 12, f"{year + 1}-06-1{i % 8}"))
    _miles -= 7000 + (i * 413) % 2100
# Retest rows sit after their failure in insertion order; present newest first.
_FOCUS_TESTS.sort(key=lambda t: t["test_date"], reverse=True)

_FOCUS = {
    "nickname": None,
    "make": "FORD",
    "model": "Focus",
    "colour": "BLUE",
    "year": 2012,
    "fuel_type": "PETROL",
    "engine_size": "1596",
    "country_code": "GB",
    "registration": "YK12 RTX",
    "first_registration_date": "2012-05-14",
    "first_registration_precision": "day",
    "tax_status": "Taxed",
    "tax_due_date": "2027-06-01",
    "co2_emissions": 159,
    "euro_status": "EURO 5",
    "type_approval": "M1",
    "wheel_plan": "2 AXLE RIGID BODY",
    "revenue_weight": None,
    "marked_for_export": False,
    "marked_as_scrapped": False,
    "date_of_last_v5c_issued": "2022-09-03",
    "real_driving_emissions": None,
    "vehicle_status": None,
    "last_successful_lookup": "2026-11-17T09:05:00+00:00",
    "tax_calculation": {
        "status": "calculated",
        "annual_rate": 275,
        "payment_options": {"single_12_month": 275.0},
        "tax_year": "2026-2027",
        "category": "2001-2017 car",
        "assumptions": ["M1/M1G vehicle", "fuel type falls within the published standard car table"],
        "missing_information": [],
        "supplement_message": None,
        "source": "mykhaya",
        "calculated_at": "2026-11-17T09:12:00+00:00",
    },
}

_FOCUS_MOT = {
    "summary": {
        "status": "valid",
        "due_date": "2027-05-31",
        "expiry_date": "2027-05-31",
        "last_test_date": _FOCUS_TESTS[0]["test_date"],
        "last_result": "passed",
        "refreshed_at": "2026-11-17T09:05:00+00:00",
    },
    "tests": _FOCUS_TESTS,
}

_CORSA_DVLA_ONLY = {
    "nickname": None,
    "make": "VAUXHALL",
    "model": None,
    "colour": "WHITE",
    "year": 2019,
    "fuel_type": "PETROL",
    "engine_size": "1199",
    "country_code": "GB",
    "registration": "LB19 NEW",
    "first_registration_date": "2019-09-27",
    "first_registration_precision": "day",
    "tax_status": "SORN",
    "tax_due_date": None,
    "co2_emissions": 108,
    "euro_status": "EURO 6 AP",
    "type_approval": "M1",
    "wheel_plan": "2 AXLE RIGID BODY",
    "marked_for_export": False,
    "date_of_last_v5c_issued": "2025-01-08",
    "last_successful_lookup": "2026-11-17T09:10:00+00:00",
    "tax_calculation": {
        "status": "conditional_estimate",
        "annual_rate": 200,
        "payment_options": _POST_2017_OPTIONS,
        "tax_year": "2026-2027",
        "category": "post-2017 car",
        "assumptions": ["base subsequent-licence rate is £200"],
        "missing_information": ["original list price"],
        "supplement_message": (
            "The premium supplement is not applied in this base estimate; it may apply if the "
            "original list-price rules are met."
        ),
        "source": "mykhaya",
        "calculated_at": "2026-11-17T09:12:00+00:00",
    },
}

_SPARSE = {
    "nickname": "Grandad's van",
    "make": None,
    "model": None,
    "colour": "Green",
    "year": None,
    "fuel_type": None,
    "engine_size": None,
    "country_code": "GB",
    "registration": "ZZ99 ZZZ",
    "tax_status": None,
    "tax_due_date": None,
    "tax_calculation": {
        "status": "insufficient_data",
        "annual_rate": None,
        "payment_options": {},
        "tax_year": "2026-2027",
        "assumptions": [],
        "missing_information": ["first registration date", "CO2 emissions"],
        "source": "mykhaya",
        "calculated_at": "2026-11-17T09:12:00+00:00",
    },
}

_SPARSE_MOT = {
    "eligible": True,
    "provider_available": True,
    "summary": {"status": None, "due_date": None, "expiry_date": None},
    "tests": [],
}

SCENARIOS = [
    # slug, title, format, source, vehicle, mot, photo
    ("01-full-saved-complete", "Full · saved vehicle · photo · complete data",
     "full", "saved", _E208, _E208_MOT, "sample-vehicle-photo.jpg"),
    ("02-full-lookup-long-history", "Full · one-off lookup · no photo · 14 MOT tests",
     "full", "lookup", _FOCUS, _FOCUS_MOT, None),
    ("03-full-saved-sparse", "Full · saved vehicle · minimal data",
     "full", "saved", _SPARSE, _SPARSE_MOT, None),
    ("04-essential-saved-complete", "Essential · saved vehicle · photo · complete data",
     "essential", "saved", _E208, _E208_MOT, "sample-vehicle-photo.jpg"),
    ("05-essential-lookup-dvla-only", "Essential · one-off lookup · DVLA only, no MOT",
     "essential", "lookup", _CORSA_DVLA_ONLY, None, None),
    ("06-essential-saved-sparse", "Essential · saved vehicle · minimal data",
     "essential", "saved", _SPARSE, _SPARSE_MOT, None),
    # Photo-fit QA: the hero frame must show portrait and square photos whole.
    ("07-essential-saved-portrait-photo", "Essential · saved vehicle · portrait photo",
     "essential", "saved", _E208, _E208_MOT, "sample-vehicle-photo-portrait.jpg"),
    ("08-full-saved-square-photo", "Full · saved vehicle · square photo",
     "full", "saved", _E208, _E208_MOT, "sample-vehicle-photo-square.jpg"),
]
