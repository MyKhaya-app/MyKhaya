import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.models import Membership, PlatformMembership, PlatformRole, Role, Session, User
from mykhaya.security import current_user, require_csrf


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: Session


@dataclass(frozen=True)
class PlatformAuthContext:
    user: User
    session: Session
    platform_membership: PlatformMembership


async def auth_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    require_csrf(request, settings)
    user, session = await current_user(request, db, settings)
    return AuthContext(user, session)


async def membership_for(
    group_id: uuid.UUID,
    auth: AuthContext,
    db: AsyncSession,
    roles: set[Role] | None = None,
) -> Membership:
    membership = await db.scalar(
        select(Membership)
        .options(selectinload(Membership.group), selectinload(Membership.user))
        .where(
            Membership.group_id == group_id,
            Membership.user_id == auth.user.id,
            Membership.removed_at.is_(None),
        )
    )
    # Deliberately return the same response for absent and unauthorised Homes.
    if membership is None or (roles is not None and membership.role not in roles):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Home could not be found.")
    return membership


async def platform_membership_for(
    auth: AuthContext | PlatformAuthContext,
    db: AsyncSession,
    roles: set[PlatformRole] | None = None,
) -> PlatformMembership:
    membership = await db.scalar(
        select(PlatformMembership).where(PlatformMembership.user_id == auth.user.id)
    )
    if membership is None or (roles is not None and membership.role not in roles):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this area.")
    return membership


async def platform_auth_context(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> PlatformAuthContext:
    membership = await platform_membership_for(auth, db)
    return PlatformAuthContext(auth.user, auth.session, membership)
