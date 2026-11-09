"""Database-backed Apple account-recovery and linking regressions."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_mobile_auth import ORIGIN, PASSWORD, csrf_header, register_and_verify

from mykhaya.apple_auth import AppleFlowState, ApplePendingIdentity
from mykhaya.db import SessionFactory
from mykhaya.google_auth import GooglePendingIdentity
from mykhaya.main import app
from mykhaya.models import (
    AuditEvent,
    BetaPendingRegistration,
    ExternalIdentity,
    ExternalIdentityProvider,
    Group,
    HomeSubscription,
    Membership,
    SignupMode,
    User,
)
from mykhaya.platform_runtime import SignupPolicy
from mykhaya.routers import auth as auth_router


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
def fake_apple_callback(monkeypatch: pytest.MonkeyPatch):
    pending: dict[str, ApplePendingIdentity] = {}
    subject = f"apple-recovery-{uuid4().hex}"
    provider_email = f"relay-{uuid4().hex}@privaterelay.appleid.com"

    async def consume_flow_state(_settings, _state: str) -> AppleFlowState:
        return AppleFlowState(nonce="nonce", intent="login", user_id=None, return_path=None)

    async def exchange_code(_settings, _code: str) -> str:
        return "verified-id-token"

    async def verify_identity_token(_settings, _token: str, _nonce: str) -> dict[str, object]:
        return {
            "sub": subject,
            "email": provider_email,
            "email_verified": True,
        }

    async def store_pending(_settings, transaction_id: str, value: ApplePendingIdentity) -> None:
        pending[transaction_id] = value

    async def load_pending(_settings, transaction_id: str) -> ApplePendingIdentity | None:
        return pending.get(transaction_id)

    async def consume_pending(_settings, transaction_id: str) -> ApplePendingIdentity | None:
        return pending.pop(transaction_id, None)

    monkeypatch.setattr(auth_router, "consume_flow_state", consume_flow_state)
    monkeypatch.setattr(auth_router, "exchange_code", exchange_code)
    monkeypatch.setattr(auth_router, "verify_identity_token", verify_identity_token)
    monkeypatch.setattr(auth_router, "store_pending_identity", store_pending)
    monkeypatch.setattr(auth_router, "load_pending_identity", load_pending)
    monkeypatch.setattr(auth_router, "consume_pending_identity", consume_pending)
    return pending, subject


@pytest.mark.asyncio
async def test_hide_my_email_requires_explicit_link_and_creates_no_duplicate_user(
    client: AsyncClient, fake_apple_callback
) -> None:
    _pending, subject = fake_apple_callback
    email = f"apple-existing-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    await register_and_verify(client, email, "Existing Apple User")
    async with SessionFactory() as db:
        before = await db.scalar(select(func.count()).select_from(User))

    callback = await client.post(
        "/api/v1/auth/apple/callback",
        data={
            "state": "state",
            "code": "code",
            "user": '{"name":{"firstName":"Apple","lastName":"User"}}',
        },
        headers={"Origin": "https://appleid.apple.com"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    location = callback.headers["location"]
    assert "apple=choose" in location
    transaction = parse_qs(urlparse(location).query)["transaction"][0]
    options = await client.get(f"/api/v1/auth/apple/recovery/options?transaction_id={transaction}")
    assert options.status_code == 200
    assert options.json()["can_register"] is True

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    linked = await client.post(
        "/api/v1/auth/apple/recovery/link",
        headers=csrf_header(client),
        json={"transaction_id": transaction},
    )
    assert linked.status_code == 200, linked.text
    methods = await client.get("/api/v1/auth/identities")
    assert methods.status_code == 200, methods.text
    assert methods.json()["password_available"] is True
    assert methods.json()["identities"][0]["provider"] == "apple"
    assert "provider_subject" not in methods.json()["identities"][0]

    async with SessionFactory() as db:
        after = await db.scalar(select(func.count()).select_from(User))
        identity = await db.scalar(
            select(ExternalIdentity).where(ExternalIdentity.provider_subject == subject)
        )
        user = await db.scalar(select(User).where(User.email == email))
        assert after == before
        assert identity is not None and user is not None and identity.user_id == user.id
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.actor_user_id == user.id))
        ).all()
        event_types = [event.action for event in events]
        assert "APPLE_IDENTITY_LINKED" in event_types
        assert "GOOGLE_IDENTITY_LINKED" not in event_types


@pytest.mark.asyncio
async def test_existing_apple_link_survives_cross_site_form_post_without_session_cookie(
    client: AsyncClient, fake_apple_callback, monkeypatch: pytest.MonkeyPatch
) -> None:
    pending, subject = fake_apple_callback
    email = f"apple-link-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    await register_and_verify(client, email, "Apple Link User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        user_id = str(user.id)

    async def consume_link_state(_settings, _state: str) -> AppleFlowState:
        return AppleFlowState(nonce="nonce", intent="link", user_id=user_id, return_path=None)

    monkeypatch.setattr(auth_router, "consume_flow_state", consume_link_state)
    callback_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": "https://appleid.apple.com"},
    )
    try:
        callback = await callback_client.post(
            "/api/v1/auth/apple/callback",
            data={"state": "state", "code": "code"},
            follow_redirects=False,
        )
    finally:
        await callback_client.aclose()
    assert callback.status_code == 303
    query = parse_qs(urlparse(callback.headers["location"]).query)
    assert query["apple"] == ["link_required"]
    transaction = query["transaction"][0]
    assert pending[transaction].intended_user_id == user_id

    linked = await client.post(
        "/api/v1/auth/apple/recovery/link",
        headers=csrf_header(client),
        json={"transaction_id": transaction},
    )
    assert linked.status_code == 200, linked.text
    async with SessionFactory() as db:
        identity = await db.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == ExternalIdentityProvider.apple,
                ExternalIdentity.provider_subject == subject,
            )
        )
        assert identity is not None and str(identity.user_id) == user_id


@pytest.mark.asyncio
async def test_explicit_new_apple_registration_creates_one_user_and_identity(
    client: AsyncClient, fake_apple_callback
) -> None:
    _pending, subject = fake_apple_callback
    callback = await client.get(
        "/api/v1/auth/apple/callback?state=state&code=code", follow_redirects=False
    )
    transaction = parse_qs(urlparse(callback.headers["location"]).query)["transaction"][0]
    provider_email = _pending[transaction].provider_email
    registered = await client.post(
        "/api/v1/auth/apple/recovery/register", json={"transaction_id": transaction}
    )
    assert registered.status_code == 200, registered.text
    async with SessionFactory() as db:
        users = (await db.scalars(select(User).where(User.email == provider_email))).all()
        identities = (
            await db.scalars(
                select(ExternalIdentity).where(
                    ExternalIdentity.provider == ExternalIdentityProvider.apple,
                    ExternalIdentity.provider_subject == subject,
                )
            )
        ).all()
        assert len(users) == 1
        assert len(identities) == 1


@pytest.mark.asyncio
async def test_exact_email_match_cannot_choose_new_apple_registration(
    client: AsyncClient, fake_apple_callback, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pending, subject = fake_apple_callback
    email = f"apple-existing-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    await register_and_verify(client, email, "Existing Relay User")

    async def verify_existing_email(_settings, _token: str, _nonce: str) -> dict[str, object]:
        return {
            "sub": subject,
            "email": email,
            "email_verified": True,
        }

    monkeypatch.setattr(auth_router, "verify_identity_token", verify_existing_email)
    callback = await client.get(
        "/api/v1/auth/apple/callback?state=state&code=code", follow_redirects=False
    )
    transaction = parse_qs(urlparse(callback.headers["location"]).query)["transaction"][0]
    options = await client.get(f"/api/v1/auth/apple/recovery/options?transaction_id={transaction}")
    assert options.json()["can_register"] is False
    rejected = await client.post(
        "/api/v1/auth/apple/recovery/register", json={"transaction_id": transaction}
    )
    assert rejected.status_code == 409


@pytest.mark.asyncio
async def test_apple_recovery_link_rejects_identity_owned_by_another_user(
    client: AsyncClient, fake_apple_callback
) -> None:
    _pending, subject = fake_apple_callback
    first = f"apple-owner-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    second = f"apple-other-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    await register_and_verify(client, first, "Apple Owner")
    async with SessionFactory() as db:
        owner = await db.scalar(select(User).where(User.email == first))
        assert owner is not None
        db.add(
            ExternalIdentity(
                user_id=owner.id,
                provider=ExternalIdentityProvider.apple,
                provider_subject=subject,
                provider_email="relay@privaterelay.appleid.com",
                provider_email_verified=True,
            )
        )
        await db.commit()
    await register_and_verify(client, second, "Apple Other")
    login = await client.post("/api/v1/auth/login", json={"email": second, "password": PASSWORD})
    assert login.status_code == 200
    transaction_id = "link-transaction-12345678901234567890"
    _pending[transaction_id] = ApplePendingIdentity(
        transaction_id=transaction_id,
        subject=subject,
        provider_email="relay@privaterelay.appleid.com",
        email_verified=True,
        display_name="Apple User",
        can_register=False,
        return_path=None,
    )
    rejected = await client.post(
        "/api/v1/auth/apple/recovery/link",
        headers=csrf_header(client),
        json={"transaction_id": transaction_id},
    )
    assert rejected.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_apple_claim_has_one_owner_and_preserves_tenancy(
    client: AsyncClient, fake_apple_callback
) -> None:
    pending, subject = fake_apple_callback
    first = f"apple-race-one-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    second = f"apple-race-two-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"
    await register_and_verify(client, first, "Apple Race One")

    second_client = AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )
    try:
        await register_and_verify(second_client, second, "Apple Race Two")
        first_login = await client.post(
            "/api/v1/auth/login", json={"email": first, "password": PASSWORD}
        )
        second_login = await second_client.post(
            "/api/v1/auth/login", json={"email": second, "password": PASSWORD}
        )
        assert first_login.status_code == 200
        assert second_login.status_code == 200

        async with SessionFactory() as db:
            before = {
                User: await db.scalar(select(func.count()).select_from(User)),
                Group: await db.scalar(select(func.count()).select_from(Group)),
                Membership: await db.scalar(select(func.count()).select_from(Membership)),
                HomeSubscription: await db.scalar(
                    select(func.count()).select_from(HomeSubscription)
                ),
            }

        tx_one = "apple-race-transaction-one-1234567890"
        tx_two = "apple-race-transaction-two-1234567890"
        pending[tx_one] = ApplePendingIdentity(
            transaction_id=tx_one,
            subject=subject,
            provider_email="relay-race@privaterelay.appleid.com",
            email_verified=True,
            display_name="Apple Race",
            can_register=False,
            return_path=None,
        )
        pending[tx_two] = ApplePendingIdentity(
            transaction_id=tx_two,
            subject=subject,
            provider_email="relay-race@privaterelay.appleid.com",
            email_verified=True,
            display_name="Apple Race",
            can_register=False,
            return_path=None,
        )
        results = await asyncio.gather(
            client.post(
                "/api/v1/auth/apple/recovery/link",
                headers=csrf_header(client),
                json={"transaction_id": tx_one},
            ),
            second_client.post(
                "/api/v1/auth/apple/recovery/link",
                headers=csrf_header(second_client),
                json={"transaction_id": tx_two},
            ),
        )
        assert sorted(response.status_code for response in results) == [200, 409]

        async with SessionFactory() as db:
            identities = (
                await db.scalars(
                    select(ExternalIdentity).where(
                        ExternalIdentity.provider == ExternalIdentityProvider.apple,
                        ExternalIdentity.provider_subject == subject,
                    )
                )
            ).all()
            assert len(identities) == 1
            assert identities[0].user_id in {
                await db.scalar(select(User.id).where(User.email == first)),
                await db.scalar(select(User.id).where(User.email == second)),
            }
            assert await db.scalar(select(func.count()).select_from(User)) == before[User]
            assert await db.scalar(select(func.count()).select_from(Group)) == before[Group]
            assert (
                await db.scalar(select(func.count()).select_from(Membership)) == before[Membership]
            )
            assert (
                await db.scalar(select(func.count()).select_from(HomeSubscription))
                == before[HomeSubscription]
            )
    finally:
        await second_client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider", [ExternalIdentityProvider.apple, ExternalIdentityProvider.google]
)
async def test_social_beta_rejects_disabled_beta_path(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, provider: ExternalIdentityProvider
) -> None:
    transaction = f"social-beta-disabled-{provider.value}-{uuid4().hex}"
    email = f"social-beta-{provider.value}-{uuid4().hex}@example.com"
    if provider is ExternalIdentityProvider.apple:
        pending = ApplePendingIdentity(
            transaction_id=transaction,
            subject=f"subject-{uuid4().hex}",
            provider_email=email,
            email_verified=True,
            display_name="Apple Beta User",
            can_register=True,
            return_path="/register?beta=1",
        )

        async def load_pending(*_args):
            return pending

        monkeypatch.setattr(auth_router, "load_pending_identity", load_pending)
        endpoint = "/api/v1/auth/apple/recovery/register"
    else:
        pending = GooglePendingIdentity(
            transaction_id=transaction,
            subject=f"subject-{uuid4().hex}",
            provider_email=email,
            email_verified=True,
            display_name="Google Beta User",
            can_register=True,
            return_path="/register?beta=1",
        )

        async def load_pending(*_args):
            return pending

        monkeypatch.setattr(auth_router, "load_google_pending_identity", load_pending)
        endpoint = "/api/v1/auth/google/recovery/register"

    async def policy(*_args, **_kwargs):
        return SignupPolicy(
            mode=SignupMode.normal,
            open=True,
            normal_path=True,
            beta_path=False,
            invitation_required=False,
            allowed_domains=(),
        )

    monkeypatch.setattr(auth_router, "evaluate_signup_policy", policy)
    response = await client.post(
        endpoint,
        json={
            "transaction_id": transaction,
            "beta": True,
            "beta_invitation_token": "i" * 40,
            "legal_acceptances": [],
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider", [ExternalIdentityProvider.apple, ExternalIdentityProvider.google]
)
async def test_social_beta_rejects_invalid_invitation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, provider: ExternalIdentityProvider
) -> None:
    transaction = f"social-beta-invite-{provider.value}-{uuid4().hex}"
    email = f"social-beta-invite-{provider.value}-{uuid4().hex}@example.com"
    if provider is ExternalIdentityProvider.apple:
        pending = ApplePendingIdentity(
            transaction_id=transaction,
            subject=f"subject-{uuid4().hex}",
            provider_email=email,
            email_verified=True,
            display_name="Apple Beta User",
            can_register=True,
            return_path="/register?beta=1",
        )

        async def load_pending(*_args):
            return pending

        monkeypatch.setattr(auth_router, "load_pending_identity", load_pending)
        endpoint = "/api/v1/auth/apple/recovery/register"
    else:
        pending = GooglePendingIdentity(
            transaction_id=transaction,
            subject=f"subject-{uuid4().hex}",
            provider_email=email,
            email_verified=True,
            display_name="Google Beta User",
            can_register=True,
            return_path="/register?beta=1",
        )

        async def load_pending(*_args):
            return pending

        monkeypatch.setattr(auth_router, "load_google_pending_identity", load_pending)
        endpoint = "/api/v1/auth/google/recovery/register"

    async def policy(*_args, **_kwargs):
        return SignupPolicy(
            mode=SignupMode.mixed,
            open=True,
            normal_path=True,
            beta_path=True,
            invitation_required=True,
            allowed_domains=(),
        )

    async def invalid_invitation(*_args, **_kwargs):
        return False

    monkeypatch.setattr(auth_router, "evaluate_signup_policy", policy)
    monkeypatch.setattr(auth_router, "beta_invitation_valid", invalid_invitation)
    response = await client.post(
        endpoint,
        json={
            "transaction_id": transaction,
            "beta": True,
            "beta_invitation_token": "i" * 40,
            "legal_acceptances": [],
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider", [ExternalIdentityProvider.apple, ExternalIdentityProvider.google]
)
async def test_social_beta_accepts_valid_invited_registration(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, provider: ExternalIdentityProvider
) -> None:
    transaction = f"social-beta-valid-{provider.value}-{uuid4().hex}"
    email = f"social-beta-valid-{provider.value}-{uuid4().hex}@example.com"
    subject = f"subject-{uuid4().hex}"
    if provider is ExternalIdentityProvider.apple:
        pending = ApplePendingIdentity(
            transaction_id=transaction,
            subject=subject,
            provider_email=email,
            email_verified=True,
            display_name="Apple Beta User",
            can_register=True,
            return_path="/register?beta=1",
        )

        async def load_pending(*_args):
            return pending

        async def consume_pending(*_args):
            return pending

        monkeypatch.setattr(auth_router, "load_pending_identity", load_pending)
        monkeypatch.setattr(auth_router, "consume_pending_identity", consume_pending)
        endpoint = "/api/v1/auth/apple/recovery/register"
    else:
        pending = GooglePendingIdentity(
            transaction_id=transaction,
            subject=subject,
            provider_email=email,
            email_verified=True,
            display_name="Google Beta User",
            can_register=True,
            return_path="/register?beta=1",
        )

        async def load_pending(*_args):
            return pending

        async def consume_pending(*_args):
            return pending

        monkeypatch.setattr(auth_router, "load_google_pending_identity", load_pending)
        monkeypatch.setattr(auth_router, "consume_google_pending_identity", consume_pending)
        endpoint = "/api/v1/auth/google/recovery/register"

    async def policy(*_args, **_kwargs):
        return SignupPolicy(
            mode=SignupMode.mixed,
            open=True,
            normal_path=True,
            beta_path=True,
            invitation_required=True,
            allowed_domains=(),
        )

    async def valid_invitation(*_args, **_kwargs):
        return True

    monkeypatch.setattr(auth_router, "evaluate_signup_policy", policy)
    monkeypatch.setattr(auth_router, "beta_invitation_valid", valid_invitation)
    response = await client.post(
        endpoint,
        json={
            "transaction_id": transaction,
            "beta": True,
            "beta_invitation_token": "i" * 40,
            "legal_acceptances": [],
        },
    )
    assert response.status_code == 200, response.text
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        pending_intent = (
            await db.scalar(
                select(BetaPendingRegistration).where(BetaPendingRegistration.user_id == user.id)
            )
            if user is not None
            else None
        )
        identity = await db.scalar(
            select(ExternalIdentity).where(ExternalIdentity.provider_subject == subject)
        )
        assert user is not None
        assert pending_intent is not None
        assert identity is not None and identity.user_id == user.id
