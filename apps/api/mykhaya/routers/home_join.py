"""Home join codes — the joiner-facing half.

Any authenticated user (with or without an existing Home membership — see
components/app-shell.tsx's "Home-less Free account UX" on the frontend, and
routers.auth.register never creating a Home) can look up a Home by its join
code and submit a request to join it. Possessing the code never creates a
membership on its own: a Home Admin must approve (see routers.groups' admin-
facing join-code/join-request endpoints), the same "code alone never grants
membership" boundary CalendarShare's approval gate already enforces for
external calendar access.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.models import (
    Group,
    HomeJoinRequest,
    HomeJoinRequestStatus,
    HouseholdRelationship,
    Membership,
)
from mykhaya.notifications.deep_links import target as deep_link_target
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.schemas import (
    HomeJoinCodeLookupRequest,
    HomeJoinCodeLookupResponse,
    HomeJoinRequestCreate,
    HomeJoinRequestResponse,
)
from mykhaya.security import hash_secret, normalise_home_join_code

router = APIRouter(prefix="/home-join", tags=["Homes"])


async def _find_group_by_code(db: AsyncSession, settings: Settings, code: str) -> Group | None:
    normalised = normalise_home_join_code(code)
    if not normalised:
        return None
    digest = hash_secret(normalised, settings.secret_key.get_secret_value())
    group: Group | None = await db.scalar(
        select(Group).where(Group.join_code_hash == digest, Group.is_active.is_(True))
    )
    return group


@router.post("/lookup", response_model=HomeJoinCodeLookupResponse)
async def lookup_home_join_code(
    body: HomeJoinCodeLookupRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HomeJoinCodeLookupResponse:
    # Same-shaped rate limit as invitations/child-login-style secret lookups
    # — enough attempts for a genuine typo, far too few to brute-force an
    # 8-character, ~32^8-space code.
    await enforce_rate_limit(request, settings, "home-join-lookup", 10, 300)
    group = await _find_group_by_code(db, settings, body.code)
    if group is None:
        # Deliberately identical to "code not found" — never distinguishes
        # "wrong code" from "Home disabled" from "rate limited elsewhere",
        # matching the codebase's existing no-enumeration convention.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Home join code was not recognised.")
    return HomeJoinCodeLookupResponse(group_id=group.id, group_name=group.name)


@router.post(
    "/request", response_model=HomeJoinRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_home_join_request(
    body: HomeJoinRequestCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HomeJoinRequestResponse:
    await enforce_rate_limit(request, settings, "home-join-request", 10, 300)
    group = await _find_group_by_code(db, settings, body.code)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Home join code was not recognised.")

    existing_membership = await db.scalar(
        select(Membership).where(
            Membership.group_id == group.id,
            Membership.user_id == auth.user.id,
            Membership.removed_at.is_(None),
        )
    )
    if existing_membership is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You are already a member of this Home."
        )

    existing_pending = await db.scalar(
        select(HomeJoinRequest).where(
            HomeJoinRequest.group_id == group.id,
            HomeJoinRequest.user_id == auth.user.id,
            HomeJoinRequest.status == HomeJoinRequestStatus.pending,
        )
    )
    if existing_pending is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You already have a pending request to join this Home.",
        )

    row = HomeJoinRequest(group_id=group.id, user_id=auth.user.id, method="join_code")
    db.add(row)
    await db.flush()

    # Best-effort: a Home Admin who never sees this in-app is still not
    # locked out of the flow — the request is fully visible from Members and
    # roles' own pending-requests list either way (see routers.groups'
    # list_join_requests). Never blocks/fails the request itself.
    admins = (
        await db.execute(
            select(Membership.user_id).where(
                Membership.group_id == group.id,
                Membership.relationship == HouseholdRelationship.home_admin,
                Membership.removed_at.is_(None),
            )
        )
    ).scalars().all()
    notification_title, notification_body = await render_notification(
        db,
        "home_join_request",
        {"requester_display_name": auth.user.display_name, "home_name": group.name},
    )
    for admin_id in admins:
        await notify(
            db,
            settings=settings,
            recipient_user_id=admin_id,
            notification_type="home_join_request",
            title=notification_title,
            body=notification_body,
            idempotency_key=f"home_join_request:{row.id}",
            group_id=group.id,
            related_entity_type="home_join_request",
            related_entity_id=row.id,
            deep_link=deep_link_target("member"),
            allow_email=False,
        )

    audit(
        db,
        request,
        "home_join_request.created",
        auth.user.id,
        group.id,
        "home_join_request",
        row.id,
    )
    await db.commit()
    return HomeJoinRequestResponse(
        id=row.id, group_id=row.group_id, status=row.status, created_at=row.created_at
    )
