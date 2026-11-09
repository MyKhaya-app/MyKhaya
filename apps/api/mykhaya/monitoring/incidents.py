"""Automatic public incidents for confirmed, customer-facing failures.

When a monitored component's confirmed state change affects a public
service, the open *automated* incident for that service is created,
escalated, eased or resolved to match. Incidents use fixed, generic,
customer-safe wording: no provider error, host, credential or internal
detail ever reaches them.

Automated incidents are ordinary PublicIncident rows (source="automated").
An administrator can update, resolve or delete one through the existing PCC
endpoints; monitoring only acts again on the next confirmed transition, so a
manual resolution is never immediately undone. An active "suppress" or
"force" override stops automated incidents for that service altogether.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import (
    IncidentLifecycleState,
    MonitorComponent,
    MonitorOverride,
    MonitorTransition,
    PublicIncident,
    ServiceState,
    StatusIncidentService,
    StatusIncidentUpdate,
)
from mykhaya.monitoring.catalogue import BY_KEY
from mykhaya.monitoring.results import HEALTHY
from mykhaya.monitoring.state import component_public_impact, effective_state, worst_public
from mykhaya.status_aggregation import ALL_STATUS_SERVICES, is_override_active

AUTOMATED_SOURCE = "automated"

_IMPACT_WORDS = {
    ServiceState.degraded.value: "degraded performance",
    ServiceState.partial_outage.value: "partial outage",
    ServiceState.major_outage.value: "outage",
}
_PRIORITY = {
    ServiceState.operational.value: 0,
    ServiceState.degraded.value: 2,
    ServiceState.partial_outage.value: 3,
    ServiceState.major_outage.value: 4,
}


@dataclass
class TransitionEvent:
    transition: MonitorTransition
    component: MonitorComponent
    previous_success_at: datetime | None


def _title(name: str, impact: str) -> str:
    return f"{name}: {_IMPACT_WORDS.get(impact, 'service disruption')}"[:160]


async def _active_override(db: AsyncSession, service_key: str, now: datetime) -> bool:
    rows = (
        await db.scalars(
            select(MonitorOverride).where(
                MonitorOverride.service_key == service_key, MonitorOverride.revoked_at.is_(None)
            )
        )
    ).all()
    return any(is_override_active(row, now) for row in rows)


async def automated_service_impact(
    db: AsyncSession, service_key: str, now: datetime
) -> tuple[str | None, bool]:
    """(worst automated public impact, every known component healthy)."""
    components = (await db.scalars(select(MonitorComponent))).all()
    impacts: list[str] = []
    all_healthy = True
    for component in components:
        definition = BY_KEY.get(component.key)
        if definition is None or service_key not in definition.service_keys:
            continue
        if not component.public_visible:
            continue
        state = effective_state(component, now, runner_fresh=True)
        impact = component_public_impact(state, component.severity)
        if impact is None:
            continue
        impacts.append(impact)
        if state != HEALTHY:
            all_healthy = False
    if not impacts:
        return None, False
    return worst_public(impacts), all_healthy


async def reconcile_incidents(
    db: AsyncSession, events: list[TransitionEvent], now: datetime
) -> dict[str, uuid.UUID]:
    """Bring each affected service's automated incident in line with its
    automated state. Returns service_key -> open incident id."""
    affected: list[str] = []
    for event in events:
        definition = BY_KEY.get(event.component.key)
        if definition is None or not event.component.public_visible:
            continue
        for key in definition.service_keys:
            if key not in affected:
                affected.append(key)

    open_by_service: dict[str, uuid.UUID] = {}
    for service_key in affected:
        name = ALL_STATUS_SERVICES.get(service_key, service_key)
        incident = await db.scalar(
            select(PublicIncident)
            .where(
                PublicIncident.source == AUTOMATED_SOURCE,
                PublicIncident.monitor_service_key == service_key,
                PublicIncident.resolved_at.is_(None),
            )
            .order_by(PublicIncident.starts_at.desc())
            .limit(1)
            .with_for_update()
        )
        if await _active_override(db, service_key, now):
            if incident is not None:
                open_by_service[service_key] = incident.id
            continue
        impact, all_healthy = await automated_service_impact(db, service_key, now)
        if impact is None:
            continue
        if impact == ServiceState.operational.value:
            if incident is not None and all_healthy:
                incident.lifecycle_state = IncidentLifecycleState.resolved
                incident.resolved_at = now
                db.add(
                    StatusIncidentUpdate(
                        incident_id=incident.id,
                        lifecycle_state=IncidentLifecycleState.resolved,
                        message=f"{name} is operating normally again. We'll continue to monitor.",
                        occurred_at=now,
                        created_by=None,
                    )
                )
            continue
        impact_state = ServiceState(impact)
        if incident is None:
            message = (
                f"Our automated monitoring has detected a problem affecting {name}. "
                "Our team has been alerted and is investigating."
            )
            incident = PublicIncident(
                title=_title(name, impact),
                message=message,
                service=service_key,
                state=impact_state,
                lifecycle_state=IncidentLifecycleState.investigating,
                starts_at=now,
                created_by=None,
                source=AUTOMATED_SOURCE,
                monitor_service_key=service_key,
                internal_notes="Opened automatically by service monitoring.",
            )
            db.add(incident)
            await db.flush()
            db.add(
                StatusIncidentService(
                    incident_id=incident.id, service=service_key, impact=impact_state
                )
            )
            db.add(
                StatusIncidentUpdate(
                    incident_id=incident.id,
                    lifecycle_state=IncidentLifecycleState.investigating,
                    message=message,
                    occurred_at=now,
                    created_by=None,
                )
            )
        else:
            entry = await db.scalar(
                select(StatusIncidentService).where(
                    StatusIncidentService.incident_id == incident.id,
                    StatusIncidentService.service == service_key,
                )
            )
            previous = entry.impact.value if entry is not None else None
            if previous != impact:
                if entry is None:
                    db.add(
                        StatusIncidentService(
                            incident_id=incident.id, service=service_key, impact=impact_state
                        )
                    )
                else:
                    entry.impact = impact_state
                worse = _PRIORITY.get(impact, 0) > _PRIORITY.get(previous or "", 0)
                db.add(
                    StatusIncidentUpdate(
                        incident_id=incident.id,
                        lifecycle_state=incident.lifecycle_state,
                        message=(
                            f"The problem affecting {name} has worsened. "
                            "We're continuing to investigate."
                            if worse
                            else f"{name} is partially recovering. We're continuing to monitor."
                        ),
                        occurred_at=now,
                        created_by=None,
                    )
                )
        open_by_service[service_key] = incident.id

    for event in events:
        definition = BY_KEY.get(event.component.key)
        if definition is None:
            continue
        for key in definition.service_keys:
            if key in open_by_service:
                event.transition.incident_id = open_by_service[key]
                break
    return open_by_service
