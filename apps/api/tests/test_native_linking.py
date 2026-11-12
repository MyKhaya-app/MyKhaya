"""Native provider linking binds to the account that started it.

These tests use the real Redis-backed sign-in records (no monkeypatched
load/consume), because the defect they guard against was in the loader
itself: it dropped `intent` and `intended_user_id`, which disabled every
link check that depends on them.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from starlette.requests import Request
from test_mobile_auth import ORIGIN, PASSWORD, bearer, register_and_verify

from mykhaya.apple_auth import AppleFlowState
from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.external_identities import link_external_identity
from mykhaya.main import app
from mykhaya.models import ExternalIdentity, ExternalIdentityProvider, Session, User
from mykhaya.native_external_auth import (
    NativeExternalPendingIdentity,
    consume_native_external_pending,
    hash_redemption_verifier,
    load_native_external_pending,
    store_native_external_pending,
)
from mykhaya.routers import auth as auth_router

VERIFIER = "v" * 64
ALREADY_LINKED = "That Apple account is already linked to another MyKhaya account."


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
def native_settings() -> Iterator[Settings]:
    settings = get_settings().model_copy(
        update={
            "apple_sign_in_enabled": True,
            "apple_native_client_id": "app.mykhaya.dev",
            "google_sign_in_enabled": True,
            "google_native_client_id": "1234567890-native.apps.googleusercontent.com",
            "native_apple_return_uri": "app.mykhaya.mobile://auth/callback",
            "native_google_return_uri": "mykhaya://auth/callback",
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


async def signed_in_user(client: AsyncClient, label: str) -> tuple[str, str]:
    """A verified adult with a fresh native (bearer) session: (user id, token)."""
    email = f"native-link-{label}-{uuid4().hex}@example.com"
    await register_and_verify(client, email, f"Native Link {label}")
    login = await client.post(
        "/api/v1/auth/mobile/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    token = login.json()["session_token"]
    me = await client.get("/api/v1/users/me", headers=bearer(token))
    assert me.status_code == 200
    return str(me.json()["id"]), token


async def store_link_pending(
    settings: Settings, *, intended_user_id: str | None, subject: str | None = None
) -> NativeExternalPendingIdentity:
    """What the native Apple/Google browser callback stores for a link request."""
    pending = NativeExternalPendingIdentity(
        transaction_id=f"native-link-tx-{uuid4().hex}",
        provider=ExternalIdentityProvider.apple,
        subject=subject or f"native-link-subject-{uuid4().hex}",
        provider_email=f"relay-{uuid4().hex}@privaterelay.appleid.com",
        email_verified=True,
        display_name="Linked Person",
        can_register=False,
        platform="android",
        redemption_verifier_hash=hash_redemption_verifier(VERIFIER),
        intended_user_id=intended_user_id,
        intent="link",
    )
    await store_native_external_pending(settings, pending)
    return pending


async def owner_of(subject: str) -> str | None:
    async with SessionFactory() as db:
        identity = await db.scalar(
            select(ExternalIdentity).where(ExternalIdentity.provider_subject == subject)
        )
        return str(identity.user_id) if identity is not None else None


async def redeem(client: AsyncClient, transaction_id: str, token: str | None = None):
    return await client.post(
        "/api/v1/auth/mobile/external/redeem",
        headers=bearer(token) if token else {},
        json={"transaction_id": transaction_id, "redemption_verifier": VERIFIER},
    )


@pytest.mark.asyncio
async def test_load_and_consume_read_back_every_stored_field(native_settings) -> None:
    pending = NativeExternalPendingIdentity(
        transaction_id=f"native-parse-{uuid4().hex}",
        provider=ExternalIdentityProvider.google,
        subject=f"native-parse-subject-{uuid4().hex}",
        provider_email="person@example.com",
        email_verified=True,
        display_name="Parsed Person",
        can_register=True,
        platform="ios",
        redemption_verifier_hash=hash_redemption_verifier(VERIFIER),
        intended_user_id=str(uuid4()),
        intent="link",
        beta=True,
        beta_invitation_hash="a" * 64,
    )
    await store_native_external_pending(native_settings, pending)
    assert await load_native_external_pending(native_settings, pending.transaction_id) == pending
    assert await consume_native_external_pending(native_settings, pending.transaction_id) == pending
    assert await load_native_external_pending(native_settings, pending.transaction_id) is None


@pytest.mark.asyncio
async def test_browser_link_links_the_account_that_started_it(
    client: AsyncClient, native_settings
) -> None:
    user_a, token_a = await signed_in_user(client, "a")
    pending = await store_link_pending(native_settings, intended_user_id=user_a)
    response = await redeem(client, pending.transaction_id, token_a)
    assert response.status_code == 200, response.text
    assert "session_token" not in response.json()
    assert await owner_of(pending.subject) == user_a
    # Single use.
    assert await load_native_external_pending(native_settings, pending.transaction_id) is None


@pytest.mark.asyncio
async def test_browser_link_rejects_another_signed_in_user(
    client: AsyncClient, native_settings
) -> None:
    user_a, _token_a = await signed_in_user(client, "a")
    _user_b, token_b = await signed_in_user(client, "b")
    pending = await store_link_pending(native_settings, intended_user_id=user_a)
    response = await redeem(client, pending.transaction_id, token_b)
    assert response.status_code == 403
    assert await owner_of(pending.subject) is None


@pytest.mark.asyncio
async def test_browser_link_requires_a_session(client: AsyncClient, native_settings) -> None:
    user_a, _token_a = await signed_in_user(client, "a")
    pending = await store_link_pending(native_settings, intended_user_id=user_a)
    response = await redeem(client, pending.transaction_id)
    assert response.status_code == 401
    assert "session_token" not in response.text
    assert await owner_of(pending.subject) is None


@pytest.mark.asyncio
async def test_link_request_without_a_bound_user_is_rejected(
    client: AsyncClient, native_settings
) -> None:
    _user_a, token_a = await signed_in_user(client, "a")
    pending = await store_link_pending(native_settings, intended_user_id=None)
    response = await redeem(client, pending.transaction_id, token_a)
    assert response.status_code == 400
    assert await owner_of(pending.subject) is None


@pytest.mark.asyncio
async def test_shared_device_link_never_issues_the_owners_session(
    client: AsyncClient, native_settings
) -> None:
    """User A starts a link on a shared phone but authenticates in the browser
    with a provider account that already belongs to user X. Redeeming must
    refuse (409), must not issue X a session, and must leave A signed in."""
    user_a, token_a = await signed_in_user(client, "a")
    user_x, _token_x = await signed_in_user(client, "x")
    subject = f"native-link-owned-{uuid4().hex}"
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    async with SessionFactory() as db:
        await link_external_identity(
            db,
            request,
            user_id=UUID(user_x),
            provider=ExternalIdentityProvider.apple,
            provider_subject=subject,
            provider_email="owner@privaterelay.appleid.com",
            provider_email_verified=True,
        )
        await db.commit()

    async def sessions_for(user_id: str) -> int:
        async with SessionFactory() as db:
            return int(
                await db.scalar(
                    select(func.count()).select_from(Session).where(Session.user_id == user_id)
                )
                or 0
            )

    x_sessions_before = await sessions_for(user_x)
    pending = await store_link_pending(native_settings, intended_user_id=user_a, subject=subject)
    response = await redeem(client, pending.transaction_id, token_a)

    assert response.status_code == 409
    assert response.json()["detail"] == ALREADY_LINKED
    assert "session_token" not in response.text
    assert "device_token" not in response.text
    assert await sessions_for(user_x) == x_sessions_before
    assert await owner_of(subject) == user_x
    # A's session on the device is untouched and still A's.
    me = await client.get("/api/v1/users/me", headers=bearer(token_a))
    assert me.status_code == 200
    assert str(me.json()["id"]) == user_a
    # The refused attempt cannot be retried.
    assert await load_native_external_pending(native_settings, pending.transaction_id) is None


@pytest.mark.asyncio
async def test_recovery_link_enforces_the_starting_account(
    client: AsyncClient, native_settings
) -> None:
    user_a, _token_a = await signed_in_user(client, "a")
    _user_b, token_b = await signed_in_user(client, "b")
    pending = await store_link_pending(native_settings, intended_user_id=user_a)
    response = await client.post(
        "/api/v1/auth/mobile/external/recovery/link",
        headers=bearer(token_b),
        json={"transaction_id": pending.transaction_id, "redemption_verifier": VERIFIER},
    )
    assert response.status_code == 403
    assert await owner_of(pending.subject) is None


@pytest.mark.asyncio
async def test_recovery_register_rejects_a_link_request(
    client: AsyncClient, native_settings
) -> None:
    user_a, _token_a = await signed_in_user(client, "a")
    pending = await store_link_pending(native_settings, intended_user_id=user_a)
    response = await client.post(
        "/api/v1/auth/mobile/external/recovery/register",
        json={
            "transaction_id": pending.transaction_id,
            "display_name": "Should Not Exist",
            "legal_acceptances": [],
            "platform": "android",
            "redemption_verifier": VERIFIER,
        },
    )
    assert response.status_code == 409
    async with SessionFactory() as db:
        assert await db.scalar(select(User).where(User.email == pending.provider_email)) is None


@pytest.mark.asyncio
async def test_native_callback_never_offers_registration_for_a_link(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_a, _token_a = await signed_in_user(client, "a")
    subject = f"native-link-callback-{uuid4().hex}"
    transaction_id = f"native-link-callback-tx-{uuid4().hex}"
    flow = AppleFlowState(
        nonce="nonce",
        intent="link",
        user_id=user_a,
        return_path=None,
        native_return_uri=native_settings.native_apple_return_uri,
        native_platform="android",
        native_environment=native_settings.environment,
        native_transaction_id=transaction_id,
        native_redemption_verifier_hash=hash_redemption_verifier(VERIFIER),
    )

    async def consume_flow_state(_settings: Any, _state: str) -> AppleFlowState:
        return flow

    async def exchange_code(_settings: Any, _code: str) -> str:
        return "verified-id-token"

    async def verify(_settings: Any, _token: Any, _nonce: Any, _audience: Any = None):
        return {"sub": subject, "email": f"{subject}@example.com", "email_verified": True}

    monkeypatch.setattr(auth_router, "consume_flow_state", consume_flow_state)
    monkeypatch.setattr(auth_router, "exchange_code", exchange_code)
    monkeypatch.setattr(auth_router, "verify_identity_token", verify)
    callback = await client.post(
        "/api/v1/auth/apple/callback",
        data={"state": "state", "code": "code"},
        headers={"Origin": "https://appleid.apple.com"},
        follow_redirects=False,
    )
    assert callback.status_code == 303, callback.text
    pending = await load_native_external_pending(native_settings, transaction_id)
    assert pending is not None
    assert pending.intent == "link"
    assert pending.intended_user_id == user_a
    assert pending.can_register is False
