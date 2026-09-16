"""Contract tests for PCC usage-report filters and reporting boundaries."""

from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException

from mykhaya.models import ProductUsageEvent
from mykhaya.routers.usage_admin import UsageClassification, _classification_clause, _date_range


def test_report_periods_are_inclusive_utc_days() -> None:
    start, end, start_date = _date_range(7, date(2026, 9, 16))
    assert start_date == date(2026, 9, 10)
    assert start == datetime(2026, 9, 10, tzinfo=UTC)
    assert end == datetime(2026, 9, 17, tzinfo=UTC)


def test_report_rejects_unsupported_period() -> None:
    with pytest.raises(HTTPException) as error:
        _date_range(14, date(2026, 9, 16))
    assert error.value.status_code == 422


@pytest.mark.parametrize("classification", list(UsageClassification))
def test_classification_is_explicit_and_production_is_null_safe(
    classification: UsageClassification,
) -> None:
    clauses = _classification_clause(classification)
    if classification is UsageClassification.all:
        assert clauses is None
    else:
        assert clauses
        # The production predicate must not turn events with no home/user into
        # a SQL NULL/NOT IN false result.
        if classification is UsageClassification.production:
            sql = " ".join(str(clause) for clause in clauses)
            assert "IS NULL" in sql.upper()
            assert ProductUsageEvent.__tablename__ in sql
