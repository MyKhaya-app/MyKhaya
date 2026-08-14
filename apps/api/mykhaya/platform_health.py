"""Authoritative current health calculations for Platform Control Centre views."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.billing.config import resolve_stripe_config
from mykhaya.config import Settings
from mykhaya.mailer import SmtpConfig, resolve_smtp_config
from mykhaya.models import OutboxEvent, StripeWebhookEvent, StripeWebhookFailure, WorkerJobRecord

# How many recent failures (in the trailing window below) tips webhook
# health from "healthy" to "warning". A single failure is expected to
# self-resolve via Stripe's own retry — see mykhaya.billing.webhooks's
# module docstring — so this only fires on a *pattern* of failures, not one
# transient blip.
_STRIPE_WEBHOOK_FAILURE_WARNING_THRESHOLD = 3
_STRIPE_WEBHOOK_FAILURE_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class StripeWebhookHealth:
    configured: bool
    # "not_configured" | "healthy" | "warning"
    state: str
    reason: str | None
    # Most recent Stripe webhook delivery MyKhaya recorded (processed or
    # ignored) — informational only, never itself a source of alarm: long
    # gaps between real Stripe lifecycle events are entirely normal (see
    # "Stale webhook detection" in docs/architecture/commercial-entitlements.md
    # for why failure count, not staleness, is the chosen health signal).
    last_event_at: datetime | None
    recent_failure_count: int


@dataclass(frozen=True)
class PlatformHealthSnapshot:
    smtp: SmtpConfig
    queue_depth: int
    queue_state: str
    queue_reason: str | None
    actionable_failed_jobs: int
    stripe_webhook: StripeWebhookHealth


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
        stripe_webhook=await _stripe_webhook_health(db, settings, checked_at),
    )


async def _stripe_webhook_health(
    db: AsyncSession, settings: Settings, checked_at: datetime
) -> StripeWebhookHealth:
    if not resolve_stripe_config(settings).configured:
        return StripeWebhookHealth(
            configured=False,
            state="not_configured",
            reason=None,
            last_event_at=None,
            recent_failure_count=0,
        )
    last_event_at = await db.scalar(select(func.max(StripeWebhookEvent.received_at)))
    recent_failure_count = int(
        await db.scalar(
            select(func.count(StripeWebhookFailure.id)).where(
                StripeWebhookFailure.occurred_at >= checked_at - _STRIPE_WEBHOOK_FAILURE_WINDOW
            )
        )
        or 0
    )
    warning = recent_failure_count >= _STRIPE_WEBHOOK_FAILURE_WARNING_THRESHOLD
    return StripeWebhookHealth(
        configured=True,
        state="warning" if warning else "healthy",
        reason=(
            f"{recent_failure_count} webhook processing failures in the last 24 hours."
            if warning
            else None
        ),
        last_event_at=last_event_at,
        recent_failure_count=recent_failure_count,
    )
