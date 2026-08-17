"""Daily morning briefing: a durable due-briefing scan plus worker-side content
generation. Content is computed fresh at delivery time from current data (not stored
hours earlier), reusing the exact same calendar visibility rules as the calendar API —
see mykhaya.notifications.visibility and mykhaya.calendar_occurrences.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from unicodedata import category

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.calendar_occurrences import expand_occurrences, recurrence_candidate_filter
from mykhaya.config import Settings
from mykhaya.features import is_feature_enabled
from mykhaya.household_permissions import Capability, capabilities_for
from mykhaya.models import (
    BriefingDays,
    CalendarEvent,
    ChildProfile,
    FeatureKey,
    Membership,
    NotificationPreferences,
    OutboxEvent,
    User,
)
from mykhaya.notifications.birthday_occurrences import is_birthday_date
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
MAX_DISPLAYED_EVENTS = 5


@dataclass(frozen=True)
class BriefingOccurrence:
    event_id: uuid.UUID
    title: str
    start_at: datetime
    is_all_day: bool


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


def _safe_push_text(value: str, *, max_length: int = 180) -> str:
    """Keep user-provided text on one safe, readable push-notification line."""
    cleaned = "".join(" " if category(char).startswith("C") else char for char in value)
    return " ".join(cleaned.split())[:max_length].strip() or "Untitled event"


def _briefing_event_line(occurrence: BriefingOccurrence, tz: tzinfo) -> str:
    title = _safe_push_text(occurrence.title)
    if occurrence.is_all_day:
        return f"• All day – {title}"
    local_start = occurrence.start_at.astimezone(tz)
    return f"• {local_start.strftime('%H:%M')} {title}"


def format_daily_briefing(
    occurrences: list[BriefingOccurrence],
    *,
    local_date: date,
    tz: tzinfo,
    birthday_phrases: list[str] | None = None,
) -> tuple[str, str]:
    """Build the stable title/body while keeping event ordering deterministic."""
    ordered = sorted(
        occurrences,
        key=lambda item: (
            item.start_at,
            _safe_push_text(item.title).casefold(),
            str(item.event_id),
        ),
    )
    count = len(ordered)
    title = f"You have {count} event{'s' if count != 1 else ''} today."
    lines = ["Please take care of yourself!"]

    # Birthdays are an existing briefing feature. Preserve them without allowing
    # display names to introduce control characters into the push payload.
    for phrase in birthday_phrases or []:
        safe_phrase = _safe_push_text(phrase).capitalize()
        lines.append(f"{safe_phrase}.")

    lines.extend(_briefing_event_line(item, tz) for item in ordered[:MAX_DISPLAYED_EVENTS])
    if count > MAX_DISPLAYED_EVENTS:
        lines.append(f"• +{count - MAX_DISPLAYED_EVENTS} more events")
    if not ordered and not (birthday_phrases or []):
        lines.append(empty_day_message(local_date))
    return title, "\n".join(lines)


async def _events_for_user_today(
    db: AsyncSession, user_id: uuid.UUID, local_date: date, tz: tzinfo
) -> list[BriefingOccurrence]:
    day_start_local = datetime.combine(local_date, datetime.min.time(), tzinfo=tz)
    day_end_local = day_start_local + timedelta(days=1)
    day_start = day_start_local.astimezone(UTC)
    day_end = day_end_local.astimezone(UTC)

    memberships = (
        await db.scalars(
            select(Membership).where(Membership.user_id == user_id, Membership.removed_at.is_(None))
        )
    ).all()

    occurrences: list[BriefingOccurrence] = []
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
            for occurrence_start, _occurrence_end in expand_occurrences(event, day_start, day_end):
                occurrences.append(
                    BriefingOccurrence(
                        event_id=event.id,
                        title=event.title,
                        start_at=occurrence_start,
                        is_all_day=event.is_all_day,
                    )
                )

    return occurrences


async def _birthdays_for_user_today(
    db: AsyncSession, user_id: uuid.UUID, local_date: date
) -> list[str]:
    """Birthdays are folded into the briefing sentence as a first-class item, not
    just another calendar occurrence — see mykhaya.notifications.birthdays."""
    memberships = (
        await db.scalars(
            select(Membership).where(Membership.user_id == user_id, Membership.removed_at.is_(None))
        )
    ).all()

    phrases: list[str] = []
    seen_child_ids: set[uuid.UUID] = set()
    for membership in memberships:
        if not await is_feature_enabled(db, FeatureKey.notifications, membership.group_id):
            continue

        co_members = (
            await db.scalars(
                select(Membership).where(
                    Membership.group_id == membership.group_id, Membership.removed_at.is_(None)
                )
            )
        ).all()
        for co_membership in co_members:
            user = await db.get(User, co_membership.user_id)
            if user is None or user.birth_month is None or user.birth_day is None:
                continue
            if not is_birthday_date(user.birth_month, user.birth_day, local_date):
                continue
            if user.id == user_id:
                phrases.append("it's your birthday")
            else:
                phrases.append(f"it's {user.display_name}'s birthday")

        co_members_by_id = {row.id: row for row in co_members}
        children = (
            await db.scalars(
                select(ChildProfile).where(
                    ChildProfile.membership_id.in_(co_members_by_id.keys()),
                    ChildProfile.birthday_visible.is_(True),
                )
            )
        ).all()
        for child in children:
            if child.id in seen_child_ids:
                continue
            if child.birth_month is None or child.birth_day is None:
                continue
            if not is_birthday_date(child.birth_month, child.birth_day, local_date):
                continue
            child_membership = co_members_by_id[child.membership_id]
            child_user = await db.get(User, child_membership.user_id)
            seen_child_ids.add(child.id)
            if child_user is not None:
                phrases.append(f"it's {child_user.display_name}'s birthday")

    return phrases


async def scan_due_briefings(db: AsyncSession, settings: Settings) -> None:
    now_utc = datetime.now(UTC)
    window_end_utc = now_utc + LOOKAHEAD

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
        # The unique durable key is the actual idempotency boundary. In-memory
        # or pending-row checks fail once the previous occurrence is processed,
        # and are racy when two scheduler instances scan concurrently.
        await db.execute(
            pg_insert(OutboxEvent)
            .values(
                topic=BRIEFING_TOPIC,
                payload={"user_id": key[0], "date": key[1]},
                dedupe_key=f"daily-briefing:{key[0]}:{key[1]}",
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
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
    birthday_phrases = await _birthdays_for_user_today(db, user.id, local_date)
    occurrences = await _events_for_user_today(db, user.id, local_date, tz)

    if not occurrences and not birthday_phrases and not prefs.empty_day_briefing_enabled:
        return

    title, body = format_daily_briefing(
        occurrences,
        local_date=local_date,
        tz=tz,
        birthday_phrases=birthday_phrases,
    )
    await notify(
        db,
        settings=settings,
        recipient_user_id=user.id,
        notification_type="daily_briefing",
        title=title,
        body=body,
        idempotency_key=f"briefing:{user_id}:{date_iso}",
        deep_link=target("calendar_today"),
    )
