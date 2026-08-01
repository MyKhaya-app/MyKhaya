import asyncio
import json
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import OperationalHeartbeat, OutboxEvent


async def run() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        while True:
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
                    row.processed_at = datetime.now(UTC)
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
