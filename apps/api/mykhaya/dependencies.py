import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.models import Group, Membership, Role, Session, SessionKind, User
from mykhaya.security import require_csrf, resolve_session


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: Session
    transport: Literal["cookie", "bearer"]


async def auth_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    resolved = await resolve_session(request, db, settings)
    if resolved.transport == "cookie":
        require_csrf(request, settings)
    return AuthContext(resolved.user, resolved.session, resolved.transport)


def require_adult_session(auth: AuthContext) -> None:
    """A hard boundary independent of the capability system, for the handful of
    actions that must never be reachable by a managed Child session no matter what
    a capability override might say — creating a Home, inviting someone, and
    managing another Child's sign-in credentials. Everything else is governed by
    the normal per-Home capability checks, which already deny a Child by default;
    this is defence in depth for the highest-risk surfaces, not a replacement for
    them."""
    if auth.session.kind != SessionKind.adult:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This action is not available to a Child sign-in."
        )


async def membership_for(
    group_id: uuid.UUID,
    auth: AuthContext,
    db: AsyncSession,
    roles: set[Role] | None = None,
) -> Membership:
    membership = await db.scalar(
        select(Membership)
        .join(Group, Group.id == Membership.group_id)
        .options(selectinload(Membership.group), selectinload(Membership.user))
        .where(
            Membership.group_id == group_id,
            Membership.user_id == auth.user.id,
            Membership.removed_at.is_(None),
            Group.is_active.is_(True),
        )
    )
    # Deliberately return the same response for absent and unauthorised Homes.
    if membership is None or (roles is not None and membership.role not in roles):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Home could not be found.")
    return membership
