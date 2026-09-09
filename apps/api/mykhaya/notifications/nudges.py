"""Unified Nudges summaries built on the existing outbox/notification engine.

To-dos are included here because they have no independent reminder schedule. Existing
Routine and standalone Reminder scans remain authoritative for their own notifications;
this module only adds the calm daily summary and never creates duplicate per-item sends.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import (
    Group,
    HouseholdRoutine,
    HouseholdRoutineCompletion,
    HouseholdRoutineMember,
    Membership,
    NotificationPreferences,
    OutboxEvent,
    Reminder,
    ReminderCompletion,
    ReminderMember,
    ReminderRepeat,
    RoutineScope,
    Todo,
    TodoMember,
    User,
)
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import get_or_create_preferences, notify
from mykhaya.notifications.quiet_hours import effective_timezone
from mykhaya.notifications.reminder_occurrences import last_occurrence_on_or_before
from mykhaya.notifications.routine_occurrences import is_occurrence_date
from mykhaya.notifications.templates import render_notification

log = structlog.get_logger()

LOOKAHEAD = timedelta(minutes=2)
EVENING_CLEANUP_TOPIC = "notification.nudges.evening_cleanup"
DAY_COMPLETE_TOPIC = "notification.nudges.day_complete"
DAILY_SUMMARY_TOPIC = "notification.daily_nudge_summary"


async def relevant_todos(
    db: AsyncSession, user_id: uuid.UUID, local_date: date, *, outstanding_only: bool = True
) -> list[Todo]:
    memberships = (
        await db.scalars(
            select(Membership).where(Membership.user_id == user_id, Membership.removed_at.is_(None))
        )
    ).all()
    group_ids = [membership.group_id for membership in memberships]
    if not group_ids:
        return []
    rows = (
        await db.scalars(
            select(Todo).where(
                Todo.group_id.in_(group_ids),
                (Todo.scope == "personal") & (Todo.owner_user_id == user_id)
                | (Todo.scope == "household"),
                Todo.due_date <= local_date,
                Todo.completed_at.is_(None) if outstanding_only else True,
            )
        )
    ).all()
    result: list[Todo] = []
    for row in rows:
        if row.scope == "personal" and row.owner_user_id != user_id:
            continue
        assigned = set(
            (
                await db.scalars(select(TodoMember.user_id).where(TodoMember.todo_id == row.id))
            ).all()
        )
        if row.scope == "household" and assigned and user_id not in assigned:
            continue
        result.append(row)
    return result


async def _relevant_routines(
    db: AsyncSession, user_id: uuid.UUID, local_date: date
) -> list[HouseholdRoutine]:
    memberships = (
        await db.scalars(
            select(Membership).where(Membership.user_id == user_id, Membership.removed_at.is_(None))
        )
    ).all()
    rows = (
        await db.scalars(
            select(HouseholdRoutine)
            .join(Group, Group.id == HouseholdRoutine.group_id)
            .where(
                HouseholdRoutine.group_id.in_([row.group_id for row in memberships]),
                HouseholdRoutine.enabled.is_(True),
                Group.is_active.is_(True),
            )
        )
    ).all()
    result: list[HouseholdRoutine] = []
    for row in rows:
        if row.scope == RoutineScope.personal and row.owner_user_id != user_id:
            continue
        if row.scope == RoutineScope.household:
            assigned = set(
                (
                    await db.scalars(
                        select(HouseholdRoutineMember.user_id).where(
                            HouseholdRoutineMember.routine_id == row.id
                        )
                    )
                ).all()
            )
            if assigned and user_id not in assigned:
                continue
        if not is_occurrence_date(row, local_date):
            continue
        completed = await db.scalar(
            select(HouseholdRoutineCompletion.id).where(
                HouseholdRoutineCompletion.routine_id == row.id,
                HouseholdRoutineCompletion.occurrence_date == local_date,
            )
        )
        if completed is None:
            result.append(row)
    return result


async def _relevant_reminders(
    db: AsyncSession, user_id: uuid.UUID, local_date: date, *, evening: bool = False
) -> list[Reminder]:
    memberships = (
        await db.scalars(
            select(Membership).where(Membership.user_id == user_id, Membership.removed_at.is_(None))
        )
    ).all()
    rows = (
        await db.scalars(
            select(Reminder)
            .join(Group, Group.id == Reminder.group_id)
            .where(
                Reminder.group_id.in_([row.group_id for row in memberships]),
                Reminder.enabled.is_(True),
                Group.is_active.is_(True),
            )
        )
    ).all()
    result: list[Reminder] = []
    for row in rows:
        if evening and row.repeat == ReminderRepeat.never:
            continue
        if row.scope == RoutineScope.personal and row.owner_user_id != user_id:
            continue
        if row.scope == RoutineScope.household:
            assigned = set(
                (
                    await db.scalars(
                        select(ReminderMember.user_id).where(ReminderMember.reminder_id == row.id)
                    )
                ).all()
            )
            if assigned and user_id not in assigned:
                continue
        occurrence = last_occurrence_on_or_before(row, local_date)
        if occurrence is None:
            continue
        completed = await db.scalar(
            select(ReminderCompletion.id).where(
                ReminderCompletion.reminder_id == row.id,
                ReminderCompletion.occurrence_date == occurrence,
            )
        )
        if completed is None:
            result.append(row)
    return result


def _summary(rows: list[Todo], local_date: date) -> tuple[int, int, str]:
    overdue = sum(row.due_date < local_date for row in rows)
    lines = [f"• {row.title}" for row in rows[:5]]
    return len(rows), overdue, "\n".join(lines)


async def scan_due_nudges(db: AsyncSession, settings: Settings) -> None:
    now = datetime.now(UTC)
    prefs_rows = (
        await db.scalars(
            select(NotificationPreferences).where(
                or_(
                    NotificationPreferences.nudges_evening_cleanup_enabled.is_(True),
                    NotificationPreferences.nudges_day_complete_enabled.is_(True),
                )
            )
        )
    ).all()
    for prefs in prefs_rows:
        user = await db.get(User, prefs.user_id)
        if user is None or not user.is_active:
            continue
        tz = effective_timezone(user.timezone, settings.default_timezone)
        local_now = now.astimezone(tz)
        scheduled = datetime.combine(local_now.date(), prefs.nudges_evening_time, tzinfo=tz)
        if not (scheduled <= local_now < scheduled + LOOKAHEAD):
            continue
        rows = await relevant_todos(db, user.id, local_now.date())
        routines = await _relevant_routines(db, user.id, local_now.date())
        reminders = await _relevant_reminders(db, user.id, local_now.date(), evening=True)
        outstanding = rows or routines or reminders
        topic = EVENING_CLEANUP_TOPIC if outstanding else DAY_COMPLETE_TOPIC
        if not outstanding and not prefs.nudges_day_complete_enabled:
            continue
        date_iso = local_now.date().isoformat()
        await db.execute(
            pg_insert(OutboxEvent)
            .values(
                topic=topic,
                payload={"user_id": str(user.id), "date": date_iso},
                dedupe_key=f"{topic}:{user.id}:{date_iso}",
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )
    await db.commit()


async def deliver_nudge_summary(
    db: AsyncSession,
    settings: Settings,
    user_id: str,
    date_iso: str,
    *,
    day_complete: bool,
) -> None:
    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        return
    prefs = await get_or_create_preferences(db, user.id)
    if day_complete and not prefs.nudges_day_complete_enabled:
        return
    if not day_complete and not prefs.nudges_evening_cleanup_enabled:
        return
    local_date = date.fromisoformat(date_iso)
    rows = await relevant_todos(db, user.id, local_date)
    routines = await _relevant_routines(db, user.id, local_date)
    reminders = await _relevant_reminders(db, user.id, local_date, evening=True)
    outstanding = rows or routines or reminders
    if day_complete and outstanding:
        return
    if not day_complete and not outstanding:
        return
    count, overdue, todo_summary = _summary(rows, local_date)
    count += len(routines) + len(reminders)
    summary_lines = [f"• {item.title}" for item in routines[:3]]
    summary_lines.extend(f"• {item.title}" for item in reminders[:3])
    if todo_summary:
        summary_lines.extend(todo_summary.splitlines())
    summary = "\n".join(summary_lines[:5])
    template = "nudges.day_complete" if day_complete else "nudges.evening_cleanup"
    variables = {
        "first_name": user.display_name.split(" ", 1)[0],
        "outstanding_count": str(count),
        "completed_count": "0",
        "routine_count": str(len(routines)),
        "todo_count": str(len(rows)),
        "reminder_count": str(len(reminders)),
        "overdue_count": str(overdue),
        "summary": summary,
        "deep_link": "/settings/routines-reminders",
    }
    title, body = await render_notification(db, template, variables)
    await notify(
        db,
        settings=settings,
        recipient_user_id=user.id,
        notification_type="nudges_day_complete" if day_complete else "nudges_evening_cleanup",
        title=title,
        body=body,
        idempotency_key=f"nudges:{'complete' if day_complete else 'cleanup'}:{user.id}:{date_iso}",
        deep_link=target("nudges"),
    )


# --- Daily Nudge Summary -----------------------------------------------------
# A separate, user-configurable *morning* summary — "what do I need to do
# today?" — distinct from Daily Briefing ("what is happening today?", see
# mykhaya.notifications.briefing) and from the *evening* nudges above ("what's
# still outstanding tonight?"). Same scan-to-outbox / worker-delivers pattern
# as every other notification type in this package; own preference fields
# (NotificationPreferences.daily_nudge_summary_enabled/_time), own topic, own
# notification_type, own idempotency key — never merged with either sibling.


def _count_phrase(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


async def scan_due_daily_nudge_summary(db: AsyncSession, settings: Settings) -> None:
    now_utc = datetime.now(UTC)
    window_end_utc = now_utc + LOOKAHEAD

    prefs_rows = (
        await db.scalars(
            select(NotificationPreferences).where(
                NotificationPreferences.daily_nudge_summary_enabled.is_(True)
            )
        )
    ).all()
    for prefs in prefs_rows:
        user = await db.get(User, prefs.user_id)
        if user is None or not user.is_active:
            continue
        tz = effective_timezone(user.timezone, settings.default_timezone)
        now_local = now_utc.astimezone(tz)
        scheduled_local = datetime.combine(
            now_local.date(), prefs.daily_nudge_summary_time, tzinfo=tz
        )
        window_end_local = window_end_utc.astimezone(tz)
        if not (scheduled_local <= now_local < window_end_local):
            continue
        date_iso = now_local.date().isoformat()
        # The unique durable dedupe_key is the actual idempotency boundary —
        # see scan_due_briefings' identical comment. Safe under overlapping
        # scheduler iterations, worker restarts, and multiple processes.
        await db.execute(
            pg_insert(OutboxEvent)
            .values(
                topic=DAILY_SUMMARY_TOPIC,
                payload={"user_id": str(user.id), "date": date_iso},
                dedupe_key=f"daily-nudge-summary:{user.id}:{date_iso}",
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )
    await db.commit()


async def deliver_daily_nudge_summary(
    db: AsyncSession, settings: Settings, user_id: str, date_iso: str
) -> None:
    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        return  # gone, or Disabled/Archived since this was scanned
    prefs = await get_or_create_preferences(db, user.id)
    if not prefs.daily_nudge_summary_enabled:
        return  # disabled since this was scanned — do not send

    local_date = date.fromisoformat(date_iso)
    tz = effective_timezone(user.timezone, settings.default_timezone)
    routines = await _relevant_routines(db, user.id, local_date)
    reminders = await _relevant_reminders(db, user.id, local_date)
    todos = await relevant_todos(db, user.id, local_date)

    if not routines and not reminders and not todos:
        # Deliberately no "0 routines, 0 to-dos, 0 reminders" send — an empty
        # day produces no Daily Nudge Summary at all (Daily Briefing has its
        # own, separate empty-day rule and is unaffected by this).
        await log.ainfo(
            "daily_nudge_summary_skipped_empty",
            user_id=user_id,
            local_date=date_iso,
            timezone=str(tz),
        )
        return

    routine_count, reminder_count, todo_count = len(routines), len(reminders), len(todos)
    count_summary = (
        f"{_count_phrase(routine_count, 'routine')}, {_count_phrase(todo_count, 'to-do')} "
        f"and {_count_phrase(reminder_count, 'reminder')}"
    )
    item_summary = "\n".join(
        (
            *(f"• {item.title}" for item in routines),
            *(f"• {item.title}" for item in reminders),
            *(f"• {item.title}" for item in todos),
        )[:5]
    )
    title, body = await render_notification(
        db,
        "daily_nudge_summary",
        {
            "user_display_name": user.display_name,
            "routine_count": str(routine_count),
            "todo_count": str(todo_count),
            "reminder_count": str(reminder_count),
            "total_count": str(routine_count + todo_count + reminder_count),
            "count_summary": count_summary,
            "item_summary": item_summary,
            "delivery_date": local_date.isoformat(),
            "deep_link": "/settings/routines-reminders",
        },
    )
    notification = await notify(
        db,
        settings=settings,
        recipient_user_id=user.id,
        notification_type="daily_nudge_summary",
        title=title,
        body=body,
        idempotency_key=f"daily-nudge-summary:{user_id}:{date_iso}",
        deep_link=target("nudges"),
    )
    await log.ainfo(
        "daily_nudge_summary_delivered",
        user_id=user_id,
        local_date=date_iso,
        timezone=str(tz),
        routine_count=routine_count,
        reminder_count=reminder_count,
        todo_count=todo_count,
        notification_id=str(notification.id) if notification else None,
    )


async def is_covered_by_daily_nudge_summary(
    db: AsyncSession,
    settings: Settings,
    *,
    recipient_id: uuid.UUID,
    item_scheduled_utc: datetime,
    kind: str,
    item_id: uuid.UUID,
) -> bool:
    """True if `recipient_id` has an enabled Daily Nudge Summary scheduled for
    the same canonical local occurrence as `item_scheduled_utc`, AND the
    given routine/reminder is one of the items that summary would include
    right now — i.e. sending the individual notification for this specific
    occurrence would be pure duplicate noise on top of the summary.

    Deliberately identifier-based, never title/body string matching:
    `kind`+`item_id` are checked against the same canonical
    `_relevant_routines`/`_relevant_reminders` queries the summary itself
    uses. The occurrence match itself is an exact same-minute comparison
    between the item's configured local time and the recipient's configured
    `daily_nudge_summary_time` — both are minute-precision stored settings
    (a routine's fixed same-day time, a reminder's due_time, the summary's
    delivery time), not "now" vs. a moving scan cursor, so there is no
    tolerance window here. LOOKAHEAD elsewhere in this package is a
    *scanner* polling-resolution constant (how far ahead a scan cycle looks
    for what just became due) and is deliberately NOT reused for this
    comparison — a scheduler implementation detail must not silently become
    a several-minute-wide product suppression window. An item scheduled a
    few minutes either side of the summary time is a different occurrence
    and must not be suppressed.

    Callers are expected to only consult this for an item's *first* send of
    the day (routines have only one same-day slot; standalone reminders
    should only check this at cadence slot 0) — a later repeat/escalation
    slot must never be suppressed, so this function is simply not called for
    those, rather than trying to encode "first occurrence only" here.
    """
    prefs = await get_or_create_preferences(db, recipient_id)
    if not prefs.daily_nudge_summary_enabled:
        return False
    user = await db.get(User, recipient_id)
    if user is None:
        return False
    tz = effective_timezone(user.timezone, settings.default_timezone)
    item_local = item_scheduled_utc.astimezone(tz)
    item_minute = item_local.time().replace(second=0, microsecond=0)
    summary_minute = prefs.daily_nudge_summary_time.replace(second=0, microsecond=0)
    if item_minute != summary_minute:
        return False

    local_date = item_local.date()
    covered_ids: set[uuid.UUID]
    if kind == "routine":
        covered_ids = {row.id for row in await _relevant_routines(db, recipient_id, local_date)}
    elif kind == "reminder":
        covered_ids = {row.id for row in await _relevant_reminders(db, recipient_id, local_date)}
    else:
        return False
    return item_id in covered_ids
