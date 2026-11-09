"""Monitoring the monitor, from a different process.

The runner lives in the scheduler, so it cannot report its own death. The
worker calls ``watchdog_tick`` about once a minute: it reads the runner's
heartbeat and records a success or failure for the ``monitoring.runner``
component using the same state machine, transitions and alerts as every
other component. A stopped runner therefore produces a "Monitoring Stopped"
alert, and its return a "Monitoring Resumed" one.

If the scheduler is down, nothing moves outbox rows onto the Redis job
queue, so an alert email would sit unsent. While the scheduler heartbeat is
stale the watchdog dispatches pending *monitoring alert* emails itself
(same lease semantics as the scheduler, so nothing is sent twice).

Neither process can report a whole-host outage; that is what the optional
external dead-man's switch (settings.monitoring_watchdog_url) is for.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import cast

import structlog
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mykhaya.config import Settings
from mykhaya.db import SessionFactory
from mykhaya.models import MonitorComponent, OperationalHeartbeat, OutboxEvent
from mykhaya.monitoring import alerts
from mykhaya.monitoring.alerts import ALERT_NOTIFICATION_TYPE
from mykhaya.monitoring.catalogue import RUNNER_COMPONENT_KEY
from mykhaya.monitoring.engine import WATCHDOG_LOCK_KEY, apply_result, ensure_components
from mykhaya.monitoring.results import CheckResult
from mykhaya.monitoring.state import RUNNER_HEARTBEAT_SERVICE, RUNNER_STALE_SECONDS

log = structlog.get_logger()

TICK_INTERVAL = timedelta(seconds=60)
SCHEDULER_STALE_SECONDS = 60
LEASE_SECONDS = 120

_last_tick_at: datetime | None = None


async def runner_observation(db: AsyncSession, now: datetime) -> CheckResult:
    heartbeat = await db.get(OperationalHeartbeat, RUNNER_HEARTBEAT_SERVICE)
    if heartbeat is None:
        return CheckResult.failure(
            "heartbeat", "The monitoring runner has never completed a cycle."
        )
    age = int((now - heartbeat.observed_at).total_seconds())
    if age > RUNNER_STALE_SECONDS:
        return CheckResult.failure(
            "heartbeat",
            f"The monitoring runner last completed a cycle {age}s ago; "
            "service status is no longer being verified.",
        )
    return CheckResult.success(f"The monitoring runner completed a cycle {age}s ago.")


async def dispatch_alert_emails(db: AsyncSession, redis: Redis, now: datetime) -> int:
    """Queue only *monitoring alert* emails, selected in SQL: a backlog of
    ordinary customer emails (common precisely when processing has stalled)
    must never push an alert out of the batch."""
    rows = (
        await db.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.topic == "notification.email",
                OutboxEvent.processed_at.is_(None),
                OutboxEvent.available_at <= now,
                OutboxEvent.payload["notification_type"].as_string() == ALERT_NOTIFICATION_TYPE,
            )
            .order_by(OutboxEvent.created_at)
            .limit(200)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for row in rows:
        # redis-py types sync/async clients together; this is the async client.
        await cast(
            "Awaitable[int]", redis.rpush("mykhaya:jobs", json.dumps({"event_id": str(row.id)}))
        )
        row.available_at = now + timedelta(seconds=LEASE_SECONDS)
    return len(rows)


async def watchdog_tick(
    settings: Settings,
    *,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
    now: datetime | None = None,
    force: bool = False,
) -> bool:
    """Returns True when this call actually ran (it is throttled to once a
    minute per process, and to one process at a time via an advisory lock)."""
    global _last_tick_at
    if not settings.monitoring_enabled:
        return False
    now = now or datetime.now(UTC)
    if not force and _last_tick_at is not None and now - _last_tick_at < TICK_INTERVAL:
        return False
    _last_tick_at = now
    async with session_factory() as db:
        locked = await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": WATCHDOG_LOCK_KEY}
        )
        if not locked:
            return False
        await ensure_components(db)
        component = await db.scalar(
            select(MonitorComponent)
            .where(MonitorComponent.key == RUNNER_COMPONENT_KEY)
            .with_for_update()
        )
        if component is None or not component.enabled:
            await db.commit()
            return True
        result = await runner_observation(db, now)
        event = await apply_result(db, component, result, now, trigger="watchdog")
        if event is not None:
            await alerts.raise_for_transitions(db, settings, [event], now)
        scheduler = await db.get(OperationalHeartbeat, "scheduler")
        scheduler_stale = (
            scheduler is None
            or (now - scheduler.observed_at).total_seconds() > SCHEDULER_STALE_SECONDS
        )
        if scheduler_stale:
            await db.flush()
            dispatched = await dispatch_alert_emails(db, redis, now)
            if dispatched:
                log.warning("monitoring.watchdog_dispatched_alerts", count=dispatched)
        await db.commit()
    return True
