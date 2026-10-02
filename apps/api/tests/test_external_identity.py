"""Provider-neutral identity foundation invariants.

Phase 1 intentionally has no provider sign-in route or UI.  These tests protect
the schema contract that later Apple/Google ceremonies will consume.
"""

import uuid

from sqlalchemy import UniqueConstraint

from mykhaya.models import ExternalIdentity, ExternalIdentityProvider, User


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
