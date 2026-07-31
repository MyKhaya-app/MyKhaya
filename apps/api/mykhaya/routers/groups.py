import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.models import Group, Membership, Role, User
from mykhaya.schemas import (
    GroupCreate,
    GroupResponse,
    GroupUpdate,
    MemberResponse,
    MemberRoleUpdate,
)

router = APIRouter(prefix="/groups", tags=["Homes"])
MANAGERS = {Role.owner, Role.administrator}


async def group_response(db: AsyncSession, group: Group, membership: Membership) -> GroupResponse:
    count = await db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.group_id == group.id, Membership.removed_at.is_(None))
    )
    return GroupResponse(
        id=group.id, name=group.name, role=membership.role, member_count=count or 0
    )


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
    group = Group(name=body.name, created_by=auth.user.id)
    db.add(group)
    await db.flush()
    membership = Membership(group_id=group.id, user_id=auth.user.id, role=Role.owner)
    db.add(membership)
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
    membership = await membership_for(group_id, auth, db, MANAGERS)
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
    await membership_for(group_id, auth, db)
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
            user_id=user.id, display_name=user.display_name, email=user.email, role=membership.role
        )
        for membership, user in rows
    ]


@router.patch("/{group_id}/members/{user_id}", response_model=MemberResponse)
async def update_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberRoleUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    actor = await membership_for(group_id, auth, db, MANAGERS)
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
        target.role == Role.owner
        or body.role == Role.owner
        or (actor.role != Role.owner and body.role == Role.administrator)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the Home owner can make that change.")
    target.role = body.role
    user = await db.get(User, user_id)
    assert user is not None
    audit(
        db,
        request,
        "membership.role_changed",
        auth.user.id,
        group_id,
        "user",
        user_id,
        {"role": body.role.value},
    )
    await db.commit()
    return MemberResponse(
        user_id=user.id, display_name=user.display_name, email=user.email, role=target.role
    )


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await membership_for(group_id, auth, db, MANAGERS)
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
    if target.role == Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The Home owner cannot be removed.")
    target.removed_at = datetime.now(UTC)
    audit(db, request, "membership.removed", auth.user.id, group_id, "user", user_id)
    await db.commit()
