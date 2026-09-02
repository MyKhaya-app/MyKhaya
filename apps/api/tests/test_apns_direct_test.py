"""Focused tests for the temporary direct APNs diagnostic."""

import uuid
from io import StringIO
from types import SimpleNamespace

import httpx
from pydantic import SecretStr

from mykhaya.models import NativePushDevice
from mykhaya.notifications import apns_direct_test


def _private_key_pem() -> str:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    return ec.generate_private_key(ec.SECP256R1()).private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode()


class _FakeDb:
    def __init__(self, device: NativePushDevice) -> None:
        self.device = device
        self.scalar_calls = 0
        self.write_calls = 0

    async def __aenter__(self) -> "_FakeDb":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def scalar(self, statement: object) -> NativePushDevice:
        self.scalar_calls += 1
        return self.device

    def add(self, value: object) -> None:
        self.write_calls += 1

    async def commit(self) -> None:
        self.write_calls += 1


class _FakeClient:
    response_status = 200
    response_body: dict[str, str] | None = None
    response_headers = {"apns-id": "request-id-123"}
    http2_values: list[bool] = []
    request: httpx.Request | None = None
    payload: dict[str, object] | None = None

    def __init__(self, *, http2: bool = True, **_: object) -> None:
        self.http2_values.append(http2)

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


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        apns_delivery_configured=True,
        apns_team_id="TEAM123",
        apns_key_id="KEY123",
        apns_bundle_id="app.mykhaya.mobile",
        apns_private_key=SecretStr(_private_key_pem()),
    )


def _device() -> NativePushDevice:
    return NativePushDevice(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        platform="ios",
        token="secret-device-token",
        installation_id="installation-123456",
    )


def test_direct_test_uses_production_http2_headers_and_redacts_secrets(monkeypatch, capsys) -> None:
    fake_db = _FakeDb(_device())
    fake_client = _FakeClient()
    monkeypatch.setattr(apns_direct_test, "get_settings", _settings)
    monkeypatch.setattr(apns_direct_test, "SessionFactory", lambda: fake_db)
    monkeypatch.setattr(apns_direct_test.httpx, "Client", lambda **kwargs: fake_client)

    assert apns_direct_test.main([]) == 0

    output = capsys.readouterr().out
    assert "status=200" in output
    assert "request_id=request-id-123" in output
    assert "success=true" in output
    assert "secret-device-token" not in output
    assert "TEAM123" not in output
    assert "BEGIN PRIVATE KEY" not in output
    assert fake_client.http2_values == [True]
    assert fake_client.request is not None
    assert fake_client.request.url == "https://api.push.apple.com/3/device/secret-device-token"
    assert fake_client.request.headers["apns-topic"] == "app.mykhaya.mobile"
    assert fake_client.request.headers["apns-push-type"] == "alert"
    assert fake_client.request.headers["apns-priority"] == "10"
    assert fake_db.scalar_calls == 1
    assert fake_db.write_calls == 0


def test_direct_test_extracts_400_403_and_410_reasons(monkeypatch, capsys) -> None:
    fake_db = _FakeDb(_device())
    fake_client = _FakeClient()
    monkeypatch.setattr(apns_direct_test, "get_settings", _settings)
    monkeypatch.setattr(apns_direct_test, "SessionFactory", lambda: fake_db)
    monkeypatch.setattr(apns_direct_test.httpx, "Client", lambda **kwargs: fake_client)

    for status, reason in (
        (400, "BadDeviceToken"),
        (403, "InvalidProviderToken"),
        (410, "Unregistered"),
    ):
        fake_client.response_status = status
        fake_client.response_body = {"reason": reason}
        assert apns_direct_test.main([]) == 1
        output = capsys.readouterr().out
        assert f"status={status}" in output
        assert f"reason={reason}" in output
        assert "success=false" in output


def test_direct_test_jwt_stdin_changes_only_authorization(monkeypatch, capsys) -> None:
    fake_db = _FakeDb(_device())
    fake_client = _FakeClient()
    supplied_jwt = "apple-generated-jwt"
    monkeypatch.setattr(apns_direct_test, "get_settings", _settings)
    monkeypatch.setattr(apns_direct_test, "SessionFactory", lambda: fake_db)
    monkeypatch.setattr(apns_direct_test.httpx, "Client", lambda **kwargs: fake_client)
    monkeypatch.setattr(
        apns_direct_test,
        "_build_apns_bearer",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("signer called")),
    )
    monkeypatch.setattr("sys.stdin", StringIO(f"  {supplied_jwt}\n"))

    assert apns_direct_test.main(["--jwt-stdin"]) == 0

    output = capsys.readouterr().out
    assert supplied_jwt not in output
    assert "status=200" in output
    assert "success=true" in output
    assert fake_client.request is not None
    request = fake_client.request
    assert request.headers["authorization"] == f"bearer {supplied_jwt}"
    assert request.url == "https://api.push.apple.com/3/device/secret-device-token"
    assert request.headers["apns-topic"] == "app.mykhaya.mobile"
    assert request.headers["apns-push-type"] == "alert"
    assert request.headers["apns-priority"] == "10"
    assert fake_client.payload == apns_direct_test.APNS_DIRECT_PAYLOAD
    assert fake_client.http2_values[-1] is True
