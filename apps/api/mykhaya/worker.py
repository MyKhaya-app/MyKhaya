import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from pywebpush import WebPushException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.mailer import EmailPermanentError, EmailTemporaryError, resolve_smtp_config, send_email
from mykhaya.models import (
    NotificationDelivery,
    NotificationDeliveryStatus,
    OperationalHeartbeat,
    OutboxEvent,
    PushSubscription,
    WorkerJobRecord,
)
from mykhaya.notifications.birthdays import deliver_birthday_reminder
from mykhaya.notifications.briefing import deliver_daily_briefing
from mykhaya.notifications.push import is_subscription_gone, resolve_push_config, send_push
from mykhaya.notifications.reminders import deliver_event_reminder
from mykhaya.notifications.routines import deliver_routine_reminder
from mykhaya.notifications.standalone_reminders import deliver_standalone_reminder

log = structlog.get_logger()

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
    subscription = await db.get(PushSubscription, uuid.UUID(event.payload["push_subscription_id"]))
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


async def _process_email(db: AsyncSession, settings: Settings, event: OutboxEvent) -> None:
    delivery_key = event.payload["delivery_idempotency_key"]
    delivery = await db.scalar(
        select(NotificationDelivery).where(NotificationDelivery.idempotency_key == delivery_key)
    )
    if delivery is None:
        return  # diagnostic record missing — nothing more to do

    smtp_config = await resolve_smtp_config(settings, db)
    try:
        await asyncio.to_thread(
            send_email,
            smtp_config,
            event.payload["recipient_email"],
            event.payload["subject"],
            event.payload["body"],
            event.payload.get("html_body"),
        )
        delivery.status = NotificationDeliveryStatus.sent
        delivery.attempted_at = datetime.now(UTC)
    except EmailPermanentError as exc:
        delivery.attempted_at = datetime.now(UTC)
        delivery.retry_count += 1
        delivery.status = NotificationDeliveryStatus.cancelled
        delivery.sanitised_failure_reason = exc.category
        # Permanent (e.g. recipient/sender rejected) failures are never
        # retried — retrying a 5xx recipient rejection indefinitely wastes
        # sends and can itself hurt sender reputation. Not re-raised, so the
        # outbox event is marked processed rather than scheduled for retry.
    except EmailTemporaryError as exc:
        delivery.attempted_at = datetime.now(UTC)
        delivery.retry_count += 1
        delivery.status = NotificationDeliveryStatus.failed
        delivery.sanitised_failure_reason = exc.category
        raise
    except Exception:
        delivery.attempted_at = datetime.now(UTC)
        delivery.retry_count += 1
        delivery.status = NotificationDeliveryStatus.failed
        delivery.sanitised_failure_reason = "Email delivery temporarily unavailable."
        raise


async def process(event_id: uuid.UUID) -> None:
    settings = get_settings()
    async with SessionFactory() as db:
        # Serialize all workers attempting the same outbox row. Redis is only
        # transport; the database row lock is the durable execution claim.
        event = await db.scalar(
            select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update()
        )
        if event is None or event.processed_at is not None:
            return
        existing = await db.get(WorkerJobRecord, event_id)
        if existing and existing.status == "completed":
            return

        job = existing or WorkerJobRecord(
            id=event.id, outbox_event_id=event.id, topic=event.topic, status="running", attempts=0
        )
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.finished_at = None
        job.error = None
        db.add(job)

        try:
            if event.topic == "notification.email":
                await _process_email(db, settings, event)
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
            elif event.topic == "notification.standalone_reminder":
                await deliver_standalone_reminder(
                    db,
                    settings,
                    event.payload["reminder_id"],
                    event.payload["occurrence_date"],
                    event.payload["cadence"],
                    event.payload["slot"],
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
                except Exception as exc:
                    # process() already recorded the failure on the OutboxEvent/
                    # WorkerJobRecord rows and re-raised — this is the last chance
                    # to make it visible anywhere at all, since the loop must not
                    # die on one bad job. Previously this was a bare `except
                    # Exception: pass`-equivalent, which is why a large backlog of
                    # failing jobs (e.g. email delivery misconfiguration) could
                    # build up completely silently with nothing in the logs.
                    log.error(
                        "worker.job_failed",
                        event_id=str(payload.get("event_id")),
                        error=type(exc).__name__,
                    )
                    await asyncio.sleep(2)
    finally:
        await redis.aclose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
