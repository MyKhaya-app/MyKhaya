"""Focused unit coverage for native APNs delivery boundaries."""

import base64
import json
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)

from mykhaya.models import NativePushDevice
from mykhaya.notifications import push
from mykhaya.notifications.push import ApnsConfig, ApnsPermanentError, send_apns


def _private_key_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


class _FakeClient:
    response_status = 200
    response_body: dict[str, str] | None = None
    response_headers: dict[str, str] = {}
    request: httpx.Request | None = None
    payload: dict[str, object] | None = None

    def __init__(self, **_: object) -> None:
        pass

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
        self.request = httpx.Request("POST", url, headers=headers, json=json)
        self.payload = json
        return httpx.Response(
            self.response_status,
            request=self.request,
            headers=self.response_headers,
            json=self.response_body,
        )


def _device() -> NativePushDevice:
    return NativePushDevice(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        platform="ios",
        token="a" * 64,
        installation_id="installation-123456",
    )


def test_send_apns_uses_signed_bearer_and_safe_alert_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    monkeypatch.setattr("mykhaya.notifications.push.httpx.Client", lambda **kwargs: fake)
    config = ApnsConfig(
        configured=True,
        team_id="TEAM123",
        key_id="KEY123",
        bundle_id="app.mykhaya.mobile",
        private_key=_private_key_pem(),
    )

    send_apns(
        config,
        _device(),
        {
            "title": "Dinner",
            "body": "Dinner starts soon",
            "deep_link": {"path": "/calendar"},
            "notification_type": "event_reminder",
        },
    )

    assert fake.request is not None
    assert fake.request.url.path.startswith("/3/device/")
    authorization = fake.request.headers["authorization"]
    assert authorization.startswith("bearer ey")
    token = authorization.removeprefix("bearer ").split(".")
    assert len(token) == 3
    assert json.loads(base64.urlsafe_b64decode(token[1] + "=="))["iss"] == "TEAM123"
    assert fake.payload == {
        "aps": {"alert": {"title": "Dinner", "body": "Dinner starts soon"}, "sound": "default"},
        "deep_link": {"path": "/calendar"},
        "notification_type": "event_reminder",
    }
    assert "password" not in json.dumps(fake.payload).lower()
    assert "authorization" not in json.dumps(fake.payload).lower()


@pytest.mark.parametrize(
    "private_key",
    [_private_key_pem(), _private_key_pem().replace("\n", r"\n")],
)
def test_apns_accepts_multiline_and_escaped_newline_private_keys(
    monkeypatch: pytest.MonkeyPatch, private_key: str
) -> None:
    fake = _FakeClient()
    monkeypatch.setattr("mykhaya.notifications.push.httpx.Client", lambda **kwargs: fake)
    config = ApnsConfig(
        configured=True,
        team_id="TEAM123",
        key_id="KEY123",
        private_key=private_key,
    )

    send_apns(config, _device(), {"title": "T", "body": "B"})

    assert fake.request is not None
    assert fake.request.headers["authorization"].startswith("bearer ")


def test_apns_jwt_uses_configured_kid_iss_seconds_and_es256(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    diagnostics: list[dict[str, object]] = []
    signer_calls: list[tuple[object, object, object]] = []
    monkeypatch.setattr("mykhaya.notifications.push.httpx.Client", lambda **kwargs: fake)
    monkeypatch.setattr(
        push.log, "info", lambda *args, **kwargs: diagnostics.append(kwargs)
    )
    real_encode = push.apns_jwt.encode

    def encode(header: object, payload: object, key: object) -> object:
        signer_calls.append((header, payload, key))
        return real_encode(header, payload, key)

    monkeypatch.setattr(push.apns_jwt, "encode", encode)
    issued_at = 1_700_000_000
    monkeypatch.setattr("mykhaya.notifications.push.time.time", lambda: issued_at)
    config = ApnsConfig(
        configured=True,
        team_id="TEAM123",
        key_id="KEY123",
        bundle_id="app.mykhaya.mobile",
        private_key=_private_key_pem(),
    )

    send_apns(config, _device(), {"title": "T", "body": "B"})

    assert signer_calls == [
        (
            {"alg": "ES256", "kid": "KEY123", "typ": "JWT"},
            {"iss": "TEAM123", "iat": issued_at},
            config.private_key.strip().encode(),
        )
    ]
    assert fake.request is not None
    encoded = fake.request.headers["authorization"].removeprefix("bearer ").split(".")
    def decode(value: str) -> dict[str, object]:
        return json.loads(base64.urlsafe_b64decode(value + "=="))
    assert decode(encoded[0]) == {"alg": "ES256", "kid": "KEY123", "typ": "JWT"}
    assert decode(encoded[1]) == {"iss": "TEAM123", "iat": issued_at}
    signature = base64.urlsafe_b64decode(encoded[2] + "==")
    assert len(signature) == 64
    assert len(signature[:32]) == 32
    assert len(signature[32:]) == 32
    assert "=" not in encoded[2]
    key = load_pem_private_key(config.private_key.encode(), password=None)
    assert isinstance(key, ec.EllipticCurvePrivateKey)
    key.public_key().verify(
        encode_dss_signature(
            int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
        ),
        f"{encoded[0]}.{encoded[1]}".encode("ascii"),
        ec.ECDSA(hashes.SHA256()),
    )
    assert fake.request.headers["apns-topic"] == "app.mykhaya.mobile"
    assert fake.request.url.host == "api.push.apple.com"
    assert diagnostics == [{
            "jwt_kid_matches_config": True,
            "jwt_iss_matches_config": True,
            "jwt_iat_age_seconds": 0,
            "private_key_parsed": True,
            "apns_endpoint": "production",
            "apns_topic_matches_bundle": True,
        }]


def test_apns_provider_token_is_not_cached_and_refreshes_before_one_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    monkeypatch.setattr("mykhaya.notifications.push.httpx.Client", lambda **kwargs: fake)
    now = 1_700_000_000
    monkeypatch.setattr("mykhaya.notifications.push.time.time", lambda: now)
    config = ApnsConfig(
        configured=True,
        team_id="TEAM123",
        key_id="KEY123",
        private_key=_private_key_pem(),
    )

    send_apns(config, _device(), {"title": "T", "body": "B"})
    first = fake.request.headers["authorization"] if fake.request else ""
    now += 3_500
    send_apns(config, _device(), {"title": "T", "body": "B"})
    second = fake.request.headers["authorization"] if fake.request else ""

    assert first != second
    assert json.loads(base64.urlsafe_b64decode(first.split(".")[1] + "=="))["iat"] == 1_700_000_000
    assert json.loads(base64.urlsafe_b64decode(second.split(".")[1] + "=="))["iat"] == 1_700_003_500


def test_apns_jwt_diagnostics_never_log_token_or_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        push.log, "info", lambda *args, **kwargs: captured.append((args, kwargs))
    )
    issued_at = 1_700_000_000
    monkeypatch.setattr("mykhaya.notifications.push.time.time", lambda: issued_at)
    private_key = _private_key_pem()
    config = ApnsConfig(
        configured=True,
        team_id="TEAM123",
        key_id="KEY123",
        bundle_id="app.mykhaya.mobile",
        private_key=private_key,
    )

    push._build_apns_bearer(config, topic="app.mykhaya.mobile")

    logged = json.dumps(captured)
    assert private_key not in logged
    assert "TEAM123" not in logged
    assert "KEY123" not in logged
    assert "secret-device-token" not in logged


def test_send_apns_classifies_device_rejection_as_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    fake.response_status = 410
    monkeypatch.setattr("mykhaya.notifications.push.httpx.Client", lambda **kwargs: fake)
    config = ApnsConfig(
        configured=True,
        team_id="TEAM123",
        key_id="KEY123",
        private_key=_private_key_pem(),
    )

    with pytest.raises(ApnsPermanentError):
        send_apns(config, _device(), {"title": "T", "body": "B"})


@pytest.mark.parametrize(
    ("status", "reason", "retryable", "exception"),
    [
        (400, "BadDeviceToken", False, ApnsPermanentError),
        (403, "InvalidProviderToken", False, httpx.HTTPStatusError),
        (410, "Unregistered", False, ApnsPermanentError),
        (500, "InternalServerError", True, httpx.HTTPStatusError),
    ],
)
def test_send_apns_logs_safe_failure_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    reason: str,
    retryable: bool,
    exception: type[Exception],
) -> None:
    fake = _FakeClient()
    fake.response_status = status
    fake.response_body = {"reason": reason}
    fake.response_headers = {"apns-id": "request-id-123"}
    monkeypatch.setattr("mykhaya.notifications.push.httpx.Client", lambda **kwargs: fake)
    captured: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(push.log, "error", lambda *args, **kwargs: captured.append((args, kwargs)))
    config = ApnsConfig(
        configured=True,
        team_id="TEAM123",
        key_id="KEY123",
        private_key=_private_key_pem(),
    )

    with pytest.raises(exception):
        send_apns(config, _device(), {"title": "T", "body": "B"})

    assert captured == [
        (
            ("apns_delivery_failed",),
            {
                "status": status,
                "reason": reason,
                "request_id": "request-id-123",
                "retryable": retryable,
            },
        )
    ]


def test_send_apns_failure_diagnostics_never_log_response_body_or_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    fake.response_status = 403
    fake.response_body = {
        "reason": "InvalidProviderToken",
        "token": "secret-device-token",
        "private_key": "-----BEGIN PRIVATE KEY----- secret-key",
    }
    fake.response_headers = {"apns-id": "safe-request-id"}
    monkeypatch.setattr("mykhaya.notifications.push.httpx.Client", lambda **kwargs: fake)
    captured: list[object] = []
    monkeypatch.setattr(push.log, "error", lambda *args, **kwargs: captured.append((args, kwargs)))
    config = ApnsConfig(
        configured=True,
        team_id="TEAM123",
        key_id="KEY123",
        private_key=_private_key_pem(),
    )

    with pytest.raises(httpx.HTTPStatusError):
        send_apns(config, _device(), {"title": "T", "body": "B"})

    logged = json.dumps(captured)
    assert "secret-device-token" not in logged
    assert "PRIVATE KEY" not in logged
    assert "authorization" not in logged.lower()
    assert "request_payload" not in logged
