import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update
from starlette.datastructures import Headers

from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    AdministrativeNote,
    FeatureFlag,
    FeatureKey,
    Group,
    OutboxEvent,
    PlatformAdministrator,
    PlatformRole,
    PlatformSession,
    PlatformSmtpSettings,
    SecurityEvent,
    User,
    WorkerJobRecord,
)
from mykhaya.platform_audit import safe_values
from mykhaya.platform_security import resolve_client_ip
from mykhaya.security import password_hash, resolve_forwarded_proto

ADMIN_ORIGIN = "http://admin.localhost:8080"
PASSWORD = "A separate operator password!"
TEST_PROXY_PEER = "172.16.0.2"
TEST_CLIENT_IP = "127.0.0.1"


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(TEST_PROXY_PEER, 44000)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN, "X-Forwarded-For": TEST_CLIENT_IP},
    ) as value:
        yield value


async def create_admin(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with SessionFactory() as db:
        row = PlatformAdministrator(
            email=f"operator-{suffix}@example.com",
            display_name="Test Operator",
            password_hash=password_hash.hash(PASSWORD),
            role=role,
            mfa_enrolled=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


@pytest.fixture
async def admin_factory() -> AsyncIterator[
    Callable[[PlatformRole], Awaitable[PlatformAdministrator]]
]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        row = await create_admin(role)
        identifiers.append(row.id)
        return row

    yield factory
    if identifiers:
        async with SessionFactory() as db:
            await db.execute(
                delete(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id.in_(identifiers)
                )
            )
            await db.execute(
                delete(AdministrativeNote).where(
                    AdministrativeNote.administrator_id.in_(identifiers)
                )
            )
            await db.execute(
                delete(SecurityEvent).where(SecurityEvent.administrator_id.in_(identifiers))
            )
            await db.execute(
                delete(PlatformAdministrator).where(PlatformAdministrator.id.in_(identifiers))
            )
            await db.commit()


async def login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login",
        json={"email": admin.email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert client.cookies.get("mk_admin_session")
    assert client.cookies.get("mk_admin_csrf")
    assert client.cookies.get("mk_session") is None


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_admin_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


@pytest.mark.asyncio
async def test_overview_uses_live_database_counts_and_omits_missing_metadata(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    before = (await admin_client.get("/api/v1/platform/overview")).json()
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with SessionFactory() as db:
        user = User(
            email=f"overview-{suffix}@example.com",
            display_name="Overview User",
            email_verified_at=datetime.now(UTC),
            is_active=False,
        )
        db.add(user)
        await db.flush()
        home = Group(name="Overview Home", created_by=user.id, is_active=False)
        db.add(home)
        await db.commit()
        user_id, home_id = user.id, home.id
    try:
        response = await admin_client.get("/api/v1/platform/overview")
        assert response.status_code == 200
        payload = response.json()
        assert payload["users"]["total"] == before["users"]["total"] + 1
        assert payload["users"]["suspended"] == before["users"]["suspended"] + 1
        assert payload["homes"]["total"] == before["homes"]["total"] + 1
        assert payload["homes"]["suspended"] == before["homes"]["suspended"] + 1
        assert "unknown" not in response.text.casefold()
        assert "commit" not in payload["deployment"]
        assert "build_time" not in payload["deployment"]
    finally:
        async with SessionFactory() as db:
            await db.execute(delete(Group).where(Group.id == home_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


@pytest.mark.asyncio
async def test_persisted_smtp_state_is_consistent_across_control_centre_health_pages(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    async with SessionFactory() as db:
        db.add(
            PlatformSmtpSettings(
                enabled=True,
                host="smtp.persisted.example",
                sender_email="noreply@persisted.example",
                sender_name="MyKhaya",
                auth_enabled=False,
            )
        )
        await db.commit()
    try:
        overview = (await admin_client.get("/api/v1/platform/overview")).json()
        mail = (await admin_client.get("/api/v1/platform/mail")).json()
        communications = (await admin_client.get("/api/v1/platform/communications/health")).json()
        email_health = next(item for item in overview["health"] if item["service"] == "Email")
        assert email_health["state"] == "Healthy"
        assert mail["configured"] is True
        assert communications["smtp"] == {"configured": True, "status": "connected"}
    finally:
        async with SessionFactory() as db:
            await db.execute(delete(PlatformSmtpSettings))
            await db.commit()


@pytest.mark.asyncio
async def test_historical_failed_job_does_not_degrade_current_overview(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    async with SessionFactory() as db:
        event = OutboxEvent(
            topic="notification.email",
            payload={},
            processed_at=datetime.now(UTC) - timedelta(days=2),
        )
        db.add(event)
        await db.flush()
        db.add(
            WorkerJobRecord(
                id=event.id,
                outbox_event_id=event.id,
                topic=event.topic,
                status="failed",
                finished_at=event.processed_at,
            )
        )
        await db.commit()
    try:
        payload = (await admin_client.get("/api/v1/platform/overview")).json()
        assert not any(
            action["title"] == "1 background job failed" for action in payload["actions"]
        )
    finally:
        async with SessionFactory() as db:
            await db.execute(delete(WorkerJobRecord).where(WorkerJobRecord.id == event.id))
            await db.execute(delete(OutboxEvent).where(OutboxEvent.id == event.id))
            await db.commit()


@pytest.mark.asyncio
async def test_overview_exposes_configured_build_metadata_but_production_hides_debug_fields(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    configured = get_settings().model_copy(
        update={
            "environment": "development",
            "version": "1.2.3",
            "commit_sha": "abc123def456",
            "build_time": "2026-08-01T12:00:00Z",
            "build_channel": "stable",
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        payload = (await admin_client.get("/api/v1/platform/overview")).json()
        assert payload["deployment"]["version"] == "1.2.3"
        assert payload["deployment"]["commit"] == "abc123def456"
        production = configured.model_copy(update={"environment": "production"})
        app.dependency_overrides[get_settings] = lambda: production
        production_payload = (await admin_client.get("/api/v1/platform/overview")).json()
        assert production_payload["deployment"] == {"version": "1.2.3", "channel": "stable"}
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_health_reports_live_states_without_unknown_placeholders(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    response = await admin_client.get("/api/v1/platform/health")
    assert response.status_code == 200
    services = {item["service"]: item for item in response.json()["services"]}
    assert services["Application process"]["state"] == "Healthy"
    assert services["Database"]["state"] == "Healthy"
    assert services["Backup service"]["state"] == "Not configured"
    assert "unknown" not in response.text.casefold()


@pytest.mark.asyncio
async def test_overview_failed_login_metric_uses_the_last_24_hours(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    recent_id = uuid.uuid4()
    old_id = uuid.uuid4()
    async with SessionFactory() as db:
        db.add_all(
            [
                SecurityEvent(
                    id=recent_id,
                    created_at=datetime.now(UTC) - timedelta(hours=2),
                    event_type="login_failed",
                    severity="medium",
                    outcome="denied",
                ),
                SecurityEvent(
                    id=old_id,
                    created_at=datetime.now(UTC) - timedelta(days=2),
                    event_type="login_failed",
                    severity="medium",
                    outcome="denied",
                ),
            ]
        )
        await db.commit()
        expected = await db.scalar(
            select(func.count(SecurityEvent.id)).where(
                SecurityEvent.event_type.in_(["login_failed", "administrator_login_failed"]),
                SecurityEvent.created_at >= datetime.now(UTC) - timedelta(hours=24),
            )
        )
    try:
        payload = (await admin_client.get("/api/v1/platform/overview")).json()
        assert payload["security"]["failed_logins_24h"] == expected
    finally:
        async with SessionFactory() as db:
            await db.execute(delete(SecurityEvent).where(SecurityEvent.id.in_([recent_id, old_id])))
            await db.commit()


@pytest.mark.asyncio
async def test_queue_metric_uses_database_outbox_as_source_of_truth(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    response = await admin_client.get("/api/v1/platform/overview")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["operations"]["queue_depth"], int)
    assert not any(item["title"] == "Queue state is unavailable" for item in payload["actions"])


@pytest.mark.asyncio
async def test_household_cookie_and_hostname_do_not_grant_platform_access() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44001)),
        base_url="http://localhost:8080",
        cookies={"mk_session": "household-session", "mk_admin_session": "invented"},
    ) as client:
        response = await client.get("/api/v1/platform/overview")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_readonly_role_cannot_suspend_user_and_admin_action_is_audited(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.readonly)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/users/00000000-0000-0000-0000-000000000001/suspend",
        json={"reason": "Required for a security investigation", "confirmed": True},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_module_lifecycle_requires_operator_confirmation_and_is_audited(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    # Capture Calendar's real FeatureFlag state before this test mutates it,
    # so it can be restored exactly afterwards — including the "no row
    # exists at all" case, not just hardcoding a guessed default. See
    # migration 0063_feature_flag_backfill for what the row's actual
    # steady-state should be; this test must never assume or leave a
    # different one, or it leaks state into whatever Calendar test runs
    # next in the same session (see mykhaya.features.platform_feature_
    # enabled/is_feature_enabled, which reads this row directly).
    async with SessionFactory() as db:
        original = await db.scalar(
            select(FeatureFlag).where(FeatureFlag.key == FeatureKey.calendar)
        )
        original_existed = original is not None
        original_enabled = original.enabled if original else None
        original_release_state = original.release_state if original else None

    try:
        await _run_calendar_module_lifecycle(admin_client, admin_factory)
    finally:
        async with SessionFactory() as db:
            row = await db.scalar(
                select(FeatureFlag).where(FeatureFlag.key == FeatureKey.calendar)
            )
            if original_existed:
                assert original_enabled is not None
                if row is None:
                    db.add(
                        FeatureFlag(
                            key=FeatureKey.calendar,
                            enabled=original_enabled,
                            release_state=original_release_state,
                        )
                    )
                else:
                    row.enabled = original_enabled
                    row.release_state = original_release_state
            elif row is not None:
                await db.delete(row)
            await db.commit()


async def _run_calendar_module_lifecycle(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    readonly = await admin_factory(PlatformRole.readonly)
    await login(admin_client, readonly)
    listed = await admin_client.get("/api/v1/platform/modules")
    assert listed.status_code == 200
    # Phase 3A: hidden modules (Tasks, Plans) are structurally excluded from
    # PCC's global live catalogue — see mykhaya.module_registry.
    # feature_modules(). Only operationally controllable modules/capability
    # flags appear here.
    keys = {item["key"] for item in listed.json()}
    assert "calendar" in keys
    assert "tasks" not in keys
    assert "plans" not in keys
    denied = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/modules/calendar",
        json={
            "enabled": True,
            "release_state": "beta",
            "reason": "Readonly operators cannot enable previews.",
            "confirmed": True,
        },
    )
    assert denied.status_code == 403

    admin_client.cookies.clear()
    owner = await admin_factory(PlatformRole.owner)
    await login(admin_client, owner)
    unconfirmed = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/modules/calendar",
        json={
            "enabled": True,
            "release_state": "beta",
            "reason": "Enable the Calendar pilot safely.",
        },
    )
    assert unconfirmed.status_code == 422
    enabled = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/modules/calendar",
        json={
            "enabled": True,
            "release_state": "beta",
            "reason": "Enable the Calendar pilot safely.",
            "confirmed": True,
        },
    )
    assert enabled.status_code == 200
    assert enabled.json() == {"key": "calendar", "enabled": True, "release_state": "beta"}
    async with SessionFactory() as db:
        event = await db.scalar(
            select(AdministrativeAuditEvent)
            .where(
                AdministrativeAuditEvent.administrator_id == owner.id,
                AdministrativeAuditEvent.action == "module.updated",
            )
            .order_by(AdministrativeAuditEvent.created_at.desc())
        )
        assert event is not None
        assert event.reason == "Enable the Calendar pilot safely."

    # Exercises the disable transition itself (coverage this test already
    # wanted) — this is no longer what restores Calendar's real global
    # state afterwards; the caller's try/finally does that from the
    # snapshot taken before this function ran, regardless of what state
    # this leaves things in or whether an assertion above already failed.
    disabled = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/modules/calendar",
        json={
            "enabled": False,
            "release_state": "released",
            "reason": "Exercise the disable transition.",
            "confirmed": True,
        },
    )
    assert disabled.status_code == 200


@pytest.mark.asyncio
async def test_global_module_catalogue_shows_real_operational_entries_only(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """Phase 3A. The current approved module/capability set: Calendar,
    Lists, Meal Plans, Wishlists and Nudges (Home-Admin-toggleable
    modules), plus Notifications and External sharing (infrastructure/Beta
    capability flags PCC still legitimately controls at the platform level,
    even though neither is a Home-Admin-toggleable module — see
    module_registry.ModuleDefinition.home_admin_manageable). Hidden modules
    (Tasks, Plans) must never appear as live editable entries."""
    admin = await admin_factory(PlatformRole.readonly)
    await login(admin_client, admin)
    listed = await admin_client.get("/api/v1/platform/modules")
    assert listed.status_code == 200
    keys = {item["key"] for item in listed.json()}
    expected_keys = (
        "nudges",
        "calendar",
        "shopping",
        "meals",
        "wish_lists",
        "notifications",
        "external_sharing",
    )
    for expected in expected_keys:
        assert expected in keys, f"{expected} should still be in PCC's global catalogue"
    for hidden in ("tasks", "plans"):
        assert hidden not in keys, f"{hidden} is hidden and must not be an editable catalogue entry"


@pytest.mark.asyncio
async def test_hidden_module_write_is_rejected_even_with_a_stale_feature_flag_row(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    """A hidden module must remain fail-closed and unavailable unless
    deliberately promoted through code/release governance — never through
    this lifecycle control, and never merely because a stale database row
    claims otherwise (see routers.platform.update_module's guard, checked
    against the static registry, never the FeatureFlag row's own value)."""
    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.tasks))
        if row is None:
            db.add(FeatureFlag(key=FeatureKey.tasks, enabled=True, release_state="released"))
        else:
            row.enabled = True
            row.release_state = "released"
        await db.commit()

    owner = await admin_factory(PlatformRole.owner)
    await login(admin_client, owner)
    rejected = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/modules/tasks",
        json={
            "enabled": True,
            "release_state": "released",
            "reason": "Attempting to promote a hidden module.",
            "confirmed": True,
        },
    )
    assert rejected.status_code == 409

    # Still absent from the global catalogue despite the stale row above.
    listed = await admin_client.get("/api/v1/platform/modules")
    assert "tasks" not in {item["key"] for item in listed.json()}


@pytest.mark.asyncio
async def test_separate_admin_session_revocation_and_audit(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    async with SessionFactory() as db:
        await db.execute(
            update(PlatformSession)
            .where(PlatformSession.administrator_id == admin.id)
            .values(authenticated_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await db.commit()
    stale = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/revoke-all",
        json={"reason": "Operator requested sign out from every device", "confirmed": True},
    )
    assert stale.status_code == 403
    reauthenticated = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/reauthenticate",
        json={"password": PASSWORD},
    )
    assert reauthenticated.status_code == 200
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/auth/revoke-all",
        json={"reason": "Operator requested sign out from every device", "confirmed": True},
    )
    assert response.status_code == 204
    assert (await admin_client.get("/api/v1/platform/auth/me")).status_code == 401
    async with SessionFactory() as db:
        event = await db.scalar(
            select(AdministrativeAuditEvent)
            .where(AdministrativeAuditEvent.administrator_id == admin.id)
            .order_by(AdministrativeAuditEvent.created_at.desc())
        )
        assert event is not None
        assert event.action == "administrator.sessions_revoked"
        assert event.reason == "Operator requested sign out from every device"


@pytest.mark.asyncio
async def test_public_status_contains_only_customer_facing_keys() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://status.localhost:8080"
    ) as client:
        response = await client.get("/api/v1/status")
    assert response.status_code == 200
    serialised = response.text.casefold()
    for forbidden in ("postgres", "redis", "queue_depth", "commit", "worker_name", "backup"):
        assert forbidden not in serialised


def make_request(
    peer: str,
    forwarded: str | None = None,
    forwarded_proto: str | None = None,
    scheme: str = "https",
) -> Request:
    raw_headers = {}
    if forwarded:
        raw_headers["x-forwarded-for"] = forwarded
    if forwarded_proto:
        raw_headers["x-forwarded-proto"] = forwarded_proto
    headers = Headers(raw_headers)
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers.raw,
            "client": (peer, 443),
            "scheme": scheme,
            "server": ("admin.mykhaya.app", 443),
            "query_string": b"",
        }
    )


def test_untrusted_proxy_header_cannot_change_client_address() -> None:
    settings = get_settings().model_copy(update={"trusted_proxy_cidrs": ["10.0.0.0/8"]})
    assert resolve_client_ip(make_request("203.0.113.9", "127.0.0.1"), settings) == "203.0.113.9"
    assert resolve_client_ip(make_request("10.0.0.2", "198.51.100.3"), settings) == "198.51.100.3"


def test_admin_client_ip_requires_trusted_proxy_and_valid_chain() -> None:
    from mykhaya.security import resolve_admin_client_ip

    settings = get_settings().model_copy(update={"trusted_proxy_cidrs": ["10.0.0.0/8"]})
    assert (
        resolve_admin_client_ip(make_request("10.0.0.2", "198.51.100.3"), settings)
        == "198.51.100.3"
    )
    assert resolve_admin_client_ip(make_request("203.0.113.2", "198.51.100.3"), settings) is None
    assert resolve_admin_client_ip(make_request("10.0.0.2", "not-an-ip"), settings) is None
    assert resolve_admin_client_ip(make_request("10.0.0.2"), settings) is None


def test_trusted_proxy_resolution_keeps_the_direct_peer_and_trusts_forwarded_proto() -> None:
    from mykhaya.security import resolve_admin_client_ip

    settings = get_settings().model_copy(update={"trusted_proxy_cidrs": ["172.16.0.0/12"]})
    request = make_request(
        "172.16.0.2",
        "185.241.225.58",
        forwarded_proto="https",
        scheme="http",
    )

    assert request.client is not None
    assert request.client.host == "172.16.0.2"
    assert resolve_admin_client_ip(request, settings) == "185.241.225.58"
    assert resolve_forwarded_proto(request, settings) == "https"

    untrusted = make_request(
        "203.0.113.9",
        "185.241.225.58",
        forwarded_proto="https",
        scheme="http",
    )
    assert resolve_admin_client_ip(untrusted, settings) is None
    assert resolve_forwarded_proto(untrusted, settings) == "http"


def test_admin_client_ip_rejects_an_untrusted_intermediate_hop() -> None:
    from mykhaya.security import resolve_admin_client_ip

    settings = get_settings().model_copy(update={"trusted_proxy_cidrs": ["10.0.0.0/8"]})
    assert (
        resolve_admin_client_ip(
            make_request("10.0.0.2", "198.51.100.3, 203.0.113.9, 10.0.0.3"), settings
        )
        is None
    )


def test_admin_client_ip_never_returns_proxy_address() -> None:
    from mykhaya.security import resolve_admin_client_ip

    settings = get_settings().model_copy(update={"trusted_proxy_cidrs": ["10.0.0.0/8"]})
    assert resolve_admin_client_ip(make_request("10.0.0.2", "10.0.0.3"), settings) is None


def test_admin_audit_redacts_secret_shaped_values() -> None:
    assert safe_values({"smtp_password": "secret", "api_key": "value", "enabled": True}) == {
        "smtp_password": "[REDACTED]",
        "api_key": "[REDACTED]",
        "enabled": True,
    }


def test_production_configuration_fails_closed_without_admin_networks() -> None:
    with pytest.raises(ValueError, match="ADMIN_ALLOWED_NETWORKS"):
        Settings(
            environment="production",
            secret_key="x" * 32,
            cookie_secure=True,
            admin_allowed_networks=[],
            admin_mfa_required=True,
        )
