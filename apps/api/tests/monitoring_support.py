"""Shared test support: seed fresh, healthy automated monitoring.

Since automated monitoring feeds the public status page, a service with no
fresh observation is reported "unknown", never "operational". Tests that
want to assert "this service is back to Operational once its incident is
resolved" first establish that monitoring genuinely says it is healthy.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import delete, update

from mykhaya.db import SessionFactory
from mykhaya.models import (
    MonitorComponent,
    MonitorObservation,
    MonitorTransition,
    OperationalHeartbeat,
)
from mykhaya.monitoring.engine import ensure_components


async def seed_healthy_monitoring(now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    async with SessionFactory() as db:
        await ensure_components(db)
        await db.execute(
            update(MonitorComponent).values(
                state="healthy",
                confidence="verified",
                enabled=True,
                # As if every vantage-dependent check had been validated live
                # and public reporting enabled (they start PCC-only).
                public_visible=True,
                last_checked_at=now,
                last_attempted_at=now,
                last_success_at=now,
                consecutive_failures=0,
                consecutive_successes=1,
            )
        )
        await db.merge(
            OperationalHeartbeat(
                service="monitoring", observed_at=now, last_success_at=now, safe_detail="test"
            )
        )
        await db.commit()


async def clear_monitoring() -> None:
    async with SessionFactory() as db:
        await db.execute(delete(MonitorTransition))
        await db.execute(delete(MonitorObservation))
        await db.execute(
            delete(OperationalHeartbeat).where(OperationalHeartbeat.service == "monitoring")
        )
        await db.execute(
            update(MonitorComponent).values(state="unknown", last_checked_at=None, confidence=None)
        )
        await db.commit()


@asynccontextmanager
async def healthy_monitoring() -> AsyncIterator[None]:
    await seed_healthy_monitoring()
    try:
        yield
    finally:
        await clear_monitoring()
