"""Shared Apple/Google Beta registration-context regressions."""

from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.platform_runtime import SignupPolicy
from mykhaya.routers import auth as auth_router


@pytest.mark.parametrize(
    ("path", "expected_invitation"),
    [
        ("/register?beta=1", None),
        ("/register?beta=1&beta_invitation=invite-token", "invite-token"),
        ("/onboarding?beta=1", None),
        ("/onboarding?beta=1&invitation=invite-token", "invite-token"),
    ],
)
def test_social_registration_context_preserves_only_approved_beta_paths(
    path: str, expected_invitation: str | None
) -> None:
    assert auth_router._social_registration_details(path) == (True, expected_invitation)


@pytest.mark.parametrize(
    "path",
    [
        None,
        "/login?beta=1",
        "/register",
        "/onboarding",
        "https://attacker.example/register?beta=1",
        "//attacker.example/register?beta=1",
    ],
)
def test_social_registration_context_rejects_unapproved_or_unsafe_paths(
    path: str | None,
) -> None:
    assert auth_router._social_registration_details(path) == (False, None)
    assert auth_router._social_registration_context(path) == ""


def test_social_registration_context_rewrites_onboarding_invitation_for_recovery() -> None:
    assert (
        auth_router._social_registration_context("/onboarding?beta=1&invitation=invite-token")
        == "&beta=1&beta_invitation=invite-token"
    )


@pytest.mark.asyncio
async def test_social_registration_allowed_delegates_beta_to_central_invitation_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    async def allowed(
        db: AsyncSession,
        settings: Settings,
        policy: SignupPolicy,
        invitation_token: str | None,
        email: str,
        *,
        invitation_token_hash: str | None = None,
    ) -> bool:
        observed.update(
            invitation_token=invitation_token,
            email=email,
            invitation_token_hash=invitation_token_hash,
        )
        return True

    monkeypatch.setattr(auth_router, "_beta_signup_allowed", allowed)
    result = await auth_router._social_registration_allowed(
        cast(AsyncSession, object()),
        cast(Settings, object()),
        cast(
            SignupPolicy,
            SimpleNamespace(normal_path=False, invitation_required=True),
        ),
        beta=True,
        invitation_token="invite-token",
        email="person@example.com",
    )

    assert result is True
    assert observed == {
        "invitation_token": "invite-token",
        "email": "person@example.com",
        # Web provider registration passes the raw token, never a hash.
        "invitation_token_hash": None,
    }
