"""Database-backed regressions for native external authentication."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from test_mobile_auth import ORIGIN, PASSWORD, bearer, register_and_verify

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.external_identities import (
    ExternalIdentityOwnershipConflict,
    link_external_identity,
)
from mykhaya.main import app
from mykhaya.models import ExternalIdentity, ExternalIdentityProvider, User
from mykhaya.native_external_auth import NativeExternalPendingIdentity, NativeExternalTransaction
from mykhaya.routers import auth as auth_router


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
def native_settings():
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


@pytest.mark.asyncio
async def test_native_link_is_explicit_and_single_use(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = "v" * 64
    email = f"native-link-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    await register_and_verify(client, email, "Native Link User")
    login = await client.post(
        "/api/v1/auth/mobile/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    token = login.json()["session_token"]

    async def verify(_settings, _token, _nonce, _audience=None):
        assert _audience == native_settings.apple_native_client_id
        return {
            "sub": "native-link-subject",
            "email": "relay@privaterelay.appleid.com",
            "email_verified": True,
        }

    monkeypatch.setattr(auth_router, "verify_identity_token", verify)
    started = await client.post(
        "/api/v1/auth/mobile/external/start",
        headers=bearer(token),
        json={
            "provider": "apple",
            "intent": "link",
            "platform": "ios",
            "redemption_verifier": verifier,
        },
    )
    assert started.status_code == 200, started.text
    exchanged = await client.post(
        "/api/v1/auth/mobile/external/exchange",
        headers=bearer(token),
        json={
            "transaction_id": started.json()["transaction_id"],
            "identity_token": "synthetic-identity-token-12345",
            "redemption_verifier": verifier,
        },
    )
    assert exchanged.status_code == 200, exchanged.text

    replay = await client.post(
        "/api/v1/auth/mobile/external/exchange",
        headers=bearer(token),
        json={
            "transaction_id": started.json()["transaction_id"],
            "identity_token": "synthetic-identity-token-12345",
            "redemption_verifier": verifier,
        },
    )
    assert replay.status_code == 400
    async with SessionFactory() as db:
        identities = await db.scalar(
            select(func.count())
            .select_from(ExternalIdentity)
            .where(ExternalIdentity.provider_subject == "native-link-subject")
        )
        assert identities == 1


@pytest.mark.asyncio
async def test_native_new_registration_creates_one_user_after_explicit_choice(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = "v" * 64
    subject = f"native-register-{uuid4().hex}"

    async def verify(_settings, _token, _nonce, _audience=None):
        return {"sub": subject, "email": f"new-{subject}@example.com", "email_verified": True}

    monkeypatch.setattr(auth_router, "verify_identity_token", verify)
    before = await client.post(
        "/api/v1/auth/mobile/external/start",
        json={
            "provider": "apple",
            "intent": "login",
            "platform": "ios",
            "redemption_verifier": verifier,
        },
    )
    exchanged = await client.post(
        "/api/v1/auth/mobile/external/exchange",
        json={
            "transaction_id": before.json()["transaction_id"],
            "identity_token": "synthetic-identity-token-12345",
            "redemption_verifier": verifier,
        },
    )
    assert exchanged.status_code == 200
    recovery = exchanged.json()
    assert recovery["authentication_state"] == "account_choice"

    registered = await client.post(
        "/api/v1/auth/mobile/external/recovery/register",
        json={
            "transaction_id": recovery["transaction_id"],
            "display_name": "Native New User",
            "legal_acceptances": [],
            "platform": "ios",
            "redemption_verifier": verifier,
        },
    )
    assert registered.status_code == 200, registered.text
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == f"new-{subject}@example.com"))
        identity = await db.scalar(
            select(ExternalIdentity).where(ExternalIdentity.provider_subject == subject)
        )
        assert user is not None
        assert identity is not None


@pytest.mark.asyncio
async def test_concurrent_native_claims_leave_one_provider_owner() -> None:
    """Two users racing to claim one provider subject: exactly one wins.

    The loser is rejected either by the ownership check (it observed the
    winner's committed row) or by the unique constraint (both inserted); the
    timing decides which, and both are correct. The subject is unique per run
    so the test does not depend on database state from earlier runs."""
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    subject = f"concurrent-native-subject-{uuid4().hex}"
    first = User(email=f"race-a-{uuid4().hex}@example.com", display_name="Race A")
    second = User(email=f"race-b-{uuid4().hex}@example.com", display_name="Race B")
    async with SessionFactory() as db:
        db.add_all([first, second])
        await db.commit()
        first_id, second_id = first.id, second.id

    async def claim(user_id):
        async with SessionFactory() as db:
            try:
                await link_external_identity(
                    db,
                    request,
                    user_id=user_id,
                    provider=ExternalIdentityProvider.apple,
                    provider_subject=subject,
                    provider_email="relay@privaterelay.appleid.com",
                    provider_email_verified=True,
                )
                await db.commit()
                return True
            except (IntegrityError, ExternalIdentityOwnershipConflict):
                await db.rollback()
                return False

    results = await asyncio.gather(claim(first_id), claim(second_id))
    assert sorted(results) == [False, True]
    async with SessionFactory() as db:
        owners = await db.scalars(
            select(ExternalIdentity).where(ExternalIdentity.provider_subject == subject)
        )
        assert len(owners.all()) == 1


@pytest.mark.asyncio
async def test_native_transaction_rejects_cross_environment_redemption(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = "v" * 64
    started = await client.post(
        "/api/v1/auth/mobile/external/start",
        json={
            "provider": "apple",
            "intent": "login",
            "platform": "ios",
            "redemption_verifier": verifier,
        },
    )
    assert started.status_code == 200
    transaction = NativeExternalTransaction(
        transaction_id=started.json()["transaction_id"],
        provider=ExternalIdentityProvider.apple,
        nonce="nonce",
        client_nonce="",
        client_id="app.mykhaya.dev",
        environment="production",
        intent="login",
        user_id=None,
        platform="ios",
        redemption_verifier_hash="wrong-hash",
    )

    async def consume(_settings, _transaction_id):
        return transaction

    monkeypatch.setattr(auth_router, "consume_native_external_transaction", consume)
    verify_called = False

    async def verify(*_args, **_kwargs):
        nonlocal verify_called
        verify_called = True
        return {"sub": "should-not-be-accepted"}

    monkeypatch.setattr(auth_router, "verify_identity_token", verify)
    exchanged = await client.post(
        "/api/v1/auth/mobile/external/exchange",
        json={
            "transaction_id": transaction.transaction_id,
            "identity_token": "synthetic-identity-token-12345",
            "redemption_verifier": verifier,
        },
    )
    assert exchanged.status_code == 400
    assert verify_called is False


def test_native_browser_callback_mapping_is_explicit(native_settings) -> None:
    assert (
        auth_router._native_browser_return_uri(
            native_settings, ExternalIdentityProvider.apple, "android"
        )
        == native_settings.native_apple_return_uri
    )
    assert (
        auth_router._native_browser_return_uri(
            native_settings, ExternalIdentityProvider.google, "ios"
        )
        == native_settings.native_google_return_uri
    )
    with pytest.raises(HTTPException):
        auth_router._native_browser_return_uri(
            native_settings, ExternalIdentityProvider.apple, "ios"
        )


@pytest.mark.asyncio
async def test_native_exchange_rejects_wrong_redemption_verifier_before_provider_validation(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = await client.post(
        "/api/v1/auth/mobile/external/start",
        json={
            "provider": "apple",
            "intent": "login",
            "platform": "ios",
            "redemption_verifier": "v" * 64,
        },
    )
    assert started.status_code == 200, started.text
    verify_called = False

    async def verify(*_args, **_kwargs):
        nonlocal verify_called
        verify_called = True
        return {"sub": "must-not-be-reached"}

    monkeypatch.setattr(auth_router, "verify_identity_token", verify)
    exchanged = await client.post(
        "/api/v1/auth/mobile/external/exchange",
        json={
            "transaction_id": started.json()["transaction_id"],
            "identity_token": "synthetic-identity-token-12345",
            "redemption_verifier": "w" * 64,
        },
    )
    assert exchanged.status_code == 400
    assert verify_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("intended_user_id", [None, "not-a-user-id"])
async def test_native_link_rejects_missing_or_malformed_intended_user_binding(
    client: AsyncClient,
    native_settings,
    monkeypatch: pytest.MonkeyPatch,
    intended_user_id: str | None,
) -> None:
    email = f"native-binding-{uuid4().hex}@example.com"
    await register_and_verify(client, email, "Native Binding User")
    login = await client.post(
        "/api/v1/auth/mobile/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    token = login.json()["session_token"]
    pending = NativeExternalPendingIdentity(
        transaction_id="binding-test-transaction",
        provider=ExternalIdentityProvider.apple,
        subject="binding-test-subject",
        provider_email="relay@privaterelay.appleid.com",
        email_verified=True,
        display_name="Binding Test",
        can_register=False,
        platform="ios",
        redemption_verifier_hash=auth_router.hash_redemption_verifier("v" * 64),
        intended_user_id=intended_user_id,
        intent="link",
    )

    async def load_pending(_settings, _transaction_id):
        return pending

    monkeypatch.setattr(auth_router, "load_native_external_pending", load_pending)
    response = await client.post(
        "/api/v1/auth/mobile/external/recovery/link",
        headers=bearer(token),
        json={"transaction_id": pending.transaction_id, "redemption_verifier": "v" * 64},
    )
    assert response.status_code in {400, 403}
