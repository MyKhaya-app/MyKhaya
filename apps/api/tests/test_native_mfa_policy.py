"""Native sign-in follows the consumer MFA policy; browser enforcement stays intact.

Nothing in a request proves it came from the MyKhaya app (there is no app
attestation, and X-MyKhaya-* headers are display-only), so every native
session-issuing path must apply the same consumer MFA policy as the browser.
These tests pin that contract for native password, Apple and Google sign-in,
native renewal, spoofed native signals and replay.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from test_mobile_auth import ORIGIN, PASSWORD, bearer, register_and_verify

from mykhaya.config import Settings, get_settings
from mykhaya.consumer_mfa_policy import CONSUMER_MFA_POLICY_SETTING_KEY
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ExternalIdentity,
    ExternalIdentityProvider,
    PlatformSetting,
    Session,
    TrustedDevice,
    User,
)
from mykhaya.routers import auth as auth_router

VERIFIER = "n" * 64
EMAIL_CODE = "246810"
NATIVE_HEADERS = {
    "X-MyKhaya-Client": "MyKhaya iOS",
    "X-MyKhaya-Platform": "ios",
    "X-MyKhaya-App-Version": "9.9.9",
    "User-Agent": "MyKhaya/9.9.9 (iPhone; iOS 26.0) Capacitor",
}


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def _settings(*, handoff: bool) -> Settings:
    return get_settings().model_copy(
        update={
            "browser_mfa_handoff_enabled": handoff,
            "apple_sign_in_enabled": True,
            "apple_native_client_id": "app.mykhaya.dev",
            "google_sign_in_enabled": True,
            "google_native_client_id": "1234567890-native.apps.googleusercontent.com",
        }
    )


@pytest.fixture
def mfa_required() -> Iterator[Settings]:
    settings = _settings(handoff=True)
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
async def required_policy(mfa_required: Settings) -> AsyncIterator[Settings]:
    await _set_policy("required")
    yield mfa_required
    await _clear_policy()


async def _set_policy(policy: str) -> None:
    async with SessionFactory() as db:
        await db.execute(
            delete(PlatformSetting).where(PlatformSetting.key == CONSUMER_MFA_POLICY_SETTING_KEY)
        )
        db.add(
            PlatformSetting(
                key=CONSUMER_MFA_POLICY_SETTING_KEY,
                value={"policy": policy, "allowed_methods": ["email", "totp"]},
            )
        )
        await db.commit()


async def _clear_policy() -> None:
    async with SessionFactory() as db:
        await db.execute(
            delete(PlatformSetting).where(PlatformSetting.key == CONSUMER_MFA_POLICY_SETTING_KEY)
        )
        await db.commit()


async def _user(client: AsyncClient, prefix: str) -> tuple[str, User]:
    email = f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    await register_and_verify(client, email, "Native MFA User")
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
    return email, user


async def _session_count(user: User) -> tuple[int, int]:
    async with SessionFactory() as db:
        sessions = await db.scalar(
            select(func.count()).select_from(Session).where(Session.user_id == user.id)
        )
        devices = await db.scalar(
            select(func.count()).select_from(TrustedDevice).where(TrustedDevice.user_id == user.id)
        )
    return int(sessions or 0), int(devices or 0)


async def _native_password(client: AsyncClient, email: str, **extra: str):
    return await client.post(
        "/api/v1/auth/mobile/login",
        headers=NATIVE_HEADERS,
        json={"email": email, "password": PASSWORD, **extra},
    )


# --- Native password -------------------------------------------------------


@pytest.mark.asyncio
async def test_native_password_login_requires_mfa_when_policy_required(
    client: AsyncClient, required_policy: Settings
) -> None:
    email, user = await _user(client, "native-pw-required")
    before = await _session_count(user)

    login = await _native_password(client, email, redemption_verifier=VERIFIER)

    assert login.status_code == 200, login.text
    body = login.json()
    assert body["authentication_state"] == "additional_auth_required"
    assert body["provider"] == "password"
    assert "session_token" not in body
    assert "device_token" not in body
    assert login.headers["cache-control"] == "no-store"
    # Pre-authentication only: no Session and no long-lived device credential.
    assert await _session_count(user) == before


@pytest.mark.asyncio
async def test_native_password_login_without_verifier_fails_closed(
    client: AsyncClient, required_policy: Settings
) -> None:
    email, user = await _user(client, "native-pw-no-verifier")
    before = await _session_count(user)

    login = await _native_password(client, email)

    assert login.status_code == 400
    assert "session_token" not in login.text
    assert await _session_count(user) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(("handoff", "policy"), [(False, "required"), (True, "optional")])
async def test_native_password_login_issues_session_when_policy_not_enforced(
    client: AsyncClient, handoff: bool, policy: str
) -> None:
    settings = _settings(handoff=handoff)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        await _set_policy(policy)
        email, _user_row = await _user(client, f"native-pw-{policy}-{str(handoff).lower()}")
        login = await _native_password(client, email)
        assert login.status_code == 200, login.text
        assert login.json()["session_token"]
        assert login.json()["device_token"]
    finally:
        await _clear_policy()
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_native_password_mfa_completes_once_and_rejects_replay(
    client: AsyncClient, required_policy: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_router, "new_email_code", lambda: EMAIL_CODE)
    email, user = await _user(client, "native-pw-complete")
    login = await _native_password(client, email, redemption_verifier=VERIFIER)
    transaction = login.json()["transaction_id"]

    # The transaction id alone is useless without the client's verifier.
    wrong = "x" * 64
    stolen_options = await client.get(
        "/api/v1/auth/mobile/mfa/options",
        params={"transaction_id": transaction, "redemption_verifier": wrong},
    )
    assert stolen_options.status_code == 400
    stolen_start = await client.post(
        "/api/v1/auth/mobile/mfa/start",
        json={"transaction_id": transaction, "method": "email", "redemption_verifier": wrong},
    )
    assert stolen_start.status_code == 400

    options = await client.get(
        "/api/v1/auth/mobile/mfa/options",
        params={"transaction_id": transaction, "redemption_verifier": VERIFIER},
    )
    assert options.status_code == 200, options.text
    assert options.json()["primary_auth_method"] == "password"
    assert "email" in options.json()["methods"]

    started = await client.post(
        "/api/v1/auth/mobile/mfa/start",
        json={"transaction_id": transaction, "method": "email", "redemption_verifier": VERIFIER},
    )
    assert started.status_code == 200, started.text

    # A mistyped code is rejected without discarding the primary factor.
    mistyped = await client.post(
        "/api/v1/auth/mobile/mfa/verify",
        json={
            "transaction_id": transaction,
            "method": "email",
            "code": "000000",
            "redemption_verifier": VERIFIER,
        },
    )
    assert mistyped.status_code == 401
    assert await _session_count(user) == (0, 0)

    # A correct code with the wrong verifier still cannot mint a session.
    hijack = await client.post(
        "/api/v1/auth/mobile/mfa/verify",
        json={
            "transaction_id": transaction,
            "method": "email",
            "code": EMAIL_CODE,
            "redemption_verifier": wrong,
        },
    )
    assert hijack.status_code == 400

    verified = await client.post(
        "/api/v1/auth/mobile/mfa/verify",
        json={
            "transaction_id": transaction,
            "method": "email",
            "code": EMAIL_CODE,
            "redemption_verifier": VERIFIER,
        },
    )
    assert verified.status_code == 200, verified.text
    token = verified.json()["session_token"]
    assert verified.json()["device_token"]
    me = await client.get("/api/v1/users/me", headers=bearer(token))
    assert me.status_code == 200

    replay = await client.post(
        "/api/v1/auth/mobile/mfa/verify",
        json={
            "transaction_id": transaction,
            "method": "email",
            "code": EMAIL_CODE,
            "redemption_verifier": VERIFIER,
        },
    )
    assert replay.status_code == 400
    assert await _session_count(user) == (1, 1)


# --- Spoofed native signals against the browser path -------------------------


@pytest.mark.asyncio
async def test_spoofed_native_headers_do_not_bypass_browser_mfa(
    client: AsyncClient, required_policy: Settings
) -> None:
    email, _user_row = await _user(client, "native-spoof-browser")

    login = await client.post(
        "/api/v1/auth/login",
        headers=NATIVE_HEADERS,
        json={"email": email, "password": PASSWORD},
    )

    assert login.status_code == 200, login.text
    assert login.json()["authentication_state"] == "additional_auth_required"
    assert "mk_session" not in client.cookies


@pytest.mark.asyncio
async def test_native_and_browser_pre_auth_transactions_are_not_interchangeable(
    client: AsyncClient, required_policy: Settings
) -> None:
    email, _user_row = await _user(client, "native-cross-transaction")
    browser = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    browser_transaction = browser.json()["transaction_id"]
    native = await _native_password(client, email, redemption_verifier=VERIFIER)
    native_transaction = native.json()["transaction_id"]

    as_native = await client.get(
        "/api/v1/auth/mobile/mfa/options",
        params={"transaction_id": browser_transaction, "redemption_verifier": VERIFIER},
    )
    assert as_native.status_code == 400
    as_browser = await client.get(
        "/api/v1/auth/mfa/options", params={"transaction_id": native_transaction}
    )
    assert as_browser.status_code == 400


# --- Native Apple / Google ---------------------------------------------------


async def _link(user: User, provider: ExternalIdentityProvider, subject: str) -> None:
    async with SessionFactory() as db:
        db.add(
            ExternalIdentity(
                user_id=user.id,
                provider=provider,
                provider_subject=subject,
                provider_email=None,
                provider_email_verified=False,
            )
        )
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "platform", "verifier_name"),
    [
        ("apple", "ios", "verify_identity_token"),
        ("google", "android", "verify_google_identity_token"),
    ],
)
async def test_native_provider_exchange_requires_mfa_and_rejects_replay(
    client: AsyncClient,
    required_policy: Settings,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    platform: str,
    verifier_name: str,
) -> None:
    email, user = await _user(client, f"native-{provider}-mfa")
    subject = f"native-{provider}-{uuid4().hex}"
    await _link(user, ExternalIdentityProvider(provider), subject)

    async def verify(_settings, _token, _nonce, _audience=None):
        return {"sub": subject, "email": email, "email_verified": True}

    monkeypatch.setattr(auth_router, verifier_name, verify)
    started = await client.post(
        "/api/v1/auth/mobile/external/start",
        headers=NATIVE_HEADERS,
        json={
            "provider": provider,
            "platform": platform,
            "intent": "login",
            "redemption_verifier": VERIFIER,
        },
    )
    assert started.status_code == 200, started.text
    exchange_body = {
        "transaction_id": started.json()["transaction_id"],
        "identity_token": "provider-asserted-token",
        "redemption_verifier": VERIFIER,
    }

    exchanged = await client.post("/api/v1/auth/mobile/external/exchange", json=exchange_body)

    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["authentication_state"] == "additional_auth_required"
    assert exchanged.json()["provider"] == provider
    assert "session_token" not in exchanged.json()
    assert await _session_count(user) == (0, 0)

    replay = await client.post("/api/v1/auth/mobile/external/exchange", json=exchange_body)
    assert replay.status_code == 400


# --- Native renewal ----------------------------------------------------------


@pytest.mark.asyncio
async def test_native_renewal_is_blocked_once_mfa_becomes_required(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, user = await _user(client, "native-renew-blocked")
        login = await _native_password(client, email)
        assert login.status_code == 200, login.text
        device_token = login.json()["device_token"]

        await _set_policy("required")
        renewed = await client.post(
            "/api/v1/auth/mobile/sessions/renew", json={"device_token": device_token}
        )

        assert renewed.status_code == 401
        async with SessionFactory() as db:
            device = await db.scalar(select(TrustedDevice).where(TrustedDevice.user_id == user.id))
            assert device is not None
            assert device.revoked_at is not None
        # The revoked credential stays dead even if the policy is relaxed again.
        await _set_policy("optional")
        again = await client.post(
            "/api/v1/auth/mobile/sessions/renew", json={"device_token": device_token}
        )
        assert again.status_code == 401
    finally:
        await _clear_policy()


@pytest.mark.asyncio
async def test_native_renewal_unchanged_when_policy_optional(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, _user_row = await _user(client, "native-renew-optional")
        login = await _native_password(client, email)
        renewed = await client.post(
            "/api/v1/auth/mobile/sessions/renew",
            json={"device_token": login.json()["device_token"]},
        )
        assert renewed.status_code == 200, renewed.text
        assert renewed.json()["session_token"]
    finally:
        await _clear_policy()


# --- Valid sessions, rotation, bounds, throttling ----------------------------


@pytest.mark.asyncio
async def test_valid_native_session_keeps_working_but_cannot_be_extended_when_required(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, _user_row = await _user(client, "native-valid-session")
        login = await _native_password(client, email)
        token = login.json()["session_token"]

        await _set_policy("required")
        # A still-valid session restores normally: no MFA prompt per launch.
        assert (await client.get("/api/v1/users/me", headers=bearer(token))).status_code == 200
        # Rotation still works, but cannot stretch it past its original expiry
        # (full coverage in test_session_rotation_policy.py).
        async with SessionFactory() as db:
            original = await db.scalar(
                select(Session.expires_at).where(Session.user_id == _user_row.id)
            )
        rotated = await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(token))
        assert rotated.status_code == 200, rotated.text
        new_token = rotated.json()["session_token"]
        assert (await client.get("/api/v1/users/me", headers=bearer(new_token))).status_code == 200
        async with SessionFactory() as db:
            expiries = (
                await db.scalars(
                    select(Session.expires_at).where(
                        Session.user_id == _user_row.id, Session.revoked_at.is_(None)
                    )
                )
            ).all()
        assert expiries == [original]
    finally:
        await _clear_policy()


@pytest.mark.asyncio
async def test_native_rotation_unchanged_when_policy_optional(
    client: AsyncClient, mfa_required: Settings
) -> None:
    await _set_policy("optional")
    try:
        email, _user_row = await _user(client, "native-rotate-optional")
        token = (await _native_password(client, email)).json()["session_token"]
        rotated = await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(token))
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["session_token"] != token
    finally:
        await _clear_policy()


@pytest.mark.asyncio
async def test_native_mfa_transaction_is_bounded(
    client: AsyncClient, required_policy: Settings
) -> None:
    from redis.asyncio import Redis

    from mykhaya.native_external_auth import TRANSACTION_TTL_SECONDS, _mfa_key

    email, _user_row = await _user(client, "native-mfa-ttl")
    transaction = (await _native_password(client, email, redemption_verifier=VERIFIER)).json()[
        "transaction_id"
    ]
    redis = Redis.from_url(required_policy.redis_url, decode_responses=True)
    try:
        ttl = await redis.ttl(_mfa_key(transaction))
        stored = await redis.get(_mfa_key(transaction))
    finally:
        await redis.aclose()
    assert 0 < ttl <= TRANSACTION_TTL_SECONDS <= 600
    assert stored is not None and VERIFIER not in stored  # only the verifier hash is stored


@pytest.mark.asyncio
async def test_native_mfa_failed_codes_are_rate_limited_and_audited(
    client: AsyncClient, required_policy: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mykhaya.models import AuditEvent

    monkeypatch.setattr(auth_router, "new_email_code", lambda: EMAIL_CODE)
    email, user = await _user(client, "native-mfa-throttle")
    transaction = (await _native_password(client, email, redemption_verifier=VERIFIER)).json()[
        "transaction_id"
    ]
    await client.post(
        "/api/v1/auth/mobile/mfa/start",
        json={"transaction_id": transaction, "method": "email", "redemption_verifier": VERIFIER},
    )
    statuses = []
    for _ in range(11):
        attempt = await client.post(
            "/api/v1/auth/mobile/mfa/verify",
            json={
                "transaction_id": transaction,
                "method": "email",
                "code": "000000",
                "redemption_verifier": VERIFIER,
            },
        )
        statuses.append(attempt.status_code)
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
    # The per-challenge attempt cap means even the right code is now refused.
    right = await client.post(
        "/api/v1/auth/mobile/mfa/verify",
        json={
            "transaction_id": transaction,
            "method": "email",
            "code": EMAIL_CODE,
            "redemption_verifier": VERIFIER,
        },
    )
    assert right.status_code in {401, 429}
    assert await _session_count(user) == (0, 0)
    async with SessionFactory() as db:
        failures = await db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.actor_user_id == user.id,
                AuditEvent.action == "MFA_LOGIN_FAILED",
                AuditEvent.target_type == "native_mfa",
            )
        )
    assert failures == 10
