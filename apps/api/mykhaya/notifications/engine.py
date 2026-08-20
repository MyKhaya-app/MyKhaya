"""The single Notification Engine dispatch point.

Every notification-producing module (calendar, household routines, birthdays,
invitations, account verification/reset, and any future module) calls `notify()`
instead of writing its own delivery logic. No module sends email or push directly, or
invents its own reminder/notification scheduling — see
docs/architecture/notification-engine.md. As of Stage 8, email is a full third channel
alongside push and in-app, not a special case: `mykhaya.mailer.send_email` is called
from exactly one place (`worker.py`'s `notification.email` handler), the same way
`mykhaya.notifications.push.send_push` is called from exactly one place.
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

# Notification types that must always be delivered by email regardless of any
# preference — account security and household-membership actions the recipient is
# actively waiting on, not an optional update. `notify()` still writes the normal
# NotificationDelivery diagnostic row for these, it just never suppresses them.
MANDATORY_EMAIL_TYPES = {
    "email_verification",
    "password_reset",
    "household_invitation",
    "platform_administrator_invitation",
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
    recipient_user_id: uuid.UUID | None = None,
    recipient_email: str | None = None,
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
    html_body: str | None = None,
    allow_email: bool = True,
) -> Notification | None:
    """Dispatch a notification to a single recipient across their enabled channels.

    Idempotent: a second call with the same `idempotency_key` is a no-op (the unique
    constraint on NotificationDelivery.idempotency_key is the actual safety net, this
    check just avoids a needless failed-insert round trip under normal operation).
    Returns the created in-app Notification row, or None if nothing was delivered
    (channel disabled, category disabled, or the type is email-only).

    `recipient_user_id` may be omitted only for a `MANDATORY_EMAIL_TYPES` notification
    with no MyKhaya account yet (a household invitation sent to an email address that
    hasn't registered) — `recipient_email` is required in that case. Every other caller
    passes `recipient_user_id`.
    """
    is_mandatory = notification_type in MANDATORY_EMAIL_TYPES

    if recipient_user_id is None:
        if not is_mandatory or not recipient_email:
            raise ValueError(
                "notify() requires recipient_user_id, unless notification_type is a "
                "MANDATORY_EMAIL_TYPES type sent with recipient_email (no account yet)"
            )
        await _enqueue_email(
            db,
            recipient_user_id=None,
            recipient_email=recipient_email,
            notification_type=notification_type,
            title=title,
            body=body,
            idempotency_key=idempotency_key,
            html_body=html_body,
        )
        return None

    prefs = await get_or_create_preferences(db, recipient_user_id)
    category_enabled = _category_enabled(prefs, notification_type)

    notification: Notification | None = None
    if not is_mandatory and prefs.in_app_enabled and category_enabled:
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

    if not is_mandatory and prefs.push_enabled and category_enabled:
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

    if allow_email and (is_mandatory or (prefs.email_enabled and category_enabled)):
        user = await db.get(User, recipient_user_id)
        resolved_email = recipient_email or (user.email if user else None)
        if resolved_email:
            await _enqueue_email(
                db,
                recipient_user_id=recipient_user_id,
                recipient_email=resolved_email,
                notification_type=notification_type,
                title=title,
                body=body,
                idempotency_key=idempotency_key,
                html_body=html_body,
            )

    return notification


async def _enqueue_email(
    db: AsyncSession,
    *,
    recipient_user_id: uuid.UUID | None,
    recipient_email: str,
    notification_type: str,
    title: str,
    body: str,
    idempotency_key: str,
    html_body: str | None = None,
) -> None:
    email_key = f"{idempotency_key}:email"
    already_queued = await db.scalar(
        select(NotificationDelivery.id).where(NotificationDelivery.idempotency_key == email_key)
    )
    if already_queued is not None:
        return
    event = OutboxEvent(
        topic="notification.email",
        payload={
            "recipient_email": recipient_email,
            "subject": title,
            "body": body,
            "html_body": html_body,
            "delivery_idempotency_key": email_key,
            "notification_type": notification_type,
        },
    )
    db.add(event)
    await db.flush()
    db.add(
        NotificationDelivery(
            channel=NotificationChannel.email,
            recipient_user_id=recipient_user_id,
            notification_type=notification_type,
            idempotency_key=email_key,
            outbox_event_id=event.id,
            scheduled_at=datetime.now(UTC),
        )
    )


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
