"""The monitoring runner: executes due checks, persists observations, applies
the state machine, opens/updates automatic incidents and raises alerts.

Runs as a background task inside the scheduler process (``run_forever``), so
it never blocks API requests or the scheduler's own notification scans.
Exactly one runner executes at a time across every scheduler instance: each
cycle holds a PostgreSQL session advisory lock, and component rows are
updated under ``SELECT ... FOR UPDATE``. All state is read from and written
to the database, so a restart resumes exactly where it stopped (failure
counters, open incidents and alert history included).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from redis.asyncio import Redis
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mykhaya.config import Settings
from mykhaya.db import SessionFactory
from mykhaya.models import (
    MonitorComponent,
    MonitorObservation,
    MonitorTransition,
    OperationalHeartbeat,
)
from mykhaya.monitoring import alerts, incidents
from mykhaya.monitoring.catalogue import BY_KEY, CATALOGUE, ComponentDefinition
from mykhaya.monitoring.checks import CheckContext
from mykhaya.monitoring.incidents import TransitionEvent
from mykhaya.monitoring.results import (
    NETWORK_CATEGORIES,
    UNAVAILABLE,
    UNKNOWN,
    CheckResult,
)
from mykhaya.monitoring.state import (
    RUNNER_HEARTBEAT_SERVICE,
    effective_state,
    is_stale,
    next_state,
)
from mykhaya.platform_runtime import maintenance_active

log = structlog.get_logger()

# Arbitrary, fixed advisory-lock identifiers ("MKMON" / "MKWDG").
RUNNER_LOCK_KEY = 0x4D4B4D4F4E
WATCHDOG_LOCK_KEY = 0x4D4B574447
CYCLE_SECONDS = 15
MAX_CONCURRENT_CHECKS = 8
OBSERVATION_RETENTION = timedelta(days=90)
PURGE_INTERVAL = timedelta(hours=1)
WATCHDOG_PING_INTERVAL = timedelta(seconds=60)
USER_AGENT = "MyKhaya-Monitoring/1.0"

_last_purge_at: datetime | None = None
_last_watchdog_ping_at: datetime | None = None


@dataclass
class CycleReport:
    ran: bool
    executed: list[str] = field(default_factory=list)
    transitions: list[str] = field(default_factory=list)
    alerts: int = 0
    errors: int = 0


def component_defaults(definition: ComponentDefinition) -> dict[str, object]:
    return {
        "key": definition.key,
        "enabled": True,
        "interval_seconds": definition.interval_seconds,
        "timeout_seconds": definition.timeout_seconds,
        "failure_threshold": definition.failure_threshold,
        "recovery_threshold": definition.recovery_threshold,
        # Unvalidated vantage-dependent checks can never cause a false public
        # incident: they start PCC-only (see ComponentDefinition).
        "public_visible": definition.public_visible and not definition.requires_live_validation,
        "severity": definition.severity,
        "state": UNKNOWN,
    }


async def ensure_components(db: AsyncSession) -> dict[str, MonitorComponent]:
    """Insert a row for every catalogued component that does not have one
    yet (concurrency-safe), and return every row keyed by component key."""
    await db.execute(
        pg_insert(MonitorComponent)
        .values([component_defaults(definition) for definition in CATALOGUE])
        .on_conflict_do_nothing(index_elements=["key"])
    )
    rows = (await db.scalars(select(MonitorComponent))).all()
    return {row.key: row for row in rows}


async def apply_result(
    db: AsyncSession,
    component: MonitorComponent,
    result: CheckResult,
    now: datetime,
    *,
    trigger: str = "scheduled",
) -> TransitionEvent | None:
    """Persist one observation and advance the component's state machine.
    The caller must hold the component row lock (SELECT ... FOR UPDATE)."""
    definition = BY_KEY.get(component.key)
    db.add(
        MonitorObservation(
            component_key=component.key,
            observed_at=now,
            outcome=result.outcome,
            failure_severity=result.failure_severity if result.outcome == "failure" else None,
            latency_ms=result.latency_ms,
            failure_category=result.category if result.outcome != "success" else None,
            detail=result.detail,
            trigger=trigger,
        )
    )
    component.last_attempted_at = now
    if result.outcome == "monitor_error":
        # Recorded for PCC (e.g. "blocked by a WAF challenge") but never counted
        # against the service: the component simply goes stale -> Unknown.
        component.last_failure_category = result.category
        component.last_failure_detail = result.detail
        return None
    component.last_checked_at = now
    if result.latency_ms is not None:
        component.last_latency_ms = result.latency_ms
    if result.outcome == "inconclusive":
        return None
    previous_success_at = component.last_success_at
    if result.outcome == "success":
        component.last_success_at = now
        component.confidence = result.confidence or "verified"
    elif result.outcome == "failure":
        component.last_failure_at = now
        component.last_failure_category = result.category
        component.last_failure_detail = result.detail
    target = next_state(component, result)
    if target == component.state:
        return None
    from_state = component.state
    component.state = target
    component.state_changed_at = now
    count = (
        component.consecutive_failures
        if result.outcome == "failure"
        else component.consecutive_successes
    )
    transition = MonitorTransition(
        component_key=component.key,
        occurred_at=now,
        from_state=from_state,
        to_state=target,
        consecutive_count=count,
        failure_category=result.category if result.outcome == "failure" else None,
        detail=result.detail if result.outcome == "failure" else None,
    )
    db.add(transition)
    await db.flush()
    log.info(
        "monitoring.transition",
        component=component.key,
        from_state=from_state,
        to_state=target,
        category=transition.failure_category,
        public=bool(definition and component.public_visible),
    )
    return TransitionEvent(transition, component, previous_success_at)


async def sweep_stale(db: AsyncSession, now: datetime) -> list[TransitionEvent]:
    """Components whose checks have stopped producing conclusive results
    are moved to Unknown with a "stale" transition, so the gap is recorded
    and alerted on rather than silently left green."""
    events: list[TransitionEvent] = []
    rows = (
        await db.scalars(
            select(MonitorComponent)
            .where(
                MonitorComponent.enabled.is_(True),
                MonitorComponent.state.in_(["healthy", "degraded", "unavailable"]),
            )
            .with_for_update()
        )
    ).all()
    for component in rows:
        definition = BY_KEY.get(component.key)
        if definition is None or definition.watchdog_managed or not is_stale(component, now):
            continue
        transition = MonitorTransition(
            component_key=component.key,
            occurred_at=now,
            from_state=component.state,
            to_state=UNKNOWN,
            consecutive_count=0,
            failure_category="stale",
            detail="No conclusive check result within the freshness window.",
        )
        previous_success_at = component.last_success_at
        component.state = UNKNOWN
        component.state_changed_at = now
        db.add(transition)
        await db.flush()
        events.append(TransitionEvent(transition, component, previous_success_at))
    return events


def _due(component: MonitorComponent, now: datetime) -> bool:
    last = component.last_attempted_at or component.last_checked_at
    return last is None or (now - last).total_seconds() >= component.interval_seconds


def _reclassify_egress(results: dict[str, CheckResult]) -> dict[str, CheckResult]:
    """Several unrelated external providers failing at the network level at
    the same moment points at MyKhaya's own outbound network or DNS, not at
    each provider. Re-label those failures so alerts say so."""
    network_failures = {
        key: result
        for key, result in results.items()
        if result.outcome == "failure"
        and result.category in NETWORK_CATEGORIES
        and (definition := BY_KEY.get(key)) is not None
        and definition.category == "external"
    }
    providers = {BY_KEY[key].provider for key in network_failures}
    if len(providers) < 3:
        return results
    updated = dict(results)
    for key, result in network_failures.items():
        updated[key] = replace(
            result,
            category="egress",
            detail="Several unrelated providers are unreachable at once; this is most likely "
            "a MyKhaya network or DNS problem rather than a provider outage.",
        )
    return updated


async def _execute(
    definition: ComponentDefinition,
    component: MonitorComponent,
    base: CheckContext,
    settings: Settings,
    now: datetime,
) -> tuple[CheckResult, str]:
    if (
        component.simulate_failure_until is not None
        and component.simulate_failure_until > now
        and settings.environment != "production"
    ):
        return (
            CheckResult.failure(
                "simulated",
                "Simulated failure (DEV fault injection).",
                severity="degraded"
                if component.simulate_failure_severity == "degraded"
                else "unavailable",
            ),
            "simulated",
        )
    context = replace(
        base,
        timeout=float(component.timeout_seconds),
        previous_checked_at=component.last_checked_at,
    )
    try:
        result = await asyncio.wait_for(definition.run(context), component.timeout_seconds + 5)
    except TimeoutError:
        result = CheckResult.failure(
            "timeout", f"The check did not complete within {component.timeout_seconds}s."
        )
    except Exception as exc:  # noqa: BLE001 - a broken check must never stop the cycle
        log.warning("monitoring.check_error", component=definition.key, error=type(exc).__name__)
        result = CheckResult.monitor_error(f"The check raised {type(exc).__name__}.")
    return result, "scheduled"


async def _try_lock(db: AsyncSession, key: int, wait_seconds: float) -> bool:
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        if await db.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.5)


async def run_cycle(
    settings: Settings,
    *,
    http: httpx.AsyncClient,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
    now: datetime | None = None,
    only_keys: set[str] | None = None,
    force: bool = False,
    trigger: str = "scheduled",
    wait_for_lock: float = 0.0,
) -> CycleReport:
    """One monitoring pass. Returns ran=False without doing anything when
    another runner holds the lock (or, with ``wait_for_lock``, still holds it
    after that many seconds)."""
    async with session_factory() as lock_db:
        if not await _try_lock(lock_db, RUNNER_LOCK_KEY, wait_for_lock):
            return CycleReport(ran=False)
        try:
            return await _locked_cycle(
                settings,
                http=http,
                redis=redis,
                session_factory=session_factory,
                now=now or datetime.now(UTC),
                only_keys=only_keys,
                force=force,
                trigger=trigger,
            )
        finally:
            await lock_db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": RUNNER_LOCK_KEY})
            await lock_db.commit()


async def _locked_cycle(
    settings: Settings,
    *,
    http: httpx.AsyncClient,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime,
    only_keys: set[str] | None,
    force: bool,
    trigger: str,
) -> CycleReport:
    report = CycleReport(ran=True)
    async with session_factory() as db:
        components = await ensure_components(db)
        in_maintenance = await maintenance_active(db)
        await db.commit()

    due: list[tuple[ComponentDefinition, MonitorComponent]] = []
    for definition in CATALOGUE:
        component = components.get(definition.key)
        if component is None or definition.watchdog_managed:
            continue
        if only_keys is not None and definition.key not in only_keys:
            continue
        if not component.enabled and not force:
            continue
        if force or _due(component, now):
            due.append((definition, component))

    base = CheckContext(
        settings=settings,
        session_factory=session_factory,
        http=http,
        redis=redis,
        timeout=10.0,
        now=now,
    )
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

    async def guarded(
        definition: ComponentDefinition, component: MonitorComponent
    ) -> tuple[str, CheckResult, str]:
        async with semaphore:
            result, how = await _execute(definition, component, base, settings, now)
            return definition.key, result, how

    executed = await asyncio.gather(*(guarded(d, c) for d, c in due))
    results = _reclassify_egress({key: result for key, result, _ in executed})
    triggers = {key: how for key, _, how in executed}
    if in_maintenance:
        # Planned maintenance makes the public routes answer 503 on purpose.
        # Those failures say nothing new; the maintenance incident does.
        results = {
            key: (
                CheckResult.inconclusive("Platform maintenance mode is active.")
                if result.outcome == "failure" and BY_KEY[key].check_type == "http"
                else result
            )
            for key, result in results.items()
        }

    events: list[TransitionEvent] = []
    async with session_factory() as db:
        for key, result in results.items():
            component = await db.scalar(
                select(MonitorComponent).where(MonitorComponent.key == key).with_for_update()
            )
            if component is None:
                continue
            how = triggers[key] if triggers[key] == "simulated" else trigger
            event = await apply_result(db, component, result, now, trigger=how)
            report.executed.append(key)
            if result.outcome == "monitor_error":
                report.errors += 1
            if event is not None:
                events.append(event)
        if only_keys is None:
            events.extend(await sweep_stale(db, now))
        await incidents.reconcile_incidents(db, events, now)
        raised = await alerts.raise_for_transitions(db, settings, events, now)
        report.alerts = len(raised)
        report.transitions = [f"{e.component.key}:{e.transition.to_state}" for e in events]
        if only_keys is None:
            await db.merge(
                OperationalHeartbeat(
                    service=RUNNER_HEARTBEAT_SERVICE,
                    observed_at=now,
                    last_success_at=now,
                    safe_detail=(
                        f"Monitoring cycle completed: {len(report.executed)} checks, "
                        f"{report.errors} check errors."
                    )[:300],
                )
            )
        await db.commit()

    if only_keys is None:
        await _maybe_purge(session_factory, now)
        await _maybe_ping_watchdog(settings, http, session_factory, now)
    return report


async def _maybe_purge(session_factory: async_sessionmaker[AsyncSession], now: datetime) -> None:
    global _last_purge_at
    if _last_purge_at is not None and now - _last_purge_at < PURGE_INTERVAL:
        return
    _last_purge_at = now
    try:
        async with session_factory() as db:
            await db.execute(
                delete(MonitorObservation).where(
                    MonitorObservation.observed_at < now - OBSERVATION_RETENTION
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - retention must never stop monitoring
        log.warning("monitoring.purge_failed", error=type(exc).__name__)


async def critical_unavailable(db: AsyncSession, now: datetime) -> list[str]:
    rows = (await db.scalars(select(MonitorComponent))).all()
    return [
        row.key
        for row in rows
        if row.severity == "critical"
        and effective_state(row, now, runner_fresh=True) == UNAVAILABLE
    ]


async def _maybe_ping_watchdog(
    settings: Settings,
    http: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime,
) -> None:
    """Independent dead-man's switch. A missed ping (MyKhaya or its host is
    down) or a fail ping (a critical component is unavailable, which may
    include email itself) makes the external service alert on its own."""
    global _last_watchdog_ping_at
    if settings.monitoring_watchdog_url is None:
        return
    if _last_watchdog_ping_at is not None and now - _last_watchdog_ping_at < WATCHDOG_PING_INTERVAL:
        return
    _last_watchdog_ping_at = now
    url = settings.monitoring_watchdog_url.get_secret_value().rstrip("/")
    try:
        async with session_factory() as db:
            failing = await critical_unavailable(db, now)
        target = f"{url}{settings.monitoring_watchdog_fail_suffix}" if failing else url
        await http.get(target, timeout=5)
    except Exception as exc:  # noqa: BLE001 - never log the URL: it contains a token
        log.warning("monitoring.watchdog_ping_failed", error=type(exc).__name__)


def build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        timeout=10,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
    )


async def run_forever(settings: Settings) -> None:
    """The scheduler's background monitoring loop."""
    if not settings.monitoring_enabled:
        log.info("monitoring.disabled")
        return
    redis = Redis.from_url(settings.redis_url, socket_timeout=5, decode_responses=True)
    async with build_http_client() as http:
        try:
            while True:
                try:
                    await run_cycle(settings, http=http, redis=redis)
                except Exception as exc:  # noqa: BLE001 - the loop must survive any cycle failure
                    # A failed cycle writes no heartbeat; the worker watchdog
                    # notices the gap and alerts.
                    log.error("monitoring.cycle_failed", error=type(exc).__name__)
                await asyncio.sleep(CYCLE_SECONDS)
        finally:
            await redis.aclose()
