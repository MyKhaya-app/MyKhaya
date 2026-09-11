"""Central provider configuration state for consumer auth and the PCC.

This module reports configuration health only. It does not verify provider
tokens, create sessions, or infer account links. Provider ceremonies must reuse
the existing session and identity boundaries when a later phase enables them.
"""

from dataclasses import dataclass
from typing import Literal

from mykhaya.config import Settings

ProviderName = Literal["apple", "google"]
ProviderState = Literal["enabled", "disabled", "not_configured", "framework_available"]


@dataclass(frozen=True)
class ExternalAuthProviderStatus:
    provider: ProviderName
    state: ProviderState
    configured: bool
    framework_available: bool
    client_identifier: str | None
    redirect_uri: str | None
    credential_configured: bool
    enabled: bool
    last_configuration_test: str | None = None

    def public_dict(self) -> dict[str, object | None]:
        return {
            "provider": self.provider,
            "state": self.state,
            "configured": self.configured,
            "framework_available": self.framework_available,
            "client_identifier": self.client_identifier,
            "redirect_uri": self.redirect_uri,
            "credential_configured": self.credential_configured,
            "enabled": self.enabled,
            "last_configuration_test": self.last_configuration_test,
        }


def _apple_status(settings: Settings) -> ExternalAuthProviderStatus:
    client_identifier = settings.apple_service_id or settings.apple_client_id
    redirect_uri = settings.apple_redirect_uri or (
        f"{settings.public_web_url.rstrip('/')}/api/v1/auth/apple/callback"
    )
    credential_configured = bool(
        settings.apple_team_id and settings.apple_key_id and settings.apple_private_key
    )
    configured = bool(client_identifier and credential_configured and redirect_uri)
    state: ProviderState = "disabled" if configured else "not_configured"
    if settings.apple_sign_in_enabled and configured:
        state = "enabled"
    return ExternalAuthProviderStatus(
        provider="apple",
        state=state,
        configured=configured,
        framework_available=True,
        client_identifier=client_identifier,
        redirect_uri=redirect_uri,
        credential_configured=credential_configured,
        enabled=state == "enabled",
    )


def _google_status(settings: Settings) -> ExternalAuthProviderStatus:
    configured = bool(settings.google_client_id and settings.google_client_secret)
    state: ProviderState = "disabled" if configured else "not_configured"
    return ExternalAuthProviderStatus(
        provider="google",
        state=state,
        configured=configured,
        framework_available=True,
        client_identifier=settings.google_client_id,
        redirect_uri=None,
        credential_configured=bool(settings.google_client_secret),
        enabled=False,
    )


def external_auth_provider_statuses(settings: Settings) -> list[ExternalAuthProviderStatus]:
    return [_apple_status(settings), _google_status(settings)]


def external_auth_provider_status(
    settings: Settings, provider: ProviderName
) -> ExternalAuthProviderStatus:
    return next(
        item for item in external_auth_provider_statuses(settings) if item.provider == provider
    )
