import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from pywebpush import WebPushException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.mailer import resolve_smtp_config, send_email
from mykhaya.models import (
    ActionToken,
    Group,
    Invitation,
    NotificationDelivery,
    NotificationDeliveryStatus,
    OperationalHeartbeat,
    OutboxEvent,
    PushSubscription,
    User,
    WorkerJobRecord,
)
from mykhaya.notifications.birthdays import deliver_birthday_reminder
from mykhaya.notifications.briefing import deliver_daily_briefing
from mykhaya.notifications.push import is_subscription_gone, resolve_push_config, send_push
from mykhaya.notifications.reminders import deliver_event_reminder
from mykhaya.notifications.routines import deliver_routine_reminder
from mykhaya.security import derived_token

# Bounded retry with exponential backoff. attempts=1 -> 30s, 2 -> 60s,
# 3 -> 120s ... capped at MAX_BACKOFF_SECONDS. After MAX_ATTEMPTS the event
# is marked processed (given up) so it stops being retried forever; the
# WorkerJobRecord row remains as the permanent diagnostic record of why.
MAX_ATTEMPTS = 8
BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 3600


def _backoff_seconds(attempts: int) -> int:
    delay = BASE_BACKOFF_SECONDS * (2 ** max(attempts - 1, 0))
    return int(min(delay, MAX_BACKOFF_SECONDS))


async def _process_push(db: AsyncSession, settings: Settings, event: OutboxEvent) -> None:
    delivery_key = event.payload["delivery_idempotency_key"]
    delivery = await db.scalar(
        select(NotificationDelivery).where(NotificationDelivery.idempotency_key == delivery_key)
    )
    subscription = await db.get(
        PushSubscription, uuid.UUID(event.payload["push_subscription_id"])
    )
    if delivery is None or subscription is None or subscription.disabled_at is not None:
        return  # already pruned or diagnostic record missing — nothing more to do

    push_config = await resolve_push_config(settings, db)
    payload = {
        "title": event.payload["title"],
        "body": event.payload["body"],
        "deep_link": event.payload.get("deep_link"),
        "notification_type": event.payload.get("notification_type"),
    }
    try:
        await asyncio.to_thread(send_push, push_config, subscription, payload)
        delivery.status = NotificationDeliveryStatus.sent
        delivery.attempted_at = datetime.now(UTC)
        subscription.last_seen_at = datetime.now(UTC)
    except WebPushException as exc:
        delivery.attempted_at = datetime.now(UTC)
        delivery.retry_count += 1
        if is_subscription_gone(exc):
            subscription.disabled_at = datetime.now(UTC)
            subscription.disabled_reason = (
                "Push service reported this subscription no longer exists."
            )
            delivery.status = NotificationDeliveryStatus.cancelled
            delivery.sanitised_failure_reason = "Device unsubscribed or expired."
            # Nothing more can be done for this subscription — do not re-raise, so the
            # outbox event is marked processed rather than retried forever.
        else:
            delivery.status = NotificationDeliveryStatus.failed
            delivery.sanitised_failure_reason = "Push service temporarily unavailable."
            raise
    except Exception:
        # A malformed/corrupted subscription (e.g. invalid stored keys) fails encoding
        # before any network call is even made — retrying it would fail identically
        # forever, so this is treated as permanent, the same as an expired subscription.
        delivery.attempted_at = datetime.now(UTC)
        delivery.retry_count += 1
        delivery.status = NotificationDeliveryStatus.cancelled
        delivery.sanitised_failure_reason = "This device's push registration is invalid."


async def process(event_id: uuid.UUID) -> None:
    settings = get_settings()
    async with SessionFactory() as db:
        event = await db.get(OutboxEvent, event_id)
        if event is None or event.processed_at is not None:
            return
        existing = await db.get(WorkerJobRecord, event_id)
        if existing and existing.status == "completed":
            return

        job = existing or WorkerJobRecord(
            id=event.id, outbox_event_id=event.id, topic=event.topic, status="running"
        )
        job.status = "running"
        job.finished_at = None
        job.error = None
        db.add(job)

        try:
            if event.topic.startswith("email."):
                smtp_config = await resolve_smtp_config(settings, db)
            if event.topic in {"email.verify", "email.reset"}:
                token = await db.get(ActionToken, uuid.UUID(event.payload["token_id"]))
                if token is None:
                    raise ValueError("action token not found")
                user = await db.get(User, token.user_id)
                if user is None:
                    raise ValueError("user not found")
                raw = derived_token(
                    token.id, token.purpose.value, settings.secret_key.get_secret_value()
                )
                page = "verify-email" if event.topic == "email.verify" else "reset-password"
                subject = (
                    "Verify your MyKhaya email"
                    if event.topic == "email.verify"
                    else "Reset your MyKhaya password"
                )
                await asyncio.to_thread(
                    send_email,
                    smtp_config,
                    user.email,
                    subject,
                    f"Open this secure link:\n\n{settings.public_web_url}/{page}?token={raw}\n\n"
                    "If you did not request this, you can ignore it.",
                )
            elif event.topic == "email.invitation":
                invitation = await db.get(Invitation, uuid.UUID(event.payload["invitation_id"]))
                if invitation is None:
                    raise ValueError("invitation not found")
                home = await db.get(Group, invitation.group_id)
                inviter = await db.get(User, invitation.invited_by)
                if home is None or inviter is None:
                    raise ValueError("invitation context not found")
                raw = derived_token(
                    invitation.id, "invitation", settings.secret_key.get_secret_value()
                )
                await asyncio.to_thread(
                    send_email,
                    smtp_config,
                    invitation.email,
                    "You are invited to a MyKhaya Home",
                    f"{inviter.display_name} invited you to join {home.name}.\n\n"
                    "Use this secure link to accept the invitation:\n\n"
                    f"{settings.public_web_url}/register?invitation={raw}\n\n"
                    f"This invitation expires on {invitation.expires_at.isoformat()}.\n\n"
                    "If you were not expecting this invitation, you can ignore this email.",
                )
            elif event.topic == "notification.push":
                await _process_push(db, settings, event)
            elif event.topic == "notification.event_reminder":
                await deliver_event_reminder(
                    db,
                    settings,
                    event.payload["event_id"],
                    event.payload["occurrence_start"],
                    event.payload["reminder_minutes"],
                )
            elif event.topic == "notification.daily_briefing":
                await deliver_daily_briefing(
                    db, settings, event.payload["user_id"], event.payload["date"]
                )
            elif event.topic == "notification.household_routine":
                await deliver_routine_reminder(
                    db,
                    settings,
                    event.payload["routine_id"],
                    event.payload["occurrence_date"],
                    event.payload["timing"],
                )
            elif event.topic == "notification.birthday":
                await deliver_birthday_reminder(
                    db,
                    settings,
                    event.payload["owner_type"],
                    event.payload["owner_id"],
                    event.payload["year"],
                )

            job.status = "completed"
            job.finished_at = datetime.now(UTC)
            event.processed_at = datetime.now(UTC)
        except Exception as exc:
            job.status = "failed"
            job.attempts += 1
            job.error = type(exc).__name__[:500]
            job.finished_at = datetime.now(UTC)
            event.attempts += 1
            event.last_error = type(exc).__name__[:500]
            if event.attempts >= MAX_ATTEMPTS:
                # Give up for good: stop the row being selected again, but
                # leave the WorkerJobRecord as the permanent diagnostic
                # record of the last failure.
                event.processed_at = datetime.now(UTC)
            else:
                event.available_at = datetime.now(UTC) + timedelta(
                    seconds=_backoff_seconds(event.attempts)
                )
            await db.commit()
            raise

        await db.commit()


async def run() -> None:
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        while True:
            item = await redis.blpop("mykhaya:jobs", timeout=5)
            async with SessionFactory() as db:
                await db.merge(
                    OperationalHeartbeat(
                        service="worker",
                        observed_at=datetime.now(UTC),
                        last_success_at=datetime.now(UTC),
                        safe_detail="Worker loop is active.",
                    )
                )
                await db.commit()
            if item:
                payload = json.loads(item[1])
                try:
                    await process(uuid.UUID(payload["event_id"]))
                except Exception:
                    await asyncio.sleep(2)
    finally:
        await redis.aclose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
