import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pyotp
import pytest
from fastapi import HTTPException, Response
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.consumer_mfa_policy import CONSUMER_MFA_POLICY_SETTING_KEY, ConsumerMfaPolicyError
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import ActionToken, PlatformSetting, Session, TokenPurpose, User, UserMfaMethod
from mykhaya.routers import auth as auth_router
from mykhaya.schemas import AuthContinuationResponse
from mykhaya.security import derived_token

PASSWORD = "Correct horse battery staple!"


def test_browser_mfa_methods_only_include_currently_usable_factors() -> None:
    assert auth_router._usable_browser_mfa_methods(
        {UserMfaMethod.email, UserMfaMethod.totp}, set(), True
    ) == ["email"]
    assert auth_router._usable_browser_mfa_methods(
        {UserMfaMethod.email, UserMfaMethod.totp},
        {UserMfaMethod.totp},
        True,
    ) == ["totp", "email"]
    assert auth_router._usable_browser_mfa_methods({UserMfaMethod.totp}, set(), False) == []
    assert auth_router._usable_browser_mfa_methods(
        {UserMfaMethod.totp}, set(), False, allow_totp_enrolment=True
    ) == ["totp"]


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
async def test_invalid_required_policy_fails_closed_before_session_issue(monkeypatch) -> None:
    async def invalid_policy(*_args, **_kwargs):
        raise ConsumerMfaPolicyError("invalid effective policy")

    monkeypatch.setattr(auth_router, "resolve_consumer_mfa_policy", invalid_policy)
    with pytest.raises(HTTPException) as error:
        await auth_router._resolve_browser_mfa_policy(
            object(),  # type: ignore[arg-type]
            uuid.uuid4(),
            get_settings(),
        )

    assert error.value.status_code == 503
    assert error.value.detail == "We couldn't complete secure sign-in. Please contact support."


@pytest.mark.asyncio
async def test_existing_session_can_read_mfa_status_without_fresh_auth(client: AsyncClient) -> None:
    email = await _verified_user(client, "mfa-legacy-status")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        session = await db.scalar(select(Session).where(Session.user_id == user.id))
        assert session is not None
        session.fresh_auth_at = None
        await db.commit()

    status_response = await client.get("/api/v1/auth/mfa/status")
    assert status_response.status_code == 200
    assert status_response.json() == {
        "required": False,
        "allowed_methods": ["email", "totp"],
        "email_available": True,
        "email_destination": auth_router._masked_email(email),
        "totp_enabled": False,
        "can_disable_totp": False,
        "usable_methods": ["email"],
        "preferred_method": "email",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handoff_enabled", "policy", "expects_preauth"),
    [
        (False, "optional", False),
        (False, "required", False),
        (True, "optional", False),
        (True, "required", True),
    ],
)
async def test_login_enforcement_matrix_uses_real_authentication_completion_path(
    client: AsyncClient,
    handoff_enabled: bool,
    policy: str,
    expects_preauth: bool,
) -> None:
    settings = get_settings().model_copy(update={"browser_mfa_handoff_enabled": handoff_enabled})
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        email = await _verified_user(client, f"mfa-matrix-{str(handoff_enabled).lower()}-{policy}")
        async with SessionFactory() as db:
            db.add(
                PlatformSetting(
                    key=CONSUMER_MFA_POLICY_SETTING_KEY,
                    value={"policy": policy, "allowed_methods": ["email"]},
                )
            )
            await db.commit()

        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200
        assert (
            login.json().get("authentication_state") == "additional_auth_required"
        ) is expects_preauth
        assert ("mk_session" not in client.cookies) is expects_preauth
        if not expects_preauth:
            assert "mk_session" in client.cookies
    finally:
        async with SessionFactory() as db:
            await db.execute(
                delete(PlatformSetting).where(
                    PlatformSetting.key == CONSUMER_MFA_POLICY_SETTING_KEY
                )
            )
            await db.commit()
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_email_mfa_handoff_has_no_session_before_success(
    client: AsyncClient, monkeypatch
) -> None:
    settings = get_settings().model_copy(update={"browser_mfa_handoff_enabled": True})
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(auth_router, "new_email_code", lambda: "123456")
    try:
        email = await _verified_user(client, "mfa-email")
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200
        transaction = login.json()["transaction_id"]
        assert login.json()["authentication_state"] == "additional_auth_required"
        assert "mk_session" not in client.cookies
        async with SessionFactory() as db:
            user = await db.scalar(select(User).where(User.email == email))
            assert user is not None
            assert await db.scalar(select(Session.id).where(Session.user_id == user.id)) is None

        options = await client.get(f"/api/v1/auth/mfa/options?transaction_id={transaction}")
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
        async with SessionFactory() as db:
            db.add(
                PlatformSetting(
                    key=CONSUMER_MFA_POLICY_SETTING_KEY,
                    value={"policy": "required", "allowed_methods": ["totp"]},
                )
            )
            await db.commit()
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
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
        async with SessionFactory() as db:
            await db.execute(
                delete(PlatformSetting).where(
                    PlatformSetting.key == CONSUMER_MFA_POLICY_SETTING_KEY
                )
            )
            await db.commit()
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
            await db.execute(
                delete(PlatformSetting).where(
                    PlatformSetting.key == CONSUMER_MFA_POLICY_SETTING_KEY
                )
            )
            await db.commit()
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_social_login_completion_is_gated_by_the_same_shared_seam(
    monkeypatch,
) -> None:
    """Apple/Google sign-in completes through `complete_browser_authentication`,
    the exact function the password-login enforcement matrix above exercises
    (see auth.py's apple callback, which calls this same function). This
    proves the gate is not something password login alone passes through —
    any adult-kind caller of this seam is bound by the same required-policy
    check, with no separate, weaker path for social providers."""
    email = f"mfa-social-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    settings = get_settings().model_copy(update={"browser_mfa_handoff_enabled": True})
    async with SessionFactory() as db:
        user = User(email=email, display_name="Social MFA User")
        db.add(user)
        await db.flush()
        db.add(
            PlatformSetting(
                key=CONSUMER_MFA_POLICY_SETTING_KEY,
                value={"policy": "required", "allowed_methods": ["email"]},
            )
        )
        await db.commit()
        user_id = user.id
    try:
        async with SessionFactory() as db:
            user = await db.get(User, user_id)
            assert user is not None
            result = await auth_router.complete_browser_authentication(
                db,
                Response(),
                _fake_request(),
                user,
                settings,
                method="apple",
            )
        assert isinstance(result, AuthContinuationResponse)
        assert result.authentication_state == "additional_auth_required"
        async with SessionFactory() as db:
            assert await db.scalar(select(Session.id).where(Session.user_id == user_id)) is None
    finally:
        async with SessionFactory() as db:
            await db.execute(
                delete(PlatformSetting).where(
                    PlatformSetting.key == CONSUMER_MFA_POLICY_SETTING_KEY
                )
            )
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


def test_issue_family_session_call_sites_are_an_explicit_reviewed_allowlist() -> None:
    """`issue_family_session` is the only function that mints a browser cookie
    session for an adult user. Every call site that reaches it while bypassing
    `complete_browser_authentication` (and therefore the required-MFA check)
    must be deliberately reviewed and added here. If this count changes, a new
    bypass path may have been introduced — update this test only after
    confirming the new call site cannot skip mandatory MFA when required.

    Known, reviewed call sites today:
    - `complete_browser_authentication` itself, after the MFA gate passes.
    - the `/auth/mfa/verify` completion endpoint, which only runs after a
      caller has already proven possession of an enrolled MFA factor.
    - `/auth/passkeys/login/verify`, which is intentionally exempt: a WebAuthn
      passkey is itself a phishing-resistant, possession-bound credential, and
      registering one (`/auth/passkeys/register/verify`) requires
      `require_fresh_adult_auth`, i.e. a session that already satisfied
      whatever policy was in force at registration time. There is no path to
      register a passkey without first clearing the required-MFA gate.
    - `/auth/child-login`, which issues a `SessionKind.child` session; the
      consumer MFA policy only ever applies to `SessionKind.adult`.
    """
    import inspect

    source = inspect.getsource(auth_router)
    assert source.count("await issue_family_session(") == 4


def _fake_request():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/apple/callback",
        "headers": [(b"origin", b"http://localhost:8080")],
        "client": ("127.0.0.1", 0),
        "server": ("localhost", 8080),
        "scheme": "http",
    }
    return Request(scope)
