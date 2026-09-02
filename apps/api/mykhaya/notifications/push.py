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
import structlog
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
log = structlog.get_logger(__name__)


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


APNS_PRODUCTION_ENDPOINT = "https://api.push.apple.com"


def is_apns_response_retryable(status_code: int) -> bool:
    """Classify an APNs HTTP response without inspecting any request secrets."""
    return status_code in (408, 425, 429) or 500 <= status_code <= 599


def _safe_apns_log_value(value: object, fallback: str = "unknown") -> str:
    """Keep provider metadata single-line, bounded, and free of control characters."""
    if not isinstance(value, str):
        return fallback
    value = value.strip()
    if not value or len(value) > 128 or any(ord(character) < 0x20 for character in value):
        return fallback
    return value


def apns_failure_diagnostics(response: httpx.Response) -> dict[str, object]:
    """Extract only safe metadata from a non-successful APNs response.

    The response body is parsed for Apple's documented ``reason`` field, but is
    never included in logs. The APNs request ID is an opaque response header and
    is bounded/sanitised before logging.
    """
    reason: object = None
    try:
        response_json = response.json()
    except (TypeError, ValueError):
        response_json = None
    if isinstance(response_json, dict):
        reason = response_json.get("reason")
    return {
        "status": response.status_code,
        "reason": _safe_apns_log_value(reason),
        "request_id": _safe_apns_log_value(response.headers.get("apns-id")),
        "retryable": is_apns_response_retryable(response.status_code),
    }


def _normalise_apns_private_key(private_key: str) -> str:
    """Accept PEM values from either multiline files or escaped environment vars."""
    return private_key.replace("\\n", "\n").strip()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _is_unpadded_base64url(value: str, expected: bytes) -> bool:
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    if not value or "=" in value or any(character not in allowed for character in value):
        return False
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError):
        return False
    return decoded == expected and _b64(decoded) == value


def _build_apns_bearer(
    config: ApnsConfig,
    issued_at: int | None = None,
    topic: str | None = None,
    emit_diagnostics: bool = True,
) -> str:
    """Build one short-lived APNs provider JWT; deliberately does not cache it."""
    if not config.team_id or not config.key_id or not config.private_key:
        raise RuntimeError("APNs provider-token configuration is incomplete")

    issued_at = int(time.time()) if issued_at is None else int(issued_at)
    header = _b64(
        json.dumps({"alg": "ES256", "kid": config.key_id}, separators=(",", ":")).encode()
    )
    claims = _b64(
        json.dumps(
            {"iss": config.team_id, "iat": issued_at}, separators=(",", ":")
        ).encode()
    )
    signing_input = f"{header}.{claims}".encode("ascii")
    key_parsed = False
    try:
        key = load_pem_private_key(
            _normalise_apns_private_key(config.private_key).encode("utf-8"), password=None
        )
        key_parsed = isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(
            key.curve, ec.SECP256R1
        )
        if not key_parsed:
            raise RuntimeError("APNs key is not an EC P-256 private key")
        signature = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    except Exception:
        if emit_diagnostics:
            log.error(
                "apns_jwt_diagnostics",
                jwt_kid_matches_config=False,
                jwt_iss_matches_config=False,
                jwt_iat_age_seconds=0,
                private_key_parsed=key_parsed,
                apns_endpoint="production",
                apns_topic_matches_bundle=False,
            )
        raise

    # APNs expects the JOSE raw r||s signature, not ASN.1 DER.
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    r, s = decode_dss_signature(signature)
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    encoded_signature = _b64(raw_signature)
    signature_self_verifies = False
    try:
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

        key.public_key().verify(
            encode_dss_signature(r, s), signing_input, ec.ECDSA(hashes.SHA256())
        )
        signature_self_verifies = True
    except Exception:
        signature_self_verifies = False
    signature_base64url_valid = _is_unpadded_base64url(encoded_signature, raw_signature)
    if emit_diagnostics:
        log.info(
            "apns_jwt_signature_diagnostics",
            jwt_signature_bytes=len(raw_signature),
            jwt_r_bytes=len(raw_signature[:32]),
            jwt_s_bytes=len(raw_signature[32:]),
            jwt_signature_self_verifies=signature_self_verifies,
            jwt_base64url_valid=signature_base64url_valid,
        )
    if not signature_self_verifies or not signature_base64url_valid:
        raise RuntimeError("APNs provider-token signature self-verification failed")
    bearer = f"{header}.{claims}.{encoded_signature}"
    if emit_diagnostics:
        log.info(
            "apns_jwt_diagnostics",
            jwt_kid_matches_config=True,
            jwt_iss_matches_config=True,
            jwt_iat_age_seconds=max(0, int(time.time()) - issued_at),
            private_key_parsed=True,
            apns_endpoint="production",
            apns_topic_matches_bundle=topic is not None and topic == config.bundle_id,
        )
    return bearer


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
    topic = config.bundle_id or "app.mykhaya.mobile"
    bearer = _build_apns_bearer(config, topic=topic)
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
            f"{APNS_PRODUCTION_ENDPOINT}/3/device/{device.token}",
            headers={"authorization": f"bearer {bearer}", "apns-topic": topic},
            json=request_payload,
        )
    if not 200 <= response.status_code < 300:
        log.error("apns_delivery_failed", **apns_failure_diagnostics(response))
    if response.status_code in (400, 404, 410):
        raise ApnsPermanentError("APNs rejected this device registration")
    response.raise_for_status()
