"""Shared state for one showcase seed run."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.avatars.storage import get_avatar_storage
from mykhaya.config import Settings
from mykhaya.meal_images import get_meal_image_storage
from mykhaya.models import (
    CalendarEventLabel,
    HomeCalendar,
    Membership,
    SubscriptionPlan,
    TodoCategory,
    User,
)
from mykhaya.vehicle_photo_storage import get_vehicle_photo_storage

SHOWCASE_TIMEZONE_NAME = "Europe/London"
SHOWCASE_TIMEZONE = ZoneInfo(SHOWCASE_TIMEZONE_NAME)
log = structlog.get_logger("showcase")


@dataclass
class StoredFiles:
    """Storage keys of image files, grouped by storage seam.

    Used two ways: the files a seed run wrote (removed again if the run
    fails, so a rolled-back Home never leaves orphaned images), and the files
    a reset made obsolete (removed only after the reset commits)."""

    avatars: list[str] = field(default_factory=list)
    meal_images: list[str] = field(default_factory=list)
    vehicle_photos: list[str] = field(default_factory=list)

    def extend(self, other: StoredFiles) -> None:
        self.avatars.extend(other.avatars)
        self.meal_images.extend(other.meal_images)
        self.vehicle_photos.extend(other.vehicle_photos)

    async def delete_all(self, settings: Settings) -> None:
        """Best-effort removal: a missing file is not an error, and a failed
        delete is logged (key only) rather than failing the caller."""
        groups = (
            (get_avatar_storage, self.avatars),
            (get_meal_image_storage, self.meal_images),
            (get_vehicle_photo_storage, self.vehicle_photos),
        )
        for storage_for, keys in groups:
            if not keys:
                continue
            try:
                # Constructing a storage creates its directory, which can
                # itself fail — cleanup must never mask the original error.
                storage = storage_for(settings)
            except OSError:
                log.warning("showcase_image_cleanup_failed", file_count=len(keys))
                continue
            for key in keys:
                try:
                    await storage.delete(key)
                except (OSError, ValueError):
                    log.warning("showcase_image_cleanup_failed", storage_key=key)


@dataclass
class ShowcaseContext:
    db: AsyncSession
    settings: Settings
    home_id: uuid.UUID
    owner: User
    owner_membership: Membership
    plan: SubscriptionPlan
    fixture_key: str
    reference_date: date
    home_calendar: HomeCalendar
    preserved_member_emails: dict[str, str] = field(default_factory=dict)
    users: dict[str, User] = field(default_factory=dict)
    memberships: dict[str, Membership] = field(default_factory=dict)
    personal_calendars: dict[str, HomeCalendar] = field(default_factory=dict)
    labels: dict[str, CalendarEventLabel] = field(default_factory=dict)
    nudge_categories: dict[str, TodoCategory] = field(default_factory=dict)
    written: StoredFiles = field(default_factory=StoredFiles)
    counts: dict[str, int] = field(default_factory=dict)

    def day(self, offset: int) -> date:
        return self.reference_date + timedelta(days=offset)

    def at(self, value: date, clock: str) -> datetime:
        hour, minute = (int(part) for part in clock.split(":"))
        return datetime.combine(value, time(hour, minute), tzinfo=SHOWCASE_TIMEZONE)

    @staticmethod
    def clock(clock: str) -> time:
        hour, minute = (int(part) for part in clock.split(":"))
        return time(hour, minute)

    @staticmethod
    def all_day_start(value: date) -> datetime:
        # Matches routers.calendar._all_day_midnight: all-day bounds are UTC
        # midnights with an exclusive end.
        return datetime(value.year, value.month, value.day, tzinfo=UTC)

    def user_ids(self, keys: tuple[str, ...]) -> list[uuid.UUID]:
        return [self.users[key].id for key in keys if key in self.users]

    def add_count(self, module: str, amount: int) -> None:
        self.counts[module] = self.counts.get(module, 0) + amount
