"""Google OpenID Connect provider-boundary helpers.

Account ownership, recovery, MFA and session policy remain in the auth router.
This module only handles the short-lived OAuth ceremony and verifies Google's
signed ID token before the stable ``sub`` reaches the identity service.
"""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, jwt  # type: ignore[import-untyped]
from authlib.jose.errors import JoseError  # type: ignore[import-untyped]
from redis.asyncio import Redis

from mykhaya.config import Settings

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — a URL
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
STATE_TTL_SECONDS = 600
PENDING_IDENTITY_TTL_SECONDS = 600


class GoogleAuthenticationError(Exception):
    """An expected, user-safe Google protocol failure."""


@dataclass(frozen=True)
class GoogleFlowState:
    nonce: str
    code_verifier: str
    intent: str
    user_id: str | None
    return_path: str | None
    native_return_uri: str | None = None


@dataclass(frozen=True)
class GooglePendingIdentity:
    transaction_id: str
    subject: str
    provider_email: str
    email_verified: bool
    display_name: str
    can_register: bool
    return_path: str | None


def google_redirect_uri(settings: Settings) -> str:
    return settings.google_redirect_uri or (
        f"{settings.public_web_url.rstrip('/')}/api/v1/auth/google/callback"
    )


def require_google_configuration(settings: Settings) -> None:
    if not settings.google_sign_in_enabled:
        raise GoogleAuthenticationError("Google sign-in is not enabled.")
    if not settings.google_client_id or not settings.google_client_secret:
        raise GoogleAuthenticationError("Google sign-in is not configured.")


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(settings: Settings, state: str, nonce: str, verifier: str) -> str:
    require_google_configuration(settings)
    return f"{settings.google_authorize_url}?{
        urlencode(
            {
                'client_id': settings.google_client_id,
                'redirect_uri': google_redirect_uri(settings),
                'response_type': 'code',
                'scope': 'openid email profile',
                'state': state,
                'nonce': nonce,
                'code_challenge': code_challenge(verifier),
                'code_challenge_method': 'S256',
                'access_type': 'online',
                'prompt': 'select_account',
            }
        )
    }"


def _state_key(state: str) -> str:
    return f"mykhaya:auth:google:state:{state}"


def _pending_key(transaction_id: str) -> str:
    return f"mykhaya:auth:google:pending:{transaction_id}"


async def store_flow_state(settings: Settings, state: str, value: GoogleFlowState) -> None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.set(
            _state_key(state),
            json.dumps(value.__dict__),
            ex=STATE_TTL_SECONDS,
            nx=True,
        )
    finally:
        await redis.aclose()


async def consume_flow_state(settings: Settings, state: str) -> GoogleFlowState:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.getdel(_state_key(state))
    finally:
        await redis.aclose()
    if not raw:
        raise GoogleAuthenticationError("This Google sign-in attempt is invalid or has expired.")
    try:
        data = json.loads(raw)
        return GoogleFlowState(
            nonce=str(data["nonce"]),
            code_verifier=str(data["code_verifier"]),
            intent=str(data["intent"]),
            user_id=str(data["user_id"]) if data.get("user_id") else None,
            return_path=str(data["return_path"]) if data.get("return_path") else None,
            native_return_uri=str(data["native_return_uri"])
            if data.get("native_return_uri")
            else None,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GoogleAuthenticationError(
            "This Google sign-in attempt is invalid or has expired."
        ) from exc


async def exchange_code(settings: Settings, code: str, verifier: str) -> str:
    require_google_configuration(settings)
    if not code or len(code) > 4096:
        raise GoogleAuthenticationError("Google sign-in could not be completed.")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.google_token_url,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret.get_secret_value(),
                    "redirect_uri": google_redirect_uri(settings),
                    "grant_type": "authorization_code",
                    "code_verifier": verifier,
                },
            )
        payload = response.json()
        token = payload.get("id_token") if isinstance(payload, dict) else None
        if response.status_code >= 400 or not isinstance(token, str):
            raise GoogleAuthenticationError("Google sign-in could not be completed.")
        return token
    except (httpx.HTTPError, ValueError, GoogleAuthenticationError) as exc:
        if isinstance(exc, GoogleAuthenticationError):
            raise
        raise GoogleAuthenticationError("Google sign-in could not be completed.") from exc


async def verify_identity_token(
    settings: Settings, identity_token: str, nonce: str, expected_audience: str | None = None
) -> dict[str, Any]:
    if not identity_token or len(identity_token) > 20000:
        raise GoogleAuthenticationError("Google sign-in could not be verified.")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(settings.google_jwks_url)
        response.raise_for_status()
        claims = jwt.decode(identity_token, JsonWebKey.import_key_set(response.json()))
        claims.validate()
        audience = claims.get("aud")
        required_audience = expected_audience or settings.google_client_id
        valid_audience = audience == required_audience or (
            isinstance(audience, list) and required_audience in audience
        )
        if claims.get("iss") not in (GOOGLE_ISSUER, "accounts.google.com") or not valid_audience:
            raise GoogleAuthenticationError("Google sign-in could not be verified.")
        subject = claims.get("sub")
        email = claims.get("email")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise GoogleAuthenticationError("Google sign-in could not be verified.")
        if not isinstance(email, str) or not email or claims.get("email_verified") is not True:
            raise GoogleAuthenticationError("Google sign-in requires a verified email address.")
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not secrets.compare_digest(token_nonce, nonce):
            raise GoogleAuthenticationError("Google sign-in could not be verified.")
        return dict(claims)
    except (httpx.HTTPError, ValueError, TypeError, JoseError, GoogleAuthenticationError) as exc:
        if isinstance(exc, GoogleAuthenticationError):
            raise
        raise GoogleAuthenticationError("Google sign-in could not be verified.") from exc


async def store_pending_identity(
    settings: Settings, transaction_id: str, value: GooglePendingIdentity
) -> None:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.set(
            _pending_key(transaction_id),
            json.dumps(
                {
                    "subject": value.subject,
                    "provider_email": value.provider_email,
                    "email_verified": value.email_verified,
                    "display_name": value.display_name,
                    "can_register": value.can_register,
                    "return_path": value.return_path,
                }
            ),
            ex=PENDING_IDENTITY_TTL_SECONDS,
            nx=True,
        )
    finally:
        await redis.aclose()


async def load_pending_identity(
    settings: Settings, transaction_id: str
) -> GooglePendingIdentity | None:
    if not transaction_id or len(transaction_id) > 256:
        return None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.get(_pending_key(transaction_id))
    finally:
        await redis.aclose()
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return GooglePendingIdentity(
            transaction_id=transaction_id,
            subject=str(data["subject"]),
            provider_email=str(data["provider_email"]),
            email_verified=bool(data.get("email_verified", False)),
            display_name=str(data.get("display_name") or "Google user"),
            can_register=bool(data.get("can_register", False)),
            return_path=str(data["return_path"]) if data.get("return_path") else None,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def consume_pending_identity(
    settings: Settings, transaction_id: str
) -> GooglePendingIdentity | None:
    if not transaction_id or len(transaction_id) > 256:
        return None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.getdel(_pending_key(transaction_id))
    finally:
        await redis.aclose()
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return GooglePendingIdentity(
            transaction_id=transaction_id,
            subject=str(data["subject"]),
            provider_email=str(data["provider_email"]),
            email_verified=bool(data.get("email_verified", False)),
            display_name=str(data.get("display_name") or "Google user"),
            can_register=bool(data.get("can_register", False)),
            return_path=str(data["return_path"]) if data.get("return_path") else None,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
