import asyncio
import json
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import OperationalHeartbeat, OutboxEvent
from mykhaya.notifications.birthdays import scan_due_birthdays
from mykhaya.notifications.briefing import scan_due_briefings
from mykhaya.notifications.reminders import scan_due_reminders
from mykhaya.notifications.routines import scan_due_routines

# Visibility timeout: how long a dequeued-but-not-yet-completed job is hidden
# from re-selection. This is a lease, not completion — `processed_at` is only
# ever set by the worker on genuine success or permanent give-up (see
# worker.py). If the worker crashes mid-job, the lease simply expires and the
# row becomes selectable again without needing the worker to release it.
LEASE_SECONDS = 120


async def run() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        while True:
            async with SessionFactory() as db:
                # Durable scans — no in-memory timers. Each computes fresh from current
                # data and inserts idempotent outbox rows; see mykhaya/notifications/
                # reminders.py, briefing.py, routines.py and birthdays.py.
                await scan_due_reminders(db, settings)
                await scan_due_briefings(db, settings)
                await scan_due_routines(db, settings)
                await scan_due_birthdays(db, settings)
            async with SessionFactory() as db:
                rows = (
                    await db.scalars(
                        select(OutboxEvent)
                        .where(
                            OutboxEvent.processed_at.is_(None),
                            OutboxEvent.available_at <= datetime.now(UTC),
                        )
                        .order_by(OutboxEvent.created_at)
                        .limit(50)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                for row in rows:
                    await redis.rpush("mykhaya:jobs", json.dumps({"event_id": str(row.id)}))
                    row.available_at = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
                await db.merge(
                    OperationalHeartbeat(
                        service="scheduler",
                        observed_at=datetime.now(UTC),
                        last_success_at=datetime.now(UTC),
                        safe_detail="Scheduler cycle completed.",
                    )
                )
                await db.commit()
            await asyncio.sleep(2)
    finally:
        await redis.aclose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
