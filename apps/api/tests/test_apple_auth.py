from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from authlib.jose import JsonWebKey, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr

from mykhaya.apple_auth import (
    AppleAuthenticationError,
    apple_client_identifier,
    authorization_url,
    build_client_secret,
    verify_identity_token,
)
from mykhaya.auth_providers import external_auth_provider_status
from mykhaya.config import Settings


def apple_settings(private_key: str | None = None, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "secret_key": "test-only-secret-key-never-used-in-production-1234",
        "apple_sign_in_enabled": True,
        "apple_service_id": "com.example.web",
        "apple_team_id": "TEAM123",
        "apple_key_id": "KEY123",
        "apple_private_key": SecretStr(private_key or "not-a-real-key"),
        "public_web_url": "http://localhost:8080",
    }
    values.update(overrides)
    return Settings(**values)


def signing_material() -> tuple[str, dict[str, Any]]:
    private = ec.generate_private_key(ec.SECP256R1())
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_jwk = JsonWebKey.import_key(public_pem).as_dict(is_private=False)
    public_jwk["kid"] = "APPLE-KID"
    return private_pem, public_jwk


def signed_token(private_pem: str, **claims: Any) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": "https://appleid.apple.com",
        "aud": "com.example.web",
        "sub": "apple-subject-123",
        "nonce": "expected-nonce",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "email": "relay@example.com",
        "email_verified": True,
    }
    payload.update(claims)
    encoded = jwt.encode({"alg": "ES256", "kid": "APPLE-KID"}, payload, private_pem)
    return encoded.decode() if isinstance(encoded, bytes) else encoded


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, _url: str) -> FakeResponse:
        return self.response


def test_authorization_url_contains_state_nonce_and_exact_redirect() -> None:
    settings = apple_settings()
    url = authorization_url(settings, "state-value", "nonce-value")
    assert "client_id=com.example.web" in url
    assert "state=state-value" in url
    assert "nonce=nonce-value" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fapi%2Fv1%2Fauth%2Fapple%2Fcallback" in url


def test_client_secret_is_signed_server_side_and_never_uses_public_response_data() -> None:
    private_pem, _public_jwk = signing_material()
    settings = apple_settings(private_pem)
    token = build_client_secret(settings, now=1_700_000_000)
    claims = jwt.decode(token, settings.apple_private_key.get_secret_value())
    assert claims["iss"] == "TEAM123"
    assert claims["sub"] == apple_client_identifier(settings)
    assert "apple_private_key" not in external_auth_provider_status(settings, "apple").public_dict()


@pytest.mark.asyncio
async def test_identity_token_requires_issuer_audience_nonce_subject_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_pem, public_jwk = signing_material()
    settings = apple_settings(private_pem, apple_key_id="APPLE-KID")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda timeout: FakeClient(FakeResponse({"keys": [public_jwk]})),
    )

    claims = await verify_identity_token(settings, signed_token(private_pem), "expected-nonce")
    assert claims["sub"] == "apple-subject-123"
    assert claims["email"] == "relay@example.com"

    for invalid in (
        {"iss": "https://evil.example"},
        {"aud": "wrong-client"},
        {"nonce": "wrong-nonce"},
        {"sub": ""},
        {"exp": 1},
    ):
        with pytest.raises(AppleAuthenticationError):
            await verify_identity_token(
                settings, signed_token(private_pem, **invalid), "expected-nonce"
            )


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    private_pem, public_jwk = signing_material()
    other_private_pem, _ = signing_material()
    settings = apple_settings(private_pem, apple_key_id="APPLE-KID")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda timeout: FakeClient(FakeResponse({"keys": [public_jwk]})),
    )
    with pytest.raises(AppleAuthenticationError):
        await verify_identity_token(settings, signed_token(other_private_pem), "expected-nonce")
