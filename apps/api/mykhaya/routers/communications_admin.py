"""Platform Admin Communications: a health dashboard ("is it working?"), a Timeline
("what happened, told as a story") and Diagnostics ("why did this one fail?"). All
three read from the same notification_deliveries/worker_job_records/outbox_events
tables the Notification Engine already writes — see
docs/architecture/notification-engine.md. This page adds no new write path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import UnaryExpression

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.models import (
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    OperationalHeartbeat,
    OutboxEvent,
    User,
)
from mykhaya.notifications.labels import friendly_status, notification_type_label
from mykhaya.notifications.push import resolve_push_config
from mykhaya.platform_health import current_platform_health
from mykhaya.platform_schemas import (
    CommunicationsHealthResponse,
    DiagnosticsEntryResponse,
    DiagnosticsResponse,
    ServiceStatusResponse,
    TimelineEntryResponse,
    TimelineResponse,
    TransportStatusResponse,
)
from mykhaya.platform_security import PlatformContext, require_roles
from mykhaya.routers.platform import SUPPORT

router = APIRouter(prefix="/platform/communications", tags=["platform-communications"])

STALE_HEARTBEAT_SECONDS = 30
PAGE_SIZE = 30


def _occurred_at_order() -> UnaryExpression[datetime]:
    return func.coalesce(
        NotificationDelivery.attempted_at, NotificationDelivery.scheduled_at
    ).desc()


async def _service_status(db: AsyncSession, service: str) -> ServiceStatusResponse:
    row = await db.get(OperationalHeartbeat, service)
    if row is None:
        return ServiceStatusResponse(
            status="unavailable", last_heartbeat=None, detail="No heartbeat has been recorded."
        )
    stale = (datetime.now(UTC) - row.observed_at).total_seconds() > STALE_HEARTBEAT_SECONDS
    return ServiceStatusResponse(
        status="stale" if stale else "running",
        last_heartbeat=row.observed_at,
        detail=row.safe_detail or ("The last heartbeat is stale." if stale else "Running."),
    )


@router.get("/health")
async def communications_health(
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CommunicationsHealthResponse:
    worker = await _service_status(db, "worker")
    scheduler = await _service_status(db, "scheduler")

    current_health = await current_platform_health(db, settings)
    push_config = await resolve_push_config(settings, db)

    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    latency_seconds = func.extract(
        "epoch", NotificationDelivery.attempted_at - NotificationDelivery.scheduled_at
    )
    average_latency = await db.scalar(
        select(func.avg(latency_seconds)).where(
            NotificationDelivery.status == NotificationDeliveryStatus.sent,
            NotificationDelivery.attempted_at.is_not(None),
            NotificationDelivery.attempted_at >= today_start,
        )
    )
    deliveries_today = int(
        await db.scalar(
            select(func.count(NotificationDelivery.id)).where(
                NotificationDelivery.status == NotificationDeliveryStatus.sent,
                NotificationDelivery.attempted_at >= today_start,
            )
        )
        or 0
    )
    failures_today = int(
        await db.scalar(
            select(func.count(NotificationDelivery.id)).where(
                NotificationDelivery.status == NotificationDeliveryStatus.failed,
                NotificationDelivery.attempted_at >= today_start,
            )
        )
        or 0
    )
    retries_today = int(
        await db.scalar(
            select(func.count(NotificationDelivery.id)).where(
                NotificationDelivery.retry_count > 0,
                NotificationDelivery.attempted_at >= today_start,
            )
        )
        or 0
    )

    unhealthy = worker.status == "unavailable" or scheduler.status == "unavailable"
    degraded = worker.status == "stale" or scheduler.status == "stale" or failures_today > 0
    overall = "unhealthy" if unhealthy else ("degraded" if degraded else "healthy")

    return CommunicationsHealthResponse(
        overall=overall,
        worker=worker,
        scheduler=scheduler,
        smtp=TransportStatusResponse(
            configured=current_health.smtp.configured,
            status="connected" if current_health.smtp.configured else "not_configured",
        ),
        push=TransportStatusResponse(
            configured=push_config.configured,
            status="connected" if push_config.configured else "not_configured",
        ),
        queue_depth=current_health.queue_depth,
        queue_status=current_health.queue_state,
        queue_reason=current_health.queue_reason,
        average_latency_seconds=(
            round(float(average_latency), 2) if average_latency is not None else None
        ),
        deliveries_today=deliveries_today,
        failures_today=failures_today,
        retries_today=retries_today,
    )


@router.get("/timeline")
async def communications_timeline(
    page: int = Query(default=1, ge=1, le=1000),
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> TimelineResponse:
    offset = (page - 1) * PAGE_SIZE
    rows = (
        await db.scalars(
            select(NotificationDelivery)
            .order_by(_occurred_at_order())
            .offset(offset)
            .limit(PAGE_SIZE + 1)
        )
    ).all()
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    recipient_ids = {row.recipient_user_id for row in rows if row.recipient_user_id is not None}
    recipients: dict[uuid.UUID, str] = {}
    if recipient_ids:
        users = (await db.scalars(select(User).where(User.id.in_(recipient_ids)))).all()
        recipients = {user.id: user.display_name for user in users}

    outbox_ids = {row.outbox_event_id for row in rows if row.outbox_event_id is not None}
    pending_outbox_ids: set[uuid.UUID] = set()
    if outbox_ids:
        pending_rows = (
            await db.scalars(
                select(OutboxEvent.id).where(
                    OutboxEvent.id.in_(outbox_ids), OutboxEvent.processed_at.is_(None)
                )
            )
        ).all()
        pending_outbox_ids = set(pending_rows)

    items = [
        TimelineEntryResponse(
            id=row.id,
            occurred_at=row.attempted_at or row.scheduled_at,
            notification_type=row.notification_type,
            label=notification_type_label(row.notification_type),
            channel=row.channel.value,
            status=row.status.value,
            friendly_status=friendly_status(
                row.status.value,
                row.channel.value,
                retry_pending=row.outbox_event_id in pending_outbox_ids,
            ),
            recipient_display_name=(
                recipients.get(row.recipient_user_id) if row.recipient_user_id else None
            ),
            retry_count=row.retry_count,
        )
        for row in rows
    ]
    return TimelineResponse(items=items, next_page=page + 1 if has_more else None)


@router.get("/diagnostics")
async def communications_diagnostics(
    page: int = Query(default=1, ge=1, le=1000),
    status_filter: str | None = Query(default=None, alias="status"),
    channel: str | None = None,
    notification_type: str | None = None,
    recipient_email: str | None = None,
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> DiagnosticsResponse:
    offset = (page - 1) * PAGE_SIZE
    query = select(NotificationDelivery)
    if status_filter:
        try:
            query = query.where(
                NotificationDelivery.status == NotificationDeliveryStatus(status_filter)
            )
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown status filter."
            ) from exc
    if channel:
        try:
            query = query.where(NotificationDelivery.channel == NotificationChannel(channel))
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown channel filter."
            ) from exc
    if notification_type:
        query = query.where(NotificationDelivery.notification_type == notification_type)

    recipient_id: uuid.UUID | None = None
    if recipient_email:
        user = await db.scalar(select(User).where(User.email == recipient_email.strip().lower()))
        if user is not None:
            recipient_id = user.id
            query = query.where(NotificationDelivery.recipient_user_id == recipient_id)
        else:
            return DiagnosticsResponse(items=[], next_page=None)

    rows = (
        await db.scalars(query.order_by(_occurred_at_order()).offset(offset).limit(PAGE_SIZE + 1))
    ).all()
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    recipient_ids = {row.recipient_user_id for row in rows if row.recipient_user_id is not None}
    emails: dict[uuid.UUID, str] = {}
    if recipient_ids:
        users = (await db.scalars(select(User).where(User.id.in_(recipient_ids)))).all()
        emails = {user.id: user.email for user in users}

    items = [
        DiagnosticsEntryResponse(
            id=row.id,
            occurred_at=row.attempted_at or row.scheduled_at,
            notification_type=row.notification_type,
            label=notification_type_label(row.notification_type),
            channel=row.channel.value,
            status=row.status.value,
            recipient_email=(emails.get(row.recipient_user_id) if row.recipient_user_id else None),
            sanitised_failure_reason=row.sanitised_failure_reason,
            retry_count=row.retry_count,
            idempotency_key=row.idempotency_key,
        )
        for row in rows
    ]
    return DiagnosticsResponse(items=items, next_page=page + 1 if has_more else None)
