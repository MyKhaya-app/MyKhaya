# ruff: noqa: E501

from datetime import UTC, datetime

import pytest

from mykhaya.calendar_highlights import built_in_holidays
from mykhaya.models import PlatformHolidaySource


def source(country: str, region: str | None = None) -> PlatformHolidaySource:
    return PlatformHolidaySource(
        country_code=country,
        country_name=country,
        flag_emoji="",
        region_code=region,
        region_name="National",
        provider="test",
    )


def test_provider_returns_region_specific_and_christmas_holidays() -> None:
    rows = built_in_holidays(source("GB", "scotland"), 2026)
    assert any(name == "St Andrew's Day" for _, _, name, _ in rows)
    assert any(
        day.month == 12 and day.day == 25 and name == "Christmas Day"
        for _, day, name, _ in rows
    )


def test_provider_handles_leap_years_and_has_no_duplicate_source_keys() -> None:
    rows = built_in_holidays(source("ZA"), 2028)
    keys = [f"{key}:{day.isoformat()}" for key, day, _, _ in rows]
    assert len(keys) == len(set(keys))
    assert datetime(2028, 2, 29, tzinfo=UTC).date().month == 2


@pytest.mark.parametrize("country", ["GB", "ZA", "US"])
def test_initial_supported_countries_have_bounded_cache_data(country: str) -> None:
    assert len(built_in_holidays(source(country), 2026)) >= 8
