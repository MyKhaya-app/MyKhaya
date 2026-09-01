"""Web Push (VAPID) — covers Android Chrome and installed iOS/iPadOS Safari PWAs
(iOS 16.4+) through the one standards-based implementation, no platform-specific SDK.

Same environment-wins-over-Platform-Admin precedence model as mykhaya.mailer, and the
same encrypted-secret-at-rest handling for the VAPID private key (mykhaya.secrets_crypto).
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Literal

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import NativePushDevice, PlatformPushSettings, PushSubscription
from mykhaya.secrets_crypto import SecretDecryptionError, decrypt_secret

PushSource = Literal["environment", "platform_admin", "unconfigured"]


@dataclass(frozen=True)
class PushConfig:
    source: PushSource
    configured: bool
    public_key: str | None = None
    private_key: str | None = None
    subject: str | None = None


@dataclass(frozen=True)
class ApnsConfig:
    configured: bool
    team_id: str | None = None
    key_id: str | None = None
    bundle_id: str | None = None
    private_key: str | None = None


class ApnsPermanentError(Exception):
    pass


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


def resolve_apns_config(settings: Settings) -> ApnsConfig:
    return ApnsConfig(
        configured=settings.apns_delivery_configured
        and bool(settings.apns_team_id and settings.apns_key_id and settings.apns_private_key),
        team_id=settings.apns_team_id,
        key_id=settings.apns_key_id,
        bundle_id=settings.apns_bundle_id,
        private_key=(
            settings.apns_private_key.get_secret_value()
            if settings.apns_private_key
            else None
        ),
    )


def send_apns(config: ApnsConfig, device: NativePushDevice, payload: dict[str, object]) -> None:
    if not config.configured or not config.team_id or not config.key_id or not config.private_key:
        raise RuntimeError("APNs delivery is not configured")
    def b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    header = b64(
        json.dumps({"alg": "ES256", "kid": config.key_id}, separators=(",", ":")).encode()
    )
    claims = b64(
        json.dumps(
            {"iss": config.team_id, "iat": int(time.time())}, separators=(",", ":")
        ).encode()
    )
    signing_input = f"{header}.{claims}".encode("ascii")
    key = load_pem_private_key(config.private_key.encode("utf-8"), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise RuntimeError("APNs key is not an elliptic-curve private key")
    signature = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    # APNs expects the JOSE raw r||s signature, not ASN.1 DER.
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    r, s = decode_dss_signature(signature)
    bearer = f"{header}.{claims}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    topic = config.bundle_id or "app.mykhaya.mobile"
    request_payload = {
        "aps": {
            "alert": {"title": payload["title"], "body": payload["body"]},
            "sound": "default",
        },
        "deep_link": payload.get("deep_link"),
        "notification_type": payload.get("notification_type"),
    }
    with httpx.Client(http2=True, timeout=10) as client:
        response = client.post(
            f"https://api.push.apple.com/3/device/{device.token}",
            headers={"authorization": f"bearer {bearer}", "apns-topic": topic},
            json=request_payload,
        )
    if response.status_code in (400, 404, 410):
        raise ApnsPermanentError("APNs rejected this device registration")
    response.raise_for_status()
