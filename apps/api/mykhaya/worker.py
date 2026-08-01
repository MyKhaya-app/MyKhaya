import asyncio
import json
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.mailer import send_email
from mykhaya.models import (
    ActionToken,
    Invitation,
    OperationalHeartbeat,
    OutboxEvent,
    User,
    WorkerJobRecord,
)
from mykhaya.security import derived_token


async def process(event_id: uuid.UUID) -> None:
    settings = get_settings()
    async with SessionFactory() as db:
        event = await db.get(OutboxEvent, event_id)
        if event is None:
            return
        existing = await db.get(WorkerJobRecord, event_id)
        if existing and existing.status == "completed":
            return
        job = existing or WorkerJobRecord(
            id=event.id, outbox_event_id=event.id, topic=event.topic, status="running"
        )
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
                raw = derived_token(
                    invitation.id, "invitation", settings.secret_key.get_secret_value()
                )
                await asyncio.to_thread(
                    send_email,
                    settings,
                    invitation.email,
                    "You are invited to a MyKhaya Home",
                    "Someone has invited you to their Home. Open this secure link:\n\n"
                    f"{settings.public_web_url}/register?invitation={raw}",
                )
            job.status = "completed"
            job.finished_at = datetime.now(UTC)
        except Exception as exc:
            job.status = "failed"
            job.attempts += 1
            job.error = type(exc).__name__[:500]
            job.finished_at = datetime.now(UTC)
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
