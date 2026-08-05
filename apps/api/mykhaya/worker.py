import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.mailer import send_email
from mykhaya.models import (
    ActionToken,
    Group,
    Invitation,
    OperationalHeartbeat,
    OutboxEvent,
    User,
    WorkerJobRecord,
)
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
                    settings,
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
                    settings,
                    invitation.email,
                    "You are invited to a MyKhaya Home",
                    f"{inviter.display_name} invited you to join {home.name}.\n\n"
                    "Use this secure link to accept the invitation:\n\n"
                    f"{settings.public_web_url}/register?invitation={raw}\n\n"
                    f"This invitation expires on {invitation.expires_at.isoformat()}.\n\n"
                    "If you were not expecting this invitation, you can ignore this email.",
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
