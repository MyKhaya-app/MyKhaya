"""Consumer browser MFA primitives for the Phase 4.5 pre-auth handoff."""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

import pyotp
from pyotp.utils import strings_equal
from redis.asyncio import Redis

from mykhaya.config import Settings
from mykhaya.security import hash_secret

TOTP_ISSUER = "MyKhaya"
EMAIL_CHALLENGE_TTL_SECONDS = 15 * 60
EMAIL_MAX_ATTEMPTS = 5
TOTP_REPLAY_TTL_SECONDS = 90


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


def matched_totp_step(secret: str, code: str) -> int | None:
    if len(code) != 6 or not code.isdigit():
        return None
    now = datetime.now(UTC)
    totp = pyotp.TOTP(secret)
    base_step = totp.timecode(now)
    for offset in (-1, 0, 1):
        if strings_equal(code, totp.at(now, offset)):
            return base_step + offset
    return None


async def claim_totp_step(settings: Settings, user_id: uuid.UUID, step: int) -> bool:
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        return bool(
            await redis.set(
                f"mfa-totp-replay:{user_id}:{step}",
                "1",
                nx=True,
                ex=TOTP_REPLAY_TTL_SECONDS,
            )
        )
    finally:
        await redis.aclose()


def new_email_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_email_code(settings: Settings, code: str) -> str:
    return hash_secret(code, settings.secret_key.get_secret_value())


def hash_transaction(settings: Settings, transaction_id: str) -> str:
    return hash_secret(transaction_id, settings.secret_key.get_secret_value())
