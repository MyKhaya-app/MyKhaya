"""The four Platform Control Centre health cards that used to be hardcoded
placeholders ("No authoritative monitoring source is configured.") — Push
notifications, File storage, Backup service, External dependencies. See
mykhaya.routers.platform's /health endpoint.

Reuses the admin_client/admin_factory/login fixtures from
test_platform_control_centre.py, and the client/create_verified_user/
unique_email helpers from test_push_notifications.py.

The "Push notifications" component-health tests below (added for the PCC
Push Health Semantics Phase 2 correction) deliberately write
NotificationDelivery/NativePushDevice/PushSubscription rows directly via
SessionFactory rather than going through the worker or the registration
endpoint — this file audits the *read-time* Health calculation over
existing data, not delivery or registration behaviour, which already have
their own dedicated test files (test_native_push_worker.py,
test_native_push_registration.py).
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select
from test_platform_control_centre import admin_client, admin_factory, login  # noqa: F401
from test_push_notifications import client, create_verified_user, unique_email  # noqa: F401

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    BackupRun,
    NativePushDevice,
    NativePushDisabledSource,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    PlatformAdministrator,
    PlatformPushSettings,
    PlatformRole,
    PushSubscription,
)
from mykhaya.secrets_crypto import encrypt_secret


@pytest.fixture(autouse=True)
async def _clean_backup_runs() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        await db.execute(delete(BackupRun))
        await db.commit()


@pytest.fixture(autouse=True)
async def _clean_push_health_fixtures() -> AsyncIterator[None]:
    """The Push Health component tests below write NotificationDelivery/
    NativePushDevice/PushSubscription/PlatformPushSettings rows directly into
    the shared test database. Health's queries are global aggregates (not
    scoped to a single test's users), so without this cleanup, one test's
    rows remain inside the 24h window and inflate a later test's counts."""
    yield
    async with SessionFactory() as db:
        await db.execute(delete(NotificationDelivery))
        await db.execute(delete(NativePushDevice))
        await db.execute(delete(PushSubscription))
        await db.execute(delete(PlatformPushSettings))
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


def _push_components(services: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    push = services["Push notifications"]
    components = push["components"]
    assert isinstance(components, list)
    return {item["name"]: item for item in components}


async def _enable_web_push() -> None:
    """Direct DB row, mirroring push_payload()'s effect in
    test_push_notifications.py without needing an HTTP round-trip — this
    file is about the read-time Health calculation, not the settings-write
    endpoint."""
    async with SessionFactory() as db:
        settings = get_settings()
        db.add(
            PlatformPushSettings(
                enabled=True,
                vapid_public_key="test-public-key",
                encrypted_vapid_private_key=encrypt_secret(settings, "test-private-key"),
                subject="mailto:health-audit@example.com",
            )
        )
        await db.commit()


async def _native_delivery(
    user_id: uuid.UUID,
    *,
    platform: str,
    apns_environment: str | None,
    status: NotificationDeliveryStatus,
    attempted_at: datetime,
    device_disabled: bool = False,
) -> NativePushDevice:
    async with SessionFactory() as db:
        device = NativePushDevice(
            user_id=user_id,
            platform=platform,
            token=uuid.uuid4().hex + uuid.uuid4().hex,
            installation_id=f"installation-{uuid.uuid4()}",
            apns_environment=apns_environment,
            disabled_at=datetime.now(UTC) if device_disabled else None,
            disabled_source=NativePushDisabledSource.provider if device_disabled else None,
        )
        db.add(device)
        await db.flush()
        db.add(
            NotificationDelivery(
                channel=NotificationChannel.push,
                recipient_user_id=user_id,
                notification_type="event_reminder",
                idempotency_key=f"health-native:{uuid.uuid4()}",
                native_push_device_id=device.id,
                status=status,
                attempted_at=attempted_at,
            )
        )
        await db.commit()
        await db.refresh(device)
        return device


async def _web_delivery(
    user_id: uuid.UUID, *, status: NotificationDeliveryStatus, attempted_at: datetime
) -> PushSubscription:
    async with SessionFactory() as db:
        subscription = PushSubscription(
            user_id=user_id,
            endpoint=f"https://push.example/{uuid.uuid4()}",
            p256dh_key="abc",
            auth_key="def",
        )
        db.add(subscription)
        await db.flush()
        db.add(
            NotificationDelivery(
                channel=NotificationChannel.push,
                recipient_user_id=user_id,
                notification_type="event_reminder",
                idempotency_key=f"health-web:{uuid.uuid4()}",
                push_subscription_id=subscription.id,
                status=status,
                attempted_at=attempted_at,
            )
        )
        await db.commit()
        await db.refresh(subscription)
        return subscription


@pytest.mark.asyncio
async def test_push_health_24_hour_boundary(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(client, unique_email("boundary"), "Boundary User")
    now = datetime.now(UTC)

    # Just inside the window: must count.
    await _native_delivery(
        user_id,
        platform="ios",
        apns_environment="production",
        status=NotificationDeliveryStatus.failed,
        attempted_at=now - timedelta(hours=23, minutes=59),
    )
    services = await _health_services(admin_client)
    inside = _push_components(services)["Production APNs"]
    assert inside["failures_24h"] == 1

    # Just outside the window: must not count.
    await _native_delivery(
        user_id,
        platform="ios",
        apns_environment="production",
        status=NotificationDeliveryStatus.failed,
        attempted_at=now - timedelta(hours=24, minutes=1),
    )
    services = await _health_services(admin_client)
    still = _push_components(services)["Production APNs"]
    assert still["failures_24h"] == 1, "the older-than-24h failure must not be counted"


@pytest.mark.asyncio
async def test_push_health_classifies_web_push(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(client, unique_email("web-class"), "Web Class User")
    now = datetime.now(UTC)
    await _web_delivery(user_id, status=NotificationDeliveryStatus.failed, attempted_at=now)
    await _web_delivery(user_id, status=NotificationDeliveryStatus.sent, attempted_at=now)

    components = _push_components(await _health_services(admin_client))
    assert components["Web Push"]["failures_24h"] == 1
    assert components["Web Push"]["successes_24h"] == 1
    assert components["Web Push"]["failing_devices"] == 1
    for name in ("Production APNs", "Sandbox APNs", "Android FCM", "Legacy iOS"):
        assert components[name]["failures_24h"] == 0


@pytest.mark.asyncio
async def test_push_health_classifies_production_apns(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(client, unique_email("prod-class"), "Prod Class User")
    now = datetime.now(UTC)
    await _native_delivery(
        user_id, platform="ios", apns_environment="production",
        status=NotificationDeliveryStatus.failed, attempted_at=now,
    )

    components = _push_components(await _health_services(admin_client))
    assert components["Production APNs"]["failures_24h"] == 1
    for name in ("Sandbox APNs", "Android FCM", "Web Push", "Legacy iOS"):
        assert components[name]["failures_24h"] == 0


@pytest.mark.asyncio
async def test_push_health_classifies_sandbox_apns(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(
        client, unique_email("sandbox-class"), "Sandbox Class User"
    )
    now = datetime.now(UTC)
    await _native_delivery(
        user_id, platform="ios", apns_environment="sandbox",
        status=NotificationDeliveryStatus.failed, attempted_at=now,
    )

    components = _push_components(await _health_services(admin_client))
    assert components["Sandbox APNs"]["failures_24h"] == 1
    for name in ("Production APNs", "Android FCM", "Web Push", "Legacy iOS"):
        assert components[name]["failures_24h"] == 0


@pytest.mark.asyncio
async def test_push_health_classifies_android_fcm(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(client, unique_email("fcm-class"), "FCM Class User")
    now = datetime.now(UTC)
    await _native_delivery(
        user_id, platform="android", apns_environment=None,
        status=NotificationDeliveryStatus.failed, attempted_at=now,
    )

    components = _push_components(await _health_services(admin_client))
    assert components["Android FCM"]["failures_24h"] == 1
    for name in ("Production APNs", "Sandbox APNs", "Web Push", "Legacy iOS"):
        assert components[name]["failures_24h"] == 0


@pytest.mark.asyncio
async def test_push_health_classifies_legacy_ios(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(client, unique_email("legacy-class"), "Legacy Class User")
    now = datetime.now(UTC)
    await _native_delivery(
        user_id, platform="ios", apns_environment=None,
        status=NotificationDeliveryStatus.failed, attempted_at=now,
    )

    components = _push_components(await _health_services(admin_client))
    assert components["Legacy iOS"]["failures_24h"] == 1
    assert components["Legacy iOS"]["state"] == "Warning"
    for name in ("Production APNs", "Sandbox APNs", "Android FCM", "Web Push"):
        assert components[name]["failures_24h"] == 0


@pytest.mark.asyncio
async def test_push_health_sandbox_failure_alone_does_not_degrade_top_level(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    """The exact scenario the PCC Push Health audit was raised about: one
    notification, production succeeds, sandbox fails, the user still
    receives their real notification. The top-level card must not read the
    same as a genuine production outage, while the Sandbox component still
    honestly shows the failure."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(client, unique_email("mixed"), "Mixed User")
    now = datetime.now(UTC)
    await _native_delivery(
        user_id, platform="ios", apns_environment="production",
        status=NotificationDeliveryStatus.sent, attempted_at=now,
    )
    await _native_delivery(
        user_id, platform="ios", apns_environment="sandbox",
        status=NotificationDeliveryStatus.failed, attempted_at=now,
    )

    services = await _health_services(admin_client)
    push = services["Push notifications"]
    assert push["state"] == "Healthy"
    components = _push_components(services)
    assert components["Sandbox APNs"]["state"] == "Degraded"
    assert components["Sandbox APNs"]["failures_24h"] == 1
    assert components["Production APNs"]["state"] == "Healthy"


@pytest.mark.asyncio
async def test_push_health_production_apns_failure_degrades_top_level(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(client, unique_email("prod-fail"), "Prod Fail User")
    await _native_delivery(
        user_id, platform="ios", apns_environment="production",
        status=NotificationDeliveryStatus.failed, attempted_at=datetime.now(UTC),
    )

    services = await _health_services(admin_client)
    push = services["Push notifications"]
    assert push["state"] == "Degraded"
    assert "Production APNs" in push["explanation"]


@pytest.mark.asyncio
async def test_push_health_fcm_failure_degrades_top_level(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(client, unique_email("fcm-fail"), "FCM Fail User")
    await _native_delivery(
        user_id, platform="android", apns_environment=None,
        status=NotificationDeliveryStatus.failed, attempted_at=datetime.now(UTC),
    )

    services = await _health_services(admin_client)
    push = services["Push notifications"]
    assert push["state"] == "Degraded"
    assert "Android FCM" in push["explanation"]


@pytest.mark.asyncio
async def test_push_health_web_push_failure_degrades_top_level(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(client, unique_email("web-fail"), "Web Fail User")
    await _web_delivery(
        user_id, status=NotificationDeliveryStatus.failed, attempted_at=datetime.now(UTC)
    )

    services = await _health_services(admin_client)
    push = services["Push notifications"]
    assert push["state"] == "Degraded"
    assert "Web Push" in push["explanation"]


@pytest.mark.asyncio
async def test_push_health_excludes_failures_from_currently_disabled_native_devices(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    """A device disabled after logging some transient failures must not keep
    Health looking unhealthy for the rest of the 24h window — this is a
    read-time interpretation only; the historical NotificationDelivery rows
    themselves are untouched (still queryable/auditable elsewhere)."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(
        client, unique_email("disabled-hist"), "Disabled Hist User"
    )
    device = await _native_delivery(
        user_id, platform="ios", apns_environment="production",
        status=NotificationDeliveryStatus.failed, attempted_at=datetime.now(UTC),
    )
    services = await _health_services(admin_client)
    assert _push_components(services)["Production APNs"]["failures_24h"] == 1
    assert services["Push notifications"]["state"] == "Degraded"

    async with SessionFactory() as db:
        row = await db.get(NativePushDevice, device.id)
        assert row is not None
        row.disabled_at = datetime.now(UTC)
        row.disabled_source = NativePushDisabledSource.platform_admin
        row.disabled_reason = "Disabled by Platform Admin"
        await db.commit()

    services = await _health_services(admin_client)
    components = _push_components(services)
    assert components["Production APNs"]["failures_24h"] == 0
    assert components["Production APNs"]["failing_devices"] == 0
    assert services["Push notifications"]["state"] == "Healthy"

    # The historical delivery row itself was never touched — this is a
    # read-time Health interpretation only.
    async with SessionFactory() as db:
        remaining = (
            await db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.native_push_device_id == device.id
                )
            )
        ).all()
        assert len(remaining) == 1
        assert remaining[0].status == NotificationDeliveryStatus.failed


@pytest.mark.asyncio
async def test_push_health_excludes_cancelled_permanent_failures(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    client: AsyncClient,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _enable_web_push()
    user_id = await create_verified_user(client, unique_email("cancelled"), "Cancelled User")
    await _native_delivery(
        user_id, platform="ios", apns_environment="production",
        status=NotificationDeliveryStatus.cancelled, attempted_at=datetime.now(UTC),
    )

    services = await _health_services(admin_client)
    components = _push_components(services)
    assert components["Production APNs"]["failures_24h"] == 0
    assert services["Push notifications"]["state"] == "Healthy"


@pytest.mark.asyncio
async def test_push_health_native_only_apns_deployment_is_not_reported_not_configured(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """No VAPID/Web Push configured at all — a deployment that only ships
    native iOS push must not have its entire Push card say 'Not configured'
    (the exact blind spot the PCC Push Health audit found)."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    configured = get_settings().model_copy(
        update={
            "apns_delivery_configured": True,
            "apns_team_id": "TEAM123",
            "apns_key_id": "KEY123",
            "apns_private_key": SecretStr("fake-key-for-test-only"),
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        services = await _health_services(admin_client)
        assert services["Push notifications"]["state"] != "Not configured"
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_push_health_native_only_fcm_deployment_is_not_reported_not_configured(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    configured = get_settings().model_copy(
        update={
            "fcm_delivery_configured": True,
            "fcm_project_id": "proj",
            "fcm_client_email": "svc@proj.iam.gserviceaccount.com",
            "fcm_private_key": SecretStr("fake-key-for-test-only"),
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        services = await _health_services(admin_client)
        assert services["Push notifications"]["state"] != "Not configured"
    finally:
        app.dependency_overrides.pop(get_settings, None)


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
