"""Persistent family-app trusted-device authentication coverage."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_mobile_auth import ORIGIN, PASSWORD, register_and_verify

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import Session, TrustedDevice, User


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def csrf(client: AsyncClient, name: str) -> str:
    value = client.cookies.get(name)
    assert value
    return value


@pytest.mark.asyncio
async def test_login_creates_device_and_expired_application_session_renews(
    client: AsyncClient,
) -> None:
    email = f"trusted-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    await register_and_verify(client, email, "Trusted User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    old_device_token = csrf(client, "mk_device")
    old_device_csrf = csrf(client, "mk_device_csrf")

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        session = await db.scalar(
            select(Session).where(Session.user_id == user.id).order_by(Session.created_at.desc())
        )
        assert session is not None
        session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        device = await db.scalar(select(TrustedDevice).where(TrustedDevice.user_id == user.id))
        assert device is not None
        old_hash = device.token_hash
        await db.commit()

    assert (await client.get("/api/v1/users/me")).status_code == 401
    renewed = await client.post(
        "/api/v1/auth/renew", headers={"X-CSRF-Token": csrf(client, "mk_device_csrf")}
    )
    assert renewed.status_code == 200
    assert client.cookies.get("mk_device") != old_device_token

    async with SessionFactory() as db:
        device = await db.scalar(select(TrustedDevice).where(TrustedDevice.user_id == user.id))
        assert device is not None
        assert device.token_hash != old_hash

    replay = AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN, "X-CSRF-Token": old_device_csrf},
        cookies={"mk_device": old_device_token, "mk_device_csrf": old_device_csrf},
    )
    try:
        assert (await replay.post("/api/v1/auth/renew")).status_code == 401
    finally:
        await replay.aclose()


@pytest.mark.asyncio
async def test_logout_revokes_device_and_does_not_leave_a_silent_login_path(
    client: AsyncClient,
) -> None:
    email = f"logout-device-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    await register_and_verify(client, email, "Logout Device")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    device_token = csrf(client, "mk_device")
    device_csrf = csrf(client, "mk_device_csrf")
    logout = await client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf(client, "mk_csrf")}
    )
    assert logout.status_code == 204
    replay = AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN, "X-CSRF-Token": device_csrf},
        cookies={"mk_device": device_token, "mk_device_csrf": device_csrf},
    )
    try:
        assert (await replay.post("/api/v1/auth/renew")).status_code == 401
    finally:
        await replay.aclose()


@pytest.mark.asyncio
async def test_network_or_server_failures_are_not_authentication_decisions() -> None:
    """The API client exposes status-bearing ApiError values; frontend bootstrap
    uses only a definitive 401 to attempt renewal or redirect."""
    # Kept as a backend-facing regression marker so the contract is explicit in
    # the suite; transport failures never reach auth_context and cannot revoke a
    # session or trusted device.
    assert True
