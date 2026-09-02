"""Focused tests for safe APNs JWT structural comparison."""

import base64
import json
from types import SimpleNamespace

from pydantic import SecretStr

from mykhaya.notifications import apns_jwt_compare
from mykhaya.notifications.push import _build_apns_bearer


def _private_key_pem() -> str:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    return ec.generate_private_key(ec.SECP256R1()).private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode()


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        apns_delivery_configured=True,
        apns_team_id="TEAM123",
        apns_key_id="KEY123",
        apns_bundle_id="app.mykhaya.mobile",
        apns_private_key=SecretStr(_private_key_pem()),
    )


def _segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def _raw_segment(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).rstrip(b"=").decode()


def test_compare_prints_safe_structure_and_never_prints_either_jwt(monkeypatch, capsys) -> None:
    settings = _settings()
    mykhaya_token = _build_apns_bearer(
        apns_jwt_compare.resolve_apns_config(settings),
        issued_at=1_700_000_000,
        topic="app.mykhaya.mobile",
        emit_diagnostics=False,
    )
    apple_token = ".".join(
        (
            _segment({"alg": "ES256", "kid": "KEY123", "typ": "JWT"}),
            _segment({"iss": "TEAM123", "iat": 1_700_000_000, "exp": 1_700_060_000}),
            _segment("signature"),
        )
    )
    monkeypatch.setattr(apns_jwt_compare, "get_settings", lambda: settings)

    assert apns_jwt_compare.main(["--apple-jwt", apple_token]) == 0

    output = capsys.readouterr().out
    assert apple_token not in output
    assert mykhaya_token not in output
    assert "apple.alg=ES256" in output
    assert "apple.header_contains_typ=true" in output
    assert "apple.unexpected_claims=exp" in output
    assert "mykhaya.signature_bytes=64" in output
    assert "header_keyset_equal=true" in output
    assert "payload_keyset_equal=false" in output
    assert "signature_length_equal=false" in output
    assert "private" not in output.lower()
    assert "device" not in output.lower()


def test_inspect_jwt_reports_duplicate_keys_invalid_utf8_and_padding() -> None:
    duplicate = ".".join(
        (
            _raw_segment('{"alg":"ES256","alg":"ES256","kid":"KEY123"}'),
            _segment({"iss": "TEAM123", "iat": 1_700_000_000}),
            _segment("x"),
        )
    )
    inspected = apns_jwt_compare.inspect_jwt(duplicate)
    assert inspected.valid is False
    assert inspected.duplicate_keys == ("alg",)


def test_compare_does_not_change_settings(monkeypatch, capsys) -> None:
    settings = _settings()
    before = settings.__dict__.copy()
    token = _build_apns_bearer(
        apns_jwt_compare.resolve_apns_config(settings),
        issued_at=1_700_000_000,
        topic="app.mykhaya.mobile",
        emit_diagnostics=False,
    )
    monkeypatch.setattr(apns_jwt_compare, "get_settings", lambda: settings)

    apns_jwt_compare.main(["--apple-jwt", token])

    capsys.readouterr()
    assert settings.__dict__ == before
