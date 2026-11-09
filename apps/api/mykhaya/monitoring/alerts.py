"""Administrator alerts for confirmed monitoring transitions.

Every alert is a durable MonitorAlert row written in the same transaction as
the transition that caused it, so a crash or restart can neither lose it nor
raise it twice (``dedupe_key`` is unique). Emails go through the existing
Notification Engine outbox: each recipient gets an ordinary
NotificationDelivery row (idempotency key ``monitoring_alert:<alert id>:...``)
retried with backoff by the worker, and visible in PCC whether it was sent,
is still queued or failed. The PCC alert centre is the second channel: every
alert appears there even when email is unavailable or suppressed.

PCC administrators have no push registration (they are separate from
consumer accounts), so push is not a channel today. See
docs/architecture/service-monitoring.md "Alert channels".
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import (
    MonitorAlert,
    MonitorComponent,
    MonitorTransition,
    PlatformAdministrator,
    PlatformRole,
    PlatformSetting,
)
from mykhaya.monitoring.catalogue import BY_KEY, RUNNER_COMPONENT_KEY
from mykhaya.monitoring.incidents import TransitionEvent
from mykhaya.monitoring.results import (
    DEGRADED,
    HEALTHY,
    NOT_APPLICABLE,
    UNAVAILABLE,
    UNKNOWN,
    category_label,
)
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification_email
from mykhaya.status_aggregation import ALL_STATUS_SERVICES

log = structlog.get_logger()

ALERT_SETTINGS_KEY = "monitoring_alerts"
ALERT_NOTIFICATION_TYPE = "platform.monitoring_alert"
DEFAULT_ALERT_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "roles": [PlatformRole.owner.value, PlatformRole.administrator.value],
    "additional_recipients": [],
    "opted_out_administrator_ids": [],
    "cooldown_minutes": 30,
    "email_warning_severity": True,
}

_KIND_HEADLINE = {
    DEGRADED: "Service Degraded",
    UNAVAILABLE: "Service Unavailable",
    "recovered": "Service Recovered",
    "monitoring_stale": "Monitoring Stopped",
    "monitoring_recovered": "Monitoring Resumed",
}
_STATE_LABEL = {
    HEALTHY: "Healthy",
    DEGRADED: "Degraded",
    UNAVAILABLE: "Unavailable",
    UNKNOWN: "Unknown",
    NOT_APPLICABLE: "Not applicable",
}


def environment_label(settings: Settings) -> str:
    return {"production": "PROD", "development": "DEV"}.get(
        settings.environment, settings.environment.upper()
    )


def _format_time(value: datetime | None, *, date: bool = True) -> str:
    if value is None:
        return "never"
    return value.strftime("%d/%m/%Y %H:%M UTC" if date else "%H:%M UTC")


async def load_alert_settings(db: AsyncSession) -> dict[str, Any]:
    row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == ALERT_SETTINGS_KEY))
    stored = dict((row.value if row else {}).get("value") or {})
    return {**DEFAULT_ALERT_SETTINGS, **stored}


async def resolve_recipients(
    db: AsyncSession, alert_settings: dict[str, Any]
) -> list[tuple[str, str]]:
    """(stable recipient id, email) for every active administrator in the
    configured roles who has not opted out, plus any additional addresses.
    Deduplicated case-insensitively."""
    roles = [PlatformRole(value) for value in alert_settings.get("roles", []) if value]
    opted_out = {str(value) for value in alert_settings.get("opted_out_administrator_ids", [])}
    recipients: dict[str, tuple[str, str]] = {}
    if roles:
        for admin in await db.scalars(
            select(PlatformAdministrator).where(
                PlatformAdministrator.is_active.is_(True), PlatformAdministrator.role.in_(roles)
            )
        ):
            if str(admin.id) in opted_out or not admin.email:
                continue
            recipients.setdefault(admin.email.casefold(), (f"admin:{admin.id}", admin.email))
    for address in alert_settings.get("additional_recipients", []):
        if isinstance(address, str) and "@" in address:
            digest = hashlib.sha256(address.casefold().encode()).hexdigest()[:16]
            recipients.setdefault(address.casefold(), (f"extra:{digest}", address))
    return list(recipients.values())


def awaiting_validation(component: MonitorComponent) -> bool:
    """A vantage-dependent check (public hostname / third-party endpoint)
    that has not yet been validated on the live environment. Validation is
    the existing, audited "Affects the public status page" switch: until it is
    on, the check's alerts are recorded in PCC but not emailed, so initial
    commissioning cannot flood administrators with routine degradation mail.

    Never true for the monitoring runner or any deterministic check
    (database, Redis, worker, queue, error rates, real delivery outcomes):
    those, and therefore monitoring-system failures, always email."""
    definition = BY_KEY.get(component.key)
    return bool(definition and definition.requires_live_validation and not component.public_visible)


def alert_kind(event: TransitionEvent, came_from_stale: bool) -> str | None:
    transition = event.transition
    to_state, from_state = transition.to_state, transition.from_state
    is_runner = event.component.key == RUNNER_COMPONENT_KEY
    if to_state in (DEGRADED, UNAVAILABLE):
        if is_runner:
            return "monitoring_stale"
        return to_state
    if to_state == UNKNOWN and transition.failure_category == "stale":
        return "monitoring_stale"
    if to_state == HEALTHY:
        if from_state in (DEGRADED, UNAVAILABLE):
            return "monitoring_recovered" if is_runner else "recovered"
        if from_state == UNKNOWN and came_from_stale:
            return "monitoring_recovered"
    return None


def _compose(
    settings: Settings,
    event: TransitionEvent,
    kind: str,
    incident_id: uuid.UUID | None,
) -> tuple[str, str]:
    component = event.component
    transition = event.transition
    definition = BY_KEY.get(component.key)
    env = environment_label(settings)
    service_names = [
        ALL_STATUS_SERVICES.get(key, key) for key in (definition.service_keys if definition else ())
    ]
    primary = (
        service_names[0] if service_names else (definition.name if definition else component.key)
    )
    subject = f"[MyKhaya {env}] {_KIND_HEADLINE.get(kind, 'Monitoring Alert')}: {primary}"
    admin_base = settings.admin_url.rstrip("/")
    link = f"{admin_base}/incidents/{incident_id}" if incident_id else f"{admin_base}/health"
    lines = [
        f"Service: {primary}",
        f"Component: {definition.name if definition else component.key}",
        f"Environment: {env}",
        f"Status: {_STATE_LABEL.get(transition.to_state, transition.to_state)}",
    ]
    if kind == "recovered" or kind == "monitoring_recovered":
        lines.append(f"Recovered: {_format_time(transition.occurred_at)}")
        lines.append(
            f"Previous status: {_STATE_LABEL.get(transition.from_state, transition.from_state)}"
        )
        lines.append(f"Consecutive successful checks: {transition.consecutive_count}")
    else:
        lines.append(f"Detected: {_format_time(transition.occurred_at)}")
        if transition.failure_category:
            lines.append(f"Failure: {category_label(transition.failure_category)}")
        if transition.detail:
            lines.append(f"Detail: {transition.detail}")
        lines.append(f"Consecutive failures: {transition.consecutive_count}")
        lines.append(
            f"Last successful check: {_format_time(event.previous_success_at, date=False)}"
        )
    if len(service_names) > 1:
        lines.append(f"Public services affected: {', '.join(service_names)}")
    if definition and kind not in ("recovered", "monitoring_recovered"):
        lines.extend(["", f"Customer impact: {definition.customer_impact}"])
    lines.extend(["", f"View details in PCC: {link}"])
    return subject[:200], "\n".join(lines)[:1000]


async def _create_alert(db: AsyncSession, values: dict[str, Any]) -> MonitorAlert | None:
    """Insert once; a concurrent or repeated attempt with the same
    dedupe_key is a no-op and returns None."""
    alert_id = await db.scalar(
        pg_insert(MonitorAlert)
        .values(id=uuid.uuid4(), **values)
        .on_conflict_do_nothing(constraint="uq_monitor_alerts_dedupe_key")
        .returning(MonitorAlert.id)
    )
    if alert_id is None:
        return None
    return await db.get(MonitorAlert, alert_id)


def _alert_link(alert: MonitorAlert) -> str | None:
    for line in alert.summary.splitlines():
        if line.startswith("View details in PCC: "):
            return line.removeprefix("View details in PCC: ").strip()
    return None


async def queue_alert_emails(
    db: AsyncSession,
    settings: Settings,
    alert: MonitorAlert,
    recipients: list[tuple[str, str]],
    *,
    attempt: str = "initial",
) -> int:
    """One durable email delivery per recipient through the Notification
    Engine (branded HTML + plain text, PCC template override aware)."""
    variables = {"subject": alert.subject, "summary": alert.summary}
    link = _alert_link(alert)
    if link:
        variables["link"] = link
    subject, body, html = await render_notification_email(
        db, settings, ALERT_NOTIFICATION_TYPE, variables
    )
    for recipient_id, email in recipients:
        await notify(
            db,
            settings=settings,
            recipient_email=email,
            notification_type=ALERT_NOTIFICATION_TYPE,
            title=subject,
            body=body,
            html_body=html,
            idempotency_key=f"monitoring_alert:{alert.id}:{attempt}:{recipient_id}",
        )
    return len(recipients)


async def raise_alert(
    db: AsyncSession,
    settings: Settings,
    *,
    dedupe_key: str,
    kind: str,
    severity: str,
    component_key: str | None,
    transition_id: uuid.UUID | None,
    incident_id: uuid.UUID | None,
    subject: str,
    summary: str,
    now: datetime,
    awaiting_validation: bool = False,
) -> MonitorAlert | None:
    alert_settings = await load_alert_settings(db)
    suppressed: str | None = None
    if not alert_settings.get("enabled", True):
        suppressed = "alerting_disabled"
    elif awaiting_validation:
        # Commissioning: the alert is recorded and shown in PCC, but not
        # emailed until the check has been validated (see awaiting_validation).
        suppressed = "awaiting_validation"
    elif severity == "info":
        suppressed = "info_severity"
    elif severity == "warning" and not alert_settings.get("email_warning_severity", True):
        suppressed = "warning_severity_email_disabled"
    else:
        cooldown = timedelta(minutes=int(alert_settings.get("cooldown_minutes", 30) or 0))
        if cooldown and component_key:
            recent = await db.scalar(
                select(MonitorAlert.id).where(
                    MonitorAlert.component_key == component_key,
                    MonitorAlert.kind == kind,
                    MonitorAlert.suppressed_reason.is_(None),
                    MonitorAlert.created_at >= now - cooldown,
                )
            )
            if recent is not None:
                suppressed = "cooldown"
    recipients: list[tuple[str, str]] = []
    if suppressed is None:
        recipients = await resolve_recipients(db, alert_settings)
        if not recipients:
            suppressed = "no_recipients"
    alert = await _create_alert(
        db,
        {
            "created_at": now,
            "dedupe_key": dedupe_key[:200],
            "component_key": component_key,
            "transition_id": transition_id,
            "incident_id": incident_id,
            "kind": kind,
            "severity": severity,
            "subject": subject,
            "summary": summary,
            "suppressed_reason": suppressed,
            "recipient_count": len(recipients) if suppressed is None else 0,
        },
    )
    if alert is None:
        return None
    if suppressed is None:
        await queue_alert_emails(db, settings, alert, recipients)
    log.info(
        "monitoring.alert_raised",
        kind=kind,
        component=component_key,
        suppressed=suppressed,
        recipients=len(recipients) if suppressed is None else 0,
    )
    return alert


async def raise_for_transitions(
    db: AsyncSession, settings: Settings, events: list[TransitionEvent], now: datetime
) -> list[MonitorAlert]:
    raised: list[MonitorAlert] = []
    for event in events:
        came_from_stale = False
        if event.transition.from_state == UNKNOWN and event.transition.to_state == HEALTHY:
            previous = await db.scalar(
                select(MonitorTransition)
                .where(
                    MonitorTransition.component_key == event.component.key,
                    MonitorTransition.to_state == UNKNOWN,
                    MonitorTransition.id != event.transition.id,
                )
                .order_by(MonitorTransition.occurred_at.desc())
                .limit(1)
            )
            came_from_stale = bool(previous and previous.failure_category == "stale")
        kind = alert_kind(event, came_from_stale)
        if kind is None:
            continue
        subject, summary = _compose(settings, event, kind, event.transition.incident_id)
        alert = await raise_alert(
            db,
            settings,
            dedupe_key=f"transition:{event.transition.id}",
            kind=kind,
            severity=event.component.severity,
            component_key=event.component.key,
            transition_id=event.transition.id,
            incident_id=event.transition.incident_id,
            subject=subject,
            summary=summary,
            now=now,
            awaiting_validation=awaiting_validation(event.component),
        )
        if alert is not None:
            raised.append(alert)
    return raised


async def component_for_alert(db: AsyncSession, alert: MonitorAlert) -> MonitorComponent | None:
    if alert.component_key is None:
        return None
    return await db.get(MonitorComponent, alert.component_key)
