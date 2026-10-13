import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.calendar_highlights import sync_due_holiday_sources
from mykhaya.config import Settings, get_settings
from mykhaya.crypto.config import validate_sensitive_key_configuration
from mykhaya.db import SessionFactory
from mykhaya.family_retention import scan_family_retention
from mykhaya.home_migration_pcc import purge_expired_packages
from mykhaya.managed_demo_homes import ManagedDemoService
from mykhaya.models import OperationalHeartbeat, OutboxEvent, PlatformSetting
from mykhaya.notifications.birthdays import scan_due_birthdays
from mykhaya.notifications.briefing import scan_due_briefings
from mykhaya.notifications.nudges import scan_due_daily_nudge_summary, scan_due_nudges
from mykhaya.notifications.reminders import scan_due_reminders
from mykhaya.notifications.routines import scan_due_routines
from mykhaya.notifications.standalone_reminders import (
    scan_due_reminders as scan_due_standalone_reminders,
)
from mykhaya.syslog_forwarding import (
    SyslogConfig,
    SyslogDispatcher,
    configure_structlog_forwarding,
    syslog_config_from_platform_value,
)
from mykhaya.usage import aggregate_recent_usage, purge_expired_usage_events

# Visibility timeout: how long a dequeued-but-not-yet-completed job is hidden
# from re-selection. This is a lease, not completion — `processed_at` is only
# ever set by the worker on genuine success or permanent give-up (see
# worker.py). If the worker crashes mid-job, the lease simply expires and the
# row becomes selectable again without needing the worker to release it.
LEASE_SECONDS = 120
log = structlog.get_logger()
_last_usage_maintenance_date: date | None = None
# Home Migration package files are purged at most hourly (bounded work per
# pass — see mykhaya.home_migration_pcc.purge_expired_packages).
MIGRATION_PURGE_INTERVAL = timedelta(hours=1)
_last_migration_purge_at: datetime | None = None


async def _purge_migration_packages(db: AsyncSession, settings: Settings) -> None:
    global _last_migration_purge_at
    now = datetime.now(UTC)
    if _last_migration_purge_at and now - _last_migration_purge_at < MIGRATION_PURGE_INTERVAL:
        return
    _last_migration_purge_at = now
    try:
        await purge_expired_packages(db, settings, now=now)
    except Exception as exc:  # a storage problem must never stop notification scans
        await db.rollback()
        log.warning("home_migration.package_purge_pass_failed", error=type(exc).__name__)


async def run() -> None:
    global _last_usage_maintenance_date
    settings = get_settings()
    validate_sensitive_key_configuration(settings, service="scheduler")

    async def load_syslog_config() -> SyslogConfig:
        async with SessionFactory() as db:
            row = await db.scalar(
                select(PlatformSetting).where(PlatformSetting.key == "central_syslog")
            )
        return syslog_config_from_platform_value(row.value if row else {}, settings.environment)

    dispatcher = SyslogDispatcher(
        settings, service="mykhaya-scheduler", config_loader=load_syslog_config
    )
    configure_structlog_forwarding(dispatcher)
    await dispatcher.start()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        while True:
            async with SessionFactory() as db:
                await ManagedDemoService.expire_due(db)
                await db.commit()
                # Durable scans — no in-memory timers. Each computes fresh from current
                # data and inserts idempotent outbox rows; see mykhaya/notifications/
                # reminders.py, briefing.py, routines.py and birthdays.py.
                await scan_due_reminders(db, settings)
                await scan_due_briefings(db, settings)
                await scan_due_routines(db, settings)
                await scan_due_birthdays(db, settings)
                await scan_due_standalone_reminders(db, settings)
                await scan_due_nudges(db, settings)
                await scan_due_daily_nudge_summary(db, settings)
                await scan_family_retention(db)
                await sync_due_holiday_sources(db)
                maintenance_date = datetime.now(UTC).date()
                if _last_usage_maintenance_date != maintenance_date:
                    await purge_expired_usage_events(db)
                    await aggregate_recent_usage(db)
                    _last_usage_maintenance_date = maintenance_date
                await db.commit()
            # Own session: a purge failure's rollback must never discard the
            # scan work committed above.
            async with SessionFactory() as db:
                await _purge_migration_packages(db, settings)
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
        await dispatcher.stop()
        await redis.aclose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
