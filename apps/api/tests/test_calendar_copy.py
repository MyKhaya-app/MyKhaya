from datetime import date, time

import pytest
from pydantic import ValidationError

from mykhaya.schemas import EventCopyRequest


def test_copy_request_rejects_duplicate_destination_dates() -> None:
    with pytest.raises(ValidationError, match="unique"):
        EventCopyRequest(destination_dates=[date(2026, 11, 5), date(2026, 11, 5)])


def test_copy_request_requires_a_valid_time_pair() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        EventCopyRequest(destination_dates=[date(2026, 11, 5)], start_time=time(18, 0))
    with pytest.raises(ValidationError, match="after start"):
        EventCopyRequest(
            destination_dates=[date(2026, 11, 5)],
            start_time=time(19, 0),
            end_time=time(18, 0),
        )


def test_copy_request_accepts_multiple_dates_and_times() -> None:
    request = EventCopyRequest(
        destination_dates=[date(2026, 11, 5), date(2026, 11, 7)],
        start_time=time(18, 0),
        end_time=time(19, 0),
    )
    assert len(request.destination_dates) == 2


def test_copy_request_accepts_independent_destination_times() -> None:
    request = EventCopyRequest(
        destinations=[
            {"date": date(2026, 11, 5), "start_time": time(15, 0), "end_time": time(23, 0)},
            {"date": date(2026, 11, 7), "start_time": time(16, 0), "end_time": time(22, 0)},
        ]
    )
    assert request.destinations is not None
    assert request.destinations[0].start_time == time(15, 0)
    assert request.destinations[1].end_time == time(22, 0)


def test_copy_request_rejects_duplicate_independent_destination_dates() -> None:
    with pytest.raises(ValidationError, match="unique"):
        EventCopyRequest(
            destinations=[
                {"date": date(2026, 11, 5)},
                {"date": date(2026, 11, 5)},
            ]
        )
