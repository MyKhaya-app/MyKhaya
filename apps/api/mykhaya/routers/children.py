import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.household_permissions import (
    SAFE_CHILD_DEFAULTS,
    Capability,
    require_capability,
)
from mykhaya.models import (
    ChildProfile,
    ChildTransitionStatus,
    GuardianAssignment,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    Session,
    User,
)
from mykhaya.schemas import (
    ChildAgeBandUpdate,
    ChildCreate,
    ChildDeleteRequest,
    ChildPermissionUpdate,
    ChildResponse,
    ChildTransitionRequest,
    GuardianUpdate,
)

router = APIRouter(prefix="/groups/{group_id}/children", tags=["children"])


async def _child_response(db: AsyncSession, profile: ChildProfile) -> ChildResponse:
    membership = await db.get(Membership, profile.membership_id)
    assert membership is not None
    user = await db.get(User, membership.user_id)
    assert user is not None
    guardian_ids = list(
        await db.scalars(
            select(GuardianAssignment.guardian_membership_id).where(
                GuardianAssignment.child_profile_id == profile.id
            )
        )
    )
    return ChildResponse(
        membership_id=membership.id,
        user_id=user.id,
        display_name=user.display_name,
        age_band=profile.age_band,
        permissions=SAFE_CHILD_DEFAULTS | profile.permissions,
        guardian_membership_ids=guardian_ids,
        transition_status=profile.transition_status,
    )


async def _profile_for_group(
    db: AsyncSession, group_id: uuid.UUID, membership_id: uuid.UUID
) -> ChildProfile:
    profile = await db.scalar(
        select(ChildProfile)
        .join(Membership, Membership.id == ChildProfile.membership_id)
        .where(
            ChildProfile.membership_id == membership_id,
            Membership.group_id == group_id,
            Membership.relationship == HouseholdRelationship.child,
            Membership.removed_at.is_(None),
        )
    )
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Child profile could not be found.")
    return profile


async def _validate_guardians(
    db: AsyncSession, group_id: uuid.UUID, identifiers: list[uuid.UUID]
) -> list[Membership]:
    unique_ids = set(identifiers)
    rows = list(
        await db.scalars(
            select(Membership).where(
                Membership.id.in_(unique_ids),
                Membership.group_id == group_id,
                Membership.removed_at.is_(None),
                Membership.relationship.in_(
                    [HouseholdRelationship.home_admin, HouseholdRelationship.partner]
                ),
            )
        )
    )
    if len(rows) != len(unique_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Every guardian must be an active Home Admin or Partner in this Home.",
        )
    return rows


@router.get("", response_model=list[ChildResponse])
async def list_children(
    group_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[ChildResponse]:
    await require_capability(group_id, Capability.child_manage, auth, db)
    profiles = list(
        await db.scalars(
            select(ChildProfile)
            .join(Membership, Membership.id == ChildProfile.membership_id)
            .where(Membership.group_id == group_id, Membership.removed_at.is_(None))
            .order_by(ChildProfile.created_at)
        )
    )
    return [await _child_response(db, profile) for profile in profiles]


@router.post("", response_model=ChildResponse, status_code=status.HTTP_201_CREATED)
async def create_child(
    group_id: uuid.UUID,
    body: ChildCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ChildResponse:
    await require_capability(group_id, Capability.child_manage, auth, db)
    guardians = await _validate_guardians(db, group_id, body.guardian_membership_ids)
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"managed-child-{user_id}@managed.mykhaya.invalid",
        display_name=" ".join(body.display_name.strip().split()),
        email_verified_at=None,
    )
    db.add(user)
    await db.flush()
    membership = Membership(
        group_id=group_id,
        user_id=user.id,
        role=Role.member,
        relationship=HouseholdRelationship.child,
        permission_profile=PermissionProfile.child_restricted,
    )
    db.add(membership)
    await db.flush()
    profile = ChildProfile(
        membership_id=membership.id,
        age_band=body.age_band,
        permissions=SAFE_CHILD_DEFAULTS.copy(),
    )
    db.add(profile)
    await db.flush()
    for guardian in guardians:
        db.add(
            GuardianAssignment(
                child_profile_id=profile.id,
                guardian_membership_id=guardian.id,
                assigned_by_user_id=auth.user.id,
            )
        )
    audit(
        db,
        request,
        "child.created",
        auth.user.id,
        group_id,
        "membership",
        membership.id,
        {"age_band": body.age_band.value, "guardian_count": len(guardians)},
    )
    await db.commit()
    return await _child_response(db, profile)


@router.put("/{membership_id}/age-band", response_model=ChildResponse)
async def update_child_age_band(
    group_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: ChildAgeBandUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ChildResponse:
    await require_capability(group_id, Capability.child_manage, auth, db)
    profile = await _profile_for_group(db, group_id, membership_id)
    previous = profile.age_band
    profile.age_band = body.age_band
    audit(
        db,
        request,
        "child.age_band_changed",
        auth.user.id,
        group_id,
        "membership",
        membership_id,
        {"previous": previous.value, "new": body.age_band.value, "reason": body.reason},
    )
    await db.commit()
    return await _child_response(db, profile)


@router.put("/{membership_id}/permissions", response_model=ChildResponse)
async def update_child_permissions(
    group_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: ChildPermissionUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ChildResponse:
    await require_capability(group_id, Capability.child_permissions_manage, auth, db)
    unknown = set(body.permissions) - set(SAFE_CHILD_DEFAULTS)
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown child permission.")
    profile = await _profile_for_group(db, group_id, membership_id)
    previous = SAFE_CHILD_DEFAULTS | profile.permissions
    profile.permissions = SAFE_CHILD_DEFAULTS | body.permissions
    membership = await db.get(Membership, profile.membership_id)
    assert membership is not None
    await db.execute(
        update(Session)
        .where(Session.user_id == membership.user_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    changed = sorted(
        key for key in profile.permissions if previous[key] != profile.permissions[key]
    )
    audit(
        db,
        request,
        "child.permissions_changed",
        auth.user.id,
        group_id,
        "membership",
        membership_id,
        {"changed_permissions": changed, "reason": body.reason},
    )
    await db.commit()
    return await _child_response(db, profile)


@router.put("/{membership_id}/guardians", response_model=ChildResponse)
async def update_guardians(
    group_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: GuardianUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ChildResponse:
    await require_capability(group_id, Capability.child_manage, auth, db)
    profile = await _profile_for_group(db, group_id, membership_id)
    guardians = await _validate_guardians(db, group_id, body.guardian_membership_ids)
    await db.execute(
        delete(GuardianAssignment).where(GuardianAssignment.child_profile_id == profile.id)
    )
    for guardian in guardians:
        db.add(
            GuardianAssignment(
                child_profile_id=profile.id,
                guardian_membership_id=guardian.id,
                assigned_by_user_id=auth.user.id,
            )
        )
    audit(
        db,
        request,
        "child.guardians_changed",
        auth.user.id,
        group_id,
        "membership",
        membership_id,
        {"guardian_count": len(guardians), "reason": body.reason},
    )
    await db.commit()
    return await _child_response(db, profile)


@router.post("/{membership_id}/adult-transition-review", response_model=ChildResponse)
async def request_adult_transition_review(
    group_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: ChildTransitionRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ChildResponse:
    await require_capability(group_id, Capability.child_manage, auth, db)
    profile = await _profile_for_group(db, group_id, membership_id)
    profile.transition_status = ChildTransitionStatus.review_due
    audit(
        db,
        request,
        "child.adult_transition_review_requested",
        auth.user.id,
        group_id,
        "membership",
        membership_id,
        {"reason": body.reason},
    )
    await db.commit()
    return await _child_response(db, profile)


@router.delete("/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def anonymise_child(
    group_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: ChildDeleteRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_capability(group_id, Capability.child_manage, auth, db)
    profile = await _profile_for_group(db, group_id, membership_id)
    membership = await db.get(Membership, membership_id)
    assert membership is not None
    user = await db.get(User, membership.user_id)
    assert user is not None
    await db.execute(delete(Session).where(Session.user_id == user.id))
    await db.delete(profile)
    membership.removed_at = datetime.now(UTC)
    user.display_name = "Removed child"
    user.email = f"anonymised-{user.id}@removed.mykhaya.invalid"
    user.is_active = False
    audit(
        db,
        request,
        "child.anonymised",
        auth.user.id,
        group_id,
        "membership",
        membership_id,
        {"reason": body.reason},
    )
    await db.commit()
