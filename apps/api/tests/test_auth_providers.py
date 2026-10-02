"""Configuration-only provider state tests.

Provider callbacks are intentionally not covered because they are not enabled
until a later phase has deployment credentials and callback configuration.
"""

from pydantic import SecretStr

from mykhaya.auth_providers import external_auth_provider_statuses
from mykhaya.config import Settings


def test_provider_status_defaults_fail_closed_without_credentials() -> None:
    settings = Settings(secret_key="test-only-secret-key-never-used-in-production-1234")
    statuses = {item.provider: item for item in external_auth_provider_statuses(settings)}

    assert statuses["apple"].state == "not_configured"
    assert statuses["apple"].enabled is False
    assert statuses["google"].state == "not_configured"
    assert statuses["google"].enabled is False
    assert all(item.client_identifier is None for item in statuses.values())


def test_apple_status_is_enabled_only_when_complete_and_explicitly_enabled() -> None:
    settings = Settings(
        secret_key="test-only-secret-key-never-used-in-production-1234",
        apple_sign_in_enabled=True,
        apple_service_id="com.example.web",
        apple_team_id="TEAM123",
        apple_key_id="KEY123",
        apple_private_key=SecretStr("fake-private-key-for-test-only"),
    )
    status = external_auth_provider_statuses(settings)[0]

    assert status.state == "enabled"
    assert status.client_identifier == "com.example.web"
    assert status.redirect_uri.endswith("/api/v1/auth/apple/callback")
    assert status.credential_configured is True
    assert status.enabled is True
    assert status.public_dict().get("apple_private_key") is None


def test_google_remains_disabled_even_when_configuration_is_present() -> None:
    settings = Settings(
        secret_key="test-only-secret-key-never-used-in-production-1234",
        google_client_id="google-client-id",
        google_client_secret=SecretStr("fake-google-secret-for-test-only"),
    )
    status = external_auth_provider_statuses(settings)[1]

    assert status.state == "disabled"
    assert status.enabled is False
    assert status.credential_configured is True
