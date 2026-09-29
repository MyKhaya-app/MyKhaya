"""Canonical budget-period date calculations."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BudgetPeriod:
    """A displayed budget month and its half-open calendar-date range."""

    year: int
    month: int
    start: date
    end: date


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _period_start(year: int, month: int, month_start_day: int) -> date:
    day = min(max(month_start_day, 1), monthrange(year, month)[1])
    return date(year, month, day)


def budget_period(year: int, month: int, month_start_day: int) -> BudgetPeriod:
    """Return the displayed period using an inclusive start/exclusive end."""
    start = _period_start(year, month, month_start_day)
    next_year, next_month = _next_month(year, month)
    return BudgetPeriod(year, month, start, _period_start(next_year, next_month, month_start_day))


def budget_period_for_date(value: date, month_start_day: int) -> BudgetPeriod:
    """Resolve a transaction date to its displayed budget month."""
    start_day = min(max(month_start_day, 1), monthrange(value.year, value.month)[1])
    if start_day == 1 or value.day < start_day:
        return budget_period(value.year, value.month, month_start_day)
    next_year, next_month = _next_month(value.year, value.month)
    return budget_period(next_year, next_month, month_start_day)
