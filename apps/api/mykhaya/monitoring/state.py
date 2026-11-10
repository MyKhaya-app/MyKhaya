"""Pure state rules shared by the runner, the watchdog, PCC and the public
status aggregation. No I/O here, so the rules are unit-testable on their own.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mykhaya.models import MonitorComponent, ServiceState
from mykhaya.monitoring.catalogue import BY_KEY
from mykhaya.monitoring.results import (
    DEGRADED,
    HEALTHY,
    NOT_APPLICABLE,
    UNAVAILABLE,
    UNKNOWN,
    CheckResult,
)

# The runner writes OperationalHeartbeat("monitoring") after every cycle. If
# that is older than this, no component's stored state can be trusted.
RUNNER_HEARTBEAT_SERVICE = "monitoring"
RUNNER_STALE_SECONDS = 180

DISABLED = "disabled"


def stale_after(component: MonitorComponent) -> timedelta:
    """A component is stale once it has missed roughly three checks, with a
    floor of two minutes' grace for slow cycles."""
    interval = max(component.interval_seconds, 15)
    return timedelta(seconds=max(3 * interval, interval + 120))


def is_stale(component: MonitorComponent, now: datetime) -> bool:
    return component.last_checked_at is None or now - component.last_checked_at > stale_after(
        component
    )


def effective_state(component: MonitorComponent, now: datetime, *, runner_fresh: bool) -> str:
    """The state to *report*: the stored state, unless the observation
    behind it is stale or the runner itself has stopped, in which case
    Unknown. Monitoring that stopped must never keep a component green."""
    if not component.enabled:
        return DISABLED
    if component.state == NOT_APPLICABLE:
        return NOT_APPLICABLE
    definition = BY_KEY.get(component.key)
    watchdog_managed = bool(definition and definition.watchdog_managed)
    if not runner_fresh and not watchdog_managed:
        return UNKNOWN
    if is_stale(component, now):
        return UNKNOWN
    return component.state


def next_state(component: MonitorComponent, result: CheckResult) -> str:
    """Apply one result's counters to ``component`` (mutates counters only)
    and return the state it should now be in.

    - Unknown/Not applicable -> Healthy on the first success (nothing to
      recover from).
    - Degraded/Unavailable -> Healthy only after ``recovery_threshold``
      consecutive successes.
    - Any state -> Degraded/Unavailable only after ``failure_threshold``
      consecutive failures; the result chooses which.
    - Unavailable never de-escalates to Degraded; it recovers to Healthy.
    """
    state = component.state
    if result.outcome == "not_applicable":
        component.consecutive_failures = 0
        component.consecutive_successes = 0
        return NOT_APPLICABLE
    if result.outcome == "success":
        component.consecutive_successes += 1
        component.consecutive_failures = 0
        if state in (UNKNOWN, NOT_APPLICABLE):
            return HEALTHY
        if state in (DEGRADED, UNAVAILABLE):
            return (
                HEALTHY
                if component.consecutive_successes >= component.recovery_threshold
                else state
            )
        return HEALTHY
    if result.outcome == "failure":
        component.consecutive_failures += 1
        component.consecutive_successes = 0
        if component.consecutive_failures < component.failure_threshold:
            return state
        target = UNAVAILABLE if result.failure_severity == "unavailable" else DEGRADED
        if state == UNAVAILABLE and target == DEGRADED:
            return UNAVAILABLE
        return target
    return state


# --- Public impact ----------------------------------------------------------------------

_PUBLIC_PRIORITY: dict[str, int] = {
    ServiceState.operational.value: 0,
    ServiceState.maintenance.value: 1,
    ServiceState.degraded.value: 2,
    ServiceState.partial_outage.value: 3,
    ServiceState.major_outage.value: 4,
}


def component_public_impact(state: str, severity: str) -> str | None:
    """The public ServiceState a component's state implies, or None when it
    says nothing (unknown, not applicable, disabled)."""
    if state == HEALTHY:
        return ServiceState.operational.value
    if state == DEGRADED:
        return ServiceState.degraded.value
    if state == UNAVAILABLE:
        return (
            ServiceState.major_outage.value
            if severity == "critical"
            else ServiceState.partial_outage.value
        )
    return None


def worst_public(states: list[str]) -> str:
    if not states:
        return ServiceState.operational.value
    return max(states, key=lambda item: _PUBLIC_PRIORITY.get(item, 0))
