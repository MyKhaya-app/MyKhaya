# ruff: noqa: E501

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import HolidaySyncStatus, PlatformHolidayDate, PlatformHolidaySource


def _easter(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    leap_offset = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * leap_offset) // 451
    month = (h + leap_offset - 7 * m + 114) // 31
    day = (h + leap_offset - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def built_in_holidays(source: PlatformHolidaySource, year: int) -> list[tuple[str, date, str, bool]]:
    """Provider-neutral fallback provider used for the initial supported catalogue.

    The cache boundary is deliberate: consumer requests never call a remote feed.
    Platform sync can later replace this provider without changing Home data.
    """
    easter = _easter(year)
    if source.country_code == "GB":
        rows = [
            ("new-year", date(year, 1, 1), "New Year's Day", False),
            ("good-friday", easter - timedelta(days=2), "Good Friday", False),
            ("easter-monday", easter + timedelta(days=1), "Easter Monday", False),
            ("early-may", _nth_weekday(year, 5, 0, 1), "Early May bank holiday", False),
            ("spring-bank", _last_weekday(year, 5, 0), "Spring bank holiday", False),
            ("summer-bank", _last_weekday(year, 8, 0), "Summer bank holiday", False),
            ("christmas", date(year, 12, 25), "Christmas Day", False),
            ("boxing-day", date(year, 12, 26), "Boxing Day", False),
        ]
        if source.region_code in {"scotland", "northern_ireland"}:
            rows.append(("st-andrews", date(year, 11, 30), "St Andrew's Day" if source.region_code == "scotland" else "St Patrick's Day", False))
            if source.region_code == "northern_ireland":
                rows[-1] = ("st-patricks", date(year, 3, 17), "St Patrick's Day", False)
        return rows
    if source.country_code == "ZA":
        return [
            ("new-year", date(year, 1, 1), "New Year's Day", False),
            ("human-rights", date(year, 3, 21), "Human Rights Day", False),
            ("freedom", date(year, 4, 27), "Freedom Day", False),
            ("workers", date(year, 5, 1), "Workers' Day", False),
            ("youth", date(year, 6, 16), "Youth Day", False),
            ("national-womens", date(year, 8, 9), "National Women's Day", False),
            ("heritage", date(year, 9, 24), "Heritage Day", False),
            ("reconciliation", date(year, 12, 16), "Day of Reconciliation", False),
            ("christmas", date(year, 12, 25), "Christmas Day", False),
            ("goodwill", date(year, 12, 26), "Day of Goodwill", False),
        ]
    return [
        ("new-year", date(year, 1, 1), "New Year's Day", False),
        ("mlk", _nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day", False),
        ("presidents", _nth_weekday(year, 2, 0, 3), "Washington's Birthday", False),
        ("memorial", _last_weekday(year, 5, 0), "Memorial Day", False),
        ("juneteenth", date(year, 6, 19), "Juneteenth", False),
        ("independence", date(year, 7, 4), "Independence Day", False),
        ("labor", _nth_weekday(year, 9, 0, 1), "Labor Day", False),
        ("columbus", _nth_weekday(year, 10, 0, 2), "Columbus Day", False),
        ("veterans", date(year, 11, 11), "Veterans Day", False),
        ("thanksgiving", _nth_weekday(year, 11, 3, 4), "Thanksgiving Day", False),
        ("christmas", date(year, 12, 25), "Christmas Day", False),
    ]


async def sync_holiday_source(db: AsyncSession, source: PlatformHolidaySource, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    rows = [item for year in range(now.year - 1, now.year + 3) for item in built_in_holidays(source, year)]
    if not rows:
        source.sync_status = HolidaySyncStatus.warning.value
        source.last_sync_error = "Provider returned no holidays; cached data retained."
        return 0
    source.sync_status = HolidaySyncStatus.healthy.value
    source.last_sync_error = None
    source.last_successful_sync = now
    source.next_scheduled_sync = now + timedelta(days=7)
    source.last_sync_metadata = {"count": len(rows), "provider_mode": "cached_builtin_provider"}
    existing = {
        row.source_holiday_id: row
        for row in (await db.scalars(select(PlatformHolidayDate).where(PlatformHolidayDate.source_id == source.id))).all()
    }
    for key, holiday_date, name, observed in rows:
        row = existing.get(f"{key}:{holiday_date.isoformat()}")
        if row is None:
            db.add(PlatformHolidayDate(source_id=source.id, source_holiday_id=f"{key}:{holiday_date.isoformat()}", holiday_date=holiday_date, name=name, observed=observed, source_synced_at=now))
        else:
            row.holiday_date, row.name, row.observed, row.source_synced_at = holiday_date, name, observed, now
    return len(rows)


async def sync_due_holiday_sources(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    sources = (await db.scalars(select(PlatformHolidaySource).where(PlatformHolidaySource.enabled.is_(True)))).all()
    count = 0
    for source in sources:
        if source.next_scheduled_sync is None or source.next_scheduled_sync <= now:
            count += await sync_holiday_source(db, source, now)
    return count
