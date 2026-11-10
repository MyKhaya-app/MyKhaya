from urllib.parse import parse_qs, urlparse

from mykhaya.config import Settings
from mykhaya.google_auth import authorization_url, code_challenge, new_code_verifier


def _settings() -> Settings:
    return Settings(
        secret_key="test-only-secret-key-never-used-in-production-1234",
        google_sign_in_enabled=True,
        google_client_id="client-id.apps.googleusercontent.com",
        google_client_secret="test-secret",
    )


def test_google_authorization_uses_pkce_nonce_and_single_provider_scope() -> None:
    verifier = new_code_verifier()
    url = authorization_url(_settings(), "state-value", "nonce-value", verifier)
    query = parse_qs(urlparse(url).query)

    assert query["client_id"] == ["client-id.apps.googleusercontent.com"]
    assert query["state"] == ["state-value"]
    assert query["nonce"] == ["nonce-value"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [code_challenge(verifier)]
    assert query["scope"] == ["openid email profile"]
    assert "client_secret" not in query
