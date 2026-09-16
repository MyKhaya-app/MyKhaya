"""Focused unit coverage for native FCM delivery boundaries (Phase 5).

Mirrors tests/test_native_push.py's structure and fake-httpx-client style for
the APNs sender — FCM adds one extra network hop (the OAuth2 token exchange
before the actual send), so the fake client here dispatches on URL.
"""

import base64
import json
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from mykhaya.models import NativePushDevice
from mykhaya.notifications import push
from mykhaya.notifications.push import FcmConfig, FcmPermanentError, send_fcm


def _private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


def _device() -> NativePushDevice:
    return NativePushDevice(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        platform="android",
        token="fcm-registration-token-" + "a" * 40,
        installation_id="installation-abcdef123456",
    )


def _config(**overrides: object) -> FcmConfig:
    defaults: dict[str, object] = {
        "configured": True,
        "project_id": "mykhaya-prod",
        "client_email": "fcm@mykhaya-prod.iam.gserviceaccount.com",
        "private_key": _private_key_pem(),
    }
    defaults.update(overrides)
    return FcmConfig(**defaults)  # type: ignore[arg-type]


class _FakeFcmClient:
    token_response_status = 200
    token_response_body: dict[str, object] | None = None
    send_response_status = 200
    send_response_body: dict[str, object] | None = None

    def __init__(self, **_: object) -> None:
        self.requests: list[httpx.Request] = []
        self.messages: list[dict[str, object]] = []

    def __enter__(self) -> "_FakeFcmClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        headers = kwargs.get("headers") or {}
        request = httpx.Request("POST", url, headers=headers, data=kwargs.get("data"))
        self.requests.append(request)
        if url == push.FCM_TOKEN_ENDPOINT:
            body = self.token_response_body
            if body is None:
                body = {"access_token": "test-access-token", "expires_in": 3599}
            return httpx.Response(self.token_response_status, request=request, json=body)
        message = kwargs.get("json")
        if isinstance(message, dict):
            self.messages.append(message)
        return httpx.Response(
            self.send_response_status, request=request, json=self.send_response_body
        )


def _install(monkeypatch: pytest.MonkeyPatch) -> _FakeFcmClient:
    fake = _FakeFcmClient()
    monkeypatch.setattr("mykhaya.notifications.push.httpx.Client", lambda **kwargs: fake)
    return fake


def test_send_fcm_exchanges_token_then_sends_notification_and_data_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch)
    config = _config()

    send_fcm(
        config,
        _device(),
        {
            "title": "Dinner",
            "body": "Dinner starts soon",
            "deep_link": {"type": "calendar_event", "id": "abc"},
            "notification_type": "event_reminder",
        },
    )

    assert [str(r.url) for r in fake.requests] == [
        push.FCM_TOKEN_ENDPOINT,
        push.FCM_SEND_ENDPOINT.format(project_id="mykhaya-prod"),
    ]
    send_request = fake.requests[1]
    assert send_request.headers["authorization"] == "Bearer test-access-token"
    assert fake.messages == [
        {
            "message": {
                "token": "fcm-registration-token-" + "a" * 40,
                "notification": {"title": "Dinner", "body": "Dinner starts soon"},
                "data": {
                    "notification_type": "event_reminder",
                    "deep_link": json.dumps({"type": "calendar_event", "id": "abc"}),
                },
                "android": {"priority": "high", "notification": {"channel_id": "reminders"}},
            }
        }
    ]


def test_fcm_access_token_uses_rs256_and_service_account_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch)
    issued_at = 1_700_000_000
    monkeypatch.setattr("mykhaya.notifications.push.time.time", lambda: issued_at)
    config = _config()

    send_fcm(config, _device(), {"title": "T", "body": "B"})

    token_request = fake.requests[0]
    assertion = None
    for part in token_request.content.decode().split("&"):
        key, _, value = part.partition("=")
        if key == "assertion":
            from urllib.parse import unquote

            assertion = unquote(value)
    assert assertion is not None
    header, claims, _signature = assertion.split(".")

    def decode(value: str) -> dict[str, object]:
        return json.loads(base64.urlsafe_b64decode(value + "=="))

    assert decode(header)["alg"] == "RS256"
    assert decode(claims) == {
        "iss": "fcm@mykhaya-prod.iam.gserviceaccount.com",
        "scope": push.FCM_MESSAGING_SCOPE,
        "aud": push.FCM_TOKEN_ENDPOINT,
        "iat": issued_at,
        "exp": issued_at + 3600,
    }


def test_send_fcm_classifies_unregistered_token_as_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch)
    fake.send_response_status = 404
    fake.send_response_body = {
        "error": {
            "code": 404,
            "message": "Requested entity was not found.",
            "status": "NOT_FOUND",
            "details": [
                {
                    "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                    "errorCode": "UNREGISTERED",
                }
            ],
        }
    }
    config = _config()

    with pytest.raises(FcmPermanentError):
        send_fcm(config, _device(), {"title": "T", "body": "B"})


def test_send_fcm_treats_invalid_argument_as_retryable_not_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed-message bug on our side must not silently disable a device
    the way a genuinely dead token does — only UNREGISTERED/NOT_FOUND do."""
    fake = _install(monkeypatch)
    fake.send_response_status = 400
    fake.send_response_body = {
        "error": {"code": 400, "message": "Invalid value.", "status": "INVALID_ARGUMENT"}
    }
    config = _config()

    with pytest.raises(httpx.HTTPStatusError):
        send_fcm(config, _device(), {"title": "T", "body": "B"})


def test_send_fcm_logs_safe_failure_diagnostics_without_body_or_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch)
    fake.send_response_status = 500
    fake.send_response_body = {
        "error": {"code": 500, "message": "Backend error", "status": "INTERNAL"}
    }
    captured: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(push.log, "error", lambda *args, **kwargs: captured.append((args, kwargs)))
    config = _config()

    with pytest.raises(httpx.HTTPStatusError):
        send_fcm(config, _device(), {"title": "T", "body": "B"})

    assert captured == [
        (("fcm_delivery_failed",), {"status": 500, "error_code": "INTERNAL", "retryable": True})
    ]
    logged = json.dumps(captured)
    assert "fcm-registration-token" not in logged
    assert "PRIVATE KEY" not in logged
    assert "Bearer" not in logged


@pytest.mark.parametrize(
    ("notification_type", "expected_channel"),
    [
        ("event_reminder", "reminders"),
        ("household_routine_reminder", "reminders"),
        ("birthday_reminder", "reminders"),
        ("daily_nudge_summary", "reminders"),
        ("nudges_day_complete", "reminders"),
        ("nudges_evening_cleanup", "reminders"),
        ("standalone_reminder", "reminders"),
        ("event_invitation", "calendar_family"),
        ("event_updated", "calendar_family"),
        ("event_cancelled", "calendar_family"),
        ("list_item_assigned", "calendar_family"),
        ("wishlist_share_created", "calendar_family"),
        ("wishlist_share_revoked", "calendar_family"),
        ("calendar_share_invitation", "calendar_family"),
        ("calendar_share_accepted", "calendar_family"),
        ("calendar_share_declined", "calendar_family"),
        ("calendar_share_revoked", "calendar_family"),
        ("daily_briefing", "general"),
        ("test_push", "general"),
        ("platform_test_notification", "general"),
        ("home_join_request", "general"),
        ("some_future_unmapped_type", "general"),
        (None, "general"),
    ],
)
def test_fcm_channel_for_notification_type(
    notification_type: object, expected_channel: str
) -> None:
    assert push.fcm_channel_for_notification_type(notification_type) == expected_channel


def test_send_fcm_raises_when_not_configured() -> None:
    with pytest.raises(RuntimeError):
        send_fcm(FcmConfig(configured=False), _device(), {"title": "T", "body": "B"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"fcm_project_id": None},
        {"fcm_client_email": None},
        {"fcm_private_key": None},
    ],
)
def test_resolve_fcm_config_requires_all_three_service_account_fields(
    overrides: dict[str, object],
) -> None:
    from mykhaya.config import Settings

    base: dict[str, object] = {
        "secret_key": "test-only-secret-key-never-used-in-production-1234",
        "fcm_delivery_configured": True,
        "fcm_project_id": "proj",
        "fcm_client_email": "svc@proj.iam.gserviceaccount.com",
        "fcm_private_key": "key",
    }
    base.update(overrides)
    settings = Settings(**base)  # type: ignore[arg-type]

    config = push.resolve_fcm_config(settings)

    assert config.configured is False
