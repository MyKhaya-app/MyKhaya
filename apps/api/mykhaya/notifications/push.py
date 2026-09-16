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
from authlib.jose import jwt as apns_jwt  # type: ignore[import-untyped]
from cryptography.hazmat.primitives import serialization
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


@dataclass(frozen=True)
class FcmConfig:
    configured: bool
    project_id: str | None = None
    client_email: str | None = None
    private_key: str | None = None


class ApnsPermanentError(Exception):
    pass


class FcmPermanentError(Exception):
    pass


APNS_PRODUCTION_ENDPOINT = "https://api.push.apple.com"
APNS_SANDBOX_ENDPOINT = "https://api.sandbox.push.apple.com"

FCM_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 — a URL, not a secret
FCM_MESSAGING_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_SEND_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"


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


def is_fcm_response_retryable(status_code: int) -> bool:
    """Classify an FCM HTTP v1 response without inspecting any request secrets."""
    return status_code in (408, 429) or 500 <= status_code <= 599


def _fcm_error_code(response: httpx.Response) -> str | None:
    """FCM's structured error body nests the machine-readable reason inside
    ``error.details[].errorCode`` (e.g. ``UNREGISTERED``); ``error.status``
    (e.g. ``NOT_FOUND``) is the fallback when no detail is present."""
    try:
        response_json = response.json()
    except (TypeError, ValueError):
        return None
    if not isinstance(response_json, dict):
        return None
    error = response_json.get("error")
    if not isinstance(error, dict):
        return None
    details = error.get("details")
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, dict):
                error_code = detail.get("errorCode")
                if isinstance(error_code, str):
                    return error_code
    status_value = error.get("status")
    return status_value if isinstance(status_value, str) else None


def fcm_failure_diagnostics(response: httpx.Response) -> dict[str, object]:
    """Extract only safe metadata from a non-successful FCM response — mirrors
    apns_failure_diagnostics(); the response body is never logged verbatim."""
    return {
        "status": response.status_code,
        "error_code": _safe_apns_log_value(_fcm_error_code(response)),
        "retryable": is_fcm_response_retryable(response.status_code),
    }


# FCM error codes that mean "this registration token will never work again" —
# the direct equivalent of APNs's 400 BadDeviceToken / 410 Unregistered. Any
# other error (including INVALID_ARGUMENT, which can also mean a malformed
# message rather than a bad token) is left as retryable/transient rather than
# risking disabling a device for a bug on our side.
_FCM_PERMANENT_ERROR_CODES = frozenset({"UNREGISTERED", "NOT_FOUND"})


def _normalise_pem_private_key(private_key: str) -> str:
    """Accept PEM values from either multiline files or escaped environment vars.

    Shared by APNs (EC key) and FCM (RSA service-account key) — this is pure
    text munging, not provider-specific."""
    return private_key.replace("\\n", "\n").strip()


def _build_apns_bearer(
    config: ApnsConfig,
    issued_at: int | None = None,
) -> str:
    """Build one short-lived APNs provider JWT; deliberately does not cache it."""
    if not config.team_id or not config.key_id or not config.private_key:
        raise RuntimeError("APNs provider-token configuration is incomplete")

    issued_at = int(time.time()) if issued_at is None else int(issued_at)
    bearer = apns_jwt.encode(
        {"alg": "ES256", "kid": config.key_id},
        {"iss": config.team_id, "iat": issued_at},
        _normalise_pem_private_key(config.private_key).encode("utf-8"),
    )
    if isinstance(bearer, bytes):
        bearer = bearer.decode("ascii")
    if not isinstance(bearer, str):
        raise RuntimeError("APNs JWT library returned an invalid token")
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
    configured = settings.apns_delivery_configured and bool(
        settings.apns_team_id and settings.apns_key_id and settings.apns_private_key
    )
    return ApnsConfig(
        configured=configured,
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
    bearer = _build_apns_bearer(config)
    request_payload = {
        "aps": {
            "alert": {"title": payload["title"], "body": payload["body"]},
            "sound": "default",
        },
        "deep_link": payload.get("deep_link"),
        "notification_type": payload.get("notification_type"),
    }
    # NULL is the backward-compatible state for registrations created before
    # per-device provenance existed. Those registrations historically used the
    # production endpoint and remain deliverable until the app re-registers.
    environment = device.apns_environment or "production"
    if environment not in ("sandbox", "production"):
        raise RuntimeError("Native device has an invalid APNs environment")
    endpoint = APNS_SANDBOX_ENDPOINT if environment == "sandbox" else APNS_PRODUCTION_ENDPOINT
    with httpx.Client(http2=True, timeout=10) as client:
        response = client.post(
            f"{endpoint}/3/device/{device.token}",
            headers={"authorization": f"bearer {bearer}", "apns-topic": topic},
            json=request_payload,
        )
    if not 200 <= response.status_code < 300:
        log.error("apns_delivery_failed", **apns_failure_diagnostics(response))
    if response.status_code in (400, 404, 410):
        raise ApnsPermanentError("APNs rejected this device registration")
    response.raise_for_status()


def resolve_fcm_config(settings: Settings) -> FcmConfig:
    configured = settings.fcm_delivery_configured and bool(
        settings.fcm_project_id and settings.fcm_client_email and settings.fcm_private_key
    )
    return FcmConfig(
        configured=configured,
        project_id=settings.fcm_project_id,
        client_email=settings.fcm_client_email,
        private_key=(
            settings.fcm_private_key.get_secret_value() if settings.fcm_private_key else None
        ),
    )


def _build_fcm_access_token(config: FcmConfig) -> str:
    """Exchange a signed service-account JWT assertion for a short-lived OAuth2
    access token (Google's documented server-to-server flow). Deliberately not
    cached, mirroring _build_apns_bearer's own "regenerate every call" choice
    — FCM sends are already infrequent enough (per outbox event, off the hot
    path) that the extra round-trip is not worth the complexity of a cache
    that could serve a stale/revoked token."""
    if not config.client_email or not config.private_key:
        raise RuntimeError("FCM service-account configuration is incomplete")
    issued_at = int(time.time())
    assertion = apns_jwt.encode(
        {"alg": "RS256"},
        {
            "iss": config.client_email,
            "scope": FCM_MESSAGING_SCOPE,
            "aud": FCM_TOKEN_ENDPOINT,
            "iat": issued_at,
            "exp": issued_at + 3600,
        },
        _normalise_pem_private_key(config.private_key).encode("utf-8"),
    )
    if isinstance(assertion, bytes):
        assertion = assertion.decode("ascii")
    with httpx.Client(timeout=10) as client:
        response = client.post(
            FCM_TOKEN_ENDPOINT,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Google OAuth token exchange returned no access token")
    return token


# Android notification channels (Phase 5). Android requires every
# notification to belong to a channel the app has already created on-device
# (apps/android-shell's MainActivity.java creates exactly these three,
# matching ids, at startup) — a channel_id the device hasn't created yet
# means the notification is silently dropped, not shown with a default
# channel. Deliberately a small, meaningful set rather than one channel per
# notification_type: this mirrors the existing preference taxonomy
# (engine.PREFERENCE_GATES) closely enough that "what does this channel
# contain" is obvious from Android's own Settings > Notifications screen,
# without fragmenting into ~20 near-duplicate channels a user would have to
# manage individually. See docs/architecture/notification-engine.md for the
# full channel-strategy writeup.
FCM_CHANNEL_GENERAL = "general"
FCM_CHANNEL_REMINDERS = "reminders"
FCM_CHANNEL_CALENDAR_FAMILY = "calendar_family"

_FCM_CHANNEL_BY_NOTIFICATION_TYPE: dict[str, str] = {
    "event_reminder": FCM_CHANNEL_REMINDERS,
    "household_routine_reminder": FCM_CHANNEL_REMINDERS,
    "birthday_reminder": FCM_CHANNEL_REMINDERS,
    "daily_nudge_summary": FCM_CHANNEL_REMINDERS,
    "nudges_day_complete": FCM_CHANNEL_REMINDERS,
    "nudges_evening_cleanup": FCM_CHANNEL_REMINDERS,
    "standalone_reminder": FCM_CHANNEL_REMINDERS,
    "event_invitation": FCM_CHANNEL_CALENDAR_FAMILY,
    "event_updated": FCM_CHANNEL_CALENDAR_FAMILY,
    "event_cancelled": FCM_CHANNEL_CALENDAR_FAMILY,
    "list_item_assigned": FCM_CHANNEL_CALENDAR_FAMILY,
    "wishlist_share_created": FCM_CHANNEL_CALENDAR_FAMILY,
    "wishlist_share_revoked": FCM_CHANNEL_CALENDAR_FAMILY,
    "calendar_share_invitation": FCM_CHANNEL_CALENDAR_FAMILY,
    "calendar_share_accepted": FCM_CHANNEL_CALENDAR_FAMILY,
    "calendar_share_declined": FCM_CHANNEL_CALENDAR_FAMILY,
    "calendar_share_revoked": FCM_CHANNEL_CALENDAR_FAMILY,
}


def fcm_channel_for_notification_type(notification_type: object) -> str:
    """Everything not explicitly mapped above (account/security types,
    daily_briefing, test/admin notifications, anything added later without
    an explicit channel decision) lands on FCM_CHANNEL_GENERAL — a safe,
    always-exists default rather than a KeyError or a silently dropped
    notification for an unmapped type."""
    if isinstance(notification_type, str):
        return _FCM_CHANNEL_BY_NOTIFICATION_TYPE.get(notification_type, FCM_CHANNEL_GENERAL)
    return FCM_CHANNEL_GENERAL


def send_fcm(config: FcmConfig, device: NativePushDevice, payload: dict[str, object]) -> None:
    if not config.configured or not config.project_id:
        raise RuntimeError("FCM delivery is not configured")
    access_token = _build_fcm_access_token(config)
    message = {
        "message": {
            "token": device.token,
            "notification": {"title": payload["title"], "body": payload["body"]},
            "data": {
                "notification_type": str(payload.get("notification_type") or ""),
                "deep_link": json.dumps(payload.get("deep_link"))
                if payload.get("deep_link")
                else "",
            },
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": fcm_channel_for_notification_type(
                        payload.get("notification_type")
                    ),
                },
            },
        }
    }
    with httpx.Client(timeout=10) as client:
        response = client.post(
            FCM_SEND_ENDPOINT.format(project_id=config.project_id),
            headers={"authorization": f"Bearer {access_token}"},
            json=message,
        )
    if not 200 <= response.status_code < 300:
        log.error("fcm_delivery_failed", **fcm_failure_diagnostics(response))
        if _fcm_error_code(response) in _FCM_PERMANENT_ERROR_CODES:
            raise FcmPermanentError("FCM rejected this device registration")
    response.raise_for_status()
