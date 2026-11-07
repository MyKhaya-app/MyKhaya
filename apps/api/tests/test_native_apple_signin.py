"""Native iOS Sign in with Apple: end-to-end regressions with real signatures.

Unlike test_native_external_auth.py (which stubs ``verify_identity_token``),
these tests sign genuine identity tokens and run them through the real
verifier, so they pin the native nonce contract shared with
apps/ios-shell/native/plugin/NativeExternalAuthPlugin.swift: the API returns a
raw nonce, the plugin hands Apple ``sha256(raw).hexdigest()``, and Apple echoes
that value in the token's ``nonce`` claim.
"""

import hashlib
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from structlog.testing import capture_logs
from test_apple_auth import FakeClient, FakeResponse, signed_token, signing_material
from test_mobile_auth import ORIGIN, PASSWORD, bearer, register_and_verify

from mykhaya import apple_auth
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import ExternalIdentity, User

DEV_BUNDLE_ID = "app.mykhaya.mobile"
PROD_BUNDLE_ID = "app.mykhaya.mobile.prod"
VERIFIER = "v" * 64


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
def dev_native_settings():
    settings = get_settings().model_copy(
        update={"apple_sign_in_enabled": True, "apple_native_client_id": DEV_BUNDLE_ID}
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def apple_keys(monkeypatch: pytest.MonkeyPatch) -> str:
    """Serve a test JWKS to apple_auth only; returns the matching private key."""
    private_pem, public_jwk = signing_material()
    monkeypatch.setattr(
        apple_auth,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda timeout: FakeClient(FakeResponse({"keys": [public_jwk]})),
            HTTPError=httpx.HTTPError,
        ),
    )
    return private_pem


def plugin_nonce(raw_nonce: str) -> str:
    """Exactly what NativeExternalAuthPlugin.swift sets as request.nonce."""
    return hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()


async def start(client: AsyncClient, request_id: str | None = None) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/mobile/external/start",
        headers={"X-Request-ID": request_id} if request_id else {},
        json={
            "provider": "apple",
            "intent": "login",
            "platform": "ios",
            "redemption_verifier": VERIFIER,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["client_id"] == DEV_BUNDLE_ID
    return body


async def exchange(
    client: AsyncClient, transaction_id: str, token: str, request_id: str | None = None
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/mobile/external/exchange",
        headers={"X-Request-ID": request_id} if request_id else {},
        json={
            "transaction_id": transaction_id,
            "identity_token": token,
            "redemption_verifier": VERIFIER,
        },
    )


async def link_apple(client: AsyncClient, email: str, subject: str, private_pem: str) -> str:
    """Create an account and link an Apple subject via the native link flow."""
    await register_and_verify(client, email, "Native Apple User")
    login = await client.post(
        "/api/v1/auth/mobile/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    session = login.json()["session_token"]
    started = await client.post(
        "/api/v1/auth/mobile/external/start",
        headers=bearer(session),
        json={
            "provider": "apple",
            "intent": "link",
            "platform": "ios",
            "redemption_verifier": VERIFIER,
        },
    )
    assert started.status_code == 200, started.text
    token = signed_token(
        private_pem, aud=DEV_BUNDLE_ID, sub=subject, nonce=plugin_nonce(started.json()["nonce"])
    )
    linked = await client.post(
        "/api/v1/auth/mobile/external/exchange",
        headers=bearer(session),
        json={
            "transaction_id": started.json()["transaction_id"],
            "identity_token": token,
            "redemption_verifier": VERIFIER,
        },
    )
    assert linked.status_code == 200, linked.text
    assert "linked" in linked.json()["message"]
    return session


@pytest.mark.asyncio
async def test_native_apple_signs_in_linked_account_and_session_persists_until_logout(
    client: AsyncClient, dev_native_settings, apple_keys: str
) -> None:
    subject = f"native-apple-{uuid4().hex}"
    email = f"native-apple-{uuid4().hex}@example.com"
    await link_apple(client, email, subject, apple_keys)

    started = await start(client)
    token = signed_token(
        apple_keys,
        aud=DEV_BUNDLE_ID,
        sub=subject,
        nonce=plugin_nonce(started["nonce"]),
        email="relay@privaterelay.appleid.com",
    )
    signed_in = await exchange(client, started["transaction_id"], token)
    assert signed_in.status_code == 200, signed_in.text
    body = signed_in.json()
    assert body["email"] == email
    assert body["session_token"] and body["device_token"]
    assert signed_in.headers["cache-control"] == "no-store"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as device:
        me = await device.get("/api/v1/users/me", headers=bearer(body["session_token"]))
        assert me.status_code == 200
        assert me.json()["email"] == email
        logout = await device.post(
            "/api/v1/auth/mobile/logout", headers=bearer(body["session_token"])
        )
        assert logout.status_code == 204
        denied = await device.get("/api/v1/users/me", headers=bearer(body["session_token"]))
        assert denied.status_code == 401

    async with SessionFactory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ExternalIdentity)
                .where(ExternalIdentity.provider_subject == subject)
            )
            == 1
        )
        assert (
            await db.scalar(select(func.count()).select_from(User).where(User.email == email)) == 1
        )


@pytest.mark.asyncio
async def test_native_apple_exchange_cannot_be_replayed(
    client: AsyncClient, dev_native_settings, apple_keys: str
) -> None:
    subject = f"native-replay-{uuid4().hex}"
    await link_apple(client, f"native-replay-{uuid4().hex}@example.com", subject, apple_keys)
    started = await start(client)
    token = signed_token(
        apple_keys, aud=DEV_BUNDLE_ID, sub=subject, nonce=plugin_nonce(started["nonce"])
    )
    first = await exchange(client, started["transaction_id"], token)
    assert first.status_code == 200, first.text

    with capture_logs() as logs:
        replay = await exchange(client, started["transaction_id"], token, "nauth-replay")
    assert replay.status_code == 400
    assert replay.json()["detail"] == "This sign-in attempt is invalid or has expired."
    failure = next(entry for entry in logs if entry["event"] == "native_external_auth_failed")
    assert failure["category"] == "transaction_missing_expired_or_replayed"
    assert failure["request_id"] == "nauth-replay"


@pytest.mark.asyncio
async def test_matching_email_never_auto_links_an_existing_account(
    client: AsyncClient, dev_native_settings, apple_keys: str
) -> None:
    """An Apple identity whose verified email equals an existing account's email
    must not sign into that account: the person has to choose explicitly."""
    email = f"native-existing-{uuid4().hex}@example.com"
    await register_and_verify(client, email, "Existing Password User")
    subject = f"native-unlinked-{uuid4().hex}"
    started = await start(client)
    token = signed_token(
        apple_keys,
        aud=DEV_BUNDLE_ID,
        sub=subject,
        nonce=plugin_nonce(started["nonce"]),
        email=email,
        email_verified=True,
    )
    result = await exchange(client, started["transaction_id"], token)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["authentication_state"] == "account_choice"
    assert "session_token" not in body
    async with SessionFactory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ExternalIdentity)
                .where(ExternalIdentity.provider_subject == subject)
            )
            == 0
        )
        assert (
            await db.scalar(select(func.count()).select_from(User).where(User.email == email)) == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        # The raw nonce (not the plugin's SHA-256) must never satisfy the check.
        ({"nonce": "RAW"}, "nonce_mismatch"),
        ({"nonce": "0" * 64}, "nonce_mismatch"),
        # DEV/PROD isolation: a PROD app's assertion is rejected by DEV.
        ({"aud": PROD_BUNDLE_ID}, "audience_mismatch"),
        # The web Services ID is not the native audience.
        ({"aud": "app.mykhaya.auth.dev"}, "audience_mismatch"),
        ({"iss": "https://evil.example"}, "issuer_mismatch"),
        ({"exp": 1}, "token_expired"),
    ],
)
async def test_invalid_native_apple_assertions_are_rejected_with_safe_diagnostics(
    client: AsyncClient,
    dev_native_settings,
    apple_keys: str,
    claims: dict[str, Any],
    reason: str,
) -> None:
    started = await start(client)
    values = {"aud": DEV_BUNDLE_ID, "nonce": plugin_nonce(started["nonce"]), **claims}
    if values["nonce"] == "RAW":
        values["nonce"] = started["nonce"]
    token = signed_token(apple_keys, sub=f"native-invalid-{uuid4().hex}", **values)

    with capture_logs() as logs:
        result = await exchange(client, started["transaction_id"], token, "nauth-invalid")
    assert result.status_code == 400
    assert result.json()["detail"] == "The provider sign-in could not be verified."
    failure = next(entry for entry in logs if entry["event"] == "native_external_auth_failed")
    assert failure["category"] == "provider_token_rejected"
    assert failure["reason"] == reason
    assert failure["request_id"] == "nauth-invalid"
    logged = repr(logs)
    assert token not in logged
    assert started["nonce"] not in logged
    assert started["transaction_id"] not in logged


@pytest.mark.asyncio
async def test_forged_native_apple_assertion_is_rejected(
    client: AsyncClient, dev_native_settings, apple_keys: str
) -> None:
    other_key, _ = signing_material()
    started = await start(client)
    forged = signed_token(
        other_key, aud=DEV_BUNDLE_ID, nonce=plugin_nonce(started["nonce"]), sub="forged"
    )
    with capture_logs() as logs:
        result = await exchange(client, started["transaction_id"], forged)
    assert result.status_code == 400
    failure = next(entry for entry in logs if entry["event"] == "native_external_auth_failed")
    assert failure["reason"] == "token_signature_or_claims_invalid"


@pytest.mark.asyncio
async def test_native_apple_start_reports_missing_native_client_id(
    client: AsyncClient,
) -> None:
    settings = get_settings().model_copy(
        update={"apple_sign_in_enabled": True, "apple_native_client_id": None}
    )
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with capture_logs() as logs:
            response = await client.post(
                "/api/v1/auth/mobile/external/start",
                json={
                    "provider": "apple",
                    "intent": "login",
                    "platform": "ios",
                    "redemption_verifier": VERIFIER,
                },
            )
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert response.status_code == 503
    failure = next(entry for entry in logs if entry["event"] == "native_external_auth_failed")
    assert failure["category"] == "native_client_id_not_configured"
