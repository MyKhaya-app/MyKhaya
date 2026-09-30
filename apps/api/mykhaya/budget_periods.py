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
    if month_start_day <= 1:
        start = _period_start(year, month, 1)
        next_year, next_month = _next_month(year, month)
        end = _period_start(next_year, next_month, 1)
    else:
        previous_year, previous_month = (year - 1, 12) if month == 1 else (year, month - 1)
        start = _period_start(previous_year, previous_month, month_start_day)
        end = _period_start(year, month, month_start_day)
    return BudgetPeriod(year, month, start, end)


def budget_period_for_date(value: date, month_start_day: int) -> BudgetPeriod:
    """Resolve a transaction date to its displayed budget month."""
    start_day = min(max(month_start_day, 1), monthrange(value.year, value.month)[1])
    if start_day == 1 or value.day < start_day:
        return budget_period(value.year, value.month, month_start_day)
    next_year, next_month = _next_month(value.year, value.month)
    return budget_period(next_year, next_month, month_start_day)


def expected_income_date(
    year: int, month: int, month_start_day: int, usual_payday_day: int
) -> date:
    """Return the usual payday date represented by a displayed Budget period.

    A payday before the configured period start day belongs to the following
    calendar month; paydays on/after it belong to the period's start month.
    Short months use their final valid calendar day.  This is a display/default
    helper only: the BudgetMonth assignment remains authoritative.
    """
    period = budget_period(year, month, month_start_day)
    start = period.start
    payday = min(max(usual_payday_day, 1), 31)
    if payday < month_start_day:
        next_year, next_month = _next_month(start.year, start.month)
        target_year, target_month = next_year, next_month
    else:
        target_year, target_month = start.year, start.month
    return date(
        target_year,
        target_month,
        min(payday, monthrange(target_year, target_month)[1]),
    )
