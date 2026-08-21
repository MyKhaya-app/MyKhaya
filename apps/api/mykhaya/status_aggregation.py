"""The single source of truth for MyKhaya's customer-facing service-status
model: the monitored-service catalogue, and how active incidents combine
into a per-service state and an overall status. Both the public Status page
(mykhaya.routers.status) and Platform Control Centre's incident management
(mykhaya.routers.platform's /platform/incidents* endpoints) import from
here rather than each keeping their own copy of this logic — see
docs task "Status & Incidents" for why that duplication was worth avoiding.

Model: automated health checks are intentionally NOT part of this module —
see mykhaya.platform_health for the internal PCC diagnostics (SMTP, outbox
queue, Stripe webhook failure-rate) those already cover, and
mykhaya.routers.health for infra liveness/readiness probes. Neither feeds
the public page. The desired "automated health + manual incident impact"
model (see the task's point 8) is realised by an administrator recording an
incident with a real customer-facing impact whenever automated checks alone
wouldn't reflect what customers are actually experiencing — an incident's
declared impact always wins over "nothing is automatically detected as
broken", precisely so a human can represent reality even when a health
endpoint still returns 200.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mykhaya.models import IncidentLifecycleState, ServiceState

# The fixed catalogue of monitored, customer-facing services shown on the
# public Status page and selectable when creating/updating a status
# incident in Platform Control Centre. Adding a new customer-facing service
# (e.g. "billing") means editing this dict once.
PUBLIC_SERVICES: dict[str, str] = {
    "web_application": "MyKhaya Web Application",
    "authentication": "Authentication",
    "api": "API",
    "email_delivery": "Email Delivery",
    "notifications": "Notifications",
    "background_processing": "Background Processing",
    "billing": "Billing & Subscriptions",
}

# Kept in one place alongside the dict above (rather than re-derived) since
# pydantic's Literal[...] needs statically-known values — the two are edited
# together whenever a service is added or removed.
PUBLIC_SERVICE_KEYS = tuple(PUBLIC_SERVICES)

# Highest active severity wins, both across the incidents affecting a single
# service and across all services for the page's overall banner.
_SEVERITY_PRIORITY: dict[ServiceState, int] = {
    ServiceState.operational: 0,
    ServiceState.maintenance: 1,
    ServiceState.degraded: 2,
    ServiceState.partial_outage: 3,
    ServiceState.major_outage: 4,
}

# Concise, customer-friendly wording for the overall status banner — see the
# task's "Overall status banner" examples. Deliberately never mentions which
# specific incident or provider is responsible; that detail lives in the
# per-service list and incident cards below the banner.
_OVERALL_MESSAGES: dict[ServiceState, str] = {
    ServiceState.operational: "Operational",
    ServiceState.maintenance: "Scheduled maintenance in progress",
    ServiceState.degraded: "Some systems are experiencing degraded performance",
    ServiceState.partial_outage: "Partial service disruption",
    ServiceState.major_outage: "Major service disruption",
}


def overall_message(overall: ServiceState) -> str:
    return _OVERALL_MESSAGES[overall]


def highest_severity(states: list[ServiceState]) -> ServiceState:
    """The single worst state among `states`, or Operational if empty —
    used both to combine several active incidents' impact on one service,
    and to combine every service's state into the page's overall banner."""
    if not states:
        return ServiceState.operational
    return max(states, key=lambda item: _SEVERITY_PRIORITY[item])


def service_states_from_impacts(
    active_impacts: list[tuple[str, ServiceState]],
) -> dict[str, ServiceState]:
    """Every monitored service's current public state: Operational unless
    one or more currently-active incidents declare impact on it, in which
    case the highest of those declared impacts applies. `active_impacts` is
    (service_key, impact) pairs drawn from StatusIncidentService rows
    belonging only to incidents that are active right now (started, not yet
    resolved) — callers decide "active" (see routers.status/.platform)."""
    by_service: dict[str, list[ServiceState]] = {key: [] for key in PUBLIC_SERVICES}
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
