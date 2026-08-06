"""Birthdays: a first-class household concept, not just another recurring reminder.
Folded into the same durable scan/deliver pattern as household routines, but with
their own visibility rule — a child's birthday only surfaces if a guardian has
explicitly turned on `ChildProfile.birthday_visible` (default off, matching the
existing restrictive-by-default child-permission pattern) — and their own recipient
shape: the birthday person (adults only; children have no login) gets a "Happy
Birthday" message, everyone else in their household(s) gets a "it's their birthday"
message. See mykhaya.notifications.birthday_occurrences for the date math.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.features import is_feature_enabled
from mykhaya.models import ChildProfile, FeatureKey, Membership, OutboxEvent, User
from mykhaya.notifications.birthday_occurrences import is_birthday_date
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify
from mykhaya.notifications.quiet_hours import effective_timezone, home_timezone

LOOKAHEAD = timedelta(minutes=2)
BIRTHDAY_TOPIC = "notification.birthday"
SEND_TIME = time(7, 30)


async def _user_household_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = (
        await db.scalars(
            select(Membership.group_id).where(
                Membership.user_id == user_id, Membership.removed_at.is_(None)
            )
        )
    ).all()
    return set(rows)


async def scan_due_birthdays(db: AsyncSession, settings: Settings) -> None:
    now_utc = datetime.now(UTC)
    window_end_utc = now_utc + LOOKAHEAD

    pending = (
        await db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.topic == BIRTHDAY_TOPIC, OutboxEvent.processed_at.is_(None)
            )
        )
    ).all()
    already_queued = {
        (row.payload["owner_type"], row.payload["owner_id"], row.payload["year"])
        for row in pending
    }

    def maybe_enqueue(owner_type: str, owner_id: uuid.UUID, today_local: date) -> None:
        key = (owner_type, str(owner_id), today_local.year)
        if key in already_queued:
            return
        db.add(
            OutboxEvent(
                topic=BIRTHDAY_TOPIC,
                payload={"owner_type": key[0], "owner_id": key[1], "year": key[2]},
            )
        )

    users = (
        await db.scalars(
            select(User).where(User.birth_month.isnot(None), User.birth_day.isnot(None))
        )
    ).all()
    for user in users:
        assert user.birth_month is not None and user.birth_day is not None
        household_ids = await _user_household_ids(db, user.id)
        notifications_enabled = False
        for group_id in household_ids:
            if await is_feature_enabled(db, FeatureKey.notifications, group_id):
                notifications_enabled = True
                break
        if not notifications_enabled:
            continue
        tz = effective_timezone(user.timezone, settings.default_timezone)
        now_local = now_utc.astimezone(tz)
        if not is_birthday_date(user.birth_month, user.birth_day, now_local.date()):
            continue
        scheduled_local = datetime.combine(now_local.date(), SEND_TIME, tzinfo=tz)
        window_end_local = window_end_utc.astimezone(tz)
        if scheduled_local <= now_local < window_end_local:
            maybe_enqueue("user", user.id, now_local.date())

    children = (
        await db.scalars(
            select(ChildProfile).where(
                ChildProfile.birthday_visible.is_(True),
                ChildProfile.birth_month.isnot(None),
                ChildProfile.birth_day.isnot(None),
            )
        )
    ).all()
    for child in children:
        assert child.birth_month is not None and child.birth_day is not None
        membership = await db.get(Membership, child.membership_id)
        if membership is None or membership.removed_at is not None:
            continue
        if not await is_feature_enabled(db, FeatureKey.notifications, membership.group_id):
            continue
        tz = await home_timezone(db, membership.group_id, settings.default_timezone)
        now_local = now_utc.astimezone(tz)
        if not is_birthday_date(child.birth_month, child.birth_day, now_local.date()):
            continue
        scheduled_local = datetime.combine(now_local.date(), SEND_TIME, tzinfo=tz)
        window_end_local = window_end_utc.astimezone(tz)
        if scheduled_local <= now_local < window_end_local:
            maybe_enqueue("child", child.id, now_local.date())

    await db.commit()


async def deliver_birthday_reminder(
    db: AsyncSession, settings: Settings, owner_type: str, owner_id: str, year: int
) -> None:
    if owner_type == "user":
        await _deliver_user_birthday(db, settings, uuid.UUID(owner_id), year)
    elif owner_type == "child":
        await _deliver_child_birthday(db, settings, uuid.UUID(owner_id), year)


async def _deliver_user_birthday(
    db: AsyncSession, settings: Settings, user_id: uuid.UUID, year: int
) -> None:
    user = await db.get(User, user_id)
    if user is None or user.birth_month is None or user.birth_day is None:
        return
    tz = effective_timezone(user.timezone, settings.default_timezone)
    now_local_date = datetime.now(UTC).astimezone(tz).date()
    still_valid = now_local_date.year == year and is_birthday_date(
        user.birth_month, user.birth_day, now_local_date
    )
    if not still_valid:
        return  # no longer valid — birthday was cleared/changed since this was scanned

    idempotency_key = f"birthday:user:{user_id}:{year}"
    household_ids = await _user_household_ids(db, user_id)
    co_member_ids: set[uuid.UUID] = set()
    for group_id in household_ids:
        rows = (
            await db.scalars(
                select(Membership.user_id).where(
                    Membership.group_id == group_id, Membership.removed_at.is_(None)
                )
            )
        ).all()
        co_member_ids.update(rows)

    for recipient_id in co_member_ids:
        is_self = recipient_id == user_id
        title = "Happy Birthday!" if is_self else f"{user.display_name}'s birthday"
        body = (
            "Happy Birthday! We hope you have a wonderful day."
            if is_self
            else f"Today is {user.display_name}'s birthday."
        )
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type="birthday_reminder",
            title=title,
            body=body,
            idempotency_key=f"{idempotency_key}:{recipient_id}",
            related_entity_type="user",
            related_entity_id=user_id,
            deep_link=target("member", user_id),
        )


async def _deliver_child_birthday(
    db: AsyncSession, settings: Settings, child_id: uuid.UUID, year: int
) -> None:
    child = await db.get(ChildProfile, child_id)
    if child is None or not child.birthday_visible:
        return
    if child.birth_month is None or child.birth_day is None:
        return
    membership = await db.get(Membership, child.membership_id)
    if membership is None or membership.removed_at is not None:
        return
    tz = await home_timezone(db, membership.group_id, settings.default_timezone)
    now_local_date = datetime.now(UTC).astimezone(tz).date()
    still_valid = now_local_date.year == year and is_birthday_date(
        child.birth_month, child.birth_day, now_local_date
    )
    if not still_valid:
        return

    user = await db.get(User, membership.user_id)
    if user is None:
        return
    idempotency_key = f"birthday:child:{child_id}:{year}"
    recipients = (
        await db.scalars(
            select(Membership.user_id).where(
                Membership.group_id == membership.group_id, Membership.removed_at.is_(None)
            )
        )
    ).all()
    for recipient_id in recipients:
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type="birthday_reminder",
            title=f"{user.display_name}'s birthday",
            body=f"Today is {user.display_name}'s birthday.",
            idempotency_key=f"{idempotency_key}:{recipient_id}",
            group_id=membership.group_id,
            related_entity_type="child",
            related_entity_id=child_id,
            deep_link=target("member", membership.id),
        )
