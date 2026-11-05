"""Database-backed Google callback, recovery and registration coverage."""

import asyncio
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_mobile_auth import ORIGIN, PASSWORD, csrf_header, register_and_verify

from mykhaya.db import SessionFactory
from mykhaya.google_auth import GoogleFlowState, GooglePendingIdentity
from mykhaya.main import app
from mykhaya.models import AuditEvent, ExternalIdentity, ExternalIdentityProvider, User
from mykhaya.routers import auth as auth_router


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
def fake_google_callback(monkeypatch: pytest.MonkeyPatch):
    pending: dict[str, GooglePendingIdentity] = {}
    subject = f"google-recovery-{uuid4().hex}"
    provider_email = f"google-{uuid4().hex}@example.com"

    async def consume_flow_state(_settings, _state: str) -> GoogleFlowState:
        return GoogleFlowState(
            nonce="nonce", code_verifier="verifier", intent="login", user_id=None, return_path=None
        )

    async def exchange_code(_settings, _code: str, _verifier: str) -> str:
        return "verified-id-token"

    async def verify_identity_token(_settings, _token: str, _nonce: str) -> dict[str, object]:
        return {
            "sub": subject,
            "email": provider_email,
            "email_verified": True,
            "name": "Google User",
        }

    async def store_pending(_settings, transaction_id: str, value: GooglePendingIdentity) -> None:
        pending[transaction_id] = value

    async def load_pending(_settings, transaction_id: str) -> GooglePendingIdentity | None:
        return pending.get(transaction_id)

    async def consume_pending(_settings, transaction_id: str) -> GooglePendingIdentity | None:
        return pending.pop(transaction_id, None)

    monkeypatch.setattr(auth_router, "consume_google_flow_state", consume_flow_state)
    monkeypatch.setattr(auth_router, "exchange_google_code", exchange_code)
    monkeypatch.setattr(auth_router, "verify_google_identity_token", verify_identity_token)
    monkeypatch.setattr(auth_router, "store_google_pending_identity", store_pending)
    monkeypatch.setattr(auth_router, "load_google_pending_identity", load_pending)
    monkeypatch.setattr(auth_router, "consume_google_pending_identity", consume_pending)
    return pending, subject, provider_email


@pytest.mark.asyncio
async def test_google_callback_requires_explicit_registration_and_creates_one_identity(
    client: AsyncClient, fake_google_callback
) -> None:
    pending, subject, provider_email = fake_google_callback
    callback = await client.get(
        "/api/v1/auth/google/callback?state=state&code=code", follow_redirects=False
    )
    assert callback.status_code == 303
    transaction = parse_qs(urlparse(callback.headers["location"]).query)["transaction"][0]
    options = await client.get(f"/api/v1/auth/google/recovery/options?transaction_id={transaction}")
    assert options.json()["can_register"] is True

    registered = await client.post(
        "/api/v1/auth/google/recovery/register", json={"transaction_id": transaction}
    )
    assert registered.status_code == 200, registered.text
    async with SessionFactory() as db:
        users = (await db.scalars(select(User).where(User.email == provider_email))).all()
        identities = (
            await db.scalars(
                select(ExternalIdentity).where(
                    ExternalIdentity.provider == ExternalIdentityProvider.google,
                    ExternalIdentity.provider_subject == subject,
                )
            )
        ).all()
        assert len(users) == 1
        assert len(identities) == 1
    assert pending == {}


@pytest.mark.asyncio
async def test_google_existing_account_links_only_after_password_authentication(
    client: AsyncClient, fake_google_callback
) -> None:
    pending, subject, provider_email = fake_google_callback
    await register_and_verify(client, provider_email, "Existing Google User")
    callback = await client.get(
        "/api/v1/auth/google/callback?state=state&code=code", follow_redirects=False
    )
    transaction = parse_qs(urlparse(callback.headers["location"]).query)["transaction"][0]
    options = await client.get(f"/api/v1/auth/google/recovery/options?transaction_id={transaction}")
    assert options.json()["can_register"] is False

    login = await client.post(
        "/api/v1/auth/login", json={"email": provider_email, "password": PASSWORD}
    )
    assert login.status_code == 200
    linked = await client.post(
        "/api/v1/auth/google/recovery/link",
        headers=csrf_header(client),
        json={"transaction_id": transaction},
    )
    assert linked.status_code == 200, linked.text
    async with SessionFactory() as db:
        identity = await db.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == ExternalIdentityProvider.google,
                ExternalIdentity.provider_subject == subject,
            )
        )
        user = await db.scalar(select(User).where(User.email == provider_email))
        assert identity is not None and user is not None
        assert identity.user_id == user.id
    assert pending == {}


@pytest.mark.asyncio
async def test_google_link_rejects_wrong_user_without_consuming_transaction(
    client: AsyncClient, fake_google_callback
) -> None:
    pending, subject, provider_email = fake_google_callback
    await register_and_verify(client, provider_email, "Correct Google User")
    wrong_email = f"wrong-{uuid4().hex}@example.com"
    await register_and_verify(client, wrong_email, "Wrong User")
    callback = await client.get(
        "/api/v1/auth/google/callback?state=state&code=code", follow_redirects=False
    )
    transaction = parse_qs(urlparse(callback.headers["location"]).query)["transaction"][0]

    async with SessionFactory() as db:
        correct_user = await db.scalar(select(User).where(User.email == provider_email))
        assert correct_user is not None

    wrong_login = await client.post(
        "/api/v1/auth/login", json={"email": wrong_email, "password": PASSWORD}
    )
    assert wrong_login.status_code == 200
    rejected = await client.post(
        "/api/v1/auth/google/recovery/link",
        headers=csrf_header(client),
        json={"transaction_id": transaction},
    )
    assert rejected.status_code == 403
    assert transaction in pending
    async with SessionFactory() as db:
        wrong_user = await db.scalar(select(User).where(User.email == wrong_email))
        assert wrong_user is not None
        wrong_events = (
            await db.scalars(
                select(AuditEvent).where(AuditEvent.actor_user_id == wrong_user.id)
            )
        ).all()
        assert "GOOGLE_IDENTITY_LINKED" not in [event.action for event in wrong_events]

    correct_login = await client.post(
        "/api/v1/auth/login", json={"email": provider_email, "password": PASSWORD}
    )
    assert correct_login.status_code == 200
    linked = await client.post(
        "/api/v1/auth/google/recovery/link",
        headers=csrf_header(client),
        json={"transaction_id": transaction},
    )
    assert linked.status_code == 200, linked.text
    assert pending == {}

    async with SessionFactory() as db:
        identity = await db.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == ExternalIdentityProvider.google,
                ExternalIdentity.provider_subject == subject,
            )
        )
        events = (
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "GOOGLE_IDENTITY_LINKED")
            )
        ).all()
        assert identity is not None
        assert identity.user_id == correct_user.id
        assert events


@pytest.mark.asyncio
async def test_google_recovery_replay_is_rejected_after_successful_link(
    client: AsyncClient, fake_google_callback
) -> None:
    pending, _subject, provider_email = fake_google_callback
    await register_and_verify(client, provider_email, "Replay Google User")
    callback = await client.get(
        "/api/v1/auth/google/callback?state=state&code=code", follow_redirects=False
    )
    transaction = parse_qs(urlparse(callback.headers["location"]).query)["transaction"][0]
    login = await client.post(
        "/api/v1/auth/login", json={"email": provider_email, "password": PASSWORD}
    )
    assert login.status_code == 200
    first = await client.post(
        "/api/v1/auth/google/recovery/link",
        headers=csrf_header(client),
        json={"transaction_id": transaction},
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/v1/auth/google/recovery/link",
        headers=csrf_header(client),
        json={"transaction_id": transaction},
    )
    assert second.status_code == 400
    assert pending == {}


@pytest.mark.asyncio
async def test_concurrent_google_claims_are_single_use(
    client: AsyncClient, fake_google_callback
) -> None:
    pending, subject, provider_email = fake_google_callback
    await register_and_verify(client, provider_email, "Concurrent Google User")
    second_client = AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )
    try:
        first_login = await client.post(
            "/api/v1/auth/login", json={"email": provider_email, "password": PASSWORD}
        )
        second_login = await second_client.post(
            "/api/v1/auth/login", json={"email": provider_email, "password": PASSWORD}
        )
        assert first_login.status_code == 200
        assert second_login.status_code == 200
        transaction = "google-concurrent-transaction-1234567890"
        pending[transaction] = GooglePendingIdentity(
            transaction_id=transaction,
            subject=subject,
            provider_email=provider_email,
            email_verified=True,
            display_name="Concurrent Google User",
            can_register=False,
            return_path=None,
        )
        results = await asyncio.gather(
            client.post(
                "/api/v1/auth/google/recovery/link",
                headers=csrf_header(client),
                json={"transaction_id": transaction},
            ),
            second_client.post(
                "/api/v1/auth/google/recovery/link",
                headers=csrf_header(second_client),
                json={"transaction_id": transaction},
            ),
        )
        assert sorted(response.status_code for response in results) == [200, 400]
        assert pending == {}
    finally:
        await second_client.aclose()


@pytest.mark.asyncio
async def test_google_recovery_transaction_is_single_use(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/google/recovery/options?transaction_id=expired-google-transaction"
    )
    assert response.status_code == 400
