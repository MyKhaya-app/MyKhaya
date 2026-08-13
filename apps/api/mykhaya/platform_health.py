"""Authoritative current health calculations for Platform Control Centre views."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.mailer import SmtpConfig, resolve_smtp_config
from mykhaya.models import OutboxEvent, WorkerJobRecord


@dataclass(frozen=True)
class PlatformHealthSnapshot:
    smtp: SmtpConfig
    queue_depth: int
    queue_state: str
    queue_reason: str | None
    actionable_failed_jobs: int


async def current_platform_health(
    db: AsyncSession, settings: Settings, *, now: datetime | None = None
) -> PlatformHealthSnapshot:
    """Return current operational state, excluding historical completed failures.

    PostgreSQL outbox state is authoritative for queue depth. Redis is transport,
    so counting both would double-count the same work item.
    """
    checked_at = now or datetime.now(UTC)
    queue_depth = int(
        await db.scalar(
            select(func.count(OutboxEvent.id)).where(OutboxEvent.processed_at.is_(None))
        )
        or 0
    )
    oldest_pending = await db.scalar(
        select(func.min(OutboxEvent.created_at)).where(OutboxEvent.processed_at.is_(None))
    )
    actionable_failed_jobs = int(
        await db.scalar(
            select(func.count(WorkerJobRecord.id))
            .join(OutboxEvent, WorkerJobRecord.outbox_event_id == OutboxEvent.id)
            .where(
                WorkerJobRecord.status == "failed",
                OutboxEvent.processed_at.is_(None),
            )
        )
        or 0
    )
    stuck = bool(
        queue_depth
        and oldest_pending is not None
        and (checked_at - oldest_pending).total_seconds() > 300
    )
    return PlatformHealthSnapshot(
        smtp=await resolve_smtp_config(settings, db),
        queue_depth=queue_depth,
        queue_state="warning" if stuck else "healthy",
        queue_reason=(
            f"The oldest queued item is over five minutes old ({queue_depth} pending)."
            if stuck
            else None
        ),
        actionable_failed_jobs=actionable_failed_jobs,
    )
