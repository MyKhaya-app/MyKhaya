"""Session rotation cannot extend a session past the consumer MFA policy.

Session expiry never slides; rotation is the only way a still-valid session's
lifetime can grow. While the effective consumer MFA policy is enforced and
Required, both rotation endpoints keep the original expiry. Browser rotation
accepts only the cookie transport and native rotation only bearer, so a token
cannot be converted between transports through rotation. Rotation also keeps
the trusted-device link, and mints no new renewal credential while MFA is
Required.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from test_journey import unsafe
from test_mobile_auth import PASSWORD
from test_native_mfa_policy import (  # noqa: F401
    _clear_policy,
    _native_password,
    _set_policy,
    _user,
    bearer,
    client,
    mfa_required,
)
from test_platform_control_centre import admin_client  # noqa: F401

from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import Session, SessionKind, TrustedDevice, User
from mykhaya.security import hash_secret, new_session_token

FRESH_LIFETIME_TOLERANCE = timedelta(minutes=5)


def _digest(raw: str) -> str:
    return hash_secret(raw, get_settings().secret_key.get_secret_value())


async def _session(raw: str) -> Session:
    async with SessionFactory() as db:
        row = await db.scalar(select(Session).where(Session.token_hash == _digest(raw)))
        assert row is not None
        return row


async def _browser_login(client: AsyncClient, email: str) -> str:
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    raw = client.cookies.get("mk_session")
    assert raw
    return raw


def _fresh(expires_at: datetime, settings: Settings) -> bool:
    expected = datetime.now(UTC) + timedelta(minutes=settings.session_minutes)
    return abs(expires_at - expected) < FRESH_LIFETIME_TOLERANCE


async def _shorten(raw: str, remaining: timedelta) -> datetime:
    """Give a session a short remaining life so 'kept' vs 'extended' is obvious."""
    async with SessionFactory() as db:
        row = await db.scalar(select(Session).where(Session.token_hash == _digest(raw)))
        assert row is not None
        row.expires_at = datetime.now(UTC) + remaining
        await db.commit()
        return row.expires_at


# 1 + 9. No browser/native token exchange through rotation ------------------


@pytest.mark.asyncio
async def test_bearer_token_cannot_rotate_through_browser_endpoint(
    client: AsyncClient, mfa_required: Settings
) -> None:
    for policy in ("optional", "required"):
        await _set_policy("optional")
        try:
            email, _u = await _user(client, f"rotate-bearer-browser-{policy}")
            token = (await _native_password(client, email)).json()["session_token"]
            await _set_policy(policy)

            converted = await client.post("/api/v1/auth/sessions/rotate", headers=bearer(token))

            assert converted.status_code == 400
            assert "mk_session" not in converted.headers.get("set-cookie", "")
            assert (await _session(token)).revoked_at is None
            assert (await client.get("/api/v1/users/me", headers=bearer(token))).status_code == 200
        finally:
            await _clear_policy()


@pytest.mark.asyncio
async def test_cookie_session_cannot_rotate_through_native_endpoint(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, _u = await _user(client, "rotate-cookie-native")
        raw = await _browser_login(client, email)
        converted = await unsafe(client, "POST", "/api/v1/auth/mobile/sessions/rotate")
        assert converted.status_code == 400
        assert "session_token" not in converted.text
        assert (await _session(raw)).revoked_at is None
    finally:
        await _clear_policy()


async def _device_less_session(user: User) -> str:
    """A session with no TrustedDevice link (a pre-device legacy row)."""
    raw = new_session_token()
    async with SessionFactory() as db:
        db.add(
            Session(
                user_id=user.id,
                token_hash=_digest(raw),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                kind=SessionKind.adult,
            )
        )
        await db.commit()
    return raw


async def _device_count(user: User) -> int:
    async with SessionFactory() as db:
        count = await db.scalar(
            select(func.count()).select_from(TrustedDevice).where(TrustedDevice.user_id == user.id)
        )
    return int(count or 0)


@pytest.mark.asyncio
async def test_rotation_mints_no_renewal_credential_while_mfa_required(
    client: AsyncClient, mfa_required: Settings
) -> None:
    """A device-less session must not gain a long-lived renewal token while
    MFA is required. (When MFA is not required, the established legacy
    upgrade still applies: see test_mobile_auth's legacy-session test.)"""
    await _set_policy("required")
    try:
        _email, user = await _user(client, "rotate-no-device")
        raw = await _device_less_session(user)

        rotated = await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(raw))

        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["device_token"] is None
        assert await _device_count(user) == 0
        assert (await _session(rotated.json()["session_token"])).trusted_device_id is None
    finally:
        await _clear_policy()


@pytest.mark.asyncio
async def test_legacy_device_upgrade_on_rotation_kept_when_mfa_optional(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        _email, user = await _user(client, "rotate-legacy-upgrade")
        raw = await _device_less_session(user)
        rotated = await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(raw))
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["device_token"]
        assert await _device_count(user) == 1
    finally:
        await _clear_policy()


# 2 + 3 + 6. Rotation under Required keeps the lifetime ------------------------


@pytest.mark.asyncio
async def test_native_rotation_cannot_extend_a_session_when_mfa_required(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, _u = await _user(client, "rotate-native-required")
        login = (await _native_password(client, email)).json()
        token = login["session_token"]
        original_expiry = await _shorten(token, timedelta(minutes=30))
        original_device = (await _session(token)).trusted_device_id
        await _set_policy("required")

        current = token
        for _ in range(3):  # repeated rotation still never extends
            rotated = await client.post(
                "/api/v1/auth/mobile/sessions/rotate", headers=bearer(current)
            )
            assert rotated.status_code == 200, rotated.text
            assert rotated.json()["device_token"] is None
            new = rotated.json()["session_token"]
            row = await _session(new)
            assert row.expires_at == original_expiry
            assert row.trusted_device_id == original_device
            assert (await _session(current)).revoked_at is not None
            current = new

        # The valid session keeps working normally until its original expiry.
        assert (await client.get("/api/v1/users/me", headers=bearer(current))).status_code == 200
    finally:
        await _clear_policy()


@pytest.mark.asyncio
async def test_browser_rotation_cannot_extend_a_session_when_mfa_required(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, _u = await _user(client, "rotate-browser-required")
        raw = await _browser_login(client, email)
        original_expiry = await _shorten(raw, timedelta(minutes=30))
        original_device = (await _session(raw)).trusted_device_id
        assert original_device is not None
        await _set_policy("required")

        rotated = await unsafe(client, "POST", "/api/v1/auth/sessions/rotate")

        assert rotated.status_code == 200, rotated.text
        new_raw = client.cookies.get("mk_session")
        assert new_raw and new_raw != raw
        row = await _session(new_raw)
        assert row.expires_at == original_expiry
        assert row.trusted_device_id == original_device
        assert (await _session(raw)).revoked_at is not None
        assert (await client.get("/api/v1/users/me")).status_code == 200
    finally:
        await _clear_policy()


# 4 + 7. Policy transitions; Optional unchanged --------------------------------


@pytest.mark.asyncio
async def test_rotation_follows_policy_transitions(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, _u = await _user(client, "rotate-transitions")
        token = (await _native_password(client, email)).json()["session_token"]
        await _shorten(token, timedelta(minutes=30))

        # Optional: rotation gives the normal fresh lifetime (unchanged behaviour).
        token = (
            await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(token))
        ).json()["session_token"]
        assert _fresh((await _session(token)).expires_at, mfa_required)

        # Optional -> Required: lifetime is frozen from this point.
        frozen = await _shorten(token, timedelta(minutes=20))
        await _set_policy("required")
        token = (
            await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(token))
        ).json()["session_token"]
        assert (await _session(token)).expires_at == frozen

        # Required -> Optional: normal rotation resumes.
        await _set_policy("optional")
        token = (
            await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(token))
        ).json()["session_token"]
        assert _fresh((await _session(token)).expires_at, mfa_required)
    finally:
        await _clear_policy()


@pytest.mark.asyncio
async def test_browser_rotation_unchanged_when_mfa_optional(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, _u = await _user(client, "rotate-browser-optional")
        raw = await _browser_login(client, email)
        await _shorten(raw, timedelta(minutes=30))
        rotated = await unsafe(client, "POST", "/api/v1/auth/sessions/rotate")
        assert rotated.status_code == 200, rotated.text
        assert _fresh((await _session(client.cookies["mk_session"])).expires_at, mfa_required)
    finally:
        await _clear_policy()


@pytest.mark.asyncio
async def test_rotation_unchanged_when_deployment_gate_disabled(client: AsyncClient) -> None:
    settings = get_settings().model_copy(update={"browser_mfa_handoff_enabled": False})
    from mykhaya.main import app

    app.dependency_overrides[get_settings] = lambda: settings
    try:
        await _set_policy("required")
        email, _u = await _user(client, "rotate-gate-off")
        token = (await _native_password(client, email)).json()["session_token"]
        await _shorten(token, timedelta(minutes=30))
        rotated = await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(token))
        assert rotated.status_code == 200, rotated.text
        assert _fresh((await _session(rotated.json()["session_token"])).expires_at, settings)
    finally:
        await _clear_policy()
        app.dependency_overrides.pop(get_settings, None)


# 5. Expired and revoked sessions stay unusable --------------------------------


@pytest.mark.asyncio
async def test_expired_and_revoked_sessions_cannot_rotate(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, _u = await _user(client, "rotate-expired")
        token = (await _native_password(client, email)).json()["session_token"]
        rotated = await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(token))
        assert rotated.status_code == 200
        # The replaced (revoked) token can neither rotate nor be used.
        for path in ("/api/v1/auth/mobile/sessions/rotate", "/api/v1/auth/sessions/rotate"):
            assert (await client.post(path, headers=bearer(token))).status_code == 401
        assert (await client.get("/api/v1/users/me", headers=bearer(token))).status_code == 401

        current = rotated.json()["session_token"]
        await _shorten(current, timedelta(seconds=-1))
        for policy in ("optional", "required"):
            await _set_policy(policy)
            for path in ("/api/v1/auth/mobile/sessions/rotate", "/api/v1/auth/sessions/rotate"):
                assert (await client.post(path, headers=bearer(current))).status_code == 401
            assert (
                await client.get("/api/v1/users/me", headers=bearer(current))
            ).status_code == 401
    finally:
        await _clear_policy()


@pytest.mark.asyncio
async def test_device_revocation_still_reaches_a_browser_rotated_session(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, user = await _user(client, "rotate-device-revoke")
        await _browser_login(client, email)
        assert (await unsafe(client, "POST", "/api/v1/auth/sessions/rotate")).status_code == 200
        rotated_raw = client.cookies["mk_session"]
        device_id = (await _session(rotated_raw)).trusted_device_id
        assert device_id is not None

        # Revoke that device from a second (native) session of the same user.
        other = (await _native_password(client, email)).json()["session_token"]
        removed = await client.delete(f"/api/v1/auth/devices/{device_id}", headers=bearer(other))
        assert removed.status_code == 204, removed.text

        assert (await _session(rotated_raw)).revoked_at is not None
        assert (
            await client.get("/api/v1/users/me", headers=bearer(rotated_raw))
        ).status_code == 401
        async with SessionFactory() as db:
            assert await db.get(User, user.id) is not None
    finally:
        await _clear_policy()


# 8. PCC administrator authentication is separate ------------------------------


@pytest.mark.asyncio
async def test_consumer_sessions_never_reach_pcc(
    client: AsyncClient, admin_client: AsyncClient, mfa_required: Settings
) -> None:
    """PCC is host- and network-isolated (404 on the consumer host) and reads
    only its own mk_admin_* cookies, so a consumer token from either rotation
    path is refused even when presented to the admin host."""
    await _set_policy("optional")
    try:
        email, _u = await _user(client, "rotate-pcc")
        token = (await _native_password(client, email)).json()["session_token"]
        rotated = (
            await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(token))
        ).json()["session_token"]
        await _browser_login(client, email)
        assert (await unsafe(client, "POST", "/api/v1/auth/sessions/rotate")).status_code == 200
        cookie_token = client.cookies["mk_session"]

        on_consumer_host = await client.get("/api/v1/platform/auth/mfa/browser-policy")
        assert on_consumer_host.status_code == 404
        for raw in (rotated, cookie_token):
            on_admin_host = await admin_client.get(
                "/api/v1/platform/auth/mfa/browser-policy", headers=bearer(raw)
            )
            assert on_admin_host.status_code == 401
            admin_client.cookies.set("mk_session", raw)
            assert (
                await admin_client.get("/api/v1/platform/auth/mfa/browser-policy")
            ).status_code == 401
            admin_client.cookies.clear()
    finally:
        await _clear_policy()
