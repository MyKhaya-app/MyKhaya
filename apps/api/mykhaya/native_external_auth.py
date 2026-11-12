"""Short-lived native external-auth transactions.

Provider SDKs and system-browser callbacks must hand the API a verified
assertion before a native bearer session is issued.  This module stores only
the provider-neutral transaction metadata in Redis; provider tokens are never
stored or logged.
"""

import hashlib
import json
import secrets
from dataclasses import dataclass

from redis.asyncio import Redis

from mykhaya.config import Settings
from mykhaya.models import ExternalIdentityProvider

TRANSACTION_TTL_SECONDS = 600


@dataclass(frozen=True)
class NativeExternalTransaction:
    transaction_id: str
    provider: ExternalIdentityProvider
    nonce: str
    client_nonce: str
    client_id: str
    environment: str
    intent: str
    user_id: str | None
    platform: str
    redemption_verifier_hash: str
    intended_user_id: str | None = None
    # Founding Beta intent from the start request. Only the SHA-256 of the
    # invitation token is kept; the raw token is never stored.
    beta: bool = False
    beta_invitation_hash: str | None = None


@dataclass(frozen=True)
class NativeExternalPendingIdentity:
    transaction_id: str
    provider: ExternalIdentityProvider
    subject: str
    provider_email: str | None
    email_verified: bool
    display_name: str | None
    can_register: bool
    platform: str
    redemption_verifier_hash: str
    intended_user_id: str | None = None
    intent: str = "login"
    beta: bool = False
    beta_invitation_hash: str | None = None


NATIVE_MFA_PRIMARY_METHODS = frozenset({"apple", "google", "password"})


@dataclass(frozen=True)
class NativeMfaTransaction:
    """Native pre-authentication awaiting the consumer MFA policy.

    ``provider`` names the completed primary factor: ``apple``, ``google`` or
    ``password``.  The transaction is bound to the client that completed that
    factor by ``redemption_verifier_hash``; the transaction id alone is never
    sufficient to continue it.
    """

    transaction_id: str
    user_id: str
    provider: str
    platform: str
    redemption_verifier_hash: str

    def __post_init__(self) -> None:
        if self.provider not in NATIVE_MFA_PRIMARY_METHODS:
            raise ValueError("Unsupported native primary authentication method")


def hash_redemption_verifier(verifier: str) -> str:
    return hashlib.sha256(verifier.encode("utf-8")).hexdigest()


def verify_redemption_verifier(verifier: str, expected_hash: str) -> bool:
    return secrets.compare_digest(hash_redemption_verifier(verifier), expected_hash)


def new_native_external_transaction(
    provider: ExternalIdentityProvider,
    *,
    client_id: str,
    environment: str,
    intent: str,
    user_id: str | None,
    platform: str,
    redemption_verifier: str,
    apple_nonce_hash: bool = False,
    beta: bool = False,
    beta_invitation_hash: str | None = None,
) -> NativeExternalTransaction:
    raw_nonce = secrets.token_urlsafe(32)
    nonce = hashlib.sha256(raw_nonce.encode("ascii")).hexdigest() if apple_nonce_hash else raw_nonce
    return NativeExternalTransaction(
        transaction_id=secrets.token_urlsafe(32),
        provider=provider,
        nonce=nonce,
        client_nonce=raw_nonce,
        client_id=client_id,
        environment=environment,
        intent=intent,
        user_id=user_id,
        intended_user_id=user_id if intent == "link" else None,
        platform=platform,
        redemption_verifier_hash=hash_redemption_verifier(redemption_verifier),
        beta=beta,
        beta_invitation_hash=beta_invitation_hash if beta else None,
    )


def _beta_hash(value: dict[str, object]) -> str | None:
    """The stored invitation hash, only alongside Beta intent."""
    raw = value.get("beta_invitation_hash")
    if value.get("beta") is not True or not isinstance(raw, str) or len(raw) != 64:
        return None
    return raw


def _key(transaction_id: str) -> str:
    return f"mykhaya:auth:native-external:{transaction_id}"


def _pending_key(transaction_id: str) -> str:
    return f"mykhaya:auth:native-external-pending:{transaction_id}"


def _mfa_key(transaction_id: str) -> str:
    return f"mykhaya:auth:native-mfa:{transaction_id}"


async def store_native_external_transaction(
    settings: Settings, value: NativeExternalTransaction
) -> None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.set(
            _key(value.transaction_id),
            json.dumps(
                {
                    "provider": value.provider.value,
                    "nonce": value.nonce,
                    "client_id": value.client_id,
                    "environment": value.environment,
                    "intent": value.intent,
                    "user_id": value.user_id,
                    "platform": value.platform,
                    "redemption_verifier_hash": value.redemption_verifier_hash,
                    "intended_user_id": value.intended_user_id,
                    "beta": value.beta,
                    "beta_invitation_hash": value.beta_invitation_hash,
                }
            ),
            ex=TRANSACTION_TTL_SECONDS,
            nx=True,
        )
    finally:
        await redis.aclose()


async def consume_native_external_transaction(
    settings: Settings, transaction_id: str
) -> NativeExternalTransaction | None:
    return await _read_native_external_transaction(settings, transaction_id, consume=True)


async def load_native_external_transaction(
    settings: Settings, transaction_id: str
) -> NativeExternalTransaction | None:
    return await _read_native_external_transaction(settings, transaction_id, consume=False)


async def _read_native_external_transaction(
    settings: Settings, transaction_id: str, *, consume: bool
) -> NativeExternalTransaction | None:
    if not transaction_id or len(transaction_id) > 256:
        return None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await (
            redis.getdel(_key(transaction_id)) if consume else redis.get(_key(transaction_id))
        )
    finally:
        await redis.aclose()
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return NativeExternalTransaction(
            transaction_id=transaction_id,
            provider=ExternalIdentityProvider(str(value["provider"])),
            nonce=str(value["nonce"]),
            client_nonce="",
            client_id=str(value["client_id"]),
            environment=str(value["environment"]),
            intent=str(value["intent"]),
            user_id=str(value["user_id"]) if value.get("user_id") else None,
            platform=str(value["platform"]),
            redemption_verifier_hash=str(value["redemption_verifier_hash"]),
            intended_user_id=(
                str(value["intended_user_id"]) if value.get("intended_user_id") else None
            ),
            beta=value.get("beta") is True,
            beta_invitation_hash=_beta_hash(value),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def store_native_external_pending(
    settings: Settings, value: NativeExternalPendingIdentity
) -> None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.set(
            _pending_key(value.transaction_id),
            json.dumps(
                {
                    "provider": value.provider.value,
                    "subject": value.subject,
                    "provider_email": value.provider_email,
                    "email_verified": value.email_verified,
                    "display_name": value.display_name,
                    "can_register": value.can_register,
                    "platform": value.platform,
                    "redemption_verifier_hash": value.redemption_verifier_hash,
                    "intended_user_id": value.intended_user_id,
                    "intent": value.intent,
                    "beta": value.beta,
                    "beta_invitation_hash": value.beta_invitation_hash,
                }
            ),
            ex=TRANSACTION_TTL_SECONDS,
            nx=True,
        )
    finally:
        await redis.aclose()


def _parse_native_external_pending(
    transaction_id: str, raw: str | None
) -> NativeExternalPendingIdentity | None:
    """The single parser for a stored pending identity.

    Both load and consume use it, so every stored field (including the link
    binding: ``intent`` and ``intended_user_id``) is always read back. A
    separate copy in the loader once dropped those two fields, which disabled
    the link checks that depend on them."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return NativeExternalPendingIdentity(
            transaction_id=transaction_id,
            provider=ExternalIdentityProvider(str(value["provider"])),
            subject=str(value["subject"]),
            provider_email=str(value["provider_email"]) if value.get("provider_email") else None,
            email_verified=bool(value.get("email_verified", False)),
            display_name=str(value["display_name"]) if value.get("display_name") else None,
            can_register=bool(value.get("can_register", False)),
            platform=str(value["platform"]),
            redemption_verifier_hash=str(value["redemption_verifier_hash"]),
            intended_user_id=(
                str(value["intended_user_id"]) if value.get("intended_user_id") else None
            ),
            intent=str(value.get("intent") or "login"),
            beta=value.get("beta") is True,
            beta_invitation_hash=_beta_hash(value),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def consume_native_external_pending(
    settings: Settings, transaction_id: str
) -> NativeExternalPendingIdentity | None:
    if not transaction_id or len(transaction_id) > 256:
        return None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.getdel(_pending_key(transaction_id))
    finally:
        await redis.aclose()
    return _parse_native_external_pending(transaction_id, raw)


async def load_native_external_pending(
    settings: Settings, transaction_id: str
) -> NativeExternalPendingIdentity | None:
    if not transaction_id or len(transaction_id) > 256:
        return None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.get(_pending_key(transaction_id))
    finally:
        await redis.aclose()
    return _parse_native_external_pending(transaction_id, raw)


async def store_native_mfa_transaction(settings: Settings, value: NativeMfaTransaction) -> None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.set(
            _mfa_key(value.transaction_id),
            json.dumps(
                {
                    "user_id": value.user_id,
                    "provider": value.provider,
                    "platform": value.platform,
                    "redemption_verifier_hash": value.redemption_verifier_hash,
                }
            ),
            ex=TRANSACTION_TTL_SECONDS,
            nx=True,
        )
    finally:
        await redis.aclose()


async def consume_native_mfa_transaction(
    settings: Settings, transaction_id: str
) -> NativeMfaTransaction | None:
    return await _read_native_mfa_transaction(settings, transaction_id, consume=True)


async def load_native_mfa_transaction(
    settings: Settings, transaction_id: str
) -> NativeMfaTransaction | None:
    return await _read_native_mfa_transaction(settings, transaction_id, consume=False)


async def _read_native_mfa_transaction(
    settings: Settings, transaction_id: str, *, consume: bool
) -> NativeMfaTransaction | None:
    if not transaction_id or len(transaction_id) > 256:
        return None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await (
            redis.getdel(_mfa_key(transaction_id))
            if consume
            else redis.get(_mfa_key(transaction_id))
        )
    finally:
        await redis.aclose()
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return NativeMfaTransaction(
            transaction_id=transaction_id,
            user_id=str(value["user_id"]),
            provider=str(value["provider"]),
            platform=str(value["platform"]),
            redemption_verifier_hash=str(value["redemption_verifier_hash"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def delete_native_mfa_transaction(settings: Settings, transaction_id: str) -> None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.delete(_mfa_key(transaction_id))
    finally:
        await redis.aclose()
