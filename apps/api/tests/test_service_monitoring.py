"""Automated service monitoring (mykhaya.monitoring): state machine,
automatic public status, automated incidents, PCC alerts, the watchdog,
concurrency, and the guarantees that checks are read-only and public output
never leaks internal detail.

Failures are produced with the product's own DEV fault injection
(MonitorComponent.simulate_failure_until), which runs through exactly the
same runner, transition, incident and alert path as a real failure. Recovery
uses components whose *real* check genuinely passes in the test stack
(PostgreSQL and Redis). Network-facing checks are exercised against
httpx.MockTransport / fakes so the suite never touches a real provider.

What these tests do NOT prove: that live DEV/PROD providers are reachable,
that the hosted scheduler is running, or that real email arrives. See the
live DEV acceptance runbook in docs/operations/service-monitoring.md.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import smtplib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import delete, select, text, update
from test_platform_control_centre import admin_client, admin_factory, login, unsafe  # noqa: F401

from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.mailer import SmtpConfig
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    MonitorAlert,
    MonitorComponent,
    MonitorObservation,
    MonitorOverride,
    MonitorTransition,
    NotificationDelivery,
    NotificationDeliveryStatus,
    OperationalHeartbeat,
    OutboxEvent,
    PlatformAdministrator,
    PlatformRole,
    PlatformSetting,
    PublicIncident,
    StatusIncidentUpdate,
)
from mykhaya.monitoring import alerts, checks, engine, http_metrics, watchdog
from mykhaya.monitoring.catalogue import BY_KEY, CATALOGUE, RUNNER_COMPONENT_KEY
from mykhaya.monitoring.checks import CheckContext
from mykhaya.monitoring.results import CheckResult
from mykhaya.monitoring.state import next_state
from mykhaya.platform_schemas import PublicServiceKey
from mykhaya.status_aggregation import ALL_STATUS_SERVICES, compute_status_snapshot

STATUS_ORIGIN = "http://status.localhost:8080"
# Simulated clock: in the past, so automated incidents are already active
# (starts_at <= the database's real now()) when the public page is read.
T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)


# --- fixtures and helpers -----------------------------------------------------------------


async def _reset_monitoring() -> None:
    async with SessionFactory() as db:
        alert_rows = (await db.scalars(select(NotificationDelivery))).all()
        monitoring_deliveries = [
            row for row in alert_rows if row.notification_type == alerts.ALERT_NOTIFICATION_TYPE
        ]
        outbox_ids = [row.outbox_event_id for row in monitoring_deliveries if row.outbox_event_id]
        if monitoring_deliveries:
            await db.execute(
                delete(NotificationDelivery).where(
                    NotificationDelivery.id.in_([row.id for row in monitoring_deliveries])
                )
            )
        if outbox_ids:
            await db.execute(delete(OutboxEvent).where(OutboxEvent.id.in_(outbox_ids)))
        await db.execute(delete(MonitorAlert))
        await db.execute(delete(MonitorTransition))
        await db.execute(delete(MonitorObservation))
        await db.execute(delete(MonitorOverride))
        await db.execute(delete(MonitorComponent))
        await db.execute(delete(PublicIncident).where(PublicIncident.source == "automated"))
        await db.execute(
            delete(OperationalHeartbeat).where(OperationalHeartbeat.service == "monitoring")
        )
        await db.execute(
            delete(PlatformSetting).where(PlatformSetting.key == alerts.ALERT_SETTINGS_KEY)
        )
        await db.commit()
    engine._last_purge_at = None
    engine._last_watchdog_ping_at = None
    watchdog._last_tick_at = None


@pytest.fixture
async def monitoring_state(
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],  # noqa: F811
) -> AsyncIterator[Callable[[PlatformRole], Awaitable[PlatformAdministrator]]]:
    """Clean monitoring tables before and after. Depends on admin_factory so
    its teardown (overrides reference administrators) runs first."""
    await _reset_monitoring()
    yield admin_factory
    await _reset_monitoring()


@pytest.fixture
async def status_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=STATUS_ORIGIN) as value:
        yield value


@pytest_asyncio.fixture(loop_scope="session")
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield client
    await client.aclose()


def _offline_http() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline in tests", request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def cycle(
    redis: Redis,
    keys: set[str],
    now: datetime,
    *,
    settings: Settings | None = None,
) -> engine.CycleReport:
    async with _offline_http() as http:
        return await engine.run_cycle(
            settings or get_settings(),
            http=http,
            redis=redis,
            now=now,
            only_keys=keys,
            force=True,
        )


async def write_runner_heartbeat(now: datetime) -> None:
    async with SessionFactory() as db:
        await db.merge(
            OperationalHeartbeat(
                service="monitoring", observed_at=now, last_success_at=now, safe_detail="test"
            )
        )
        await db.commit()


async def simulate(key: str, until: datetime | None, severity: str = "unavailable") -> None:
    async with SessionFactory() as db:
        await engine.ensure_components(db)
        await db.execute(
            update(MonitorComponent)
            .where(MonitorComponent.key == key)
            .values(simulate_failure_until=until, simulate_failure_severity=severity)
        )
        await db.commit()


async def component(key: str) -> MonitorComponent:
    async with SessionFactory() as db:
        row = await db.get(MonitorComponent, key)
        assert row is not None
        return row


async def alerts_for(key: str) -> list[MonitorAlert]:
    async with SessionFactory() as db:
        return list(
            (
                await db.scalars(
                    select(MonitorAlert)
                    .where(MonitorAlert.component_key == key)
                    .order_by(MonitorAlert.created_at)
                )
            ).all()
        )


async def deliveries_for(alert: MonitorAlert) -> list[NotificationDelivery]:
    async with SessionFactory() as db:
        return list(
            (
                await db.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.idempotency_key.like(f"monitoring_alert:{alert.id}:%")
                    )
                )
            ).all()
        )


async def automated_incidents(service_key: str) -> list[PublicIncident]:
    async with SessionFactory() as db:
        return list(
            (
                await db.scalars(
                    select(PublicIncident).where(
                        PublicIncident.source == "automated",
                        PublicIncident.monitor_service_key == service_key,
                    )
                )
            ).all()
        )


async def fail_n(redis: Redis, key: str, start: datetime, count: int) -> datetime:
    await simulate(key, start + timedelta(hours=6))
    now = start
    for _ in range(count):
        await write_runner_heartbeat(now)
        await cycle(redis, {key}, now)
        now += timedelta(seconds=60)
    return now


async def succeed_n(redis: Redis, key: str, start: datetime, count: int) -> datetime:
    await simulate(key, None)
    now = start
    for _ in range(count):
        await write_runner_heartbeat(now)
        await cycle(redis, {key}, now)
        now += timedelta(seconds=60)
    return now


# --- catalogue consistency ----------------------------------------------------------------


def test_catalogue_service_keys_are_published_services() -> None:
    literal_keys = set(get_args(PublicServiceKey))
    assert literal_keys == set(ALL_STATUS_SERVICES)
    for definition in CATALOGUE:
        for key in definition.service_keys:
            assert key in ALL_STATUS_SERVICES, (definition.key, key)
    assert len({item.key for item in CATALOGUE}) == len(CATALOGUE)


@pytest.mark.parametrize(
    "service_key",
    [
        "web_application",
        "authentication",
        "api",
        "email_delivery",
        "notifications",
        "background_processing",
        "billing",
    ],
)
def test_every_public_service_has_automated_checks(service_key: str) -> None:
    assert any(service_key in item.service_keys for item in CATALOGUE)


# --- state machine (pure) -------------------------------------------------------------------


def _row(state: str = "unknown", failure: int = 3, recovery: int = 3) -> MonitorComponent:
    return MonitorComponent(
        key="api.database",
        state=state,
        failure_threshold=failure,
        recovery_threshold=recovery,
        consecutive_failures=0,
        consecutive_successes=0,
        interval_seconds=60,
        timeout_seconds=10,
        severity="critical",
        enabled=True,
        public_visible=True,
    )


def test_state_machine_thresholds() -> None:
    row = _row("healthy")
    fail = CheckResult.failure("connectivity", "x")
    assert next_state(row, fail) == "healthy"
    assert next_state(row, fail) == "healthy"
    assert next_state(row, fail) == "unavailable"
    row.state = "unavailable"
    ok = CheckResult.success()
    assert next_state(row, ok) == "unavailable"
    assert next_state(row, ok) == "unavailable"
    assert next_state(row, ok) == "healthy"


def test_unavailable_never_deescalates_to_degraded() -> None:
    row = _row("unavailable")
    row.consecutive_failures = 5
    assert next_state(row, CheckResult.failure("latency", "x", severity="degraded")) == (
        "unavailable"
    )


def test_unknown_becomes_healthy_on_first_success_and_inconclusive_changes_nothing() -> None:
    row = _row("unknown")
    assert next_state(row, CheckResult.inconclusive("quiet")) == "unknown"
    assert next_state(row, CheckResult.monitor_error("boom")) == "unknown"
    assert next_state(row, CheckResult.success()) == "healthy"


# --- scenarios 1-8: lifecycle through the real runner -----------------------------------------


@pytest.mark.asyncio
async def test_healthy_service_stays_operational(monitoring_state: Any, redis: Redis) -> None:
    now = await succeed_n(redis, "api.database", T0, 4)
    row = await component("api.database")
    assert row.state == "healthy"
    assert row.consecutive_successes == 4
    assert await alerts_for("api.database") == []
    async with SessionFactory() as db:
        snapshot = await compute_status_snapshot(db, now - timedelta(seconds=30))
    api = next(item for item in snapshot.services if item.key == "api")
    assert api.state == "operational"


@pytest.mark.asyncio
async def test_single_transient_failure_does_not_alert(monitoring_state: Any, redis: Redis) -> None:
    now = await succeed_n(redis, "api.database", T0, 1)
    now = await fail_n(redis, "api.database", now, 1)
    now = await succeed_n(redis, "api.database", now, 1)
    row = await component("api.database")
    assert row.state == "healthy"
    assert await alerts_for("api.database") == []
    assert await automated_incidents("api") == []


@pytest.mark.asyncio
async def test_three_failures_degrade_update_public_status_and_alert_admins(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
    status_client: AsyncClient,
) -> None:
    owner = await monitoring_state(PlatformRole.owner)
    read_only = await monitoring_state(PlatformRole.readonly)
    now = await succeed_n(redis, "api.database", T0, 1)
    now = await fail_n(redis, "api.database", now, 2)
    assert (await component("api.database")).state == "healthy"
    assert await alerts_for("api.database") == []

    now = await fail_n(redis, "api.database", now, 1)
    row = await component("api.database")
    assert row.state == "unavailable"
    assert row.last_failure_category == "simulated"

    # Scenario 4: the confirmed failure is reflected publicly, through an
    # automated incident with generic wording.
    incidents = await automated_incidents("api")
    assert len(incidents) == 1
    assert incidents[0].created_by is None
    assert "automated monitoring" in incidents[0].message.lower()

    # Scenario 5: an alert was raised and emailed to authorised admins only.
    raised = await alerts_for("api.database")
    assert [alert.kind for alert in raised] == ["unavailable"]
    alert = raised[0]
    assert alert.suppressed_reason is None
    assert alert.incident_id == incidents[0].id
    assert alert.subject.startswith("[MyKhaya TEST] Service Unavailable: API")
    for line in ("Environment: TEST", "Consecutive failures: 3", "Customer impact:"):
        assert line in alert.summary
    assert f"/incidents/{incidents[0].id}" in alert.summary
    keys = {delivery.idempotency_key for delivery in await deliveries_for(alert)}
    assert any(f"admin:{owner.id}" in key for key in keys)
    assert not any(f"admin:{read_only.id}" in key for key in keys)

    await write_runner_heartbeat(datetime.now(UTC))
    async with SessionFactory() as db:
        await db.execute(
            update(MonitorComponent)
            .where(MonitorComponent.key == "api.database")
            .values(last_checked_at=datetime.now(UTC))
        )
        await db.commit()
    payload = (await status_client.get("/api/v1/status")).json()
    states = {item["key"]: item["state"] for item in payload["services"]}
    assert states["api"] == "major_outage"
    assert any(item["title"] == incidents[0].title for item in payload["current_incidents"])


@pytest.mark.asyncio
async def test_prolonged_failure_does_not_repeat_alerts(
    monitoring_state: Any, redis: Redis
) -> None:
    now = await succeed_n(redis, "api.database", T0, 1)
    now = await fail_n(redis, "api.database", now, 10)
    raised = await alerts_for("api.database")
    assert len(raised) == 1
    async with SessionFactory() as db:
        transitions = (
            await db.scalars(
                select(MonitorTransition).where(
                    MonitorTransition.component_key == "api.database",
                    MonitorTransition.to_state == "unavailable",
                )
            )
        ).all()
    assert len(transitions) == 1
    assert len(await automated_incidents("api")) == 1


@pytest.mark.asyncio
async def test_recovery_is_detected_communicated_and_resolves_incident(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
) -> None:
    await monitoring_state(PlatformRole.owner)
    now = await succeed_n(redis, "api.database", T0, 1)
    now = await fail_n(redis, "api.database", now, 3)
    now = await succeed_n(redis, "api.database", now, 2)
    assert (await component("api.database")).state == "unavailable"
    now = await succeed_n(redis, "api.database", now, 1)
    assert (await component("api.database")).state == "healthy"
    kinds = [alert.kind for alert in await alerts_for("api.database")]
    assert kinds == ["unavailable", "recovered"]
    recovered = (await alerts_for("api.database"))[-1]
    assert recovered.suppressed_reason is None
    assert "Service Recovered" in recovered.subject
    incidents = await automated_incidents("api")
    assert len(incidents) == 1
    assert incidents[0].resolved_at is not None


@pytest.mark.asyncio
async def test_flapping_within_cooldown_does_not_resend_email(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
) -> None:
    await monitoring_state(PlatformRole.owner)
    now = await succeed_n(redis, "api.database", T0, 1)
    now = await fail_n(redis, "api.database", now, 3)
    now = await succeed_n(redis, "api.database", now, 3)
    now = await fail_n(redis, "api.database", now, 3)
    raised = await alerts_for("api.database")
    assert [alert.kind for alert in raised] == ["unavailable", "recovered", "unavailable"]
    assert raised[0].suppressed_reason is None
    assert raised[2].suppressed_reason == "cooldown"
    assert await deliveries_for(raised[2]) == []


@pytest.mark.asyncio
async def test_monitoring_that_stops_reports_unknown_not_operational(
    monitoring_state: Any, redis: Redis, status_client: AsyncClient
) -> None:
    now = await succeed_n(redis, "api.database", T0, 1)
    async with SessionFactory() as db:
        fresh = await compute_status_snapshot(db, now)
        later = await compute_status_snapshot(db, now + timedelta(minutes=10))
    assert next(s for s in fresh.services if s.key == "api").state == "operational"
    # Runner heartbeat now 10 minutes old: nothing can be trusted.
    assert later.monitoring_active is False
    assert next(s for s in later.services if s.key == "api").state == "unknown"
    assert later.overall == "unknown"
    assert later.overall_message == "Live service monitoring is temporarily unavailable"

    # With nothing ever observed (this test DB), the public page must also
    # say Unknown rather than Operational.
    payload = (await status_client.get("/api/v1/status")).json()
    assert payload["monitoring"] == {"active": False}
    assert {item["state"] for item in payload["services"]} == {"unknown"}


@pytest.mark.asyncio
async def test_stale_component_is_swept_to_unknown_and_alerted(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
) -> None:
    await monitoring_state(PlatformRole.owner)
    now = await succeed_n(redis, "api.database", T0, 1)
    later = now + timedelta(minutes=10)
    async with SessionFactory() as db:
        events = await engine.sweep_stale(db, later)
        raised = await alerts.raise_for_transitions(db, get_settings(), events, later)
        await db.commit()
    assert "api.database" in {event.component.key for event in events}
    assert (await component("api.database")).state == "unknown"
    assert any(
        alert.kind == "monitoring_stale" and alert.component_key == "api.database"
        for alert in raised
    )
    # The next good check recovers it and says so.
    await succeed_n(redis, "api.database", later + timedelta(minutes=1), 1)
    assert [a.kind for a in await alerts_for("api.database")][-1] == "monitoring_recovered"


# --- scenario 9: environment separation --------------------------------------------------------


@pytest.mark.asyncio
async def test_fault_injection_is_ignored_and_refused_in_production(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    production = get_settings().model_copy(update={"environment": "production"})
    await simulate("api.database", T0 + timedelta(hours=1))
    for offset in range(3):
        await write_runner_heartbeat(T0 + timedelta(minutes=offset))
        await cycle(redis, {"api.database"}, T0 + timedelta(minutes=offset), settings=production)
    assert (await component("api.database")).state == "healthy"

    admin = await monitoring_state(PlatformRole.owner)
    await login(admin_client, admin)
    app.dependency_overrides[get_settings] = lambda: production
    try:
        response = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/monitoring/components/api.database/simulate-failure",
            json={"minutes": 5, "reason": "Attempting PROD fault injection", "confirmed": True},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_fault_injection_confirmation_is_ignored_in_production(
    monitoring_state: Any, redis: Redis
) -> None:
    production = get_settings().model_copy(update={"environment": "production"})
    await succeed_n(redis, "api.database", T0, 1)
    await simulate("api.database", T0 + timedelta(hours=1))
    async with _offline_http() as http:
        await engine.run_cycle(
            production,
            http=http,
            redis=redis,
            now=T0 + timedelta(minutes=2),
            only_keys={"api.database"},
            force=True,
            confirm_fault_injection=True,
        )
    row = await component("api.database")
    assert row.state == "healthy"
    assert row.last_failure_category is None


def test_fault_injection_never_confirms_a_real_failure_or_real_recovery() -> None:
    real_outage = _row("unavailable")
    real_outage.last_failure_category = "connectivity"
    assert not engine.holds_simulated_failure(real_outage)
    assert not engine._fault_injection_confirms(real_outage, CheckResult.success())
    assert not engine._fault_injection_confirms(
        _row("healthy"), CheckResult.failure("connectivity", "x")
    )
    simulated = _row("unavailable")
    simulated.last_failure_category = "simulated"
    assert engine.holds_simulated_failure(simulated)
    assert engine._fault_injection_confirms(simulated, CheckResult.success())
    assert engine._fault_injection_confirms(_row("healthy"), CheckResult.failure("simulated", "x"))


async def _transitions(key: str) -> list[MonitorTransition]:
    async with SessionFactory() as db:
        return list(
            (
                await db.scalars(
                    select(MonitorTransition)
                    .where(MonitorTransition.component_key == key)
                    .order_by(MonitorTransition.occurred_at)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_pcc_fault_injection_confirms_immediately_and_stop_recovers(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    owner = await monitoring_state(PlatformRole.owner)
    await succeed_n(redis, "api.database", T0, 1)
    before = await component("api.database")
    assert before.state == "healthy"
    thresholds = (before.failure_threshold, before.recovery_threshold)
    assert thresholds[0] > 1
    await login(admin_client, owner)

    # One action: an already-confirmed failure through the real pipeline.
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/monitoring/components/api.database/simulate-failure",
        json={
            "minutes": 10,
            "severity": "unavailable",
            "reason": "DEV alert drill",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transitions"] == ["api.database:unavailable"]
    assert body["component"]["stored_state"] == "unavailable"
    assert body["component"]["simulating_until"] is not None
    transitions = await _transitions("api.database")
    failure = transitions[-1]
    assert (failure.from_state, failure.to_state) == ("healthy", "unavailable")
    assert failure.failure_category == "simulated"
    assert failure.consecutive_count == 1
    assert "DEV fault injection" in (failure.detail or "")
    incidents = await automated_incidents("api")
    assert len(incidents) == 1
    assert "fault injection" in (incidents[0].internal_notes or "")
    assert "fault injection" not in incidents[0].message.lower()
    raised = await alerts_for("api.database")
    assert [alert.kind for alert in raised] == ["unavailable"]
    assert raised[0].suppressed_reason is None
    assert "DEV fault injection" in raised[0].summary
    # One email per configured recipient (other tests may leave further
    # active administrators behind), including this owner.
    delivery_keys = {delivery.idempotency_key for delivery in await deliveries_for(raised[0])}
    assert len(delivery_keys) == raised[0].recipient_count
    assert any(f"admin:{owner.id}" in key for key in delivery_keys)

    # Scheduled checks during the simulation repeat the state: nothing new.
    now = datetime.now(UTC)
    for offset in range(1, 5):
        await write_runner_heartbeat(now + timedelta(minutes=offset))
        await cycle(redis, {"api.database"}, now + timedelta(minutes=offset))
    assert len(await _transitions("api.database")) == len(transitions)
    assert len(await alerts_for("api.database")) == 1
    assert len(await automated_incidents("api")) == 1
    async with SessionFactory() as db:
        triggers = set(
            (
                await db.scalars(
                    select(MonitorObservation.trigger).where(
                        MonitorObservation.component_key == "api.database",
                        MonitorObservation.failure_category == "simulated",
                    )
                )
            ).all()
        )
    assert triggers == {"simulated"}

    # One action: the real check runs and the recovery is confirmed at once.
    stopped = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/monitoring/components/api.database/simulate-failure/clear",
        json={"reason": "End DEV alert drill", "confirmed": True},
    )
    assert stopped.status_code == 200, stopped.text
    stop_body = stopped.json()
    assert stop_body["transitions"] == ["api.database:healthy"]
    assert stop_body["recovery_pending"] is False
    assert stop_body["component"]["simulating_until"] is None
    assert stop_body["component"]["simulated_failure_held"] is False
    row = await component("api.database")
    assert row.state == "healthy"
    assert (row.failure_threshold, row.recovery_threshold) == thresholds
    recovery = (await _transitions("api.database"))[-1]
    assert (recovery.from_state, recovery.to_state) == ("unavailable", "healthy")
    assert recovery.consecutive_count == 1
    assert "DEV fault injection" in (recovery.detail or "")
    incidents = await automated_incidents("api")
    assert len(incidents) == 1 and incidents[0].resolved_at is not None
    raised = await alerts_for("api.database")
    assert [alert.kind for alert in raised] == ["unavailable", "recovered"]
    assert raised[1].suppressed_reason is None
    assert "DEV fault injection" in raised[1].summary

    async with SessionFactory() as db:
        actions = (
            await db.scalars(
                select(AdministrativeAuditEvent.action).where(
                    AdministrativeAuditEvent.administrator_id == owner.id,
                    AdministrativeAuditEvent.action.like("monitoring.fault_injection%"),
                )
            )
        ).all()
    assert sorted(actions) == [
        "monitoring.fault_injection_cleared",
        "monitoring.fault_injection_started",
    ]


@pytest.mark.asyncio
async def test_pcc_stop_simulation_never_reports_a_false_recovery(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
    admin_client: AsyncClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await monitoring_state(PlatformRole.owner)
    await succeed_n(redis, "api.database", T0, 1)
    await login(admin_client, owner)
    started = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/monitoring/components/api.database/simulate-failure",
        json={"minutes": 10, "reason": "DEV alert drill", "confirmed": True},
    )
    assert started.status_code == 200, started.text
    assert (await component("api.database")).state == "unavailable"

    # The real service is genuinely failing when the simulation is stopped.
    async def real_failure(_: CheckContext) -> CheckResult:
        return CheckResult.failure("connectivity", "The database refused the connection.")

    failing = dataclasses.replace(BY_KEY["api.database"], run=real_failure)
    monkeypatch.setattr(
        engine,
        "CATALOGUE",
        [failing if item.key == "api.database" else item for item in engine.CATALOGUE],
    )
    stopped = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/monitoring/components/api.database/simulate-failure/clear",
        json={"reason": "End DEV alert drill", "confirmed": True},
    )
    assert stopped.status_code == 200, stopped.text
    body = stopped.json()
    assert body["transitions"] == []
    assert body["recovery_pending"] is False
    assert body["component"]["simulated_failure_held"] is False
    row = await component("api.database")
    assert row.state == "unavailable"
    assert row.last_failure_category == "connectivity"
    assert row.consecutive_failures == 1
    assert [t.to_state for t in await _transitions("api.database")][-1] == "unavailable"
    incidents = await automated_incidents("api")
    assert len(incidents) == 1 and incidents[0].resolved_at is None
    assert [alert.kind for alert in await alerts_for("api.database")] == ["unavailable"]

    # Once the service really recovers, the normal recovery threshold applies.
    monkeypatch.undo()
    now = datetime.now(UTC) + timedelta(minutes=1)
    await write_runner_heartbeat(now)
    await cycle(redis, {"api.database"}, now)
    assert (await component("api.database")).state == "unavailable"
    assert [alert.kind for alert in await alerts_for("api.database")] == ["unavailable"]


@pytest.mark.asyncio
async def test_pcc_fault_injection_is_refused_when_busy_or_disabled(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    owner = await monitoring_state(PlatformRole.owner)
    await login(admin_client, owner)
    path = "/api/v1/platform/monitoring/components/api.database/simulate-failure"
    payload = {"minutes": 10, "reason": "DEV alert drill", "confirmed": True}

    # A monitoring cycle holds the lock: nothing is applied or left behind.
    async with SessionFactory() as holder:
        assert await holder.scalar(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": engine.RUNNER_LOCK_KEY}
        )
        try:
            busy = await unsafe(admin_client, "POST", path, json=payload)
        finally:
            await holder.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": engine.RUNNER_LOCK_KEY}
            )
            await holder.commit()
    assert busy.status_code == 409
    row = await component("api.database")
    assert row.simulate_failure_until is None
    assert row.state == "unknown"

    # A disabled component cannot be used for fault injection.
    async with SessionFactory() as db:
        await db.execute(
            update(MonitorComponent)
            .where(MonitorComponent.key == "api.database")
            .values(enabled=False)
        )
        await db.commit()
    disabled = await unsafe(admin_client, "POST", path, json=payload)
    assert disabled.status_code == 409
    assert (await component("api.database")).simulate_failure_until is None


def test_alert_environment_label_comes_from_this_deployment_only() -> None:
    settings = get_settings()
    assert alerts.environment_label(settings.model_copy(update={"environment": "production"})) == (
        "PROD"
    )
    assert alerts.environment_label(settings.model_copy(update={"environment": "development"})) == (
        "DEV"
    )
    # Every monitoring table lives in the deployment's own database and has
    # no environment column to cross-reference: DEV and PROD share nothing.
    for model in (MonitorComponent, MonitorObservation, MonitorTransition, MonitorAlert):
        assert "environment" not in model.__table__.columns


# --- scenario 10: manual incidents and overrides still work -----------------------------------


@pytest.mark.asyncio
async def test_manual_incident_still_drives_public_state_alongside_monitoring(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    now = await succeed_n(redis, "api.database", T0, 1)
    admin = await monitoring_state(PlatformRole.owner)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/incidents",
        json={
            "title": "Manual billing incident",
            "message": "We are investigating checkout problems.",
            "services": [{"service": "api", "impact": "degraded_performance"}],
            "lifecycle_state": "investigating",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "reason": "Test manual incident alongside monitoring",
            "confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    incident_id = uuid.UUID(response.json()["id"])
    try:
        async with SessionFactory() as db:
            snapshot = await compute_status_snapshot(db, now - timedelta(seconds=30))
        api = next(item for item in snapshot.services if item.key == "api")
        assert api.state == "degraded_performance"
    finally:
        async with SessionFactory() as db:
            await db.execute(delete(PublicIncident).where(PublicIncident.id == incident_id))
            await db.commit()


@pytest.mark.asyncio
async def test_override_suppresses_and_forces_public_state_and_is_audited(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    admin = await monitoring_state(PlatformRole.owner)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/monitoring/overrides",
        json={
            "service_key": "api",
            "forced_state": None,
            "expires_in_minutes": 60,
            "reason": "Known false positive while investigating",
            "confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    override = response.json()
    assert override["mode"] == "suppress"

    now = datetime.now(UTC)
    await succeed_n(redis, "api.database", now, 1)
    await fail_n(redis, "api.database", now + timedelta(minutes=1), 3)
    assert (await component("api.database")).state == "unavailable"
    async with SessionFactory() as db:
        await write_runner_heartbeat(datetime.now(UTC))
        await db.execute(
            update(MonitorComponent)
            .where(MonitorComponent.key == "api.database")
            .values(last_checked_at=datetime.now(UTC))
        )
        await db.commit()
        snapshot = await compute_status_snapshot(db)
    api = next(item for item in snapshot.services if item.key == "api")
    assert api.state == "operational"
    assert api.confidence == "override"
    # Suppressed services never get an automated incident.
    assert await automated_incidents("api") == []

    revoke = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/monitoring/overrides/{override['id']}/revoke",
        json={"reason": "Investigation complete", "confirmed": True},
    )
    assert revoke.status_code == 200
    forced = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/monitoring/overrides",
        json={
            "service_key": "billing",
            "forced_state": "maintenance",
            "expires_in_minutes": 30,
            "reason": "Planned Stripe migration window",
            "confirmed": True,
        },
    )
    assert forced.status_code == 201
    async with SessionFactory() as db:
        snapshot = await compute_status_snapshot(db)
        billing = next(item for item in snapshot.services if item.key == "billing")
        assert billing.state == "maintenance"
        from mykhaya.models import AdministrativeAuditEvent

        actions = set(
            (
                await db.scalars(
                    select(AdministrativeAuditEvent.action).where(
                        AdministrativeAuditEvent.administrator_id == admin.id
                    )
                )
            ).all()
        )
    assert {"monitoring.override_created", "monitoring.override_revoked"} <= actions


# --- scenario 11: external failures stay contained ----------------------------------------------


@pytest.mark.asyncio
async def test_external_provider_failure_is_partial_disruption_only(
    monitoring_state: Any, redis: Redis
) -> None:
    now = await succeed_n(redis, "api.database", T0, 1)
    # An operator has validated this vantage-dependent check on the live
    # environment and enabled public reporting (it starts PCC-only).
    async with SessionFactory() as db:
        await db.execute(
            update(MonitorComponent)
            .where(MonitorComponent.key == "provider.dvsa.connectivity")
            .values(public_visible=True)
        )
        await db.commit()
    now = await fail_n(redis, "provider.dvsa.connectivity", now, 3)
    await write_runner_heartbeat(now)
    async with SessionFactory() as db:
        await db.execute(
            update(MonitorComponent)
            .where(MonitorComponent.key == "api.database")
            .values(last_checked_at=now)
        )
        await db.commit()
        snapshot = await compute_status_snapshot(db, now)
    dvsa = next(item for item in snapshot.external_services if item.key == "dvsa_mot_history")
    assert dvsa.state == "major_outage"
    assert next(item for item in snapshot.services if item.key == "api").state == "operational"
    assert snapshot.overall == "partial_outage"
    assert snapshot.overall_message == "Partial service disruption"


@pytest.mark.asyncio
async def test_a_check_that_crashes_or_hangs_never_stops_the_cycle() -> None:
    async def explode(_: CheckContext) -> CheckResult:
        raise RuntimeError("secret-token-in-message")

    async def hang(_: CheckContext) -> CheckResult:
        await asyncio.sleep(30)
        return CheckResult.success()

    base_definition = BY_KEY["api.database"]
    row = _row("healthy")
    row.timeout_seconds = 1
    async with _offline_http() as http:
        context = CheckContext(
            settings=get_settings(),
            session_factory=SessionFactory,
            http=http,
            redis=Redis.from_url(get_settings().redis_url),
            timeout=1,
            now=T0,
        )
        crashed, _ = await engine._execute(
            _replace(base_definition, run=explode), row, context, get_settings(), T0
        )
        hung, _ = await engine._execute(
            _replace(base_definition, run=hang), row, context, get_settings(), T0
        )
        await context.redis.aclose()
    assert crashed.outcome == "monitor_error"
    assert "secret-token" not in (crashed.detail or "")
    assert hung.outcome == "failure" and hung.category == "timeout"


def _replace(definition: Any, **changes: Any) -> Any:
    from dataclasses import replace

    return replace(definition, **changes)


def test_simultaneous_network_failures_across_providers_are_labelled_egress() -> None:
    failure = CheckResult.failure("dns", "DNS resolution failed.")
    results = {
        "provider.dvsa.connectivity": failure,
        "provider.apple.sign_in": failure,
        "billing.stripe_api": failure,
        "api.database": CheckResult.success(),
    }
    relabelled = engine._reclassify_egress(results)
    assert relabelled["provider.dvsa.connectivity"].category == "egress"
    assert relabelled["billing.stripe_api"].category == "egress"
    assert relabelled["api.database"].outcome == "success"
    single = engine._reclassify_egress({"provider.dvsa.connectivity": failure})
    assert single["provider.dvsa.connectivity"].category == "dns"


# --- scenario 12: concurrency --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_runners_cannot_both_run_or_duplicate_alerts(
    monitoring_state: Any, redis: Redis
) -> None:
    await simulate("api.database", T0 + timedelta(hours=1))
    await write_runner_heartbeat(T0)

    async def slow_run(now: datetime) -> engine.CycleReport:
        return await cycle(redis, {"api.database"}, now)

    reports = await asyncio.gather(*(slow_run(T0) for _ in range(4)))
    assert sum(1 for report in reports if report.ran) >= 1
    async with SessionFactory() as db:
        observations = (
            await db.scalars(
                select(MonitorObservation).where(MonitorObservation.component_key == "api.database")
            )
        ).all()
    assert len(observations) == sum(1 for report in reports if report.ran)

    # The alert itself is idempotent on its dedupe key.
    async with SessionFactory() as db:
        first = await alerts.raise_alert(
            db,
            get_settings(),
            dedupe_key="test:race",
            kind="degraded",
            severity="info",
            component_key="api.database",
            transition_id=None,
            incident_id=None,
            subject="s",
            summary="s",
            now=T0,
        )
        second = await alerts.raise_alert(
            db,
            get_settings(),
            dedupe_key="test:race",
            kind="degraded",
            severity="info",
            component_key="api.database",
            transition_id=None,
            incident_id=None,
            subject="s",
            summary="s",
            now=T0,
        )
        await db.commit()
    assert first is not None and second is None


@pytest.mark.asyncio
async def test_runner_lock_blocks_a_second_runner(monitoring_state: Any, redis: Redis) -> None:
    async with SessionFactory() as holder:
        assert await holder.scalar(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": engine.RUNNER_LOCK_KEY}
        )
        report = await cycle(redis, {"api.database"}, T0)
        await holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": engine.RUNNER_LOCK_KEY})
        await holder.commit()
    assert report.ran is False


# --- scenario 13: nothing internal reaches the public page ---------------------------------------


@pytest.mark.asyncio
async def test_public_status_never_exposes_internal_detail(
    monitoring_state: Any, redis: Redis, status_client: AsyncClient
) -> None:
    now = await fail_n(redis, "api.database", datetime.now(UTC), 3)
    await write_runner_heartbeat(datetime.now(UTC))
    body = (await status_client.get("/api/v1/status")).text
    for forbidden in (
        "Simulated",
        "simulated",
        "api.database",
        "Database",
        "PostgreSQL",
        "consecutive",
        "latency",
        "internal_notes",
        "Opened automatically by service monitoring",
        "fault injection",
    ):
        assert forbidden not in body, forbidden
    payload = json.loads(body)
    allowed = {"key", "name", "state", "confidence", "last_checked"}
    for item in payload["services"] + payload["external_services"]:
        assert set(item) == allowed
    assert now


# --- scenario 14: read-only, quota-safe checks ----------------------------------------------------


def _context(http: httpx.AsyncClient, settings: Settings | None = None) -> CheckContext:
    return CheckContext(
        settings=settings or get_settings(),
        session_factory=SessionFactory,
        http=http,
        redis=Redis.from_url(get_settings().redis_url),
        timeout=5,
        now=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_identity_provider_checks_only_fetch_public_keys() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"keys": [{"kid": "a"}, {"kid": "b"}]})

    settings = get_settings().model_copy(
        update={"apple_sign_in_enabled": True, "google_sign_in_enabled": True}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        context = _context(http, settings)
        apple = await checks.check_apple_sign_in(context)
        google = await checks.check_google_sign_in(context)
        await context.redis.aclose()
    assert apple.outcome == "success" and google.outcome == "success"
    assert {request.method for request in seen} == {"GET"}
    assert {str(request.url) for request in seen} == {
        settings.apple_jwks_url,
        settings.google_jwks_url,
    }
    assert all("authorization" not in request.headers for request in seen)


@pytest.mark.asyncio
async def test_stripe_check_is_a_single_read_and_never_leaks_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mykhaya.billing.config import StripeConfig

    secret = "sk_test_never_leak_this_value"

    async def fake_config(*_: object) -> StripeConfig:
        return StripeConfig(source="environment", configured=True, secret_key=secret)

    monkeypatch.setattr(checks, "resolve_stripe_config", fake_config)
    seen: list[httpx.Request] = []
    responses = iter([401, 429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(next(responses), json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        context = _context(http)
        results = [await checks.check_stripe_api(context) for _ in range(4)]
        await context.redis.aclose()
    assert [r.category for r in results] == ["auth_config", "rate_limited", "provider_outage", None]
    assert results[1].failure_severity == "degraded"
    assert results[3].outcome == "success"
    assert {(request.method, request.url.path) for request in seen} == {("GET", "/v1/balance")}
    assert all(secret not in (result.detail or "") for result in results)


@pytest.mark.asyncio
async def test_disabled_stripe_is_not_applicable_but_enabled_incomplete_stripe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mykhaya.billing.config import StripeConfig

    configs = iter(
        [
            StripeConfig(source="unconfigured", configured=False),
            StripeConfig(source="database", configured=False, incomplete_reason="missing key"),
        ]
    )

    async def fake_config(*_: object) -> StripeConfig:
        return next(configs)

    monkeypatch.setattr(checks, "resolve_stripe_config", fake_config)
    async with _offline_http() as http:
        context = _context(http)
        disabled = await checks.check_stripe_api(context)
        incomplete = await checks.check_stripe_api(context)
        await context.redis.aclose()
    assert disabled.outcome == "not_applicable"
    assert disabled.category == "not_configured"
    assert incomplete.outcome == "failure"
    assert incomplete.category == "auth_config"
    assert "missing key" not in (incomplete.detail or "")


@pytest.mark.asyncio
async def test_dvsa_and_dvla_checks_make_no_vehicle_lookups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probed: list[str] = []

    async def fake_probe(host: str, port: int, timeout_seconds: float):
        probed.append(host)
        return CheckResult.success("ok", confidence="limited"), 90

    async def enabled(*_: object) -> bool:
        return True

    monkeypatch.setattr(checks, "probe_tls", fake_probe)
    monkeypatch.setattr(checks, "_platform_toggle", enabled)
    settings = get_settings().model_copy(
        update={
            "dvsa_enabled": True,
            "dvsa_token_url": "https://login.example.test/token",
            "dvsa_client_id": SecretStr("id"),
            "dvsa_client_secret": SecretStr("secret"),
            "dvsa_api_key": SecretStr("key"),
            "dvla_environment": "uat",
            "dvla_uat_endpoint": "https://uat.dvla.example.test/vehicles",
            "dvla_uat_api_key": SecretStr("dvla-key"),
        }
    )

    def no_http(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP request to {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(no_http)) as http:
        context = _context(http, settings)
        dvsa = await checks.check_dvsa_connectivity(context)
        dvla = await checks.check_dvla_connectivity(context)
        await context.redis.aclose()
    assert dvsa.outcome == "success" and dvla.outcome == "success"
    assert set(probed) == {
        "history.mot.api.gov.uk",
        "login.example.test",
        "uat.dvla.example.test",
    }


@pytest.mark.asyncio
async def test_smtp_check_never_sends_a_message(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeSmtp:
        def __init__(self, *args: object, **kwargs: object) -> None:
            calls.append("connect")

        def __enter__(self) -> FakeSmtp:
            return self

        def __exit__(self, *args: object) -> None:
            calls.append("quit")

        def ehlo(self) -> None:
            calls.append("ehlo")

        def starttls(self, **_: object) -> None:
            calls.append("starttls")

        def login(self, *_: object) -> None:
            calls.append("login")

        def noop(self) -> tuple[int, bytes]:
            calls.append("noop")
            return 250, b"ok"

        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"SMTP.{name} must never be called by monitoring")

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    config = SmtpConfig(
        source="environment",
        configured=True,
        host="mail.example.test",
        port=587,
        connection_security="starttls",
        username="user",
        password="pw",
        sender="noreply@example.test",
    )

    async def fake_config(*_: object) -> SmtpConfig:
        return config

    monkeypatch.setattr(checks, "resolve_smtp_config", fake_config)
    async with _offline_http() as http:
        context = _context(http)
        result = await checks.check_smtp(context)
        await context.redis.aclose()
    assert result.outcome == "success"
    assert calls == ["connect", "ehlo", "starttls", "ehlo", "login", "noop", "quit"]


@pytest.mark.asyncio
async def test_network_errors_are_classified_without_echoing_messages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out talking to 10.0.0.5 with token=abc", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        context = _context(http, get_settings().model_copy(update={"apple_sign_in_enabled": True}))
        result = await checks.check_apple_sign_in(context)
        await context.redis.aclose()
    assert result.category == "timeout"
    assert "10.0.0.5" not in (result.detail or "") and "token" not in (result.detail or "")


@pytest.mark.asyncio
async def test_error_rate_monitor_uses_real_request_counters(redis: Redis) -> None:
    await http_metrics.clear(redis, "api")
    async with _offline_http() as http:
        context = _context(http)
        quiet = await checks.check_api_error_rate(context)
        await http_metrics.write_bucket(redis, "api", requests=100, errors=30, latency_ms=10_000)
        failing = await checks.check_api_error_rate(context)
        await http_metrics.clear(redis, "api")
        await http_metrics.write_bucket(redis, "api", requests=100, errors=1, latency_ms=10_000)
        healthy = await checks.check_api_error_rate(context)
        await http_metrics.clear(redis, "api")
        await context.redis.aclose()
    assert quiet.outcome == "success" and quiet.confidence == "limited"
    assert failing.outcome == "failure" and failing.failure_severity == "unavailable"
    assert healthy.outcome == "success"
    assert healthy.detail is not None and "API: 1 of 100 requests" in healthy.detail


def test_request_metrics_exclude_probe_and_control_centre_paths() -> None:
    assert http_metrics.area_for_path("/api/v1/auth/login") == "auth"
    assert http_metrics.area_for_path("/api/v1/calendar/events") == "api"
    assert http_metrics.area_for_path("/api/v1/health/ready") is None
    assert http_metrics.area_for_path("/api/v1/status") is None
    assert http_metrics.area_for_path("/api/v1/platform/health") is None
    assert http_metrics.area_for_path("/_next/static/x.js") is None


# --- scenario 15: delivery failures are visible and recoverable ----------------------------------


@pytest.mark.asyncio
async def test_failed_alert_delivery_is_visible_and_can_be_resent(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    admin = await monitoring_state(PlatformRole.owner)
    now = await succeed_n(redis, "api.database", T0, 1)
    await fail_n(redis, "api.database", now, 3)
    alert = (await alerts_for("api.database"))[0]
    async with SessionFactory() as db:
        await db.execute(
            update(NotificationDelivery)
            .where(NotificationDelivery.idempotency_key.like(f"monitoring_alert:{alert.id}:%"))
            .values(
                status=NotificationDeliveryStatus.failed,
                sanitised_failure_reason="dns_or_connectivity_failure",
            )
        )
        await db.commit()

    await login(admin_client, admin)
    listing = (await admin_client.get("/api/v1/platform/monitoring/alerts")).json()
    item = next(row for row in listing["items"] if row["id"] == str(alert.id))
    assert item["deliveries"]
    assert {d["status"] for d in item["deliveries"]} == {"failed"}
    assert all("@" not in d["recipient"] for d in item["deliveries"])

    resend = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/monitoring/alerts/{alert.id}/resend",
        json={"reason": "Mail server credentials fixed", "confirmed": True},
    )
    assert resend.status_code == 200, resend.text
    assert resend.json()["queued"] >= 1
    statuses = {d.status for d in await deliveries_for(alert)}
    assert NotificationDeliveryStatus.queued in statuses

    ack = await unsafe(
        admin_client, "POST", f"/api/v1/platform/monitoring/alerts/{alert.id}/acknowledge", json={}
    )
    assert ack.status_code == 200
    assert ack.json()["acknowledged_at"] is not None


@pytest.mark.asyncio
async def test_alerts_respect_disabled_setting_and_opt_out(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    admin = await monitoring_state(PlatformRole.owner)
    await login(admin_client, admin)
    me = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/monitoring/alert-settings/me",
        json={"receive_alerts": False, "reason": "On leave this fortnight", "confirmed": True},
    )
    assert me.status_code == 200
    now = await succeed_n(redis, "api.database", T0, 1)
    await fail_n(redis, "api.database", now, 3)
    alert = (await alerts_for("api.database"))[0]
    keys = {d.idempotency_key for d in await deliveries_for(alert)}
    assert not any(f"admin:{admin.id}" in key for key in keys)


# --- the watchdog ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watchdog_alerts_when_runner_stops_and_dispatches_without_scheduler(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
) -> None:
    await monitoring_state(PlatformRole.owner)
    await redis.delete("mykhaya:jobs")
    async with SessionFactory() as db:
        await db.execute(
            delete(OperationalHeartbeat).where(OperationalHeartbeat.service == "scheduler")
        )
        await db.commit()
    # Real-time clock here: the alert's outbox row gets the database's now()
    # as available_at, and the watchdog only dispatches rows already due.
    start = datetime.now(UTC)
    await write_runner_heartbeat(start)
    settings = get_settings()
    assert await watchdog.watchdog_tick(
        settings, redis=redis, now=start + timedelta(seconds=30), force=True
    )
    assert (await component(RUNNER_COMPONENT_KEY)).state == "healthy"

    # Runner silent for 5, then 6 minutes: two failing ticks confirm it.
    await watchdog.watchdog_tick(
        settings, redis=redis, now=start + timedelta(minutes=5), force=True
    )
    assert (await component(RUNNER_COMPONENT_KEY)).state == "healthy"
    await watchdog.watchdog_tick(
        settings, redis=redis, now=start + timedelta(minutes=6), force=True
    )
    assert (await component(RUNNER_COMPONENT_KEY)).state == "unavailable"
    raised = await alerts_for(RUNNER_COMPONENT_KEY)
    assert [alert.kind for alert in raised] == ["monitoring_stale"]
    assert "Monitoring Stopped" in raised[0].subject
    # With the scheduler down too, the watchdog itself queued the email job.
    queued = await redis.lrange("mykhaya:jobs", 0, -1)
    delivery_outbox_ids = {
        str(d.outbox_event_id) for d in await deliveries_for(raised[0]) if d.outbox_event_id
    }
    assert delivery_outbox_ids
    assert delivery_outbox_ids <= {json.loads(item)["event_id"] for item in queued}

    await write_runner_heartbeat(start + timedelta(minutes=7))
    await watchdog.watchdog_tick(
        settings, redis=redis, now=start + timedelta(minutes=7), force=True
    )
    assert [a.kind for a in await alerts_for(RUNNER_COMPONENT_KEY)] == [
        "monitoring_stale",
        "monitoring_recovered",
    ]
    await redis.delete("mykhaya:jobs")


@pytest.mark.asyncio
async def test_watchdog_dispatches_alerts_even_behind_an_email_backlog(
    monitoring_state: Any, redis: Redis
) -> None:
    """Regression: the watchdog used to take the 200 oldest pending emails and
    filter afterwards, so a customer-email backlog hid the alert."""
    now = datetime.now(UTC) + timedelta(minutes=5)
    backlog_ids: list[uuid.UUID] = []
    async with SessionFactory() as db:
        for index in range(210):
            event = OutboxEvent(
                topic="notification.email",
                payload={"notification_type": "email_verification", "n": index},
                created_at=now - timedelta(hours=2),
                available_at=now - timedelta(hours=2),
            )
            db.add(event)
            await db.flush()
            backlog_ids.append(event.id)
        alert_event = OutboxEvent(
            topic="notification.email",
            payload={"notification_type": alerts.ALERT_NOTIFICATION_TYPE},
            available_at=now - timedelta(minutes=1),
        )
        db.add(alert_event)
        await db.commit()
    await redis.delete("mykhaya:jobs")
    try:
        async with SessionFactory() as db:
            dispatched = await watchdog.dispatch_alert_emails(db, redis, now)
            await db.commit()
        queued = {
            json.loads(item)["event_id"] for item in await redis.lrange("mykhaya:jobs", 0, -1)
        }
        assert str(alert_event.id) in queued
        assert not queued & {str(event_id) for event_id in backlog_ids}
        assert dispatched >= 1
    finally:
        await redis.delete("mykhaya:jobs")
        async with SessionFactory() as db:
            await db.execute(
                delete(OutboxEvent).where(OutboxEvent.id.in_([*backlog_ids, alert_event.id]))
            )
            await db.commit()


@pytest.mark.asyncio
async def test_external_watchdog_ping_reports_failure(monitoring_state: Any, redis: Redis) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    settings = get_settings().model_copy(
        update={"monitoring_watchdog_url": SecretStr("https://hc.example.test/ping/abc")}
    )
    now = await fail_n(redis, "api.database", T0, 3)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await engine._maybe_ping_watchdog(
            settings, http, SessionFactory, now - timedelta(seconds=30)
        )
    assert seen == ["https://hc.example.test/ping/abc/fail"]


# --- PCC API -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pcc_overview_history_config_and_permissions(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    await succeed_n(redis, "api.database", T0, 2)
    viewer = await monitoring_state(PlatformRole.readonly)
    await login(admin_client, viewer)
    overview = (await admin_client.get("/api/v1/platform/monitoring")).json()
    keys = {item["key"] for item in overview["components"]}
    assert "api.database" in keys and RUNNER_COMPONENT_KEY in keys
    history = (
        await admin_client.get(
            "/api/v1/platform/monitoring/components/api.database/history?hours=2160"
        )
    ).json()
    assert len(history["observations"]) == 2
    forbidden = await unsafe(
        admin_client,
        "PATCH",
        "/api/v1/platform/monitoring/components/api.database",
        json={"failure_threshold": 5, "reason": "Read-only cannot do this", "confirmed": True},
    )
    assert forbidden.status_code == 403

    owner = await monitoring_state(PlatformRole.owner)
    admin_client.cookies.clear()
    await login(admin_client, owner)
    changed = await unsafe(
        admin_client,
        "PATCH",
        "/api/v1/platform/monitoring/components/api.database",
        json={"failure_threshold": 5, "reason": "Tune threshold for noisy DB", "confirmed": True},
    )
    assert changed.status_code == 200, changed.text
    assert (await component("api.database")).failure_threshold == 5
    invalid = await unsafe(
        admin_client,
        "PATCH",
        "/api/v1/platform/monitoring/components/api.database",
        json={"interval_seconds": 1, "reason": "Too aggressive interval", "confirmed": True},
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_pcc_on_demand_run_records_a_manual_observation(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    owner = await monitoring_state(PlatformRole.owner)
    await login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/monitoring/components/api.database/run",
        json={"reason": "Verify database after failover", "confirmed": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["component"]["stored_state"] == "healthy"
    again = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/monitoring/components/api.database/run",
        json={"reason": "Verify database after failover", "confirmed": True},
    )
    assert again.status_code == 429
    async with SessionFactory() as db:
        triggers = (
            await db.scalars(
                select(MonitorObservation.trigger).where(
                    MonitorObservation.component_key == "api.database"
                )
            )
        ).all()
    assert triggers == ["manual"]


@pytest.mark.asyncio
async def test_full_cycle_runs_every_check_without_crashing(
    monitoring_state: Any, redis: Redis
) -> None:
    async with _offline_http() as http:
        report = await engine.run_cycle(get_settings(), http=http, redis=redis, now=T0)
    assert report.ran
    expected = {item.key for item in CATALOGUE if not item.watchdog_managed}
    assert set(report.executed) == expected
    async with SessionFactory() as db:
        heartbeat = await db.get(OperationalHeartbeat, "monitoring")
    assert heartbeat is not None and heartbeat.observed_at == T0


# --- restart recovery, manual precedence, public contract ------------------------------------


@pytest.mark.asyncio
async def test_restart_resumes_state_without_duplicate_incident_or_alert(
    monitoring_state: Any, redis: Redis
) -> None:
    now = await succeed_n(redis, "api.database", T0, 1)
    now = await fail_n(redis, "api.database", now, 3)
    # A process restart loses every in-memory value; all state is in the DB.
    engine._last_purge_at = None
    engine._last_watchdog_ping_at = None
    watchdog._last_tick_at = None
    row = await component("api.database")
    assert row.state == "unavailable" and row.consecutive_failures == 3
    now = await fail_n(redis, "api.database", now, 3)
    assert len(await automated_incidents("api")) == 1
    assert len(await alerts_for("api.database")) == 1
    assert (await component("api.database")).consecutive_failures == 6


@pytest.mark.asyncio
async def test_manual_resolution_of_automated_incident_is_not_undone_mid_failure(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    now = await succeed_n(redis, "api.database", T0, 1)
    now = await fail_n(redis, "api.database", now, 3)
    incident = (await automated_incidents("api"))[0]
    admin = await monitoring_state(PlatformRole.owner)
    await login(admin_client, admin)
    resolved = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/incidents/{incident.id}/updates",
        json={
            "message": "Customers are not affected; closing while we fix the check.",
            "lifecycle_state": "resolved",
            "resolved": True,
            "reason": "Operator judgement: not customer impacting",
            "confirmed": True,
        },
    )
    assert resolved.status_code == 201, resolved.text
    await fail_n(redis, "api.database", now, 5)
    incidents = await automated_incidents("api")
    assert len(incidents) == 1 and incidents[0].resolved_at is not None
    async with SessionFactory() as db:
        updates = (
            await db.scalars(
                select(StatusIncidentUpdate).where(StatusIncidentUpdate.incident_id == incident.id)
            )
        ).all()
    # The administrator's update is recorded with their identity.
    assert any(update.created_by == admin.id for update in updates)


@pytest.mark.asyncio
async def test_public_contract_keeps_every_legacy_field(status_client: AsyncClient) -> None:
    payload = (await status_client.get("/api/v1/status")).json()
    legacy = {
        "overall",
        "overall_message",
        "services",
        "current_incidents",
        "recent_incidents",
        "last_updated",
    }
    assert legacy <= set(payload)
    assert [item["key"] for item in payload["services"]] == [
        "web_application",
        "authentication",
        "api",
        "email_delivery",
        "notifications",
        "background_processing",
        "billing",
    ]
    for item in payload["services"]:
        assert {"key", "name", "state"} <= set(item)
    snapshot = await status_client.get("/api/v1/status/snapshot")
    assert snapshot.status_code == 200
    assert "stale-if-error" in snapshot.headers["cache-control"]


# --- public hostnames behind Cloudflare, and the live-validation gate -------------------------


def _cf(status: int, body: str = "", headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        text=body,
        headers={"server": "cloudflare", "cf-ray": "8abc123-LHR", **(headers or {})},
    )


def test_cloudflare_challenge_is_cannot_verify_never_an_outage() -> None:
    result = checks.classify_public_route(_cf(403, headers={"cf-mitigated": "challenge"}), "web")
    assert result is not None and result.outcome == "monitor_error"
    assert result.category == "waf_challenge"
    page = checks.classify_public_route(
        _cf(503, "<html><title>Just a moment...</title>challenge-platform</html>"), "web"
    )
    assert page is not None and page.category == "waf_challenge"
    # A WAF *block* (not a challenge) is also "cannot verify", never an outage.
    for blocked in (
        _cf(403, "<title>Attention Required! | Cloudflare</title>Sorry, you have been blocked"),
        _cf(403, "error code: 1020"),
        _cf(429, "error code: 1015"),
    ):
        verdict = checks.classify_public_route(blocked, "web")
        assert verdict is not None and verdict.outcome == "monitor_error", blocked.text
    # A plain origin 403 (no Cloudflare) still counts as a real failure.
    plain = checks.classify_public_route(httpx.Response(403), "web")
    assert plain is not None and plain.outcome == "failure"


def test_cloudflare_origin_failures_are_distinguished() -> None:
    unreachable = checks.classify_public_route(_cf(522), "web")
    assert unreachable is not None and unreachable.category == "edge_origin_unreachable"
    assert "8abc123-LHR" in (unreachable.detail or "")
    origin_dns = checks.classify_public_route(_cf(530, "error code: 1016"), "web")
    assert origin_dns is not None and "Cloudflare error 1016" in (origin_dns.detail or "")
    origin_tls = checks.classify_public_route(_cf(526), "web")
    assert origin_tls is not None and origin_tls.category == "edge_origin_tls"
    assert checks.classify_public_route(_cf(200, "<html>ok</html>"), "web") is None
    origin_5xx = checks.classify_public_route(httpx.Response(502), "web")
    assert origin_5xx is not None and origin_5xx.category == "provider_outage"


PUBLIC = {
    "public_web_url": "https://dev.mykhaya.app",
    "native_api_url": "https://api.dev.mykhaya.app",
    "monitoring_web_url": "http://web:3000",
    "monitoring_api_url": "http://api:8000",
}


async def _run_self_checks(
    handler: Callable[[httpx.Request], httpx.Response],
) -> dict[str, CheckResult]:
    settings = get_settings().model_copy(update=PUBLIC)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        context = _context(http, settings)
        results = {
            "web": await checks.check_web_http(context),
            "ready": await checks.check_api_ready(context),
            "auth": await checks.check_auth_endpoint(context),
        }
        await context.redis.aclose()
    return results


@pytest.mark.asyncio
async def test_self_checks_use_only_the_internal_docker_network() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/v1/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/api/v1/auth/providers":
            return httpx.Response(200, json={"providers": []})
        return httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})

    results = await _run_self_checks(handler)
    assert {r.outcome for r in results.values()} == {"success"}
    # Internal component health is a verified result, and says what it is not.
    assert all(r.confidence is None for r in results.values())
    assert all("not that customers can reach it" in (r.detail or "") for r in results.values())
    # Only the Docker service addresses are contacted: never a public
    # hostname, Cloudflare, NetBird or TLS to MyKhaya's own domain.
    assert {(r.url.scheme, r.url.host, r.url.port) for r in seen} == {
        ("http", "web", 3000),
        ("http", "api", 8000),
    }
    web = next(r for r in seen if r.url.host == "web")
    # Exactly what Caddy forwards, so the web app routes it as a customer request.
    assert web.headers["host"] == "dev.mykhaya.app"
    assert web.headers["x-forwarded-proto"] == "https"


@pytest.mark.asyncio
async def test_internal_web_api_and_auth_failures_are_detected() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "web":
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path == "/api/v1/health/ready":
            return httpx.Response(503, json={"detail": "A required service is unavailable."})
        return httpx.Response(500)

    results = await _run_self_checks(handler)
    assert results["web"].outcome == "failure" and results["web"].category == "connectivity"
    assert results["ready"].outcome == "failure" and results["ready"].category == "provider_outage"
    assert results["auth"].outcome == "failure" and results["auth"].category == "provider_outage"
    assert {r.url.host for r in seen} <= {"web", "api"}


@pytest.mark.asyncio
async def test_internal_web_redirect_is_never_followed_out_of_the_network() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "web":
            return httpx.Response(307, headers={"location": "https://dev.mykhaya.app/login"})
        return httpx.Response(200, json={"status": "ready", "providers": []})

    results = await _run_self_checks(handler)
    assert results["web"].outcome == "success"
    assert not any("dev.mykhaya.app" in url for url in seen)


def test_blank_internal_targets_fall_back_to_the_docker_service_addresses() -> None:
    from mykhaya.config import Settings

    settings = Settings(monitoring_web_url="", monitoring_api_url="  ")  # type: ignore[call-arg]
    assert settings.monitoring_web_url == "http://web:3000"
    assert settings.monitoring_api_url == "http://api:8000"


@pytest.mark.asyncio
async def test_unvalidated_external_checks_start_pcc_only_and_cannot_open_incidents(
    monitoring_state: Any, redis: Redis
) -> None:
    async with SessionFactory() as db:
        rows = await engine.ensure_components(db)
        await db.commit()
    gated = {item.key for item in CATALOGUE if item.requires_live_validation}
    # Only checks that leave MyKhaya for a third party need live validation.
    assert gated == {
        "notifications.apns",
        "notifications.fcm",
        "billing.stripe_api",
        "provider.dvsa.connectivity",
        "provider.dvla.connectivity",
        "provider.apple.sign_in",
        "provider.google.sign_in",
    }
    assert all(rows[key].public_visible is False for key in gated)
    # MyKhaya's own components are internal and public from the start.
    for key in ("web.http", "api.ready", "auth.endpoint", "api.database"):
        assert rows[key].public_visible is True, key

    now = await fail_n(redis, "provider.apple.sign_in", T0, 5)
    assert (await component("provider.apple.sign_in")).state == "unavailable"
    assert await automated_incidents("apple_sign_in") == []
    # Recorded and visible in PCC for commissioning, but not emailed.
    gated_alerts = await alerts_for("provider.apple.sign_in")
    assert [a.kind for a in gated_alerts] == ["unavailable"]
    assert gated_alerts[0].suppressed_reason == "awaiting_validation"
    assert await deliveries_for(gated_alerts[0]) == []
    await write_runner_heartbeat(now)
    async with SessionFactory() as db:
        snapshot = await compute_status_snapshot(db, now - timedelta(seconds=30))
    assert not any(item.key == "apple_sign_in" for item in snapshot.external_services)


@pytest.mark.asyncio
async def test_internal_web_failure_updates_public_status_and_alerts(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
) -> None:
    await monitoring_state(PlatformRole.owner)
    now = await succeed_n(redis, "api.database", T0, 1)
    now = await fail_n(redis, "web.http", now, 3)
    assert (await component("web.http")).state == "unavailable"
    incidents = await automated_incidents("web_application")
    assert len(incidents) == 1
    alert = (await alerts_for("web.http"))[0]
    assert alert.suppressed_reason is None and await deliveries_for(alert) != []


def test_probe_reports_dns_failure_layer_by_layer(capsys: pytest.CaptureFixture[str]) -> None:
    from mykhaya.monitoring import probe

    assert probe.main(["https://monitor-probe-test.invalid/", "--timeout", "2"]) == 1
    output = capsys.readouterr().out
    assert "MyKhaya-Monitoring/1.0" in output
    assert "[FAIL] DNS" in output
    assert "Monitor verdict: FAILURE / DNS resolution failure" in output


def test_probe_reads_certificate_names() -> None:
    from mykhaya.monitoring import probe

    subject = ((("countryName", "GB"),), (("commonName", "dev.mykhaya.app"),))
    assert probe._name_field(subject, "commonName") == "dev.mykhaya.app"
    assert probe._name_field(None, "commonName") is None


# --- commissioning: email only once validated; recipient privacy ---------------------------


@pytest.mark.asyncio
async def test_validated_check_emails_while_monitoring_failures_always_email(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    redis: Redis,
) -> None:
    await monitoring_state(PlatformRole.owner)
    # Validated: an administrator enabled public reporting after live checks.
    async with SessionFactory() as db:
        await engine.ensure_components(db)
        await db.execute(
            update(MonitorComponent)
            .where(MonitorComponent.key == "billing.stripe_api")
            .values(public_visible=True)
        )
        await db.commit()
    now = await succeed_n(redis, "billing.stripe_api", T0, 1)
    await fail_n(redis, "billing.stripe_api", now, 3)
    alert = (await alerts_for("billing.stripe_api"))[0]
    assert alert.suppressed_reason is None
    assert await deliveries_for(alert) != []

    # Deterministic checks are never gated: a database failure emails even
    # during commissioning.
    now = await succeed_n(redis, "api.database", T0, 1)
    await fail_n(redis, "api.database", now, 3)
    database_alert = (await alerts_for("api.database"))[0]
    assert database_alert.suppressed_reason is None
    assert await deliveries_for(database_alert) != []
    # The monitoring runner itself is never gated either.
    runner = BY_KEY[RUNNER_COMPONENT_KEY]
    assert runner.requires_live_validation is False


@pytest.mark.asyncio
async def test_only_owners_and_administrators_see_additional_recipient_addresses(
    monitoring_state: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    admin_client: AsyncClient,  # noqa: F811
) -> None:
    owner = await monitoring_state(PlatformRole.owner)
    await login(admin_client, owner)
    saved = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/monitoring/alert-settings",
        json={
            "enabled": True,
            "roles": ["platform_owner", "platform_administrator"],
            "additional_recipients": ["oncall@example.com"],
            "cooldown_minutes": 30,
            "email_warning_severity": True,
            "reason": "Add the on-call mailbox",
            "confirmed": True,
        },
    )
    assert saved.status_code == 200, saved.text
    as_owner = (await admin_client.get("/api/v1/platform/monitoring/alert-settings")).json()
    assert as_owner["additional_recipients"] == ["oncall@example.com"]
    assert as_owner["can_manage"] is True

    for role in (PlatformRole.support, PlatformRole.security, PlatformRole.readonly):
        viewer = await monitoring_state(role)
        admin_client.cookies.clear()
        await login(admin_client, viewer)
        response = await admin_client.get("/api/v1/platform/monitoring/alert-settings")
        assert response.status_code == 200
        payload = response.json()
        assert "additional_recipients" not in payload
        assert "oncall@example.com" not in response.text
        assert payload["additional_recipient_count"] == 1
        assert payload["can_manage"] is False
        assert payload["enabled"] is True
        # Status visibility is unchanged for these roles.
        assert (await admin_client.get("/api/v1/platform/monitoring")).status_code == 200
        assert (await admin_client.get("/api/v1/platform/monitoring/alerts")).status_code == 200
        denied = await unsafe(
            admin_client,
            "PUT",
            "/api/v1/platform/monitoring/alert-settings",
            json={
                "enabled": True,
                "roles": ["platform_owner"],
                "additional_recipients": [],
                "cooldown_minutes": 30,
                "email_warning_severity": True,
                "reason": "Attempt by a non-operator",
                "confirmed": True,
            },
        )
        assert denied.status_code == 403
