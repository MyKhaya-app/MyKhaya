from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from mykhaya.notifications.reminders import _reminder_when_and_location


def test_reminder_wording_is_relative_to_the_calendar_date() -> None:
    event = SimpleNamespace(timezone="Europe/London")
    delivery = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)

    same_day, _ = _reminder_when_and_location(
        event,
        datetime(2026, 11, 25, 9, 0, tzinfo=ZoneInfo("Europe/London")),
        10,
        is_all_day=False,
        location_text=None,
        delivered_at=delivery,
    )
    tomorrow, _ = _reminder_when_and_location(
        event,
        datetime(2026, 11, 26, 9, 0, tzinfo=ZoneInfo("Europe/London")),
        1440,
        is_all_day=False,
        location_text=None,
        delivered_at=delivery,
    )
    future, _ = _reminder_when_and_location(
        event,
        datetime(2026, 11, 28, 9, 0, tzinfo=ZoneInfo("Europe/London")),
        10,
        is_all_day=False,
        location_text=None,
        delivered_at=delivery,
    )

    assert same_day == "today at 09:00"
    assert tomorrow == "at 09:00 tomorrow"
    assert future == "on Saturday 28 November at 09:00"


def test_reminder_wording_handles_all_day_year_boundary_and_timezone_date() -> None:
    event = SimpleNamespace(timezone="America/New_York")

    # 00:30 UTC is still the previous calendar date in New York.
    same_day, _ = _reminder_when_and_location(
        event,
        datetime(2026, 3, 8, 15, 0, tzinfo=ZoneInfo("America/New_York")),
        60,
        is_all_day=True,
        location_text=None,
        delivered_at=datetime(2026, 3, 9, 0, 30, tzinfo=UTC),
    )
    all_day_future, _ = _reminder_when_and_location(
        event,
        datetime(2026, 3, 11, 0, 0, tzinfo=UTC),
        60,
        is_all_day=True,
        location_text=None,
        delivered_at=datetime(2026, 3, 9, 0, 30, tzinfo=UTC),
    )
    year_change, _ = _reminder_when_and_location(
        event,
        datetime(2027, 1, 2, 14, 0, tzinfo=ZoneInfo("America/New_York")),
        60,
        is_all_day=False,
        location_text=None,
        delivered_at=datetime(2026, 12, 31, 15, 0, tzinfo=UTC),
    )

    assert same_day == "today"
    assert all_day_future == "on Wednesday 11 March"
    assert year_change == "on Saturday 2 January 2027 at 14:00"


def test_reminder_wording_uses_the_effective_recurring_occurrence() -> None:
    event = SimpleNamespace(timezone="Europe/London")
    occurrence_start = datetime(2026, 11, 26, 9, 0, tzinfo=ZoneInfo("Europe/London"))

    when, _ = _reminder_when_and_location(
        event,
        occurrence_start,
        1440,
        is_all_day=False,
        location_text=None,
        delivered_at=datetime(2026, 11, 25, 9, 0, tzinfo=UTC),
    )

    assert when == "at 09:00 tomorrow"


@pytest.mark.parametrize(
    ("delivered_at", "expected"),
    [
        (datetime(2026, 11, 25, 9, 0, tzinfo=UTC), "at 09:00 tomorrow"),
        (datetime(2026, 11, 26, 10, 0, tzinfo=UTC), "today at 09:00"),
        (datetime(2026, 11, 27, 9, 0, tzinfo=UTC), "on Thursday 26 November at 09:00"),
    ],
)
def test_delayed_delivery_uses_delivery_date_not_scheduled_due_date(
    delivered_at: datetime, expected: str
) -> None:
    event = SimpleNamespace(timezone="Europe/London")
    occurrence_start = datetime(2026, 11, 26, 9, 0, tzinfo=ZoneInfo("Europe/London"))

    when, _ = _reminder_when_and_location(
        event,
        occurrence_start,
        1440,
        is_all_day=False,
        location_text=None,
        delivered_at=delivered_at,
    )

    assert when == expected
