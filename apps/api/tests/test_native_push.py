"""Focused unit coverage for native APNs delivery boundaries."""

import base64
import json
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from mykhaya.models import NativePushDevice
from mykhaya.notifications.push import ApnsConfig, ApnsPermanentError, send_apns


def _private_key_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


class _FakeClient:
    response_status = 200
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
        return httpx.Response(self.response_status, request=self.request)


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
