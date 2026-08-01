import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update
from starlette.datastructures import Headers

from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    AdministrativeNote,
    PlatformAdministrator,
    PlatformRole,
    PlatformSession,
    SecurityEvent,
)
from mykhaya.platform_audit import safe_values
from mykhaya.platform_security import resolve_client_ip
from mykhaya.security import password_hash

ADMIN_ORIGIN = "http://admin.localhost:8080"
PASSWORD = "A separate operator password!"


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44000)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
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
async def test_feature_flags_default_off_require_operator_confirmation_and_are_audited(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    readonly = await admin_factory(PlatformRole.readonly)
    await login(admin_client, readonly)
    listed = await admin_client.get("/api/v1/platform/feature-flags")
    assert listed.status_code == 200
    # Hidden modules are absent even from the operator catalogue.
    assert {item["key"] for item in listed.json()} == {"calendar"}
    assert all(item["enabled"] is False for item in listed.json())
    denied = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/feature-flags/calendar",
        json={
            "enabled": True,
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
        "/api/v1/platform/feature-flags/calendar",
        json={"enabled": True, "reason": "Enable the Calendar pilot safely."},
    )
    assert unconfirmed.status_code == 422
    enabled = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/feature-flags/calendar",
        json={
            "enabled": True,
            "reason": "Enable the Calendar pilot safely.",
            "confirmed": True,
        },
    )
    assert enabled.status_code == 200
    assert enabled.json() == {"key": "calendar", "enabled": True}
    async with SessionFactory() as db:
        event = await db.scalar(
            select(AdministrativeAuditEvent)
            .where(
                AdministrativeAuditEvent.administrator_id == owner.id,
                AdministrativeAuditEvent.action == "feature_flag.updated",
            )
            .order_by(AdministrativeAuditEvent.created_at.desc())
        )
        assert event is not None
        assert event.reason == "Enable the Calendar pilot safely."

    disabled = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/feature-flags/calendar",
        json={
            "enabled": False,
            "reason": "Restore the default after this test.",
            "confirmed": True,
        },
    )
    assert disabled.status_code == 200


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


def make_request(peer: str, forwarded: str | None = None) -> Request:
    headers = Headers({"x-forwarded-for": forwarded} if forwarded else {})
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers.raw,
            "client": (peer, 443),
            "scheme": "https",
            "server": ("admin.mykhaya.app", 443),
            "query_string": b"",
        }
    )


def test_untrusted_proxy_header_cannot_change_client_address() -> None:
    settings = get_settings().model_copy(update={"trusted_proxy_cidrs": ["10.0.0.0/8"]})
    assert resolve_client_ip(make_request("203.0.113.9", "127.0.0.1"), settings) == "203.0.113.9"
    assert resolve_client_ip(make_request("10.0.0.2", "198.51.100.3"), settings) == "198.51.100.3"


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
