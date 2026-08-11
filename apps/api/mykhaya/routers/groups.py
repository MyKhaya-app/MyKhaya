import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.colour_palette import ColourToken
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for, require_adult_session
from mykhaya.household_permissions import (
    Capability,
    capabilities_for,
    default_profile,
    home_admin_count,
    legacy_role,
    require_capability,
)
from mykhaya.member_colours import assign_member_colour
from mykhaya.models import (
    CalendarEventLabel,
    Group,
    HomeCalendar,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    User,
)
from mykhaya.schemas import (
    GroupCreate,
    GroupResponse,
    GroupUpdate,
    MemberColourUpdate,
    MemberRelationshipUpdate,
    MemberResponse,
)
from mykhaya.security import generate_home_code

router = APIRouter(prefix="/groups", tags=["Homes"])
# Kept in sync with mykhaya.routers.calendar.SYSTEM_LABELS by hand — both create
# the same starter categories for a new home, one at group-creation time and one
# lazily the first time the calendar feature is touched (_ensure_home_calendar).
DEFAULT_LABELS = [
    ("Family", ColourToken.teal),
    ("School", ColourToken.purple),
    ("Work", ColourToken.emerald),
    ("Appointment", ColourToken.orange),
    ("Birthday", ColourToken.rose),
    ("Activity", ColourToken.blue),
    ("Other", ColourToken.slate),
]


async def group_response(db: AsyncSession, group: Group, membership: Membership) -> GroupResponse:
    count = await db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.group_id == group.id, Membership.removed_at.is_(None))
    )
    return GroupResponse(
        id=group.id,
        name=group.name,
        role=membership.role,
        relationship=membership.relationship,
        permission_profile=membership.permission_profile,
        capabilities=sorted(
            capability.value for capability in await capabilities_for(db, membership)
        ),
        member_count=count or 0,
        child_login_code=group.child_login_code,
    )


async def _unique_home_code(db: AsyncSession) -> str:
    for _ in range(10):
        code = generate_home_code()
        if await db.scalar(select(Group.id).where(Group.child_login_code == code)) is None:
            return code
    # 32^8 possible codes — reaching here would mean extraordinary bad luck, not a
    # real collision risk; fail loudly rather than silently retry forever.
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create this Home.")


@router.get("", response_model=list[GroupResponse])
async def list_groups(
    auth: AuthContext = Depends(auth_context), db: AsyncSession = Depends(get_db)
) -> list[GroupResponse]:
    rows = (
        await db.execute(
            select(Group, Membership)
            .join(Membership, Membership.group_id == Group.id)
            .where(Membership.user_id == auth.user.id, Membership.removed_at.is_(None))
            .order_by(Group.created_at)
            .limit(50)
        )
    ).all()
    return [await group_response(db, group, membership) for group, membership in rows]


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    require_adult_session(auth)
    group = Group(
        name=body.name,
        created_by=auth.user.id,
        child_login_code=await _unique_home_code(db),
    )
    db.add(group)
    await db.flush()
    membership = Membership(
        group_id=group.id,
        user_id=auth.user.id,
        role=Role.owner,
        relationship=HouseholdRelationship.home_admin,
        permission_profile=PermissionProfile.home_admin,
        colour=await assign_member_colour(db, group.id),
    )
    db.add(membership)
    calendar = HomeCalendar(group_id=group.id, name="Home Calendar")
    db.add(calendar)
    await db.flush()
    for index, (name, color) in enumerate(DEFAULT_LABELS):
        db.add(
            CalendarEventLabel(
                group_id=group.id,
                name=name,
                color=color,
                is_system=True,
                sort_order=(index + 1) * 10,
            )
        )
    audit(db, request, "group.created", auth.user.id, group.id, "group", group.id)
    await db.commit()
    return await group_response(db, group, membership)


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    membership = await membership_for(group_id, auth, db)
    return await group_response(db, membership.group, membership)


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: uuid.UUID,
    body: GroupUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    membership = await require_capability(group_id, Capability.household_manage, auth, db)
    membership.group.name = body.name
    audit(db, request, "group.updated", auth.user.id, group_id, "group", group_id)
    await db.commit()
    return await group_response(db, membership.group, membership)


@router.get("/{group_id}/members", response_model=list[MemberResponse])
async def members(
    group_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[MemberResponse]:
    await require_capability(group_id, Capability.members_view, auth, db)
    rows = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.group_id == group_id, Membership.removed_at.is_(None))
            .order_by(User.display_name)
            .limit(200)
        )
    ).all()
    return [
        MemberResponse(
            membership_id=membership.id,
            user_id=user.id,
            display_name=user.display_name,
            email=None if membership.relationship == HouseholdRelationship.child else user.email,
            role=membership.role,
            relationship=membership.relationship,
            permission_profile=membership.permission_profile,
            permission_overrides=membership.permission_overrides,
            shared_resources=membership.shared_resources,
            colour=membership.colour,
            avatar_version=user.avatar_key,
        )
        for membership, user in rows
    ]


@router.patch("/{group_id}/members/{user_id}", response_model=MemberResponse)
async def update_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberRelationshipUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    await require_capability(group_id, Capability.members_manage_relationships, auth, db)
    target = await db.scalar(
        select(Membership)
        .where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
            Membership.removed_at.is_(None),
        )
        .with_for_update()
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person could not be found.")
    if body.relationship == HouseholdRelationship.child:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Use the child setup flow to create a Child profile.",
        )
    if (
        target.relationship == HouseholdRelationship.home_admin
        and body.relationship != HouseholdRelationship.home_admin
        and await home_admin_count(db, group_id) <= 1
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Assign another Home Admin before changing the final Home Admin.",
        )
    previous = {
        "relationship": target.relationship.value,
        "permission_profile": target.permission_profile.value,
    }
    target.relationship = body.relationship
    target.permission_profile = body.permission_profile or default_profile(body.relationship)
    target.permission_overrides = body.permission_overrides
    target.shared_resources = body.shared_resources
    target.role = legacy_role(body.relationship)
    user = await db.get(User, user_id)
    assert user is not None
    audit(
        db,
        request,
        "membership.relationship_changed",
        auth.user.id,
        group_id,
        "user",
        user_id,
        {
            "previous": previous,
            "new": {
                "relationship": target.relationship.value,
                "permission_profile": target.permission_profile.value,
            },
            "reason": body.reason,
        },
    )
    await db.commit()
    return MemberResponse(
        membership_id=target.id,
        user_id=user.id,
        display_name=user.display_name,
        email=user.email,
        role=target.role,
        relationship=target.relationship,
        permission_profile=target.permission_profile,
        permission_overrides=target.permission_overrides,
        shared_resources=target.shared_resources,
        colour=target.colour,
        avatar_version=user.avatar_key,
    )


@router.patch("/{group_id}/members/{user_id}/colour", response_model=MemberResponse)
async def update_member_colour(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberColourUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    # A routine, personal choice — not a household-structure change — so a
    # member picking their own colour needs no special capability beyond
    # being an active member of the home. Changing someone *else's* colour
    # (a Home Admin tidying up a child's or another adult's) reuses the same
    # capability as every other member-attribute change.
    if user_id != auth.user.id:
        await require_capability(group_id, Capability.members_manage_relationships, auth, db)
    target = await db.scalar(
        select(Membership)
        .where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
            Membership.removed_at.is_(None),
        )
        .with_for_update()
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person could not be found.")
    previous = target.colour.value if target.colour else None
    target.colour = body.colour
    user = await db.get(User, user_id)
    assert user is not None
    audit(
        db,
        request,
        "membership.colour_changed",
        auth.user.id,
        group_id,
        "user",
        user_id,
        {"previous": previous, "new": target.colour.value},
    )
    await db.commit()
    return MemberResponse(
        membership_id=target.id,
        user_id=user.id,
        display_name=user.display_name,
        email=None if target.relationship == HouseholdRelationship.child else user.email,
        role=target.role,
        relationship=target.relationship,
        permission_profile=target.permission_profile,
        permission_overrides=target.permission_overrides,
        shared_resources=target.shared_resources,
        colour=target.colour,
        avatar_version=user.avatar_key,
    )


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_capability(group_id, Capability.members_manage_relationships, auth, db)
    target = await db.scalar(
        select(Membership)
        .where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
            Membership.removed_at.is_(None),
        )
        .with_for_update()
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person could not be found.")
    if (
        target.relationship == HouseholdRelationship.home_admin
        and await home_admin_count(db, group_id) <= 1
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Assign another Home Admin before removing the final Home Admin.",
        )
    target.removed_at = datetime.now(UTC)
    audit(db, request, "membership.removed", auth.user.id, group_id, "user", user_id)
    await db.commit()
