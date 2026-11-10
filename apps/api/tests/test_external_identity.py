"""Provider-neutral identity foundation invariants.

Phase 1 intentionally has no provider sign-in route or UI.  These tests protect
the schema contract that later Apple/Google ceremonies will consume.
"""

import uuid
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import UniqueConstraint

from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.external_identities import (
    LastAuthenticationMethodError,
    link_external_identity,
    unlink_external_identity,
)
from mykhaya.models import ExternalIdentity, ExternalIdentityProvider, User


def _request() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(request_id=None))


def _settings(*, google_enabled: bool) -> Settings:
    """Test settings with Google sign-in explicitly on or off."""
    return get_settings().model_copy(
        update={
            "google_sign_in_enabled": google_enabled,
            "google_client_id": "test-client.apps.googleusercontent.com",
            "google_client_secret": SecretStr("test-secret"),
        }
    )


def test_external_identity_uses_provider_subject_as_the_stable_key() -> None:
    table = ExternalIdentity.__table__
    unique_constraints = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("provider", "provider_subject") in unique_constraints
    assert table.c.provider_email.nullable
    assert table.c.provider_email_verified.server_default is not None


def test_one_user_can_hold_apple_and_google_identities_without_email_linking() -> None:
    user_id = uuid.uuid4()
    apple = ExternalIdentity(
        user_id=user_id,
        provider=ExternalIdentityProvider.apple,
        provider_subject="apple-subject",
        provider_email="relay-123@privaterelay.appleid.com",
        provider_email_verified=True,
    )
    google = ExternalIdentity(
        user_id=user_id,
        provider=ExternalIdentityProvider.google,
        provider_subject="google-subject",
        provider_email="same-visible-email@example.com",
        provider_email_verified=True,
    )

    assert apple.user_id == google.user_id
    assert apple.provider_subject != google.provider_subject
    assert apple.provider_email != google.provider_email
    assert ExternalIdentityProvider.apple.value == "apple"
    assert ExternalIdentityProvider.google.value == "google"
    assert User.__table__.c.email.unique


@pytest.mark.asyncio
async def test_provider_neutral_service_supports_apple_and_google_and_protects_last_method() -> (
    None
):
    apple_user = User(
        email=f"identity-service-apple-{uuid.uuid4().hex}@example.com", display_name="Apple"
    )
    google_user = User(
        email=f"identity-service-google-{uuid.uuid4().hex}@example.com", display_name="Google"
    )
    async with SessionFactory() as db:
        db.add_all([apple_user, google_user])
        await db.flush()
        await link_external_identity(
            db,
            _request(),
            user_id=apple_user.id,
            provider=ExternalIdentityProvider.apple,
            provider_subject=f"apple-{uuid.uuid4().hex}",
            provider_email="relay@privaterelay.appleid.com",
            provider_email_verified=True,
        )
        google_subject = f"google-{uuid.uuid4().hex}"
        await link_external_identity(
            db,
            _request(),
            user_id=apple_user.id,
            provider=ExternalIdentityProvider.google,
            provider_subject=google_subject,
            provider_email="same-visible-email@example.com",
            provider_email_verified=True,
        )
        await link_external_identity(
            db,
            _request(),
            user_id=google_user.id,
            provider=ExternalIdentityProvider.google,
            provider_subject=f"google-only-{uuid.uuid4().hex}",
            provider_email="google-only@example.com",
            provider_email_verified=True,
        )
        await db.commit()
        apple_user_id, google_user_id = apple_user.id, google_user.id

        # Google switched off: the remaining Google identity cannot be used
        # to sign in, so it does not count as another usable method.
        with pytest.raises(LastAuthenticationMethodError):
            await unlink_external_identity(
                db,
                _request(),
                user_id=apple_user_id,
                provider=ExternalIdentityProvider.apple,
                settings=_settings(google_enabled=False),
            )
        await db.rollback()

        await unlink_external_identity(
            db,
            _request(),
            user_id=apple_user_id,
            provider=ExternalIdentityProvider.apple,
            settings=_settings(google_enabled=True),
        )
        with pytest.raises(LastAuthenticationMethodError):
            await unlink_external_identity(
                db,
                _request(),
                user_id=google_user_id,
                provider=ExternalIdentityProvider.google,
                settings=_settings(google_enabled=True),
            )
