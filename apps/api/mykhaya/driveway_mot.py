"""Driveway MOT service: eligibility, refresh orchestration, persistence,
status computation, reminder sync and the normalised API view.

Provider specifics live in mykhaya.driveway_mot_provider; this module only
sees provider-neutral records. The registration sent to a provider is ALWAYS
obtained through mykhaya.driveway_sensitive.registration_for_provider — never
from the vehicle row directly (the Driveway encryption boundary).

Refresh flow (routers.driveway calls ``refresh_vehicle_mot`` after Home
authorization):

1. eligibility — GB vehicle with a registration;
2. availability — MYKHAYA_DVSA_ENABLED, credentials configured, and the PCC
   ``driveway_dvsa_enabled`` platform setting on;
3. freshness — an ``if_stale`` refresh within MYKHAYA_DVSA_REFRESH_HOURS (or
   shortly after a failed attempt) returns persisted data without calling
   DVSA; a ``force`` refresh still respects a short cooldown;
4. a per-vehicle Redis lock, so concurrent viewers never trigger concurrent
   provider calls (the losers get the persisted data);
5. the provider call, with NO database transaction held open;
6. one transaction: re-load the vehicle, confirm its registration is still
   the one looked up, replace MOT history, update the summary, sync the
   managed MOT reminder, audit — all or nothing.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import structlog
from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mykhaya.audit import audit
from mykhaya.config import Settings
from mykhaya.driveway_mot_provider import (
    DvsaMotHistoryProvider,
    MotHistory,
    MotHistoryProvider,
    MotLookupError,
    MotNotConfigured,
    MotVehicleNotFound,
)
from mykhaya.driveway_reminders import DrivewayReminderEventType, upsert_driveway_reminder
from mykhaya.driveway_sensitive import registration_for_provider
from mykhaya.models import PlatformSetting, Vehicle, VehicleMotDefect, VehicleMotTest

log = structlog.get_logger("driveway_mot")

DVSA_SETTING_KEY = "driveway_dvsa_enabled"
MOT_ELIGIBLE_COUNTRIES = frozenset({"GB"})
FORCE_COOLDOWN = timedelta(seconds=60)
FAILURE_BACKOFF = timedelta(minutes=15)
LOCK_SECONDS = 45
HEALTH_SUCCESS_WRITE_INTERVAL = timedelta(minutes=10)

RefreshMode = Literal["if_stale", "force"]


class MotRefreshRefused(Exception):
    """A refresh that must not reach the provider. ``reason`` is a stable
    code the router maps to an HTTP status and family-friendly message."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- Eligibility / availability ---------------------------------------------------


def is_mot_eligible(vehicle: Vehicle) -> bool:
    return (vehicle.country_code or "").upper() in MOT_ELIGIBLE_COUNTRIES


async def dvsa_platform_enabled(db: AsyncSession) -> bool:
    value = await db.scalar(
        select(PlatformSetting.value).where(PlatformSetting.key == DVSA_SETTING_KEY)
    )
    return isinstance(value, dict) and value.get("value") is True


async def mot_provider_available(db: AsyncSession, settings: Settings) -> bool:
    return settings.dvsa_enabled and settings.dvsa_configured and await dvsa_platform_enabled(db)


def build_provider(settings: Settings) -> MotHistoryProvider:
    """Seam for tests (monkeypatched) and future providers."""
    return DvsaMotHistoryProvider(settings)


# --- Status computation ---------------------------------------------------------------


@dataclass(frozen=True)
class MotSummary:
    status: str | None
    due_date: date | None
    expiry_date: date | None
    first_mot_due_date: date | None
    last_test_date: date | None
    last_result: str | None


def compute_summary(history: MotHistory, *, today: date) -> MotSummary:
    """The current MOT position from normalised history.

    * valid       — some passed test's expiry is today or later;
    * expired     — passed tests exist but every expiry is in the past, or a
                    first MOT due date has already passed with no tests;
    * not_yet_due — no tests yet and the first MOT due date is in the future;
    * no_record   — the provider knows the vehicle but has nothing usable.
    A later failed test does not cancel an unexpired certificate's dates
    (the expiry shown is the latest passed expiry), matching how DVSA
    presents MOT validity.
    """
    tests = history.tests
    latest = tests[0] if tests else None
    expiries = [t.expiry_date for t in tests if t.result == "passed" and t.expiry_date]
    expiry = max(expiries) if expiries else None
    first_due = history.first_mot_due_date if not tests else None
    if expiry is not None:
        status = "valid" if expiry >= today else "expired"
        due = expiry
    elif first_due is not None:
        status = "not_yet_due" if first_due >= today else "expired"
        due = first_due
    elif tests:
        status, due = "expired", None
    else:
        status, due = "no_record", None
    return MotSummary(
        status=status,
        due_date=due,
        expiry_date=expiry,
        first_mot_due_date=history.first_mot_due_date if not tests else None,
        last_test_date=latest.test_date if latest else None,
        last_result=latest.result if latest else None,
    )


# --- Persistence -----------------------------------------------------------------------


async def _replace_history(db: AsyncSession, vehicle: Vehicle, history: MotHistory) -> None:
    await db.execute(delete(VehicleMotTest).where(VehicleMotTest.vehicle_id == vehicle.id))
    for record in history.tests:
        test = VehicleMotTest(
            group_id=vehicle.group_id,
            vehicle_id=vehicle.id,
            provider=history.provider,
            test_number=record.test_number,
            completed_at=record.completed_at,
            test_date=record.test_date,
            expiry_date=record.expiry_date,
            result=record.result,
            odometer_value=record.odometer_value,
            odometer_unit=record.odometer_unit,
            odometer_result=record.odometer_result,
        )
        test.defects = [
            VehicleMotDefect(
                position=index,
                category=defect.category,
                dangerous=defect.dangerous,
                text=defect.text,
            )
            for index, defect in enumerate(record.defects)
        ]
        db.add(test)
    await db.flush()


async def clear_mot_data(db: AsyncSession, vehicle: Vehicle) -> None:
    """The stored MOT data describes a specific registration. When that
    registration changes (or is removed) the old history no longer belongs
    to this vehicle and is removed; the managed reminder is left to the
    existing reminder conventions."""
    await db.execute(delete(VehicleMotTest).where(VehicleMotTest.vehicle_id == vehicle.id))
    vehicle.inspection_status = None
    vehicle.inspection_due_date = None
    vehicle.mot_first_due_date = None
    vehicle.mot_refreshed_at = None
    vehicle.mot_refresh_attempted_at = None
    vehicle.mot_refresh_outcome = None


def _reminder_title(summary: MotSummary) -> str:
    return "First MOT due" if summary.status == "not_yet_due" else "MOT due"


async def _sync_reminder(
    db: AsyncSession, vehicle: Vehicle, summary: MotSummary, actor_id: uuid.UUID
) -> None:
    """Keep the single managed MOT reminder (event_type=inspection) on the
    current due date. upsert_driveway_reminder is idempotent per (vehicle,
    event): repeated refreshes update the same row, never duplicate it."""
    if summary.due_date is None:
        return
    await upsert_driveway_reminder(
        db,
        group_id=vehicle.group_id,
        vehicle=vehicle,
        event_type=DrivewayReminderEventType.inspection,
        due_date=summary.due_date,
        title=_reminder_title(summary),
        created_by=actor_id,
    )


# --- PCC health (best effort, throttled) -------------------------------------------------


async def record_provider_health(db: AsyncSession, *, success: bool, category: str | None) -> None:
    """Records state for the PCC Driveway integrations card. Never raises,
    never stores anything but timestamps and a failure category."""
    try:
        row = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == DVSA_SETTING_KEY).with_for_update()
        )
        if row is None:
            await db.rollback()
            return
        health = dict(row.value.get("health") or {})
        now = datetime.now(UTC)
        if success:
            last = health.get("last_success_at")
            fresh_enough = False
            if isinstance(last, str):
                try:
                    fresh_enough = (
                        now - datetime.fromisoformat(last) < HEALTH_SUCCESS_WRITE_INTERVAL
                    )
                except ValueError:
                    fresh_enough = False
            if fresh_enough and health.get("state") == "Healthy":
                await db.rollback()
                return
            health["state"] = "Healthy"
            health["last_success_at"] = now.isoformat()
        else:
            health["state"] = "Degraded"
            health["last_failure_at"] = now.isoformat()
            health["last_failure_category"] = category or "unavailable"
        row.value = {**row.value, "health": health}
        await db.commit()
    except Exception:
        await db.rollback()
        log.warning("driveway.dvsa.health_record_failed")


# --- Redis lock --------------------------------------------------------------------------


async def _acquire_lock(settings: Settings, vehicle_id: uuid.UUID) -> tuple[Redis, str] | None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    key = f"mykhaya:driveway:mot-refresh:{vehicle_id}"
    try:
        acquired = await redis.set(key, "1", nx=True, ex=LOCK_SECONDS)
    except Exception:
        await redis.aclose()
        raise
    if not acquired:
        await redis.aclose()
        return None
    return redis, key


async def _release_lock(lock: tuple[Redis, str]) -> None:
    redis, key = lock
    try:
        await redis.delete(key)
    finally:
        await redis.aclose()


# --- Refresh -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RefreshOutcome:
    # refreshed | not_found | cached | busy
    kind: str
    error: MotLookupError | None = None


def _should_skip(vehicle: Vehicle, mode: RefreshMode, settings: Settings, now: datetime) -> bool:
    attempted = vehicle.mot_refresh_attempted_at
    if mode == "force":
        return attempted is not None and now - attempted < FORCE_COOLDOWN
    refreshed = vehicle.mot_refreshed_at
    if refreshed is not None and now - refreshed < timedelta(hours=settings.dvsa_refresh_hours):
        return True
    failed_recently = (
        attempted is not None
        and vehicle.mot_refresh_outcome not in (None, "success", "not_found")
        and now - attempted < FAILURE_BACKOFF
    )
    return failed_recently


async def refresh_vehicle_mot(
    db: AsyncSession,
    request: Request,
    settings: Settings,
    *,
    home_id: uuid.UUID,
    vehicle: Vehicle,
    actor_id: uuid.UUID,
    mode: RefreshMode,
) -> RefreshOutcome:
    """Authorization has already happened in the router. Raises
    MotRefreshRefused for ineligible/unavailable cases and returns the
    provider error (persisted as the attempt outcome) rather than raising it,
    so the caller can respond with the cached view plus a safe message."""
    if not is_mot_eligible(vehicle):
        raise MotRefreshRefused("unsupported_country")
    registration = registration_for_provider(vehicle, settings)
    if not registration:
        raise MotRefreshRefused("no_registration")
    if not await mot_provider_available(db, settings):
        raise MotRefreshRefused("provider_unavailable")
    now = datetime.now(UTC)
    if _should_skip(vehicle, mode, settings, now):
        return RefreshOutcome("cached")

    vehicle_id = vehicle.id
    lock = await _acquire_lock(settings, vehicle_id)
    if lock is None:
        return RefreshOutcome("busy")
    try:
        # Release the request's transaction/connection before the external
        # call: nothing is held open while DVSA responds.
        await db.rollback()
        started = time.monotonic()
        error: MotLookupError | None = None
        history: MotHistory | None = None
        try:
            history = await build_provider(settings).fetch(registration)
        except MotNotConfigured as exc:
            error = exc
        except MotLookupError as exc:
            error = exc
        duration_ms = round((time.monotonic() - started) * 1000, 1)

        # One transaction for everything persisted below.
        row = await db.scalar(
            select(Vehicle)
            .where(
                Vehicle.id == vehicle_id,
                Vehicle.group_id == home_id,
                Vehicle.archived_at.is_(None),
            )
            .with_for_update()
        )
        if row is None or registration_for_provider(row, settings) != registration:
            # Deleted, or its registration changed mid-flight: discard.
            await db.rollback()
            log.info(
                "driveway.dvsa.mot_refresh",
                provider="dvsa",
                operation="mot_refresh",
                outcome="discarded",
                duration_ms=duration_ms,
            )
            return RefreshOutcome("cached")
        attempted_at = datetime.now(UTC)
        row.mot_refresh_attempted_at = attempted_at
        if history is not None:
            summary = compute_summary(history, today=attempted_at.date())
            await _replace_history(db, row, history)
            row.inspection_status = summary.status
            row.inspection_due_date = summary.due_date
            row.mot_first_due_date = summary.first_mot_due_date
            row.mot_refreshed_at = attempted_at
            row.mot_refresh_outcome = "success"
            await _sync_reminder(db, row, summary, actor_id)
            outcome = "success"
            test_count = len(history.tests)
        elif isinstance(error, MotVehicleNotFound):
            # A definitive answer: the provider has no MOT record for this
            # registration, so any previous history no longer applies.
            await db.execute(delete(VehicleMotTest).where(VehicleMotTest.vehicle_id == row.id))
            row.inspection_status = "no_record"
            row.inspection_due_date = None
            row.mot_first_due_date = None
            row.mot_refreshed_at = attempted_at
            row.mot_refresh_outcome = "not_found"
            outcome = "not_found"
            test_count = 0
        else:
            assert error is not None
            row.mot_refresh_outcome = error.category
            outcome = error.category
            test_count = 0
        audit(
            db,
            request,
            "driveway.vehicle.mot_refreshed",
            actor_id,
            home_id,
            "vehicle",
            row.id,
            {"outcome": outcome, "test_count": test_count, "mode": mode},
        )
        await db.commit()
        log.info(
            "driveway.dvsa.mot_refresh",
            provider="dvsa",
            operation="mot_refresh",
            outcome=outcome,
            duration_ms=duration_ms,
            test_count=test_count,
        )
    finally:
        await _release_lock(lock)
    await record_provider_health(
        db,
        success=error is None or isinstance(error, MotVehicleNotFound),
        category=None if error is None else error.category,
    )
    if history is not None:
        return RefreshOutcome("refreshed")
    if isinstance(error, MotVehicleNotFound):
        return RefreshOutcome("not_found")
    return RefreshOutcome("cached", error=error)


# --- Normalised API view -------------------------------------------------------------------


async def mot_view(
    db: AsyncSession, settings: Settings, *, home_id: uuid.UUID, vehicle: Vehicle
) -> dict[str, Any]:
    """Everything the MOT UI needs, provider-neutral. Reads only persisted
    data — never calls the provider."""
    tests = (
        await db.scalars(
            select(VehicleMotTest)
            .where(VehicleMotTest.group_id == home_id, VehicleMotTest.vehicle_id == vehicle.id)
            .options(selectinload(VehicleMotTest.defects))
            .order_by(VehicleMotTest.test_date.desc(), VehicleMotTest.completed_at.desc())
        )
    ).all()
    eligible = is_mot_eligible(vehicle)
    available = eligible and await mot_provider_available(db, settings)
    has_registration = bool(registration_for_provider(vehicle, settings)) if eligible else False
    refreshed_at = vehicle.mot_refreshed_at
    stale = refreshed_at is None or datetime.now(UTC) - refreshed_at >= timedelta(
        hours=settings.dvsa_refresh_hours
    )
    passed_expiries = [t.expiry_date for t in tests if t.result == "passed" and t.expiry_date]
    latest = tests[0] if tests else None
    return {
        "eligible": eligible,
        "provider_available": available,
        "has_registration": has_registration,
        "summary": {
            "status": vehicle.inspection_status,
            "due_date": vehicle.inspection_due_date,
            "expiry_date": max(passed_expiries) if passed_expiries else None,
            "first_mot_due_date": vehicle.mot_first_due_date,
            "last_test_date": latest.test_date if latest else None,
            "last_result": latest.result if latest else None,
            "source": "dvsa" if refreshed_at else None,
            "refreshed_at": refreshed_at,
            "stale": stale,
            "last_attempt_at": vehicle.mot_refresh_attempted_at,
            "last_attempt_outcome": vehicle.mot_refresh_outcome,
        },
        "tests": [
            {
                "id": test.id,
                "test_number": test.test_number,
                "test_date": test.test_date,
                "completed_at": test.completed_at,
                "expiry_date": test.expiry_date,
                "result": test.result,
                "odometer_value": test.odometer_value,
                "odometer_unit": test.odometer_unit,
                "odometer_result": test.odometer_result,
                "defects": [
                    {"text": d.text, "category": d.category, "dangerous": d.dangerous}
                    for d in test.defects
                ],
            }
            for test in tests
        ],
    }
