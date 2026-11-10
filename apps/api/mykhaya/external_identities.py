"""Provider-neutral external identity ownership and linking policy.

Provider modules own their OAuth/WebAuthn protocol ceremonies. This module owns
the database identity boundary after a provider has supplied a verified stable
subject. Provider email is metadata only and is never used as an identity key.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.auth_providers import external_auth_provider_status
from mykhaya.config import Settings
from mykhaya.models import (
    AuthIdentity,
    ExternalIdentity,
    ExternalIdentityProvider,
    User,
    UserPasskey,
)


class ExternalIdentityOwnershipConflict(Exception):
    """The verified provider subject already belongs to another User."""


class ExternalIdentityNotFound(Exception):
    """The requested provider identity is not linked."""


class LastAuthenticationMethodError(Exception):
    """Removing the identity would leave the User without usable sign-in."""


async def find_external_identity(
    db: AsyncSession,
    provider: ExternalIdentityProvider,
    provider_subject: str,
    *,
    for_update: bool = False,
) -> ExternalIdentity | None:
    statement = select(ExternalIdentity).where(
        ExternalIdentity.provider == provider,
        ExternalIdentity.provider_subject == provider_subject,
    )
    if for_update:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def link_external_identity(
    db: AsyncSession,
    request: Request,
    *,
    user_id: UUID,
    provider: ExternalIdentityProvider,
    provider_subject: str,
    provider_email: str | None,
    provider_email_verified: bool,
) -> ExternalIdentity:
    """Create or update one provider identity for one canonical User.

    The caller commits the surrounding transaction. PostgreSQL's unique
    ``(provider, provider_subject)`` constraint remains the final concurrent
    ownership guard; callers should translate an IntegrityError into a safe
    conflict response.
    """

    identity = await find_external_identity(db, provider, provider_subject, for_update=True)
    if identity is not None and identity.user_id != user_id:
        audit(
            db,
            request,
            "external_identity.link_failed",
            user_id,
            target_type="external_identity",
        )
        raise ExternalIdentityOwnershipConflict
    now = datetime.now(UTC)
    if identity is None:
        identity = ExternalIdentity(
            user_id=user_id,
            provider=provider,
            provider_subject=provider_subject,
            provider_email=provider_email,
            provider_email_verified=provider_email_verified,
            last_used_at=now,
        )
        db.add(identity)
    else:
        identity.provider_email = provider_email or identity.provider_email
        identity.provider_email_verified = (
            provider_email_verified or identity.provider_email_verified
        )
        identity.last_used_at = now
    audit(db, request, "external_identity.linked", user_id, target_type="external_identity")
    return identity


async def touch_external_identity(
    db: AsyncSession,
    *,
    identity: ExternalIdentity,
    provider_email: str | None,
    provider_email_verified: bool,
) -> None:
    """Refresh provider metadata after a successful provider authentication."""

    identity.provider_email = provider_email or identity.provider_email
    identity.provider_email_verified = provider_email_verified or identity.provider_email_verified
    identity.last_used_at = datetime.now(UTC)


async def unlink_external_identity(
    db: AsyncSession,
    request: Request,
    *,
    user_id: UUID,
    provider: ExternalIdentityProvider,
    settings: Settings,
    administrator_initiated: bool = False,
) -> ExternalIdentity:
    """Unlink an identity only when another usable sign-in remains.

    Usable means: a password, an unrevoked passkey, or another provider
    identity whose provider is enabled in this environment. A linked
    identity for a provider that is switched off cannot be used to sign in,
    so it does not count (password and passkey sign-in have no such switch).

    The User row is locked first, so concurrent unlinks for the same User
    (for example the user in the app and an administrator in PCC) are
    serialised and cannot both pass the last-usable-sign-in check.

    ``administrator_initiated`` is set by the Platform Control Centre: the
    user audit row then records no user as the actor (the acting
    administrator is recorded in the administrative audit by the caller)."""

    await db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    identity = await db.scalar(
        select(ExternalIdentity)
        .where(ExternalIdentity.user_id == user_id, ExternalIdentity.provider == provider)
        .with_for_update()
    )
    if identity is None:
        raise ExternalIdentityNotFound
    password_identity = await db.scalar(
        select(AuthIdentity.id).where(AuthIdentity.user_id == user_id)
    )
    enabled_providers = [
        item
        for item in ExternalIdentityProvider
        if external_auth_provider_status(settings, item.value).enabled
    ]
    other_external_identity = (
        await db.scalar(
            select(ExternalIdentity.id).where(
                ExternalIdentity.user_id == user_id,
                ExternalIdentity.id != identity.id,
                ExternalIdentity.provider.in_(enabled_providers),
            )
        )
        if enabled_providers
        else None
    )
    active_passkey = await db.scalar(
        select(UserPasskey.id).where(
            UserPasskey.user_id == user_id,
            UserPasskey.revoked_at.is_(None),
        )
    )
    if password_identity is None and other_external_identity is None and active_passkey is None:
        raise LastAuthenticationMethodError
    await db.delete(identity)
    if administrator_initiated:
        audit(
            db,
            request,
            "external_identity.unlinked",
            None,
            target_type="user",
            target_id=user_id,
            metadata={"initiated_by": "platform_administrator", "provider": provider.value},
        )
    else:
        audit(db, request, "external_identity.unlinked", user_id, target_type="external_identity")
    return identity
