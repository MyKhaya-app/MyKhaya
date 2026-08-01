from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.models import PublicIncident, ServiceState

router = APIRouter(prefix="/status", tags=["public-status"])
SERVICES = {
    "web_application": "MyKhaya Web Application",
    "authentication": "Authentication",
    "api": "API",
    "email_delivery": "Email Delivery",
    "notifications": "Notifications",
    "background_processing": "Background Processing",
}


def enforce_status_host(request: Request, settings: Settings) -> None:
    expected = settings.status_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if (request.url.hostname or "").casefold() != expected.casefold():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.get("")
async def public_status(
    request: Request, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    enforce_status_host(request, settings)
    if not settings.status_public_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    rows = (
        await db.scalars(
            select(PublicIncident)
            .where(PublicIncident.starts_at <= datetime.now(UTC))
            .order_by(PublicIncident.starts_at.desc())
            .limit(100)
        )
    ).all()
    active = [row for row in rows if row.resolved_at is None]
    states = {key: ServiceState.operational for key in SERVICES}
    for row in active:
        if row.service in states:
            states[row.service] = row.state
    priority = {
        ServiceState.operational: 0,
        ServiceState.maintenance: 1,
        ServiceState.degraded: 2,
        ServiceState.partial_outage: 3,
        ServiceState.major_outage: 4,
    }
    overall = max(states.values(), key=lambda item: priority[item])
    cutoff = datetime.now(UTC) - timedelta(days=90)
    return {
        "overall": overall,
        "services": [
            {"key": key, "name": label, "state": states[key]} for key, label in SERVICES.items()
        ],
        "current_incidents": [
            {
                "id": row.id,
                "title": row.title,
                "message": row.message,
                "service": row.service,
                "state": row.state,
                "started_at": row.starts_at,
                "updated_at": row.updated_at,
            }
            for row in active
        ],
        "recent_incidents": [
            {
                "id": row.id,
                "title": row.title,
                "service": row.service,
                "state": row.state,
                "started_at": row.starts_at,
                "resolved_at": row.resolved_at,
            }
            for row in rows
            if row.resolved_at and row.resolved_at >= cutoff
        ][:20],
        "last_updated": max((row.updated_at for row in rows), default=datetime.now(UTC)),
    }
