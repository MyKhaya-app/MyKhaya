"""The four Platform Control Centre health cards that used to be hardcoded
placeholders ("No authoritative monitoring source is configured.") — Push
notifications, File storage, Backup service, External dependencies. See
mykhaya.routers.platform's /health endpoint.

Reuses the admin_client/admin_factory/login fixtures from
test_platform_control_centre.py.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from test_platform_control_centre import admin_client, admin_factory, login  # noqa: F401

from mykhaya.db import SessionFactory
from mykhaya.models import BackupRun, PlatformAdministrator, PlatformRole


@pytest.fixture(autouse=True)
async def _clean_backup_runs() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        await db.execute(delete(BackupRun))
        await db.commit()


async def _health_services(client: AsyncClient) -> dict[str, dict[str, object]]:
    response = await client.get("/api/v1/platform/health")
    assert response.status_code == 200
    return {item["service"]: item for item in response.json()["services"]}


@pytest.mark.asyncio
async def test_backup_service_reports_not_configured_with_no_recorded_runs(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    services = await _health_services(admin_client)
    assert services["Backup service"]["state"] == "Not configured"
    assert "No authoritative" not in services["Backup service"]["explanation"]


@pytest.mark.asyncio
async def test_backup_service_reports_healthy_for_a_recent_successful_run(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    started = datetime.now(UTC) - timedelta(hours=1)
    async with SessionFactory() as db:
        db.add(
            BackupRun(
                started_at=started,
                completed_at=started + timedelta(minutes=5),
                succeeded=True,
                size_bytes=1_048_576,
                detail="Backup completed and passed integrity verification.",
            )
        )
        await db.commit()
    services = await _health_services(admin_client)
    assert services["Backup service"]["state"] == "Healthy"
    assert services["Backup service"]["last_success"] is not None


@pytest.mark.asyncio
async def test_backup_service_reports_degraded_when_overdue(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    started = datetime.now(UTC) - timedelta(hours=48)
    async with SessionFactory() as db:
        db.add(
            BackupRun(
                started_at=started,
                completed_at=started + timedelta(minutes=5),
                succeeded=True,
                size_bytes=1_048_576,
            )
        )
        await db.commit()
    services = await _health_services(admin_client)
    assert services["Backup service"]["state"] == "Degraded"


@pytest.mark.asyncio
async def test_backup_service_reports_unavailable_for_the_most_recent_failed_run(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """A historic success must not mask a more recent failure — health reflects
    the *latest* run, not 'has it ever worked'."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    older_success = datetime.now(UTC) - timedelta(hours=30)
    newer_failure = datetime.now(UTC) - timedelta(hours=1)
    async with SessionFactory() as db:
        db.add(
            BackupRun(
                started_at=older_success,
                completed_at=older_success + timedelta(minutes=5),
                succeeded=True,
                size_bytes=1_048_576,
            )
        )
        db.add(
            BackupRun(
                started_at=newer_failure,
                completed_at=newer_failure + timedelta(minutes=1),
                succeeded=False,
                detail="pg_dump or compression failed.",
            )
        )
        await db.commit()
    services = await _health_services(admin_client)
    assert services["Backup service"]["state"] == "Unavailable"


@pytest.mark.asyncio
async def test_file_storage_card_runs_a_real_write_read_delete_probe(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    services = await _health_services(admin_client)
    card = services["File storage"]
    assert card["state"] in {"Healthy", "Degraded"}
    assert "probe succeeded" in card["explanation"]


@pytest.mark.asyncio
async def test_push_card_is_honestly_not_configured(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """This test environment has no VAPID keys — the card should say so
    honestly, never falling back to the old fixed 'No authoritative monitoring
    source is configured.' string, which claimed the same thing for every
    optional subsystem regardless of what it actually checked."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    services = await _health_services(admin_client)
    assert services["Push notifications"]["state"] == "Not configured"
    explanation = services["Push notifications"]["explanation"]
    assert "No authoritative monitoring source is configured." not in explanation


@pytest.mark.asyncio
async def test_external_dependencies_card_does_not_duplicate_email_health(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """External Dependencies must never re-derive its state from SMTP
    reachability — Email already owns SMTP health, and probing it twice could
    disagree with Email's own card (port reachable but deliveries failing, or
    vice versa). With no separate external integration today, this card is
    "Not applicable", not a second opinion on Email."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    services = await _health_services(admin_client)
    assert services["External dependencies"]["state"] == "Not applicable"
    explanation = services["External dependencies"]["explanation"]
    assert "smtp" not in explanation.casefold()
    assert "No authoritative monitoring source is configured." not in explanation
