"""Database-backed regressions for native external authentication."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from test_mobile_auth import ORIGIN, PASSWORD, bearer, register_and_verify

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.external_identities import link_external_identity
from mykhaya.main import app
from mykhaya.models import ExternalIdentity, ExternalIdentityProvider, User
from mykhaya.native_external_auth import NativeExternalTransaction
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
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_native_link_is_explicit_and_single_use(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        json={"provider": "apple", "intent": "link", "platform": "ios"},
    )
    assert started.status_code == 200, started.text
    exchanged = await client.post(
        "/api/v1/auth/mobile/external/exchange",
        headers=bearer(token),
        json={
            "transaction_id": started.json()["transaction_id"],
            "identity_token": "synthetic-identity-token-12345",
        },
    )
    assert exchanged.status_code == 200, exchanged.text

    replay = await client.post(
        "/api/v1/auth/mobile/external/exchange",
        headers=bearer(token),
        json={
            "transaction_id": started.json()["transaction_id"],
            "identity_token": "synthetic-identity-token-12345",
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
    subject = f"native-register-{uuid4().hex}"

    async def verify(_settings, _token, _nonce, _audience=None):
        return {"sub": subject, "email": f"new-{subject}@example.com", "email_verified": True}

    monkeypatch.setattr(auth_router, "verify_identity_token", verify)
    before = await client.post(
        "/api/v1/auth/mobile/external/start",
        json={"provider": "apple", "intent": "login", "platform": "ios"},
    )
    exchanged = await client.post(
        "/api/v1/auth/mobile/external/exchange",
        json={
            "transaction_id": before.json()["transaction_id"],
            "identity_token": "synthetic-identity-token-12345",
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
        },
    )
    assert registered.status_code == 200, registered.text
    async with SessionFactory() as db:
        user = await db.scalar(
            select(User).where(User.email == f"new-{subject}@example.com")
        )
        identity = await db.scalar(
            select(ExternalIdentity).where(ExternalIdentity.provider_subject == subject)
        )
        assert user is not None
        assert identity is not None


@pytest.mark.asyncio
async def test_concurrent_native_claims_leave_one_provider_owner() -> None:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
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
                    provider_subject="concurrent-native-subject",
                    provider_email="relay@privaterelay.appleid.com",
                    provider_email_verified=True,
                )
                await db.commit()
                return True
            except IntegrityError:
                await db.rollback()
                return False

    results = await asyncio.gather(claim(first_id), claim(second_id))
    assert sorted(results) == [False, True]
    async with SessionFactory() as db:
        owners = await db.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.provider_subject == "concurrent-native-subject"
            )
        )
        assert len(owners.all()) == 1


@pytest.mark.asyncio
async def test_native_transaction_rejects_cross_environment_redemption(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = await client.post(
        "/api/v1/auth/mobile/external/start",
        json={"provider": "apple", "intent": "login", "platform": "ios"},
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
        },
    )
    assert exchanged.status_code == 400
    assert verify_called is False
