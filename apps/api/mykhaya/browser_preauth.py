"""Short-lived, single-use browser authentication handoff state."""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass

from redis.asyncio import Redis

from mykhaya.config import Settings

TRANSACTION_TTL_SECONDS = 300
_PREFIX = "mykhaya:browser-preauth:"


@dataclass(frozen=True)
class BrowserPreAuth:
    transaction_id: str
    user_id: str
    method: str
    destination: str | None
    onboarding: bool


def _key(transaction_id: str) -> str:
    return f"{_PREFIX}{transaction_id}"


async def create_browser_pre_auth(
    settings: Settings,
    *,
    user_id: str,
    method: str,
    destination: str | None = None,
    onboarding: bool = False,
) -> str:
    transaction_id = secrets.token_urlsafe(32)
    payload = json.dumps(
        {
            "user_id": user_id,
            "method": method,
            "destination": destination,
            "onboarding": onboarding,
        },
        separators=(",", ":"),
    )
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.set(_key(transaction_id), payload, ex=TRANSACTION_TTL_SECONDS, nx=True)
    finally:
        await redis.aclose()
    return transaction_id


async def consume_browser_pre_auth(
    settings: Settings, transaction_id: str
) -> BrowserPreAuth | None:
    if not transaction_id or len(transaction_id) > 256:
        return None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.getdel(_key(transaction_id))
    finally:
        await redis.aclose()
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
        return BrowserPreAuth(
            transaction_id=transaction_id,
            user_id=str(payload["user_id"]),
            method=str(payload["method"]),
            destination=payload.get("destination"),
            onboarding=bool(payload.get("onboarding", False)),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def load_browser_pre_auth(settings: Settings, transaction_id: str) -> BrowserPreAuth | None:
    """Read handoff state without consuming it; successful MFA consumes it."""
    if not transaction_id or len(transaction_id) > 256:
        return None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        raw = await redis.get(_key(transaction_id))
    finally:
        await redis.aclose()
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
        return BrowserPreAuth(
            transaction_id=transaction_id,
            user_id=str(payload["user_id"]),
            method=str(payload["method"]),
            destination=payload.get("destination"),
            onboarding=bool(payload.get("onboarding", False)),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
