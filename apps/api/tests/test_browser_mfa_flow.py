from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import ActionToken, PlatformSetting, Session, TokenPurpose, User
from mykhaya.consumer_mfa_policy import CONSUMER_MFA_POLICY_SETTING_KEY
from mykhaya.security import derived_token
from mykhaya.routers import auth as auth_router


PASSWORD = "Correct horse battery staple!"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:8080",
        headers={"Origin": "http://localhost:8080"},
    ) as value:
        yield value


async def _verified_user(client: AsyncClient, prefix: str) -> str:
    email = f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": "MFA User", "password": PASSWORD},
    )
    assert response.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        token = await db.scalar(
            select(ActionToken)
            .where(ActionToken.user_id == user.id, ActionToken.purpose == TokenPurpose.verify_email)
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    return email


@pytest.mark.asyncio
async def test_email_mfa_handoff_has_no_session_before_success(client: AsyncClient, monkeypatch) -> None:
    settings = get_settings().model_copy(update={"browser_mfa_handoff_enabled": True})
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(auth_router, "new_email_code", lambda: "123456")
    try:
        email = await _verified_user(client, "mfa-email")
        login = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert login.status_code == 200
        transaction = login.json()["transaction_id"]
        assert login.json()["authentication_state"] == "additional_auth_required"
        assert "mk_session" not in client.cookies
        async with SessionFactory() as db:
            user = await db.scalar(select(User).where(User.email == email))
            assert user is not None
            assert await db.scalar(select(Session.id).where(Session.user_id == user.id)) is None

        options = await client.get(
            f"/api/v1/auth/mfa/options?transaction_id={transaction}"
        )
        assert options.status_code == 200
        start = await client.post(
            "/api/v1/auth/mfa/start",
            json={"transaction_id": transaction, "method": "email"},
        )
        assert start.status_code == 200
        verify = await client.post(
            "/api/v1/auth/mfa/verify",
            json={"transaction_id": transaction, "method": "email", "code": "123456"},
        )
        assert verify.status_code == 200
        assert "mk_session" in client.cookies
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_totp_enrolment_and_replay_protection(client: AsyncClient) -> None:
    settings = get_settings().model_copy(update={"browser_mfa_handoff_enabled": True})
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        email = await _verified_user(client, "mfa-totp")
        login = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        transaction = login.json()["transaction_id"]
        start = await client.post(
            "/api/v1/auth/mfa/start",
            json={"transaction_id": transaction, "method": "totp"},
        )
        assert start.status_code == 200
        secret = start.json()["manual_key"]
        assert secret and secret.lower() in start.text.lower()
        code = pyotp.TOTP(secret).now()
        verify = await client.post(
            "/api/v1/auth/mfa/verify",
            json={"transaction_id": transaction, "method": "totp", "code": code},
        )
        assert verify.status_code == 200
        assert "mk_session" in client.cookies
        replay = await client.post(
            "/api/v1/auth/mfa/verify",
            json={"transaction_id": transaction, "method": "totp", "code": code},
        )
        assert replay.status_code == 400
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_explicit_optional_policy_skips_browser_mfa_even_when_rollout_flag_is_on(
    client: AsyncClient,
) -> None:
    settings = get_settings().model_copy(update={"browser_mfa_handoff_enabled": True})
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        email = await _verified_user(client, "mfa-policy-optional")
        async with SessionFactory() as db:
            db.add(
                PlatformSetting(
                    key=CONSUMER_MFA_POLICY_SETTING_KEY,
                    value={"policy": "optional", "allowed_methods": ["totp", "email"]},
                )
            )
            await db.commit()
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200
        assert login.json().get("authentication_state") is None
        assert "mk_session" in client.cookies
    finally:
        async with SessionFactory() as db:
            await db.execute(delete(PlatformSetting).where(PlatformSetting.key == CONSUMER_MFA_POLICY_SETTING_KEY))
            await db.commit()
        app.dependency_overrides.pop(get_settings, None)
