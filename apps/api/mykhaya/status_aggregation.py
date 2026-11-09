"""The single source of truth for MyKhaya's customer-facing service-status
model: the service catalogue, and how monitoring observations, incidents,
overrides and freshness combine into a per-service state and an overall
status. The public Status page (mykhaya.routers.status), the Help & Support
summary (mykhaya.routers.public_config) and Platform Control Centre's
incident management (mykhaya.routers.platform) all read it from here.

A service's public state combines, in order of precedence:

1. An active administrator override (mykhaya.models.MonitorOverride):
   either a forced state, or "suppress" (ignore automated monitoring).
2. Active incidents (manual or automated) and their declared impact,
   including scheduled maintenance.
3. Automated monitoring (mykhaya.monitoring): the worst fresh component
   state mapped to the service.
4. Freshness: if no component has a fresh, conclusive observation (or the
   monitoring runner has stopped), the service is "unknown", never
   "operational".

Incidents and automated observations are combined by "highest severity
wins". An incident never hides a worse automated observation, and a healthy
observation never hides a declared incident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import (
    IncidentLifecycleState,
    MonitorComponent,
    MonitorOverride,
    OperationalHeartbeat,
    PublicIncident,
    ServiceState,
    StatusIncidentService,
)
from mykhaya.monitoring.catalogue import BY_KEY
from mykhaya.monitoring.state import (
    RUNNER_HEARTBEAT_SERVICE,
    RUNNER_STALE_SECONDS,
    component_public_impact,
    effective_state,
    worst_public,
)

# MyKhaya's own customer-facing services. Adding one means editing this dict
# and platform_schemas.PublicServiceKey together.
PUBLIC_SERVICES: dict[str, str] = {
    "web_application": "MyKhaya Web Application",
    "authentication": "Authentication",
    "api": "API",
    "email_delivery": "Email Delivery",
    "notifications": "Notifications",
    "background_processing": "Background Processing",
    "billing": "Billing & Subscriptions",
}

# Customer-relevant external providers, shown in a separate "External
# services" section only when the integration is in use in this environment.
# Internal infrastructure providers (mail server, push gateways) are not
# listed here: they surface publicly only through Email Delivery and
# Notifications, and by name only in PCC.
EXTERNAL_SERVICES: dict[str, str] = {
    "dvsa_mot_history": "DVSA MOT History",
    "dvla_vehicle_enquiry": "DVLA Vehicle Enquiry",
    "stripe_payments": "Stripe Payments",
    "stripe_webhooks": "Stripe Webhook Processing",
    "apple_sign_in": "Apple Sign-In",
    "google_sign_in": "Google Sign-In",
}

ALL_STATUS_SERVICES: dict[str, str] = {**PUBLIC_SERVICES, **EXTERNAL_SERVICES}

PUBLIC_SERVICE_KEYS = tuple(PUBLIC_SERVICES)
EXTERNAL_SERVICE_KEYS = tuple(EXTERNAL_SERVICES)

# Not a ServiceState (never stored on an incident): only ever computed.
UNKNOWN = "unknown"

_SEVERITY_PRIORITY: dict[ServiceState, int] = {
    ServiceState.operational: 0,
    ServiceState.maintenance: 1,
    ServiceState.degraded: 2,
    ServiceState.partial_outage: 3,
    ServiceState.major_outage: 4,
}

# Concise, customer-friendly wording for the overall status banner. Never
# names the responsible incident or provider.
_OVERALL_MESSAGES: dict[str, str] = {
    ServiceState.operational.value: "Operational",
    ServiceState.maintenance.value: "Scheduled maintenance in progress",
    ServiceState.degraded.value: "Some systems are experiencing degraded performance",
    ServiceState.partial_outage.value: "Partial service disruption",
    ServiceState.major_outage.value: "Major service disruption",
    UNKNOWN: "Some services could not be verified",
}
_MONITORING_UNAVAILABLE_MESSAGE = "Live service monitoring is temporarily unavailable"


def overall_message(overall: str, *, monitoring_active: bool = True) -> str:
    if overall == UNKNOWN and not monitoring_active:
        return _MONITORING_UNAVAILABLE_MESSAGE
    return _OVERALL_MESSAGES.get(str(overall), _OVERALL_MESSAGES[UNKNOWN])


def highest_severity(states: list[ServiceState]) -> ServiceState:
    """The single worst state among `states`, or Operational if empty."""
    if not states:
        return ServiceState.operational
    return max(states, key=lambda item: _SEVERITY_PRIORITY[item])


def service_states_from_impacts(
    active_impacts: list[tuple[str, ServiceState]],
) -> dict[str, ServiceState]:
    """Incident-only view: every catalogued service's state from active
    incident impacts alone (Operational when none). Kept for callers and
    tests that reason about incidents in isolation; the public page uses
    compute_status_snapshot, which also folds in monitoring."""
    by_service: dict[str, list[ServiceState]] = {key: [] for key in ALL_STATUS_SERVICES}
    for service_key, impact in active_impacts:
        if service_key in by_service:
            by_service[service_key].append(impact)
    return {key: highest_severity(values) for key, values in by_service.items()}


def is_incident_active(
    starts_at: datetime,
    resolved_at: datetime | None,
    *,
    lifecycle_state: IncidentLifecycleState | None = None,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    return (
        lifecycle_state != IncidentLifecycleState.resolved
        and resolved_at is None
        and starts_at <= now
    )


def is_override_active(row: MonitorOverride, now: datetime) -> bool:
    return row.revoked_at is None and row.starts_at <= now < row.expires_at


@dataclass(frozen=True)
class ServiceStatus:
    key: str
    name: str
    state: str
    # verified: every mapped component fresh and fully verifying;
    # limited: some components unknown or only reachability-level;
    # none: no fresh automated observation at all;
    # override: an administrator override is in force.
    confidence: str
    last_checked: datetime | None
    external: bool = False


@dataclass(frozen=True)
class StatusSnapshot:
    overall: str
    overall_message: str
    monitoring_active: bool
    services: list[ServiceStatus]
    external_services: list[ServiceStatus]
    active_incidents: list[PublicIncident] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


async def runner_is_fresh(db: AsyncSession, now: datetime) -> bool:
    heartbeat = await db.get(OperationalHeartbeat, RUNNER_HEARTBEAT_SERVICE)
    return heartbeat is not None and (now - heartbeat.observed_at).total_seconds() <= (
        RUNNER_STALE_SECONDS
    )


async def active_incident_impacts(
    db: AsyncSession, now: datetime
) -> tuple[list[PublicIncident], dict[str, list[ServiceState]]]:
    rows = (
        await db.scalars(
            select(PublicIncident)
            .where(PublicIncident.starts_at <= now, PublicIncident.resolved_at.is_(None))
            .order_by(PublicIncident.starts_at.desc())
            .limit(100)
        )
    ).all()
    active = [
        row
        for row in rows
        if is_incident_active(
            row.starts_at, row.resolved_at, lifecycle_state=row.lifecycle_state, now=now
        )
    ]
    impacts: dict[str, list[ServiceState]] = {}
    if active:
        for entry in await db.scalars(
            select(StatusIncidentService).where(
                StatusIncidentService.incident_id.in_([row.id for row in active])
            )
        ):
            impacts.setdefault(entry.service, []).append(entry.impact)
    return active, impacts


async def compute_status_snapshot(db: AsyncSession, now: datetime | None = None) -> StatusSnapshot:
    now = now or datetime.now(UTC)
    runner_fresh = await runner_is_fresh(db, now)
    components = (await db.scalars(select(MonitorComponent))).all()
    overrides = [
        row
        for row in (
            await db.scalars(
                select(MonitorOverride).where(
                    MonitorOverride.revoked_at.is_(None), MonitorOverride.expires_at > now
                )
            )
        ).all()
        if is_override_active(row, now)
    ]
    override_by_service: dict[str, MonitorOverride] = {}
    for row in sorted(overrides, key=lambda item: item.created_at or now):
        override_by_service[row.service_key] = row  # newest wins
    active_incidents, incident_impacts = await active_incident_impacts(db, now)

    def service_status(key: str, name: str, *, external: bool) -> ServiceStatus | None:
        mapped = [
            component
            for component in components
            if (definition := BY_KEY.get(component.key)) is not None
            and key in definition.service_keys
            and component.public_visible
        ]
        states = [(c, effective_state(c, now, runner_fresh=runner_fresh)) for c in mapped]
        in_use = [(c, s) for c, s in states if s not in ("not_applicable", "disabled")]
        incident_states = [impact.value for impact in incident_impacts.get(key, [])]
        if external and not in_use and not incident_states:
            # Integration not configured/enabled here: nothing to publish.
            return None
        known = [(c, s) for c, s in in_use if s != UNKNOWN]
        automated = [
            impact
            for c, s in known
            if (impact := component_public_impact(s, c.severity)) is not None
        ]
        last_checked = max(
            (c.last_checked_at for c, _ in in_use if c.last_checked_at is not None), default=None
        )
        if not known:
            confidence = "none"
        elif len(known) == len(in_use) and all(c.confidence == "verified" for c, _ in known):
            confidence = "verified"
        else:
            confidence = "limited"

        override = override_by_service.get(key)
        if override is not None and override.forced_state:
            return ServiceStatus(
                key, name, override.forced_state, "override", last_checked, external
            )
        if override is not None:
            # Suppressed: automated monitoring is ignored for the public
            # view; incidents still apply.
            automated = []
            confidence = "override"

        if automated:
            state = worst_public(automated + incident_states)
        elif incident_states:
            state = worst_public(incident_states)
        elif override is not None:
            state = ServiceState.operational.value
        else:
            state = UNKNOWN
        return ServiceStatus(key, name, state, confidence, last_checked, external)

    services = [
        status
        for key, name in PUBLIC_SERVICES.items()
        if (status := service_status(key, name, external=False)) is not None
    ]
    external_services = [
        status
        for key, name in EXTERNAL_SERVICES.items()
        if (status := service_status(key, name, external=True)) is not None
    ]

    # A single external provider must never make the whole platform look
    # down: its contribution to the overall banner is capped at Partial.
    def overall_contribution(status: ServiceStatus) -> str | None:
        if status.state == UNKNOWN:
            return None
        if status.external and status.state == ServiceState.major_outage.value:
            return ServiceState.partial_outage.value
        return status.state

    contributions = [
        value
        for status in services + external_services
        if (value := overall_contribution(status)) is not None
    ]
    worst = worst_public(contributions)
    any_core_unknown = any(status.state == UNKNOWN for status in services)
    overall = UNKNOWN if worst == ServiceState.operational.value and any_core_unknown else worst
    return StatusSnapshot(
        overall=overall,
        overall_message=overall_message(overall, monitoring_active=runner_fresh),
        monitoring_active=runner_fresh,
        services=services,
        external_services=external_services,
        active_incidents=active_incidents,
        generated_at=now,
    )


async def overall_public_state(db: AsyncSession, now: datetime | None = None) -> str:
    """The overall banner state alone, for the Help & Support summary."""
    return (await compute_status_snapshot(db, now)).overall
