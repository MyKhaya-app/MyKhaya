"""Server-side Sign in with Apple protocol helpers.

This module deliberately contains no account or session policy. It owns only
the provider boundary: short-lived state/nonce storage, client-secret signing,
code exchange, and verification of Apple's signed identity token. Callers must
resolve the verified subject through ``ExternalIdentity`` before issuing any
MyKhaya session.
"""

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, jwt  # type: ignore[import-untyped]
from authlib.jose.errors import ExpiredTokenError, JoseError  # type: ignore[import-untyped]
from fastapi import HTTPException, status
from redis.asyncio import Redis

from mykhaya.config import Settings

APPLE_ISSUER = "https://appleid.apple.com"
STATE_TTL_SECONDS = 600
CLIENT_SECRET_TTL_SECONDS = 300
PENDING_IDENTITY_TTL_SECONDS = 600


class AppleAuthenticationError(Exception):
    """An expected, user-safe Apple protocol failure.

    ``reason`` is a fixed diagnostic category for server logs only (for
    example ``audience_mismatch``). It never contains token contents, claims,
    subjects or email addresses, and is never returned to the client.
    """

    def __init__(self, message: str, reason: str = "unspecified") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class AppleFlowState:
    nonce: str
    intent: str
    user_id: str | None
    return_path: str | None
    native_return_uri: str | None = None
    native_platform: str | None = None
    native_environment: str | None = None
    native_transaction_id: str | None = None
    native_redemption_verifier_hash: str | None = None


@dataclass(frozen=True)
class ApplePendingIdentity:
    """Verified Apple identity awaiting an explicit account decision.

    This contains provider metadata only.  Apple authorization codes and ID
    tokens are never persisted in the recovery transaction.
    """

    transaction_id: str
    subject: str
    provider_email: str | None
    email_verified: bool
    display_name: str | None
    can_register: bool
    return_path: str | None
    intended_user_id: str | None = None


def apple_client_identifier(settings: Settings) -> str:
    value = settings.apple_service_id or settings.apple_client_id
    if not value:
        raise AppleAuthenticationError("Apple sign-in is not configured.")
    return value


def apple_redirect_uri(settings: Settings) -> str:
    return settings.apple_redirect_uri or (
        f"{settings.public_web_url.rstrip('/')}/api/v1/auth/apple/callback"
    )


def require_apple_configuration(settings: Settings) -> None:
    if not settings.apple_sign_in_enabled:
        raise AppleAuthenticationError("Apple sign-in is not enabled.")
    if not settings.apple_team_id or not settings.apple_key_id or not settings.apple_private_key:
        raise AppleAuthenticationError("Apple sign-in is not configured.")
    apple_client_identifier(settings)


def _state_key(state: str) -> str:
    return f"mykhaya:auth:apple:state:{state}"


def _pending_identity_key(transaction_id: str) -> str:
    return f"mykhaya:auth:apple:pending:{transaction_id}"


async def store_flow_state(settings: Settings, state: str, value: AppleFlowState) -> None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.set(
            _state_key(state),
            json.dumps(
                {
                    "nonce": value.nonce,
                    "intent": value.intent,
                    "user_id": value.user_id,
                    "return_path": value.return_path,
                    "native_return_uri": value.native_return_uri,
                    "native_platform": value.native_platform,
                    "native_environment": value.native_environment,
                    "native_transaction_id": value.native_transaction_id,
                    "native_redemption_verifier_hash": value.native_redemption_verifier_hash,
                }
            ),
            ex=STATE_TTL_SECONDS,
        )
    finally:
        await redis.aclose()


async def consume_flow_state(settings: Settings, state: str) -> AppleFlowState:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.getdel(_state_key(state))
    finally:
        await redis.aclose()
    if not raw:
        raise AppleAuthenticationError("This Apple sign-in attempt is invalid or has expired.")
    try:
        parsed = json.loads(raw)
        return AppleFlowState(
            nonce=str(parsed["nonce"]),
            intent=str(parsed["intent"]),
            user_id=str(parsed["user_id"]) if parsed.get("user_id") else None,
            return_path=str(parsed["return_path"]) if parsed.get("return_path") else None,
            native_return_uri=str(parsed["native_return_uri"])
            if parsed.get("native_return_uri")
            else None,
            native_platform=str(parsed["native_platform"])
            if parsed.get("native_platform")
            else None,
            native_environment=str(parsed["native_environment"])
            if parsed.get("native_environment")
            else None,
            native_transaction_id=str(parsed["native_transaction_id"])
            if parsed.get("native_transaction_id")
            else None,
            native_redemption_verifier_hash=str(parsed["native_redemption_verifier_hash"])
            if parsed.get("native_redemption_verifier_hash")
            else None,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AppleAuthenticationError(
            "This Apple sign-in attempt is invalid or has expired."
        ) from exc


async def store_pending_identity(
    settings: Settings, transaction_id: str, value: ApplePendingIdentity
) -> None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.set(
            _pending_identity_key(transaction_id),
            json.dumps(
                {
                    "subject": value.subject,
                    "provider_email": value.provider_email,
                    "email_verified": value.email_verified,
                    "display_name": value.display_name,
                    "can_register": value.can_register,
                    "return_path": value.return_path,
                    "intended_user_id": value.intended_user_id,
                }
            ),
            ex=PENDING_IDENTITY_TTL_SECONDS,
            nx=True,
        )
    finally:
        await redis.aclose()


async def load_pending_identity(
    settings: Settings, transaction_id: str
) -> ApplePendingIdentity | None:
    if not transaction_id or len(transaction_id) > 256:
        return None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.get(_pending_identity_key(transaction_id))
    finally:
        await redis.aclose()
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
        return ApplePendingIdentity(
            transaction_id=transaction_id,
            subject=str(payload["subject"]),
            provider_email=(
                str(payload["provider_email"]) if payload.get("provider_email") else None
            ),
            email_verified=bool(payload.get("email_verified", False)),
            display_name=str(payload["display_name"]) if payload.get("display_name") else None,
            can_register=bool(payload.get("can_register", False)),
            return_path=(str(payload["return_path"]) if payload.get("return_path") else None),
            intended_user_id=(
                str(payload["intended_user_id"]) if payload.get("intended_user_id") else None
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def consume_pending_identity(
    settings: Settings, transaction_id: str
) -> ApplePendingIdentity | None:
    if not transaction_id or len(transaction_id) > 256:
        return None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.getdel(_pending_identity_key(transaction_id))
    finally:
        await redis.aclose()
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
        return ApplePendingIdentity(
            transaction_id=transaction_id,
            subject=str(payload["subject"]),
            provider_email=(
                str(payload["provider_email"]) if payload.get("provider_email") else None
            ),
            email_verified=bool(payload.get("email_verified", False)),
            display_name=str(payload["display_name"]) if payload.get("display_name") else None,
            can_register=bool(payload.get("can_register", False)),
            return_path=(str(payload["return_path"]) if payload.get("return_path") else None),
            intended_user_id=(
                str(payload["intended_user_id"]) if payload.get("intended_user_id") else None
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def build_client_secret(settings: Settings, now: int | None = None) -> str:
    require_apple_configuration(settings)
    assert settings.apple_team_id is not None
    assert settings.apple_key_id is not None
    assert settings.apple_private_key is not None
    issued_at = int(time.time()) if now is None else now
    header = {"alg": "ES256", "kid": settings.apple_key_id}
    claims = {
        "iss": settings.apple_team_id,
        "iat": issued_at,
        "exp": issued_at + CLIENT_SECRET_TTL_SECONDS,
        "aud": APPLE_ISSUER,
        "sub": apple_client_identifier(settings),
    }
    try:
        encoded = jwt.encode(header, claims, settings.apple_private_key.get_secret_value())
        return encoded.decode("ascii") if isinstance(encoded, bytes) else encoded
    except Exception as exc:
        raise AppleAuthenticationError("Apple sign-in configuration is invalid.") from exc


def authorization_url(
    settings: Settings,
    state: str,
    nonce: str,
    scope: str = "name email",
) -> str:
    require_apple_configuration(settings)
    return f"{settings.apple_authorize_url}?{
        urlencode(
            {
                'response_type': 'code',
                # Apple requires form_post whenever name or email is requested.
                # Keep the scopes: the first authorization may contain the
                # user's display name and Apple relay address in the form body.
                'response_mode': 'form_post',
                'client_id': apple_client_identifier(settings),
                'redirect_uri': apple_redirect_uri(settings),
                'scope': scope,
                'state': state,
                'nonce': nonce,
            }
        )
    }"


async def exchange_code(settings: Settings, code: str) -> str:
    if not code or len(code) > 4096:
        raise AppleAuthenticationError("Apple sign-in could not be completed.")
    data = {
        "client_id": apple_client_identifier(settings),
        "client_secret": build_client_secret(settings),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": apple_redirect_uri(settings),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(settings.apple_token_url, data=data)
        payload = response.json()
        token = payload.get("id_token") if isinstance(payload, dict) else None
        if response.status_code >= 400 or not isinstance(token, str):
            raise AppleAuthenticationError("Apple sign-in could not be completed.")
        return token
    except (httpx.HTTPError, ValueError, AppleAuthenticationError) as exc:
        if isinstance(exc, AppleAuthenticationError):
            raise
        raise AppleAuthenticationError("Apple sign-in could not be completed.") from exc


async def verify_identity_token(
    settings: Settings, identity_token: str, nonce: str, expected_audience: str | None = None
) -> dict[str, Any]:
    failed = "Apple sign-in could not be verified."
    if not identity_token or len(identity_token) > 20000:
        raise AppleAuthenticationError(failed, "token_missing_or_oversized")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(settings.apple_jwks_url)
        response.raise_for_status()
        key_set = JsonWebKey.import_key_set(response.json())
    except (httpx.HTTPError, ValueError, TypeError, JoseError) as exc:
        raise AppleAuthenticationError(failed, "apple_keys_unavailable") from exc
    try:
        claims = jwt.decode(identity_token, key_set)
        claims.validate()
    except ExpiredTokenError as exc:
        raise AppleAuthenticationError(failed, "token_expired") from exc
    except (ValueError, TypeError, JoseError) as exc:
        raise AppleAuthenticationError(failed, "token_signature_or_claims_invalid") from exc
    issuer = claims.get("iss")
    audience = claims.get("aud")
    subject = claims.get("sub")
    token_nonce = claims.get("nonce")
    required_audience = expected_audience or apple_client_identifier(settings)
    if issuer != APPLE_ISSUER:
        raise AppleAuthenticationError(failed, "issuer_mismatch")
    valid_audience = audience == required_audience or (
        isinstance(audience, list) and required_audience in audience
    )
    if not valid_audience:
        raise AppleAuthenticationError(failed, "audience_mismatch")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise AppleAuthenticationError(failed, "subject_invalid")
    if not isinstance(token_nonce, str) or not secrets.compare_digest(token_nonce, nonce):
        raise AppleAuthenticationError(failed, "nonce_mismatch")
    return dict(claims)


def apple_error(message: str = "Apple sign-in could not be completed.") -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, message)
