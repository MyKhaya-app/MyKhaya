"""Unified Nudges summaries built on the existing outbox/notification engine.

To-dos are included here because they have no independent reminder schedule. Existing
Routine and standalone Reminder scans remain authoritative for their own notifications;
this module only adds the calm daily summary and never creates duplicate per-item sends.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

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

LOOKAHEAD = timedelta(minutes=2)
EVENING_CLEANUP_TOPIC = "notification.nudges.evening_cleanup"
DAY_COMPLETE_TOPIC = "notification.nudges.day_complete"


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
