"""Focused tests for the explicit, console-only APNs JWT diagnostic."""

from types import SimpleNamespace

from pydantic import SecretStr

from mykhaya.notifications import apns_diagnostic
from mykhaya.notifications.push import _normalise_apns_private_key


def _private_key_pem() -> str:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    return ec.generate_private_key(ec.SECP256R1()).private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode()


def test_diagnostic_uses_production_signer_and_prints_only_explicit_output(
    monkeypatch, capsys
) -> None:
    settings = SimpleNamespace(
        apns_delivery_configured=True,
        apns_team_id="TEAM123",
        apns_key_id="KEY123",
        apns_bundle_id="app.mykhaya.mobile",
        apns_private_key=SecretStr(_private_key_pem()),
    )
    private_key = settings.apns_private_key.get_secret_value()
    before = settings.__dict__.copy()
    calls = []
    real_signer = apns_diagnostic._build_apns_bearer

    def signer(*args, **kwargs):
        calls.append((args, kwargs))
        return real_signer(*args, **kwargs)

    monkeypatch.setattr(apns_diagnostic, "get_settings", lambda: settings)
    monkeypatch.setattr(apns_diagnostic, "_build_apns_bearer", signer)

    apns_diagnostic.main()

    output = capsys.readouterr().out
    assert len(calls) == 1
    assert calls[0][1]["topic"] == "app.mykhaya.mobile"
    assert "This JWT is a temporary APNs credential" in output
    assert "key_id=KEY123" in output
    assert "team_id=TEAM123" in output
    assert "algorithm=ES256" in output
    assert "endpoint_environment=production" in output
    assert "jwt=" in output
    assert private_key not in output
    assert "device-token" not in output
    assert settings.__dict__ == before


def test_diagnostic_does_not_send_or_expose_configuration(monkeypatch, capsys) -> None:
    settings = SimpleNamespace(
        apns_delivery_configured=True,
        apns_team_id="TEAM123",
        apns_key_id="KEY123",
        apns_bundle_id="app.mykhaya.mobile",
        apns_private_key=SecretStr(_private_key_pem()),
    )
    private_key = settings.apns_private_key.get_secret_value()
    monkeypatch.setattr(apns_diagnostic, "get_settings", lambda: settings)
    monkeypatch.setattr(
        apns_diagnostic,
        "_build_apns_bearer",
        lambda *args, **kwargs: "diagnostic-jwt",
    )

    apns_diagnostic.main()

    output = capsys.readouterr().out
    assert "diagnostic-jwt" in output
    assert settings.apns_bundle_id == "app.mykhaya.mobile"
    assert private_key not in output
    assert "BEGIN PRIVATE KEY" not in output
    assert "secret-device-token" not in output
    assert "Authorization" not in output


def test_diagnostic_key_normalization_is_the_production_parser_input() -> None:
    multiline = _private_key_pem()
    assert _normalise_apns_private_key(multiline) == multiline.strip()
    assert _normalise_apns_private_key(multiline.replace("\n", r"\n")) == multiline.strip()
