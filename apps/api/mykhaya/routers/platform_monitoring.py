"""Platform Control Centre: automated service monitoring.

Extends the existing Health and Incidents areas rather than duplicating
them. Reading is open to every PCC role; anything that changes behaviour
(configuration, on-demand runs, overrides, DEV fault injection, alert
settings, resends) is restricted to owners/administrators, requires recent
authentication and a reason, and is audited. Acknowledging an alert is open
to support operators too.

Nothing here is reachable from the public status host, and failure details
are the already-sanitised strings the checks produced.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import EmailStr, Field
from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.models import (
    MonitorAlert,
    MonitorComponent,
    MonitorObservation,
    MonitorOverride,
    MonitorTransition,
    NotificationDelivery,
    OperationalHeartbeat,
    PlatformAdministrator,
    PlatformRole,
    PlatformSetting,
    ServiceState,
)
from mykhaya.monitoring import alerts as monitoring_alerts
from mykhaya.monitoring.catalogue import BY_KEY, CATALOGUE
from mykhaya.monitoring.engine import (
    CycleReport,
    build_http_client,
    ensure_components,
    holds_simulated_failure,
    run_cycle,
)
from mykhaya.monitoring.results import category_label
from mykhaya.monitoring.state import (
    RUNNER_HEARTBEAT_SERVICE,
    RUNNER_STALE_SECONDS,
    effective_state,
    stale_after,
)
from mykhaya.platform_audit import platform_audit
from mykhaya.platform_schemas import PublicServiceKey, SensitiveActionRequest
from mykhaya.platform_security import PlatformContext, require_recent_auth, require_roles
from mykhaya.routers.platform import ALL_ROLES, OPERATORS, SUPPORT
from mykhaya.schemas import StrictModel
from mykhaya.status_aggregation import ALL_STATUS_SERVICES, compute_status_snapshot

router = APIRouter(prefix="/platform/monitoring", tags=["platform-monitoring"])

MANUAL_RUN_COOLDOWN = timedelta(seconds=30)
PublicState = Literal[
    "operational", "degraded_performance", "partial_outage", "major_outage", "maintenance"
]


class ComponentConfigUpdate(SensitiveActionRequest):
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=30, le=3600)
    timeout_seconds: int | None = Field(default=None, ge=1, le=30)
    failure_threshold: int | None = Field(default=None, ge=1, le=10)
    recovery_threshold: int | None = Field(default=None, ge=1, le=10)
    public_visible: bool | None = None
    severity: Literal["critical", "warning", "info"] | None = None


class ComponentRunRequest(SensitiveActionRequest):
    pass


class SimulateFailureRequest(SensitiveActionRequest):
    minutes: int = Field(default=10, ge=1, le=120)
    severity: Literal["degraded", "unavailable"] = "unavailable"


class OverrideCreate(SensitiveActionRequest):
    service_key: PublicServiceKey
    # None = suppress automated public reporting for the service.
    forced_state: PublicState | None = None
    expires_in_minutes: int = Field(ge=5, le=7 * 24 * 60)


class OverrideRevoke(SensitiveActionRequest):
    pass


class AlertAcknowledge(StrictModel):
    note: str | None = Field(default=None, max_length=300)


class AlertResend(SensitiveActionRequest):
    pass


class AlertSettingsUpdate(SensitiveActionRequest):
    enabled: bool
    roles: list[
        Literal[
            "platform_owner",
            "platform_administrator",
            "support_operator",
            "security_operator",
            "read_only_operator",
        ]
    ] = Field(max_length=5)
    additional_recipients: list[EmailStr] = Field(default_factory=list, max_length=10)
    cooldown_minutes: int = Field(ge=0, le=24 * 60)
    email_warning_severity: bool = True


class AlertSelfPreference(SensitiveActionRequest):
    receive_alerts: bool


def _component_payload(row: MonitorComponent, now: datetime, runner_fresh: bool) -> dict[str, Any]:
    definition = BY_KEY.get(row.key)
    return {
        "key": row.key,
        "name": definition.name if definition else row.key,
        "category": definition.category if definition else "internal",
        "provider": definition.provider if definition else None,
        "check_type": definition.check_type if definition else None,
        "verifies": definition.verifies if definition else None,
        "customer_impact": definition.customer_impact if definition else None,
        "services": [
            {"key": key, "name": ALL_STATUS_SERVICES.get(key, key)}
            for key in (definition.service_keys if definition else ())
        ],
        "state": effective_state(row, now, runner_fresh=runner_fresh),
        "stored_state": row.state,
        "confidence": row.confidence,
        "enabled": row.enabled,
        "interval_seconds": row.interval_seconds,
        "timeout_seconds": row.timeout_seconds,
        "failure_threshold": row.failure_threshold,
        "recovery_threshold": row.recovery_threshold,
        "public_visible": row.public_visible,
        "severity": row.severity,
        "consecutive_failures": row.consecutive_failures,
        "consecutive_successes": row.consecutive_successes,
        "last_attempted_at": row.last_attempted_at,
        "last_checked_at": row.last_checked_at,
        "last_success_at": row.last_success_at,
        "last_failure_at": row.last_failure_at,
        "last_latency_ms": row.last_latency_ms,
        "last_failure_category": row.last_failure_category,
        "last_failure_label": category_label(row.last_failure_category)
        if row.last_failure_category
        else None,
        "last_failure_detail": row.last_failure_detail,
        "state_changed_at": row.state_changed_at,
        "stale_after_seconds": int(stale_after(row).total_seconds()),
        "simulating_until": row.simulate_failure_until
        if row.simulate_failure_until and row.simulate_failure_until > now
        else None,
        # Still failed only because of fault injection (e.g. the simulation
        # expired, or its recovery check could not run yet): "Stop
        # simulation" remains available to recover it.
        "simulated_failure_held": holds_simulated_failure(row),
        "watchdog_managed": bool(definition and definition.watchdog_managed),
        "requires_live_validation": bool(definition and definition.requires_live_validation),
    }


def _override_payload(row: MonitorOverride, now: datetime) -> dict[str, Any]:
    return {
        "id": row.id,
        "service_key": row.service_key,
        "service_name": ALL_STATUS_SERVICES.get(row.service_key, row.service_key),
        "mode": "force" if row.forced_state else "suppress",
        "forced_state": row.forced_state,
        "reason": row.reason,
        "starts_at": row.starts_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "active": row.revoked_at is None and row.starts_at <= now < row.expires_at,
        "created_by": row.created_by,
    }


async def _runner_status(db: AsyncSession, now: datetime) -> dict[str, Any]:
    heartbeat = await db.get(OperationalHeartbeat, RUNNER_HEARTBEAT_SERVICE)
    age = int((now - heartbeat.observed_at).total_seconds()) if heartbeat else None
    return {
        "active": age is not None and age <= RUNNER_STALE_SECONDS,
        "last_cycle_at": heartbeat.observed_at if heartbeat else None,
        "detail": heartbeat.safe_detail if heartbeat else "No monitoring cycle has completed.",
    }


@router.get("")
async def monitoring_overview(
    _: PlatformContext = Depends(require_roles(*ALL_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    runner = await _runner_status(db, now)
    rows = {row.key: row for row in (await db.scalars(select(MonitorComponent))).all()}
    components = [
        _component_payload(rows[item.key], now, runner["active"])
        for item in CATALOGUE
        if item.key in rows
    ]
    snapshot = await compute_status_snapshot(db, now)
    overrides = (
        await db.scalars(
            select(MonitorOverride).order_by(MonitorOverride.created_at.desc()).limit(50)
        )
    ).all()
    transitions = (
        await db.scalars(
            select(MonitorTransition).order_by(MonitorTransition.occurred_at.desc()).limit(50)
        )
    ).all()
    unacknowledged = int(
        await db.scalar(
            select(func.count(MonitorAlert.id)).where(MonitorAlert.acknowledged_at.is_(None))
        )
        or 0
    )
    return {
        "environment": monitoring_alerts.environment_label(settings),
        "monitoring_enabled": settings.monitoring_enabled,
        "fault_injection_available": settings.environment != "production",
        "runner": runner,
        "components": components,
        "public_preview": {
            "overall": snapshot.overall,
            "overall_message": snapshot.overall_message,
            "services": [
                {"key": s.key, "name": s.name, "state": s.state, "confidence": s.confidence}
                for s in snapshot.services + snapshot.external_services
            ],
        },
        "overrides": [_override_payload(row, now) for row in overrides],
        "recent_transitions": [
            {
                "id": row.id,
                "component_key": row.component_key,
                "component_name": BY_KEY[row.component_key].name
                if row.component_key in BY_KEY
                else row.component_key,
                "occurred_at": row.occurred_at,
                "from_state": row.from_state,
                "to_state": row.to_state,
                "failure_label": category_label(row.failure_category)
                if row.failure_category
                else None,
                "detail": row.detail,
                "incident_id": row.incident_id,
            }
            for row in transitions
        ],
        "unacknowledged_alerts": unacknowledged,
    }


@router.get("/components/{key}/history")
async def component_history(
    key: str,
    hours: int = Query(default=24, ge=1, le=24 * 90),
    _: PlatformContext = Depends(require_roles(*ALL_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if key not in BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That monitored component does not exist.")
    since = datetime.now(UTC) - timedelta(hours=hours)
    observations = (
        await db.scalars(
            select(MonitorObservation)
            .where(MonitorObservation.component_key == key, MonitorObservation.observed_at >= since)
            .order_by(MonitorObservation.observed_at.desc())
            .limit(500)
        )
    ).all()
    transitions = (
        await db.scalars(
            select(MonitorTransition)
            .where(MonitorTransition.component_key == key, MonitorTransition.occurred_at >= since)
            .order_by(MonitorTransition.occurred_at.desc())
            .limit(200)
        )
    ).all()
    return {
        "key": key,
        "name": BY_KEY[key].name,
        "observations": [
            {
                "observed_at": row.observed_at,
                "outcome": row.outcome,
                "failure_severity": row.failure_severity,
                "latency_ms": row.latency_ms,
                "failure_label": category_label(row.failure_category)
                if row.failure_category
                else None,
                "detail": row.detail,
                "trigger": row.trigger,
            }
            for row in observations
        ],
        "transitions": [
            {
                "occurred_at": row.occurred_at,
                "from_state": row.from_state,
                "to_state": row.to_state,
                "consecutive_count": row.consecutive_count,
                "failure_label": category_label(row.failure_category)
                if row.failure_category
                else None,
                "detail": row.detail,
                "incident_id": row.incident_id,
            }
            for row in transitions
        ],
    }


async def _locked_component(db: AsyncSession, key: str) -> MonitorComponent:
    if key not in BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That monitored component does not exist.")
    await ensure_components(db)
    row = await db.scalar(
        select(MonitorComponent).where(MonitorComponent.key == key).with_for_update()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That monitored component does not exist.")
    return row


@router.patch("/components/{key}")
async def update_component(
    key: str,
    body: ComponentConfigUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    row = await _locked_component(db, key)
    fields = (
        "enabled",
        "interval_seconds",
        "timeout_seconds",
        "failure_threshold",
        "recovery_threshold",
        "public_visible",
        "severity",
    )
    changes = {name: getattr(body, name) for name in fields if getattr(body, name) is not None}
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No changes were supplied.")
    previous = {name: getattr(row, name) for name in changes}
    for name, value in changes.items():
        setattr(row, name, value)
    row.updated_by_administrator_id = context.administrator.id
    definition = BY_KEY[key]
    if changes.get("public_visible") is True and definition.requires_live_validation:
        # Distinct, searchable audit event: this is the "validated on the live
        # environment, allow it to affect the public page" decision.
        platform_audit(
            db,
            request,
            context,
            "monitoring.public_reporting_enabled",
            "monitor_component",
            reason=body.reason,
            new={"component": key},
        )
    platform_audit(
        db,
        request,
        context,
        "monitoring.component_updated",
        "monitor_component",
        reason=body.reason,
        previous={"component": key, **previous},
        new={"component": key, **changes},
    )
    await db.commit()
    return _component_payload(row, datetime.now(UTC), runner_fresh=True)


async def _run_single_check(
    settings: Settings, key: str, *, confirm_fault_injection: bool = False
) -> CycleReport:
    """Run one component's check now through the normal runner (advisory
    lock, row lock, transitions, incidents, alerts)."""
    redis = Redis.from_url(settings.redis_url, socket_timeout=5, decode_responses=True)
    try:
        async with build_http_client() as http:
            return await run_cycle(
                settings,
                http=http,
                redis=redis,
                only_keys={key},
                force=True,
                trigger="manual",
                wait_for_lock=10,
                confirm_fault_injection=confirm_fault_injection,
            )
    finally:
        await redis.aclose()


@router.post("/components/{key}/run")
async def run_component(
    key: str,
    body: ComponentRunRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Runs one check now. The result counts like any scheduled check
    (so three manual failures can confirm an outage just as the schedule
    would) and is labelled "manual" in the history. Throttled per component."""
    require_recent_auth(context, settings)
    definition = BY_KEY.get(key)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That monitored component does not exist.")
    if definition.watchdog_managed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This component is observed by the worker watchdog."
        )
    now = datetime.now(UTC)
    recent = await db.scalar(
        select(MonitorObservation.id).where(
            MonitorObservation.component_key == key,
            MonitorObservation.trigger == "manual",
            MonitorObservation.observed_at > now - MANUAL_RUN_COOLDOWN,
        )
    )
    if recent is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "This check was run moments ago; try again shortly."
        )
    report = await _run_single_check(settings, key)
    if not report.ran:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A monitoring cycle is in progress; try again shortly."
        )
    platform_audit(
        db,
        request,
        context,
        "monitoring.check_run",
        "monitor_component",
        reason=body.reason,
        new={"component": key, "transitions": report.transitions},
    )
    await db.commit()
    row = await db.get(MonitorComponent, key, populate_existing=True)
    assert row is not None
    return {
        "component": _component_payload(row, datetime.now(UTC), runner_fresh=True),
        "transitions": report.transitions,
        "alerts_raised": report.alerts,
    }


@router.post("/components/{key}/simulate-failure")
async def simulate_failure(
    key: str,
    body: SimulateFailureRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """DEV-only controlled fault injection. The component's check reports a
    simulated failure (and nothing else changes) until it expires or is
    stopped. The first simulated result is applied immediately as an
    already-confirmed failure through the normal runner, so the transition,
    automated incident and alert are produced at once by the real pipeline;
    later scheduled checks only repeat the same state, which raises nothing
    new. Thresholds are not changed. Refused outright in production."""
    require_recent_auth(context, settings)
    if settings.environment == "production":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Fault injection is not available in production."
        )
    row = await _locked_component(db, key)
    if BY_KEY[key].watchdog_managed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Stop the scheduler to exercise the monitoring watchdog."
        )
    if not row.enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Enable this component before simulating a failure."
        )
    until = datetime.now(UTC) + timedelta(minutes=body.minutes)
    row.simulate_failure_until = until
    row.simulate_failure_severity = body.severity
    platform_audit(
        db,
        request,
        context,
        "monitoring.fault_injection_started",
        "monitor_component",
        reason=body.reason,
        new={"component": key, "until": until.isoformat(), "severity": body.severity},
    )
    await db.commit()

    report = await _run_single_check(settings, key, confirm_fault_injection=True)
    if not report.ran:
        # Not applied: withdraw it rather than leave a simulation that would
        # only be counted against the normal threshold by scheduled checks.
        row = await _locked_component(db, key)
        row.simulate_failure_until = None
        row.simulate_failure_severity = None
        platform_audit(
            db,
            request,
            context,
            "monitoring.fault_injection_cleared",
            "monitor_component",
            outcome="failed",
            reason=body.reason,
            new={"component": key, "applied": False},
            failure_category="monitoring_cycle_in_progress",
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A monitoring cycle is in progress; try again shortly."
        )
    refreshed = await db.get(MonitorComponent, key, populate_existing=True)
    assert refreshed is not None
    return {
        "key": key,
        "simulating_until": until,
        "severity": body.severity,
        "transitions": report.transitions,
        "alerts_raised": report.alerts,
        "component": _component_payload(refreshed, datetime.now(UTC), runner_fresh=True),
    }


@router.post("/components/{key}/simulate-failure/clear")
async def clear_simulated_failure(
    key: str,
    body: ComponentRunRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Ends fault injection and starts a controlled recovery at once: the
    component's real check runs immediately, and if it succeeds the state
    held only by fault injection recovers through the normal pipeline
    (transition, incident resolution, recovery alert). A real failure is
    reported as a real failure and recovers under the normal thresholds."""
    require_recent_auth(context, settings)
    row = await _locked_component(db, key)
    # Only while the simulation is still running, or the state is still held
    # purely by it, do the failure counters consist of simulated results.
    # After an expiry followed by real failures, they are real evidence and
    # are kept, and no early recovery is attempted.
    was_simulated = (
        row.simulate_failure_until is not None and row.simulate_failure_until > datetime.now(UTC)
    ) or holds_simulated_failure(row)
    row.simulate_failure_until = None
    row.simulate_failure_severity = None
    if was_simulated:
        # Simulated failures must not count towards a later real outage.
        row.consecutive_failures = 0
    platform_audit(
        db,
        request,
        context,
        "monitoring.fault_injection_cleared",
        "monitor_component",
        reason=body.reason,
        new={"component": key},
    )
    await db.commit()

    transitions: list[str] = []
    alerts_raised = 0
    recovery_pending = False
    if (
        was_simulated
        and settings.environment != "production"
        and row.enabled
        and not BY_KEY[key].watchdog_managed
    ):
        report = await _run_single_check(settings, key, confirm_fault_injection=True)
        transitions, alerts_raised = report.transitions, report.alerts
        recovery_pending = not report.ran
    refreshed = await db.get(MonitorComponent, key, populate_existing=True)
    assert refreshed is not None
    return {
        "key": key,
        "simulating_until": None,
        "transitions": transitions,
        "alerts_raised": alerts_raised,
        # A monitoring cycle held the lock: the state is still held, and
        # "Stop simulation" stays available to retry the recovery.
        "recovery_pending": recovery_pending,
        "component": _component_payload(refreshed, datetime.now(UTC), runner_fresh=True),
    }


@router.post("/overrides", status_code=status.HTTP_201_CREATED)
async def create_override(
    body: OverrideCreate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    now = datetime.now(UTC)
    row = MonitorOverride(
        service_key=body.service_key,
        forced_state=ServiceState(body.forced_state).value if body.forced_state else None,
        reason=body.reason,
        starts_at=now,
        expires_at=now + timedelta(minutes=body.expires_in_minutes),
        created_by=context.administrator.id,
    )
    db.add(row)
    await db.flush()
    platform_audit(
        db,
        request,
        context,
        "monitoring.override_created",
        "monitor_override",
        row.id,
        reason=body.reason,
        new={
            "service_key": row.service_key,
            "mode": "force" if row.forced_state else "suppress",
            "forced_state": row.forced_state,
            "expires_at": row.expires_at.isoformat(),
        },
    )
    await db.commit()
    return _override_payload(row, now)


@router.post("/overrides/{override_id}/revoke")
async def revoke_override(
    override_id: uuid.UUID,
    body: OverrideRevoke,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    row = await db.get(MonitorOverride, override_id, with_for_update=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That override could not be found.")
    if row.revoked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That override is already revoked.")
    now = datetime.now(UTC)
    row.revoked_at = now
    row.revoked_by = context.administrator.id
    platform_audit(
        db,
        request,
        context,
        "monitoring.override_revoked",
        "monitor_override",
        row.id,
        reason=body.reason,
        previous={"service_key": row.service_key, "expires_at": row.expires_at.isoformat()},
        new={"revoked_at": now.isoformat()},
    )
    await db.commit()
    return _override_payload(row, now)


async def _deliveries_for(
    db: AsyncSession, alert_ids: list[uuid.UUID]
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {str(alert_id): [] for alert_id in alert_ids}
    if not alert_ids:
        return result
    rows = (
        await db.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.notification_type == monitoring_alerts.ALERT_NOTIFICATION_TYPE,
                or_(
                    *[
                        NotificationDelivery.idempotency_key.like(f"monitoring_alert:{alert_id}:%")
                        for alert_id in alert_ids
                    ]
                ),
            )
            .order_by(NotificationDelivery.created_at.desc())
        )
    ).all()
    for row in rows:
        parts = row.idempotency_key.split(":")
        if len(parts) < 4 or parts[1] not in result:
            continue
        result[parts[1]].append(
            {
                "attempt": parts[2],
                # Recipient identity is shown as the administrator's id or a
                # hashed extra-recipient reference, never the raw address.
                "recipient": ":".join(parts[3:-1]) if parts[-1] == "email" else ":".join(parts[3:]),
                "channel": row.channel.value,
                "status": row.status.value,
                "attempted_at": row.attempted_at,
                "retry_count": row.retry_count,
                "failure_reason": row.sanitised_failure_reason,
            }
        )
    return result


@router.get("/alerts")
async def list_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    _: PlatformContext = Depends(require_roles(*ALL_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    alerts = (
        await db.scalars(select(MonitorAlert).order_by(MonitorAlert.created_at.desc()).limit(limit))
    ).all()
    deliveries = await _deliveries_for(db, [alert.id for alert in alerts])
    admins = {
        admin.id: admin.display_name
        for admin in await db.scalars(
            select(PlatformAdministrator).where(
                PlatformAdministrator.id.in_(
                    {a.acknowledged_by for a in alerts if a.acknowledged_by is not None}
                )
            )
        )
    }
    return {
        "items": [
            {
                "id": alert.id,
                "created_at": alert.created_at,
                "kind": alert.kind,
                "severity": alert.severity,
                "component_key": alert.component_key,
                "component_name": BY_KEY[alert.component_key].name
                if alert.component_key in BY_KEY
                else alert.component_key,
                "incident_id": alert.incident_id,
                "subject": alert.subject,
                "summary": alert.summary,
                "suppressed_reason": alert.suppressed_reason,
                "recipient_count": alert.recipient_count,
                "deliveries": deliveries.get(str(alert.id), []),
                "acknowledged_at": alert.acknowledged_at,
                "acknowledged_by": admins.get(alert.acknowledged_by)
                if alert.acknowledged_by
                else None,
            }
            for alert in alerts
        ]
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: uuid.UUID,
    body: AlertAcknowledge,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    alert = await db.get(MonitorAlert, alert_id, with_for_update=True)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That alert could not be found.")
    if alert.acknowledged_at is None:
        alert.acknowledged_at = datetime.now(UTC)
        alert.acknowledged_by = context.administrator.id
        platform_audit(
            db,
            request,
            context,
            "monitoring.alert_acknowledged",
            "monitor_alert",
            alert.id,
            reason=body.note,
            new={"kind": alert.kind, "component": alert.component_key},
        )
        await db.commit()
    return {"id": alert.id, "acknowledged_at": alert.acknowledged_at}


@router.post("/alerts/{alert_id}/resend")
async def resend_alert(
    alert_id: uuid.UUID,
    body: AlertResend,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Re-queues the alert email to the current recipient list, e.g. after
    fixing a mail problem that made the original deliveries fail."""
    require_recent_auth(context, settings)
    alert = await db.get(MonitorAlert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That alert could not be found.")
    recipients = await monitoring_alerts.resolve_recipients(
        db, await monitoring_alerts.load_alert_settings(db)
    )
    if not recipients:
        raise HTTPException(status.HTTP_409_CONFLICT, "No alert recipients are configured.")
    attempt = f"resend-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    count = await monitoring_alerts.queue_alert_emails(
        db, settings, alert, recipients, attempt=attempt
    )
    platform_audit(
        db,
        request,
        context,
        "monitoring.alert_resent",
        "monitor_alert",
        alert.id,
        reason=body.reason,
        new={"recipients": count},
    )
    await db.commit()
    return {"id": alert.id, "queued": count}


@router.get("/alert-settings")
async def get_alert_settings(
    context: PlatformContext = Depends(require_roles(*ALL_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    values = await monitoring_alerts.load_alert_settings(db)
    recipients = await monitoring_alerts.resolve_recipients(db, values)
    # Additional recipients are personal email addresses: only the roles that
    # can manage them (Owner/Administrator) may see them. Every role still
    # sees whether alerting is on, the recipient roles and the total count.
    hidden = {"opted_out_administrator_ids"}
    can_manage = context.administrator.role in OPERATORS
    if not can_manage:
        hidden.add("additional_recipients")
    return {
        **{key: value for key, value in values.items() if key not in hidden},
        "additional_recipient_count": len(values.get("additional_recipients", [])),
        "can_manage": can_manage,
        "recipient_count": len(recipients),
        "receiving_alerts": str(context.administrator.id)
        not in {str(item) for item in values.get("opted_out_administrator_ids", [])}
        and context.administrator.role.value in values.get("roles", []),
    }


async def _store_alert_settings(
    db: AsyncSession, context: PlatformContext, values: dict[str, Any]
) -> None:
    row = await db.scalar(
        select(PlatformSetting)
        .where(PlatformSetting.key == monitoring_alerts.ALERT_SETTINGS_KEY)
        .with_for_update()
    )
    if row is None:
        db.add(
            PlatformSetting(
                key=monitoring_alerts.ALERT_SETTINGS_KEY,
                value={"value": values},
                updated_by=context.administrator.id,
            )
        )
    else:
        row.value = {"value": values}
        row.updated_by = context.administrator.id


@router.put("/alert-settings")
async def update_alert_settings(
    body: AlertSettingsUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    previous = await monitoring_alerts.load_alert_settings(db)
    values = {
        **previous,
        "enabled": body.enabled,
        "roles": [PlatformRole(role).value for role in body.roles],
        "additional_recipients": sorted({str(address) for address in body.additional_recipients}),
        "cooldown_minutes": body.cooldown_minutes,
        "email_warning_severity": body.email_warning_severity,
    }
    await _store_alert_settings(db, context, values)
    platform_audit(
        db,
        request,
        context,
        "monitoring.alert_settings_updated",
        "setting",
        reason=body.reason,
        previous={
            "enabled": previous.get("enabled"),
            "roles": previous.get("roles"),
            "additional_recipient_count": len(previous.get("additional_recipients", [])),
            "cooldown_minutes": previous.get("cooldown_minutes"),
        },
        new={
            "enabled": values["enabled"],
            "roles": values["roles"],
            "additional_recipient_count": len(values["additional_recipients"]),
            "cooldown_minutes": values["cooldown_minutes"],
        },
    )
    await db.commit()
    return {key: value for key, value in values.items() if key != "opted_out_administrator_ids"}


@router.put("/alert-settings/me")
async def update_own_alert_preference(
    body: AlertSelfPreference,
    request: Request,
    context: PlatformContext = Depends(require_roles(*ALL_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Any administrator can opt themselves out of (or back into) alert
    emails. Opting in only has effect if their role is a recipient role."""
    values = await monitoring_alerts.load_alert_settings(db)
    opted_out = {str(item) for item in values.get("opted_out_administrator_ids", [])}
    me = str(context.administrator.id)
    if body.receive_alerts:
        opted_out.discard(me)
    else:
        opted_out.add(me)
    values["opted_out_administrator_ids"] = sorted(opted_out)
    await _store_alert_settings(db, context, values)
    platform_audit(
        db,
        request,
        context,
        "monitoring.alert_preference_updated",
        "setting",
        reason=body.reason,
        new={"receive_alerts": body.receive_alerts},
    )
    await db.commit()
    return {"receive_alerts": body.receive_alerts}
