"""Daily morning briefing: a durable due-briefing scan plus worker-side content
generation. Content is computed fresh at delivery time from current data (not stored
hours earlier), reusing the exact same calendar visibility rules as the calendar API —
see mykhaya.notifications.visibility and mykhaya.calendar_occurrences.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, tzinfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.calendar_occurrences import expand_occurrences, recurrence_candidate_filter
from mykhaya.config import Settings
from mykhaya.features import is_feature_enabled
from mykhaya.household_permissions import Capability, capabilities_for
from mykhaya.models import (
    BriefingDays,
    CalendarEvent,
    FeatureKey,
    Membership,
    NotificationPreferences,
    OutboxEvent,
    User,
)
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import get_or_create_preferences, notify
from mykhaya.notifications.quiet_hours import effective_timezone
from mykhaya.notifications.visibility import viewer_ids_for_event

# Matches the reminder scan's cadence — short enough that the scan reliably catches each
# user's chosen minute exactly once per day without needing sub-minute precision.
LOOKAHEAD = timedelta(minutes=2)
BRIEFING_TOPIC = "notification.daily_briefing"

# Rotated by ordinal day so the empty-day message varies day to day but stays stable
# within a single day (matches the equivalent frontend rotation in home/page.tsx —
# see docs/design/visual-identity.md).
EMPTY_DAY_MESSAGES = (
    "Your day looks nice and calm.",
    "Nothing planned just yet — enjoy the quieter day.",
    "Today looks wonderfully open.",
)


def empty_day_message(for_date: date) -> str:
    return EMPTY_DAY_MESSAGES[for_date.toordinal() % len(EMPTY_DAY_MESSAGES)]


def oxford_join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _describe_occurrence(event: CalendarEvent, occurrence_start: datetime, tz: tzinfo) -> str:
    if event.is_all_day:
        return event.title
    local_start = occurrence_start.astimezone(tz)
    return f"{event.title} at {local_start.strftime('%H:%M')}"


async def _events_for_user_today(
    db: AsyncSession, user_id: uuid.UUID, local_date: date, tz: tzinfo
) -> list[str]:
    day_start_local = datetime.combine(local_date, datetime.min.time(), tzinfo=tz)
    day_end_local = day_start_local + timedelta(days=1)
    day_start = day_start_local.astimezone(UTC)
    day_end = day_end_local.astimezone(UTC)

    memberships = (
        await db.scalars(
            select(Membership).where(
                Membership.user_id == user_id, Membership.removed_at.is_(None)
            )
        )
    ).all()

    descriptions: list[tuple[datetime, str]] = []
    for membership in memberships:
        if not await is_feature_enabled(db, FeatureKey.calendar, membership.group_id):
            continue
        if not await is_feature_enabled(db, FeatureKey.notifications, membership.group_id):
            continue
        capabilities = await capabilities_for(db, membership)
        if Capability.calendar_view not in capabilities:
            continue
        view_all = Capability.calendar_view_all in capabilities

        events = (
            await db.scalars(
                select(CalendarEvent).where(
                    CalendarEvent.group_id == membership.group_id,
                    CalendarEvent.deleted_at.is_(None),
                    recurrence_candidate_filter(day_start, day_end),
                )
            )
        ).all()
        for event in events:
            if not view_all:
                if event.created_by != user_id and user_id not in await viewer_ids_for_event(
                    db, event
                ):
                    continue
            for occurrence_start, _occurrence_end in expand_occurrences(
                event, day_start, day_end
            ):
                description = _describe_occurrence(event, occurrence_start, tz)
                descriptions.append((occurrence_start, description))

    descriptions.sort(key=lambda item: item[0])
    return [description for _start, description in descriptions]


async def scan_due_briefings(db: AsyncSession, settings: Settings) -> None:
    now_utc = datetime.now(UTC)
    window_end_utc = now_utc + LOOKAHEAD

    pending = (
        await db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.topic == BRIEFING_TOPIC, OutboxEvent.processed_at.is_(None)
            )
        )
    ).all()
    already_queued = {(row.payload["user_id"], row.payload["date"]) for row in pending}

    prefs_rows = (
        await db.scalars(
            select(NotificationPreferences).where(
                NotificationPreferences.daily_briefing_enabled.is_(True)
            )
        )
    ).all()
    for prefs in prefs_rows:
        user = await db.get(User, prefs.user_id)
        if user is None:
            continue
        tz = effective_timezone(user.timezone, settings.default_timezone)
        now_local = now_utc.astimezone(tz)
        if prefs.briefing_days == BriefingDays.weekdays and now_local.weekday() > 4:
            continue
        scheduled_local = datetime.combine(now_local.date(), prefs.briefing_time, tzinfo=tz)
        window_end_local = window_end_utc.astimezone(tz)
        if not (scheduled_local <= now_local < window_end_local):
            continue
        key = (str(user.id), now_local.date().isoformat())
        if key in already_queued:
            continue
        db.add(
            OutboxEvent(
                topic=BRIEFING_TOPIC,
                payload={"user_id": key[0], "date": key[1]},
            )
        )
    await db.commit()


async def deliver_daily_briefing(
    db: AsyncSession, settings: Settings, user_id: str, date_iso: str
) -> None:
    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        return
    prefs = await get_or_create_preferences(db, user.id)
    if not prefs.daily_briefing_enabled:
        return  # disabled since this was scanned — do not send

    tz = effective_timezone(user.timezone, settings.default_timezone)
    local_date = date.fromisoformat(date_iso)
    descriptions = await _events_for_user_today(db, user.id, local_date, tz)

    if not descriptions and not prefs.empty_day_briefing_enabled:
        return

    body = f"{oxford_join(descriptions)}." if descriptions else empty_day_message(local_date)
    await notify(
        db,
        settings=settings,
        recipient_user_id=user.id,
        notification_type="daily_briefing",
        title="Your day at a glance",
        body=body,
        idempotency_key=f"briefing:{user_id}:{date_iso}",
        deep_link=target("home"),
    )
