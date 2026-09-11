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
from authlib.jose.errors import JoseError  # type: ignore[import-untyped]
from fastapi import HTTPException, status
from redis.asyncio import Redis

from mykhaya.config import Settings

APPLE_ISSUER = "https://appleid.apple.com"
STATE_TTL_SECONDS = 600
CLIENT_SECRET_TTL_SECONDS = 300


class AppleAuthenticationError(Exception):
    """An expected, user-safe Apple protocol failure."""


@dataclass(frozen=True)
class AppleFlowState:
    nonce: str
    intent: str
    user_id: str | None
    return_path: str | None


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
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AppleAuthenticationError(
            "This Apple sign-in attempt is invalid or has expired."
        ) from exc


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
    return f"{settings.apple_authorize_url}?{urlencode({
        'response_type': 'code',
        'response_mode': 'query',
        'client_id': apple_client_identifier(settings),
        'redirect_uri': apple_redirect_uri(settings),
        'scope': scope,
        'state': state,
        'nonce': nonce,
    })}"


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
    settings: Settings, identity_token: str, nonce: str
) -> dict[str, Any]:
    if not identity_token or len(identity_token) > 20000:
        raise AppleAuthenticationError("Apple sign-in could not be verified.")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(settings.apple_jwks_url)
        response.raise_for_status()
        key_set = JsonWebKey.import_key_set(response.json())
        claims = jwt.decode(identity_token, key_set)
        claims.validate()
        issuer = claims.get("iss")
        audience = claims.get("aud")
        subject = claims.get("sub")
        token_nonce = claims.get("nonce")
        expected_audience = apple_client_identifier(settings)
        if issuer != APPLE_ISSUER:
            raise AppleAuthenticationError("Apple sign-in could not be verified.")
        valid_audience = audience == expected_audience or (
            isinstance(audience, list) and expected_audience in audience
        )
        if not valid_audience:
            raise AppleAuthenticationError("Apple sign-in could not be verified.")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise AppleAuthenticationError("Apple sign-in could not be verified.")
        if not isinstance(token_nonce, str) or not secrets.compare_digest(token_nonce, nonce):
            raise AppleAuthenticationError("Apple sign-in could not be verified.")
        return dict(claims)
    except (httpx.HTTPError, ValueError, TypeError, JoseError, AppleAuthenticationError) as exc:
        if isinstance(exc, AppleAuthenticationError):
            raise
        raise AppleAuthenticationError("Apple sign-in could not be verified.") from exc


def apple_error(message: str = "Apple sign-in could not be completed.") -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, message)
