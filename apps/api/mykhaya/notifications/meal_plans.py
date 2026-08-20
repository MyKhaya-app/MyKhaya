"""Meal Plan notification copy, recipient resolution, and briefing items.

This module deliberately contains no delivery or scheduling code. Immediate
notifications use the shared notification engine, while briefing items are
queried by the existing daily briefing composer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, time
from unicodedata import category

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.features import is_feature_enabled
from mykhaya.models import (
    FeatureKey,
    Meal,
    MealPlanEntry,
    MealPlanParticipant,
    Membership,
    User,
)
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify


def _safe_text(value: str, fallback: str = "Meal") -> str:
    cleaned = "".join(" " if category(char).startswith("C") else char for char in value)
    return " ".join(cleaned.split())[:160].strip() or fallback


def meal_name(entry: MealPlanEntry, meal: Meal | None) -> str:
    return _safe_text(meal.name if meal is not None else (entry.quick_meal_name or "Meal"))


def _slot(entry: MealPlanEntry) -> str:
    return entry.meal_slot.value.capitalize()


def _date_label(entry_date: date, today: date | None = None) -> str:
    if today == entry_date:
        return "today"
    return entry_date.strftime("%A")


def _time_label(value: time | None) -> str:
    return f" at {value.strftime('%H:%M')}" if value is not None else ""


def created_copy(
    entry: MealPlanEntry, meal: Meal | None, *, today: date | None = None
) -> tuple[str, str]:
    name = meal_name(entry, meal)
    title = f"{_slot(entry)} planned for {_date_label(entry.date, today)}"
    return title, f"{name}{_time_label(entry.time)}"


def updated_copy(
    entry: MealPlanEntry, meal: Meal | None, *, today: date | None = None
) -> tuple[str, str]:
    name = meal_name(entry, meal)
    title = f"{_date_label(entry.date, today).capitalize()}'s {_slot(entry).lower()} changed"
    return title, f"{name}{_time_label(entry.time)}"


def removed_copy(
    entry: MealPlanEntry, meal: Meal | None, *, today: date | None = None
) -> tuple[str, str]:
    title = f"{_date_label(entry.date, today).capitalize()}'s {_slot(entry).lower()} was removed"
    return title, meal_name(entry, meal)


async def _eligible_recipients(
    db: AsyncSession, entry: MealPlanEntry, candidates: set[uuid.UUID]
) -> set[uuid.UUID]:
    if not candidates or not await is_feature_enabled(db, FeatureKey.notifications, entry.group_id):
        return set()
    return set(
        (
            await db.scalars(
                select(Membership.user_id).where(
                    Membership.group_id == entry.group_id,
                    Membership.removed_at.is_(None),
                    Membership.user_id.in_(candidates),
                )
            )
        ).all()
    )


async def _notify_recipients(
    db: AsyncSession,
    settings: Settings,
    entry: MealPlanEntry,
    meal: Meal | None,
    recipients: set[uuid.UUID],
    actor_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str,
    version_key: str,
) -> None:
    for recipient_id in await _eligible_recipients(db, entry, recipients):
        if recipient_id == actor_id:
            continue
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type=notification_type,
            title=title,
            body=body,
            idempotency_key=f"meal_plan:{notification_type}:{entry.id}:{recipient_id}:{version_key}",
            group_id=entry.group_id,
            related_entity_type="meal_plan_entry",
            related_entity_id=entry.id,
            deep_link=target("meal_plan", entry.id),
            allow_email=False,
        )


async def participant_ids(db: AsyncSession, entry_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        (
            await db.scalars(
                select(MealPlanParticipant.user_id).where(
                    MealPlanParticipant.meal_plan_entry_id == entry_id
                )
            )
        ).all()
    )


def recipients(entry: MealPlanEntry, participant_ids_: set[uuid.UUID]) -> set[uuid.UUID]:
    return participant_ids_ | ({entry.cook_member_id} if entry.cook_member_id else set())


async def _with_cook(db: AsyncSession, entry: MealPlanEntry, body: str) -> str:
    if entry.cook_member_id is None:
        return body
    cook = await db.get(User, entry.cook_member_id)
    if cook is None:
        return body
    return f"{body}\n{_safe_text(cook.display_name, 'A household member')} is cooking"


async def notify_created(
    db: AsyncSession,
    settings: Settings,
    entry: MealPlanEntry,
    meal: Meal | None,
    actor_id: uuid.UUID,
) -> None:
    title, body = created_copy(entry, meal)
    body = await _with_cook(db, entry, body)
    await _notify_recipients(
        db, settings, entry, meal, recipients(entry, await participant_ids(db, entry.id)), actor_id,
        "meal_plan_created", title, body, str(entry.updated_at)
    )


async def notify_updated(
    db: AsyncSession,
    settings: Settings,
    entry: MealPlanEntry,
    meal: Meal | None,
    actor_id: uuid.UUID,
    before_participants: set[uuid.UUID],
    before_cook: uuid.UUID | None,
    material_change: bool,
) -> None:
    after_participants = await participant_ids(db, entry.id)
    before = before_participants | ({before_cook} if before_cook else set())
    after = recipients(entry, after_participants)
    title, body = updated_copy(entry, meal)
    body = await _with_cook(db, entry, body)
    version_key = str(entry.updated_at)
    if material_change:
        await _notify_recipients(db, settings, entry, meal, after - before, actor_id,
                                 "meal_plan_updated", title, body, version_key)
        await _notify_recipients(db, settings, entry, meal, after & before, actor_id,
                                 "meal_plan_updated", title, body, version_key)
    removed = before - after
    removed_title, removed_body = f"You're no longer included in {title.lower()}", body
    await _notify_recipients(db, settings, entry, meal, removed, actor_id,
                             "meal_plan_removed", removed_title, removed_body, version_key)


async def notify_removed(
    db: AsyncSession, settings: Settings, entry: MealPlanEntry, meal: Meal | None,
    actor_id: uuid.UUID, prior_participants: set[uuid.UUID], prior_cook: uuid.UUID | None,
) -> None:
    title, body = removed_copy(entry, meal)
    body = await _with_cook(db, entry, body)
    await _notify_recipients(
        db, settings, entry, meal,
        prior_participants | ({prior_cook} if prior_cook else set()), actor_id,
        "meal_plan_removed", title, body, str(entry.id)
    )


@dataclass(frozen=True)
class MealBriefingItem:
    entry_id: uuid.UUID
    slot: str
    name: str
    meal_time: time | None
    is_cooking: bool
    cook_name: str | None


async def briefing_items_for_user(
    db: AsyncSession, user_id: uuid.UUID, local_date: date
) -> list[MealBriefingItem]:
    memberships = (
        await db.scalars(
            select(Membership).where(Membership.user_id == user_id, Membership.removed_at.is_(None))
        )
    ).all()
    group_ids = [
        row.group_id
        for row in memberships
        if await is_feature_enabled(db, FeatureKey.meals, row.group_id)
    ]
    if not group_ids:
        return []
    rows = (
        await db.execute(
            select(MealPlanEntry, Meal)
            .join(Meal, Meal.id == MealPlanEntry.meal_id, isouter=True)
            .where(
                MealPlanEntry.group_id.in_(group_ids),
                MealPlanEntry.date == local_date,
                MealPlanEntry.deleted_at.is_(None),
                or_(
                    MealPlanEntry.cook_member_id == user_id,
                    MealPlanEntry.id.in_(
                        select(MealPlanParticipant.meal_plan_entry_id).where(
                            MealPlanParticipant.user_id == user_id
                        )
                    ),
                ),
            )
            .order_by(
                case(
                    (MealPlanEntry.meal_slot == "breakfast", 0),
                    (MealPlanEntry.meal_slot == "lunch", 1),
                    else_=2,
                ),
                MealPlanEntry.time,
                MealPlanEntry.id,
            )
        )
    ).all()
    cook_ids = {entry.cook_member_id for entry, _meal in rows if entry.cook_member_id}
    cooks = {
        user.id: user.display_name
        for user in (await db.scalars(select(User).where(User.id.in_(cook_ids)))).all()
    } if cook_ids else {}
    return [
        MealBriefingItem(
            entry_id=entry.id,
            slot=entry.meal_slot.value.capitalize(),
            name=meal_name(entry, meal),
            meal_time=entry.time,
            is_cooking=entry.cook_member_id == user_id,
            cook_name=cooks.get(entry.cook_member_id) if entry.cook_member_id != user_id else None,
        )
        for entry, meal in rows
    ]
