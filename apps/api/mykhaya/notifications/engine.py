"""The single Notification Engine dispatch point.

Every notification-producing module (calendar, household routines, birthdays,
invitations, and any future module) calls `notify()` instead of writing its own
delivery logic. No module should send email or push directly, or invent its own
reminder/notification scheduling — see docs/architecture/notification-engine.md.

Email is layered on top in a later stage (Stage 8) by extending `notify()` at the
marked extension point — callers do not change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import (
    Notification,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationPreferences,
    OutboxEvent,
    PushSubscription,
    User,
)
from mykhaya.notifications.deep_links import DeepLinkTarget
from mykhaya.notifications.quiet_hours import effective_timezone, is_within_quiet_hours

# Maps a notification_type's category to the NotificationPreferences toggle that gates
# it. Types not listed here are gated only by the channel-level toggles (push_enabled /
# in_app_enabled) — used for things like test sends that don't belong to a category.
PREFERENCE_GATES: dict[str, str] = {
    "event_reminder": "event_reminders_enabled",
    "event_invitation": "event_invitations_enabled",
    "event_updated": "event_changes_enabled",
    "event_cancelled": "event_changes_enabled",
    "household_routine_reminder": "household_reminders_enabled",
    "birthday_reminder": "household_reminders_enabled",
    "daily_briefing": "daily_briefing_enabled",
}


async def get_or_create_preferences(
    db: AsyncSession, user_id: uuid.UUID
) -> NotificationPreferences:
    prefs = await db.scalar(
        select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
    )
    if prefs is None:
        prefs = NotificationPreferences(user_id=user_id)
        db.add(prefs)
        await db.flush()
    return prefs


def _category_enabled(prefs: NotificationPreferences, notification_type: str) -> bool:
    attribute = PREFERENCE_GATES.get(notification_type)
    if attribute is None:
        return True
    return bool(getattr(prefs, attribute))


async def notify(
    db: AsyncSession,
    *,
    settings: Settings,
    recipient_user_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str,
    idempotency_key: str,
    group_id: uuid.UUID | None = None,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
    deep_link: DeepLinkTarget | None = None,
    is_critical: bool = False,
    timezone_override: str | None = None,
) -> Notification | None:
    """Dispatch a notification to a single recipient across their enabled channels.

    Idempotent: a second call with the same `idempotency_key` is a no-op (the unique
    constraint on NotificationDelivery.idempotency_key is the actual safety net, this
    check just avoids a needless failed-insert round trip under normal operation).
    Returns the created in-app Notification row, or None if nothing was delivered
    (channel disabled, category disabled).
    """
    prefs = await get_or_create_preferences(db, recipient_user_id)
    category_enabled = _category_enabled(prefs, notification_type)

    notification: Notification | None = None
    if prefs.in_app_enabled and category_enabled:
        in_app_key = f"{idempotency_key}:in_app"
        already_sent = await db.scalar(
            select(NotificationDelivery.id).where(
                NotificationDelivery.idempotency_key == in_app_key
            )
        )
        if already_sent is None:
            notification = Notification(
                recipient_user_id=recipient_user_id,
                group_id=group_id,
                notification_type=notification_type,
                title=title,
                body=body,
                related_entity_type=related_entity_type,
                related_entity_id=related_entity_id,
                deep_link=dict(deep_link) if deep_link else None,
            )
            db.add(notification)
            db.add(
                NotificationDelivery(
                    channel=NotificationChannel.in_app,
                    recipient_user_id=recipient_user_id,
                    notification_type=notification_type,
                    idempotency_key=in_app_key,
                    scheduled_at=datetime.now(UTC),
                    attempted_at=datetime.now(UTC),
                    status=NotificationDeliveryStatus.sent,
                )
            )

    if prefs.push_enabled and category_enabled:
        await _enqueue_push(
            db,
            settings=settings,
            prefs=prefs,
            recipient_user_id=recipient_user_id,
            notification_type=notification_type,
            title=title,
            body=body,
            idempotency_key=idempotency_key,
            deep_link=deep_link,
            is_critical=is_critical,
            timezone_override=timezone_override,
        )

    # Extension point (Stage 8): if the notification_type also has an email rendering
    # and the recipient has no push/in-app enabled (or the type is inherently
    # email-only, e.g. verification/reset), enqueue OutboxEvent(topic=
    # "notification.email", idempotency_key=f"{idempotency_key}:email", ...).

    return notification


async def _enqueue_push(
    db: AsyncSession,
    *,
    settings: Settings,
    prefs: NotificationPreferences,
    recipient_user_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str,
    idempotency_key: str,
    deep_link: DeepLinkTarget | None,
    is_critical: bool,
    timezone_override: str | None,
) -> None:
    if not is_critical or not prefs.quiet_hours_critical_only:
        user = await db.get(User, recipient_user_id)
        tz = effective_timezone(
            timezone_override or (user.timezone if user else None), settings.default_timezone
        )
        now_local = datetime.now(UTC).astimezone(tz).time()
        if is_within_quiet_hours(prefs, now_local) and not is_critical:
            return

    subscriptions = (
        await db.scalars(
            select(PushSubscription).where(
                PushSubscription.user_id == recipient_user_id,
                PushSubscription.disabled_at.is_(None),
            )
        )
    ).all()
    for subscription in subscriptions:
        push_key = f"{idempotency_key}:push:{subscription.id}"
        already_queued = await db.scalar(
            select(NotificationDelivery.id).where(NotificationDelivery.idempotency_key == push_key)
        )
        if already_queued is not None:
            continue
        event = OutboxEvent(
            topic="notification.push",
            payload={
                "push_subscription_id": str(subscription.id),
                "title": title,
                "body": body,
                "deep_link": dict(deep_link) if deep_link else None,
                "delivery_idempotency_key": push_key,
                "notification_type": notification_type,
                "recipient_user_id": str(recipient_user_id),
            },
        )
        db.add(event)
        await db.flush()
        db.add(
            NotificationDelivery(
                channel=NotificationChannel.push,
                recipient_user_id=recipient_user_id,
                notification_type=notification_type,
                idempotency_key=push_key,
                outbox_event_id=event.id,
                push_subscription_id=subscription.id,
                scheduled_at=datetime.now(UTC),
            )
        )
