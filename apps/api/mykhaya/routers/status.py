from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.models import PublicIncident, StatusIncidentService, StatusIncidentUpdate
from mykhaya.status_aggregation import (
    ALL_STATUS_SERVICES,
    ServiceStatus,
    StatusSnapshot,
    compute_status_snapshot,
    is_incident_active,
)

router = APIRouter(prefix="/status", tags=["public-status"])


def enforce_status_host(request: Request, settings: Settings) -> None:
    expected = settings.status_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if (request.url.hostname or "").casefold() != expected.casefold():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _incident_summary(
    row: PublicIncident,
    services: list[StatusIncidentService],
    updates: list[StatusIncidentUpdate],
) -> dict[str, Any]:
    # Deliberately only customer-facing fields: no internal_notes, no
    # created_by/administrator identity, no legacy single-service
    # service/state columns. See docs task "Public versus internal
    # information".
    ordered_updates = sorted(updates, key=lambda item: item.occurred_at)
    return {
        "id": row.id,
        "title": row.title,
        "lifecycle_state": row.lifecycle_state,
        "services": [
            {
                "key": entry.service,
                "name": ALL_STATUS_SERVICES.get(entry.service, entry.service),
                "impact": entry.impact,
            }
            for entry in services
        ],
        "started_at": row.starts_at,
        "resolved_at": row.resolved_at,
        "updates": [
            {
                "lifecycle_state": update.lifecycle_state,
                "message": update.message,
                "occurred_at": update.occurred_at,
            }
            for update in ordered_updates
        ],
        "latest_update_at": ordered_updates[-1].occurred_at if ordered_updates else row.starts_at,
    }


def _service_row(status: ServiceStatus) -> dict[str, Any]:
    # Customer-safe only: a state, a confidence word and a timestamp. Never a
    # component name, failure category, latency, provider error or host.
    return {
        "key": status.key,
        "name": status.name,
        "state": status.state,
        "confidence": status.confidence,
        "last_checked": status.last_checked,
    }


async def _public_payload(db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    snapshot: StatusSnapshot = await compute_status_snapshot(db, now)
    rows = (
        await db.scalars(
            select(PublicIncident)
            .where(PublicIncident.starts_at <= now)
            .order_by(PublicIncident.starts_at.desc())
            .limit(100)
        )
    ).all()
    incident_ids = [row.id for row in rows]
    services_by_incident: dict[Any, list[StatusIncidentService]] = {row.id: [] for row in rows}
    updates_by_incident: dict[Any, list[StatusIncidentUpdate]] = {row.id: [] for row in rows}
    if incident_ids:
        for service_row in await db.scalars(
            select(StatusIncidentService).where(StatusIncidentService.incident_id.in_(incident_ids))
        ):
            services_by_incident[service_row.incident_id].append(service_row)
        for update_row in await db.scalars(
            select(StatusIncidentUpdate).where(StatusIncidentUpdate.incident_id.in_(incident_ids))
        ):
            updates_by_incident[update_row.incident_id].append(update_row)

    active_rows = [
        row
        for row in rows
        if is_incident_active(
            row.starts_at, row.resolved_at, lifecycle_state=row.lifecycle_state, now=now
        )
    ]
    cutoff = now - timedelta(days=90)
    resolved_rows = [row for row in rows if row.resolved_at and row.resolved_at >= cutoff]

    return {
        "overall": snapshot.overall,
        "overall_message": snapshot.overall_message,
        "services": [_service_row(item) for item in snapshot.services],
        # Additive (service monitoring): customer-relevant providers in use
        # in this environment, and whether live monitoring is running.
        "external_services": [_service_row(item) for item in snapshot.external_services],
        "monitoring": {"active": snapshot.monitoring_active},
        "generated_at": snapshot.generated_at,
        "current_incidents": [
            _incident_summary(row, services_by_incident[row.id], updates_by_incident[row.id])
            for row in active_rows
        ],
        "recent_incidents": [
            {
                **_incident_summary(row, services_by_incident[row.id], updates_by_incident[row.id]),
                "duration_seconds": (row.resolved_at - row.starts_at).total_seconds()
                if row.resolved_at
                else None,
            }
            for row in resolved_rows
        ][:20],
        "last_updated": max((row.updated_at for row in rows), default=now),
    }


@router.get("")
async def public_status(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    enforce_status_host(request, settings)
    if not settings.status_public_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return await _public_payload(db)


@router.get("/snapshot")
async def public_status_snapshot(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """The same public payload, cacheable: intended for an independent
    edge/static origin (or CDN) to fetch and keep serving its last good copy
    while the platform is unreachable. `generated_at` lets that copy show
    its age honestly. See docs/architecture/public-status-service.md."""
    enforce_status_host(request, settings)
    if not settings.status_public_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    response.headers["Cache-Control"] = "public, max-age=30, stale-if-error=86400"
    return await _public_payload(db)
