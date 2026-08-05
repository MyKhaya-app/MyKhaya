"""Web Push (VAPID) — covers Android Chrome and installed iOS/iPadOS Safari PWAs
(iOS 16.4+) through the one standards-based implementation, no platform-specific SDK.

Same environment-wins-over-Platform-Admin precedence model as mykhaya.mailer, and the
same encrypted-secret-at-rest handling for the VAPID private key (mykhaya.secrets_crypto).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Literal

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import PlatformPushSettings, PushSubscription
from mykhaya.secrets_crypto import SecretDecryptionError, decrypt_secret

PushSource = Literal["environment", "platform_admin", "unconfigured"]


@dataclass(frozen=True)
class PushConfig:
    source: PushSource
    configured: bool
    public_key: str | None = None
    private_key: str | None = None
    subject: str | None = None


def generate_vapid_keypair() -> tuple[str, str]:
    """Returns (public_key, private_key) as base64url-encoded strings (no padding) —
    the raw EC P-256 uncompressed point / scalar format expected by both
    PushManager.subscribe({applicationServerKey}) on the client and pywebpush here."""
    vapid = Vapid()
    vapid.generate_keys()
    public_bytes = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    private_value = vapid.private_key.private_numbers().private_value
    private_bytes = private_value.to_bytes(32, "big")
    public_b64 = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii")
    private_b64 = base64.urlsafe_b64encode(private_bytes).rstrip(b"=").decode("ascii")
    return public_b64, private_b64


async def resolve_push_config(settings: Settings, db: AsyncSession) -> PushConfig:
    if settings.push_delivery_configured:
        configured = bool(
            settings.vapid_public_key and settings.vapid_private_key and settings.vapid_subject
        )
        return PushConfig(
            source="environment",
            configured=configured,
            public_key=settings.vapid_public_key,
            private_key=(
                settings.vapid_private_key.get_secret_value()
                if settings.vapid_private_key
                else None
            ),
            subject=settings.vapid_subject,
        )

    row = await db.scalar(select(PlatformPushSettings).limit(1))
    if row is not None and row.enabled:
        try:
            private_key = (
                decrypt_secret(settings, row.encrypted_vapid_private_key)
                if row.encrypted_vapid_private_key
                else None
            )
        except SecretDecryptionError:
            return PushConfig(source="platform_admin", configured=False)
        configured = bool(row.vapid_public_key and private_key and row.subject)
        return PushConfig(
            source="platform_admin",
            configured=configured,
            public_key=row.vapid_public_key,
            private_key=private_key,
            subject=row.subject,
        )

    return PushConfig(source="unconfigured", configured=False)


def send_push(
    config: PushConfig, subscription: PushSubscription, payload: dict[str, object]
) -> None:
    if not config.configured:
        raise RuntimeError("Push delivery is not configured")
    webpush(
        subscription_info={
            "endpoint": subscription.endpoint,
            "keys": {"p256dh": subscription.p256dh_key, "auth": subscription.auth_key},
        },
        data=json.dumps(payload),
        vapid_private_key=config.private_key,
        vapid_claims={"sub": config.subject},
    )


def is_subscription_gone(exc: WebPushException) -> bool:
    """404/410 mean the push service has permanently discarded this subscription —
    the browser unsubscribed, the device was reset, etc. Any other error is treated
    as transient and left to the worker's normal retry/backoff."""
    response = getattr(exc, "response", None)
    return bool(response is not None and response.status_code in (404, 410))
