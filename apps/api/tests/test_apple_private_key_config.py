from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from pydantic import SecretStr

from mykhaya.apple_auth import build_client_secret
from mykhaya.config import Settings


def _private_pem() -> str:
    return ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _settings(**values: object) -> Settings:
    return Settings(
        _env_file=None,
        secret_key="test-only-secret-key-never-used-in-production-1234",
        apple_sign_in_enabled=True,
        apple_service_id="app.mykhaya.auth.dev",
        apple_team_id="M86392YDLQ",
        apple_key_id="JS8D8TTA92",
        **values,
    )


def test_valid_file_is_loaded_as_pem_and_signing_works(tmp_path: Path) -> None:
    pem = _private_pem()
    path = tmp_path / "apple-sign-in.p8"
    path.write_text(pem, encoding="utf-8")

    settings = _settings(apple_private_key_file=str(path))

    assert settings.apple_private_key is not None
    assert settings.apple_private_key.get_secret_value() == pem
    assert pem not in repr(settings.model_dump())
    assert build_client_secret(settings, now=1_700_000_000)


def test_environment_key_remains_supported() -> None:
    pem = _private_pem()

    settings = _settings(apple_private_key=SecretStr(pem))

    assert settings.apple_private_key is not None
    assert settings.apple_private_key.get_secret_value() == pem


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing or inaccessible"):
        _settings(apple_private_key_file=str(tmp_path / "missing.p8"))


def test_unreadable_file_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "apple-sign-in.p8"
    path.write_text(_private_pem(), encoding="utf-8")
    original_read_text = Path.read_text

    def denied_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == path:
            raise PermissionError("synthetic permission failure")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied_read_text)

    with pytest.raises(ValueError, match="missing or inaccessible"):
        _settings(apple_private_key_file=str(path))


def test_malformed_file_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "apple-sign-in.p8"
    path.write_text("not a private key", encoding="utf-8")

    with pytest.raises(ValueError, match="P-256 PEM key"):
        _settings(apple_private_key_file=str(path))


@pytest.mark.parametrize(
    "private_key",
    [
        lambda: ec.generate_private_key(ec.SECP384R1()).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        lambda: ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"test-password"),
        ),
    ],
)
def test_encrypted_non_ec_and_non_p256_files_fail_closed(
    tmp_path: Path, private_key
) -> None:
    path = tmp_path / "apple-sign-in.p8"
    path.write_bytes(private_key())

    with pytest.raises(ValueError, match="P-256 PEM key"):
        _settings(apple_private_key_file=str(path))


def test_conflicting_sources_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "apple-sign-in.p8"
    path.write_text(_private_pem(), encoding="utf-8")

    with pytest.raises(ValueError, match="must not both be configured"):
        _settings(
            apple_private_key=SecretStr(_private_pem()),
            apple_private_key_file=str(path),
        )
