"""Founding Beta registration through native Apple/Google sign-in.

Beta intent and the invitation token arrive on the native start request.
Only the token's SHA-256 is kept with the sign-in; eligibility uses the same
central `_beta_signup_allowed` check as web provider registration; and a
successful registration records the same BetaPendingRegistration and Beta
legal context as web.
"""

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from test_mobile_auth import ORIGIN

from mykhaya.apple_auth import AppleFlowState
from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.google_auth import consume_flow_state as consume_google_flow_state
from mykhaya.legal import ResolvedSignupAcceptance
from mykhaya.main import app
from mykhaya.models import (
    BetaPendingRegistration,
    ExternalIdentity,
    LegalAcceptance,
    LegalAcceptanceContext,
    LegalDocument,
    LegalDocumentVersion,
    LegalDocumentVersionStatus,
    SignupMode,
    User,
)
from mykhaya.native_external_auth import (
    _key,
    _pending_key,
    hash_redemption_verifier,
    load_native_external_pending,
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
def native_settings() -> Iterator[Settings]:
    # The same native provider configuration as test_native_external_auth.
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


VERIFIER = "v" * 64
INVITATION = "beta-invitation-token-" + "x" * 30
INVITATION_HASH = hashlib.sha256(INVITATION.encode("utf-8")).hexdigest()

BETA_ONLY = SignupPolicy(
    mode=SignupMode.beta_only,
    open=True,
    normal_path=False,
    beta_path=True,
    invitation_required=True,
    allowed_domains=(),
)
NORMAL_ONLY = SignupPolicy(
    mode=SignupMode.normal,
    open=True,
    normal_path=True,
    beta_path=False,
    invitation_required=False,
    allowed_domains=(),
)


def use_policy(monkeypatch: pytest.MonkeyPatch, policy: SignupPolicy) -> None:
    async def evaluate(*_args: Any, **_kwargs: Any) -> SignupPolicy:
        return policy

    monkeypatch.setattr(auth_router, "evaluate_signup_policy", evaluate)


def use_invitations(monkeypatch: pytest.MonkeyPatch, valid: dict[str, bool]) -> list[str]:
    """Answer the hash-based invitation check from `valid` (keyed by email)
    and record the hashes it was asked about."""
    seen: list[str] = []

    async def check(_db: Any, token_hash: str, email: str) -> bool:
        seen.append(token_hash)
        return token_hash == INVITATION_HASH and valid.get(email, False)

    monkeypatch.setattr(auth_router, "beta_invitation_hash_valid", check)
    return seen


def use_identity(
    monkeypatch: pytest.MonkeyPatch, subject: str, email: str, *, verified: bool = True
) -> None:
    async def verify(_settings: Any, _token: Any, _nonce: Any, _audience: Any = None):
        return {"sub": subject, "email": email, "email_verified": verified}

    monkeypatch.setattr(auth_router, "verify_identity_token", verify)


async def start_and_exchange(client: AsyncClient, **beta: Any) -> tuple[str, dict[str, Any]]:
    started = await client.post(
        "/api/v1/auth/mobile/external/start",
        json={
            "provider": "apple",
            "intent": "login",
            "platform": "ios",
            "redemption_verifier": VERIFIER,
            **beta,
        },
    )
    assert started.status_code == 200, started.text
    exchanged = await client.post(
        "/api/v1/auth/mobile/external/exchange",
        json={
            "transaction_id": started.json()["transaction_id"],
            "identity_token": "synthetic-identity-token-12345",
            "redemption_verifier": VERIFIER,
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    return started.text + exchanged.text, exchanged.json()


async def register(client: AsyncClient, transaction_id: str, **extra: Any):
    return await client.post(
        "/api/v1/auth/mobile/external/recovery/register",
        json={
            "transaction_id": transaction_id,
            "display_name": "Native Beta Person",
            "legal_acceptances": [],
            "platform": "ios",
            "redemption_verifier": VERIFIER,
            **extra,
        },
    )


async def beta_intent_for(email: str) -> BetaPendingRegistration | None:
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            return None
        return await db.scalar(
            select(BetaPendingRegistration).where(BetaPendingRegistration.user_id == user.id)
        )


@pytest.mark.asyncio
async def test_invited_native_beta_registration_records_beta_intent(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = f"native-beta-{uuid4().hex}"
    email = f"{subject}@example.com"
    use_identity(monkeypatch, subject, email)
    use_policy(monkeypatch, BETA_ONLY)
    seen = use_invitations(monkeypatch, {email: True})

    responses, recovery = await start_and_exchange(
        client, beta=True, beta_invitation_token=INVITATION
    )
    # Beta-only period: the invited person is offered a new account.
    assert recovery["authentication_state"] == "account_choice"
    assert recovery["can_register"] is True
    assert INVITATION not in responses

    registered = await register(client, recovery["transaction_id"])
    assert registered.status_code == 200, registered.text
    assert INVITATION not in registered.text
    intent = await beta_intent_for(email)
    assert intent is not None
    # Only the hash travelled with the sign-in, and it is what is recorded.
    assert intent.invitation_token_hash == INVITATION_HASH
    assert seen and set(seen) == {INVITATION_HASH}
    async with SessionFactory() as db:
        identity = await db.scalar(
            select(ExternalIdentity).where(ExternalIdentity.provider_subject == subject)
        )
        assert identity is not None


@pytest.mark.asyncio
async def test_open_beta_without_invitation_registers_with_beta_intent(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = f"native-open-beta-{uuid4().hex}"
    email = f"{subject}@example.com"
    use_identity(monkeypatch, subject, email)
    use_policy(
        monkeypatch,
        SignupPolicy(
            mode=SignupMode.beta_only,
            open=True,
            normal_path=False,
            beta_path=True,
            invitation_required=False,
            allowed_domains=(),
        ),
    )
    _responses, recovery = await start_and_exchange(client, beta=True)
    assert recovery["can_register"] is True
    registered = await register(client, recovery["transaction_id"])
    assert registered.status_code == 200, registered.text
    intent = await beta_intent_for(email)
    assert intent is not None and intent.invitation_token_hash is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["wrong_email", "wrong_token", "no_token"])
async def test_invalid_native_beta_invitation_cannot_register(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    subject = f"native-beta-invalid-{uuid4().hex}"
    email = f"{subject}@example.com"
    use_identity(monkeypatch, subject, email)
    use_policy(monkeypatch, BETA_ONLY)
    use_invitations(monkeypatch, {} if case == "wrong_email" else {email: True})
    beta: dict[str, Any] = {"beta": True}
    if case != "no_token":
        beta["beta_invitation_token"] = INVITATION if case == "wrong_email" else "y" * 40

    _responses, recovery = await start_and_exchange(client, **beta)
    assert recovery["can_register"] is False
    refused = await register(client, recovery["transaction_id"])
    assert refused.status_code == 409
    assert await beta_intent_for(email) is None


@pytest.mark.asyncio
async def test_native_beta_rejected_when_the_beta_path_is_closed(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = f"native-beta-closed-{uuid4().hex}"
    email = f"{subject}@example.com"
    use_identity(monkeypatch, subject, email)
    use_policy(monkeypatch, NORMAL_ONLY)
    use_invitations(monkeypatch, {email: True})
    _responses, recovery = await start_and_exchange(
        client, beta=True, beta_invitation_token=INVITATION
    )
    assert recovery["can_register"] is False
    assert (await register(client, recovery["transaction_id"])).status_code == 409


@pytest.mark.asyncio
async def test_native_beta_rechecks_eligibility_at_registration(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = f"native-beta-recheck-{uuid4().hex}"
    email = f"{subject}@example.com"
    use_identity(monkeypatch, subject, email)
    use_policy(monkeypatch, BETA_ONLY)
    valid = {email: True}
    use_invitations(monkeypatch, valid)
    _responses, recovery = await start_and_exchange(
        client, beta=True, beta_invitation_token=INVITATION
    )
    assert recovery["can_register"] is True
    # The invitation is revoked (or used) before the person taps Create.
    valid[email] = False
    refused = await register(client, recovery["transaction_id"])
    assert refused.status_code == 403
    assert await beta_intent_for(email) is None


@pytest.mark.asyncio
async def test_non_beta_native_sign_in_is_unchanged(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Normal sign-up open: a non-Beta sign-in registers without Beta intent.
    subject = f"native-normal-{uuid4().hex}"
    email = f"{subject}@example.com"
    use_identity(monkeypatch, subject, email)
    use_policy(monkeypatch, NORMAL_ONLY)
    _responses, recovery = await start_and_exchange(client)
    assert recovery["can_register"] is True
    assert (await register(client, recovery["transaction_id"])).status_code == 200
    assert await beta_intent_for(email) is None

    # Beta-only period: without Beta intent nobody can create an account.
    other = f"native-normal-closed-{uuid4().hex}"
    use_identity(monkeypatch, other, f"{other}@example.com")
    use_policy(monkeypatch, BETA_ONLY)
    _responses, recovery = await start_and_exchange(client)
    assert recovery["can_register"] is False
    assert (await register(client, recovery["transaction_id"])).status_code == 409


@pytest.mark.asyncio
async def test_native_registration_requires_a_verified_provider_email(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = f"native-unverified-{uuid4().hex}"
    email = f"{subject}@example.com"
    use_identity(monkeypatch, subject, email, verified=False)
    use_policy(monkeypatch, NORMAL_ONLY)
    _responses, recovery = await start_and_exchange(client)
    assert recovery["can_register"] is False
    assert (await register(client, recovery["transaction_id"])).status_code == 409
    async with SessionFactory() as db:
        assert await db.scalar(select(User).where(User.email == email)) is None


@pytest.mark.asyncio
async def test_native_beta_records_beta_legal_context(
    client: AsyncClient, native_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with SessionFactory() as db:
        row = (
            await db.execute(
                select(LegalDocument, LegalDocumentVersion)
                .join(LegalDocumentVersion, LegalDocumentVersion.document_id == LegalDocument.id)
                .where(LegalDocumentVersion.status == LegalDocumentVersionStatus.published)
                .limit(1)
            )
        ).first()
    if row is None:
        pytest.skip("No published legal document in this database")
    document, version = row

    async def resolved(*_args: Any, **_kwargs: Any) -> list[ResolvedSignupAcceptance]:
        return [ResolvedSignupAcceptance(document=document, version=version)]

    monkeypatch.setattr(auth_router, "validate_signup_acceptances", resolved)
    subject = f"native-beta-legal-{uuid4().hex}"
    email = f"{subject}@example.com"
    use_identity(monkeypatch, subject, email)
    use_policy(monkeypatch, BETA_ONLY)
    use_invitations(monkeypatch, {email: True})
    _responses, recovery = await start_and_exchange(
        client, beta=True, beta_invitation_token=INVITATION
    )
    assert (await register(client, recovery["transaction_id"])).status_code == 200
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        contexts = set(
            (
                await db.scalars(
                    select(LegalAcceptance.context).where(LegalAcceptance.user_id == user.id)
                )
            ).all()
        )
    assert contexts == {LegalAcceptanceContext.beta_registration}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        # A token is meaningless without Beta intent.
        {"beta_invitation_token": INVITATION},
        # Beta intent only applies to sign-in, never to linking.
        {"intent": "link", "beta": True},
        # The strict schema still rejects anything it does not know.
        {"beta": True, "beta_home_name": "Our Home"},
        # Same length limits as the web registration schemas.
        {"beta": True, "beta_invitation_token": "short"},
        {"beta": True, "beta_invitation_token": "z" * 501},
    ],
)
async def test_native_start_validates_beta_fields(
    client: AsyncClient, native_settings, body: dict[str, Any]
) -> None:
    response = await client.post(
        "/api/v1/auth/mobile/external/start",
        json={
            "provider": "apple",
            "intent": "login",
            "platform": "ios",
            "redemption_verifier": VERIFIER,
            **body,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_native_register_does_not_accept_beta_fields(
    client: AsyncClient, native_settings
) -> None:
    # Beta intent comes only from the start request, never from the client
    # at registration time.
    response = await register(client, "x" * 32, beta=True, beta_invitation_token=INVITATION)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invitation_token_is_stored_only_as_a_hash_and_never_logged(
    client: AsyncClient,
    native_settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    subject = f"native-beta-hash-{uuid4().hex}"
    email = f"{subject}@example.com"
    use_identity(monkeypatch, subject, email)
    use_policy(monkeypatch, BETA_ONLY)
    use_invitations(monkeypatch, {email: True})
    started = await client.post(
        "/api/v1/auth/mobile/external/start",
        json={
            "provider": "apple",
            "intent": "login",
            "platform": "ios",
            "redemption_verifier": VERIFIER,
            "beta": True,
            "beta_invitation_token": INVITATION,
        },
    )
    assert started.status_code == 200
    transaction_id = started.json()["transaction_id"]
    redis = Redis.from_url(native_settings.redis_url, decode_responses=True)
    try:
        stored_start = await redis.get(_key(transaction_id))
        exchanged = await client.post(
            "/api/v1/auth/mobile/external/exchange",
            json={
                "transaction_id": transaction_id,
                "identity_token": "synthetic-identity-token-12345",
                "redemption_verifier": VERIFIER,
            },
        )
        assert exchanged.status_code == 200
        stored_pending = await redis.get(_pending_key(transaction_id))
    finally:
        await redis.aclose()
    for stored in (stored_start, stored_pending):
        assert stored is not None
        assert INVITATION not in stored
        record = json.loads(stored)
        assert record["beta"] is True
        assert record["beta_invitation_hash"] == INVITATION_HASH
    assert INVITATION not in started.text + exchanged.text
    assert INVITATION not in caplog.text


@pytest.mark.asyncio
async def test_native_browser_start_keeps_beta_intent_as_a_hash(
    client: AsyncClient, native_settings
) -> None:
    native_settings.google_client_id = "synthetic-google-web-client"
    native_settings.google_client_secret = "synthetic-google-secret"  # noqa: S105
    started = await client.post(
        "/api/v1/auth/mobile/external/browser/start",
        json={
            "provider": "google",
            "intent": "login",
            "platform": "ios",
            "return_uri": native_settings.native_google_return_uri,
            "redemption_verifier": VERIFIER,
            "beta": True,
            "beta_invitation_token": INVITATION,
        },
    )
    assert started.status_code == 200, started.text
    assert INVITATION not in started.text
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    flow = await consume_google_flow_state(native_settings, state)
    assert flow.native_beta is True
    assert flow.native_beta_invitation_hash == INVITATION_HASH
    assert INVITATION not in json.dumps(flow.__dict__)


# Apple sends email_verified as a boolean or as the string "true"/"false"
# (both forms appear in Apple's identity tokens). Native registration needs a
# verified email, so each route must read both forms the same way.
APPLE_EMAIL_VERIFIED_FORMS = [
    (True, True),
    ("true", True),
    (False, False),
    ("false", False),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("claim", "verified"), APPLE_EMAIL_VERIFIED_FORMS)
async def test_apple_sdk_route_reads_email_verified_in_both_forms(
    client: AsyncClient,
    native_settings,
    monkeypatch: pytest.MonkeyPatch,
    claim: bool | str,
    verified: bool,
) -> None:
    subject = f"native-apple-verified-{uuid4().hex}"
    email = f"{subject}@example.com"

    async def verify(_settings: Any, _token: Any, _nonce: Any, _audience: Any = None):
        return {"sub": subject, "email": email, "email_verified": claim}

    monkeypatch.setattr(auth_router, "verify_identity_token", verify)
    use_policy(monkeypatch, NORMAL_ONLY)
    _responses, recovery = await start_and_exchange(client)
    assert recovery["can_register"] is verified
    registered = await register(client, recovery["transaction_id"])
    assert registered.status_code == (200 if verified else 409), registered.text
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
    assert (user is not None) is verified


@pytest.mark.asyncio
@pytest.mark.parametrize(("claim", "verified"), APPLE_EMAIL_VERIFIED_FORMS)
async def test_apple_native_callback_reads_email_verified_in_both_forms(
    client: AsyncClient,
    native_settings,
    monkeypatch: pytest.MonkeyPatch,
    claim: bool | str,
    verified: bool,
) -> None:
    subject = f"native-apple-callback-{uuid4().hex}"
    email = f"{subject}@example.com"
    transaction_id = f"native-apple-callback-tx-{uuid4().hex}"
    # Apple on Android uses the system-browser route, which returns through
    # the web Apple callback before the app redeems the transaction.
    flow = AppleFlowState(
        nonce="nonce",
        intent="login",
        user_id=None,
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
        return {"sub": subject, "email": email, "email_verified": claim}

    monkeypatch.setattr(auth_router, "consume_flow_state", consume_flow_state)
    monkeypatch.setattr(auth_router, "exchange_code", exchange_code)
    monkeypatch.setattr(auth_router, "verify_identity_token", verify)
    use_policy(monkeypatch, NORMAL_ONLY)

    callback = await client.post(
        "/api/v1/auth/apple/callback",
        data={"state": "state", "code": "code"},
        headers={"Origin": "https://appleid.apple.com"},
        follow_redirects=False,
    )
    assert callback.status_code == 303, callback.text
    assert callback.headers["location"].startswith(native_settings.native_apple_return_uri)
    pending = await load_native_external_pending(native_settings, transaction_id)
    assert pending is not None
    assert pending.email_verified is verified
    assert pending.can_register is verified

    registered = await client.post(
        "/api/v1/auth/mobile/external/recovery/register",
        json={
            "transaction_id": transaction_id,
            "display_name": "Native Apple Person",
            "legal_acceptances": [],
            "platform": "android",
            "redemption_verifier": VERIFIER,
        },
    )
    assert registered.status_code == (200 if verified else 409), registered.text
