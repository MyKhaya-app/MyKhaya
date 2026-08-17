import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, require_adult_session
from mykhaya.entitlements import require_within_limit
from mykhaya.household_permissions import (
    SAFE_CHILD_DEFAULTS,
    Capability,
    require_capability,
)
from mykhaya.member_colours import assign_member_colour
from mykhaya.models import (
    ChildProfile,
    ChildTransitionStatus,
    GuardianAssignment,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    Session,
    TrustedDevice,
    User,
)
from mykhaya.schemas import (
    ChildAgeBandUpdate,
    ChildBirthdayUpdate,
    ChildCreate,
    ChildDeleteRequest,
    ChildLoginConfigure,
    ChildPermissionUpdate,
    ChildResponse,
    ChildTransitionRequest,
    GuardianUpdate,
)
from mykhaya.security import (
    is_valid_child_pin,
    is_valid_child_username,
    normalise_child_username,
    password_hash,
)

router = APIRouter(prefix="/groups/{group_id}/children", tags=["children"])


async def _revoke_user_access(db: AsyncSession, user_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.execute(
        update(TrustedDevice)
        .where(TrustedDevice.user_id == user_id, TrustedDevice.revoked_at.is_(None))
        .values(revoked_at=now)
    )


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
        birth_month=profile.birth_month,
        birth_day=profile.birth_day,
        birthday_visible=profile.birthday_visible,
        login_enabled=profile.login_enabled,
        login_username=profile.username_normalised,
    )


async def _child_username_taken(
    db: AsyncSession, group_id: uuid.UUID, username_normalised: str, exclude_profile_id: uuid.UUID
) -> bool:
    """A friendly, fast pre-check for the common case — the actual invariant is the
    uq_child_login_username_per_home database constraint (see models.ChildProfile),
    which configure_child_login also relies on directly to catch the rare race this
    pre-check can't: two concurrent requests both passing this check before either
    has committed."""
    existing = await db.scalar(
        select(ChildProfile.id).where(
            ChildProfile.group_id == group_id,
            ChildProfile.username_normalised == username_normalised,
            ChildProfile.id != exclude_profile_id,
        )
    )
    return existing is not None


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
    # A child gets a full Membership row like any other household member (see
    # below), so this is a genuine member-add path and must respect
    # home.max_members exactly like routers.invitations' invite()/accept() —
    # same advisory-lock pattern, same lock key, so both paths serialise
    # against each other for the same Home.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"members:{group_id}"}
    )
    member_count = (
        await db.scalar(
            select(func.count(Membership.id)).where(
                Membership.group_id == group_id, Membership.removed_at.is_(None)
            )
        )
        or 0
    )
    await require_within_limit(db, group_id, "home.max_members", member_count)
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
        colour=await assign_member_colour(db, group_id),
    )
    db.add(membership)
    await db.flush()
    profile = ChildProfile(
        membership_id=membership.id,
        group_id=group_id,
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


@router.put("/{membership_id}/birthday", response_model=ChildResponse)
async def update_child_birthday(
    group_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: ChildBirthdayUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ChildResponse:
    await require_capability(group_id, Capability.child_manage, auth, db)
    profile = await _profile_for_group(db, group_id, membership_id)
    previous_visible = profile.birthday_visible
    profile.birth_month = body.birth_month
    profile.birth_day = body.birth_day
    profile.birthday_visible = body.birthday_visible
    audit(
        db,
        request,
        "child.birthday_changed",
        auth.user.id,
        group_id,
        "membership",
        membership_id,
        {
            "previous_visible": previous_visible,
            "new_visible": body.birthday_visible,
            "reason": body.reason,
        },
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
    await _revoke_user_access(db, membership.user_id)
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


@router.put("/{membership_id}/login", response_model=ChildResponse)
async def configure_child_login(
    group_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: ChildLoginConfigure,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ChildResponse:
    """Covers every login-config action from the Child profile screen: enable
    (username + PIN both required), change username only, change/reset PIN
    only, and disable. See mykhaya.schemas.ChildLoginConfigure."""
    require_adult_session(auth)
    await require_capability(group_id, Capability.child_manage, auth, db)
    profile = await _profile_for_group(db, group_id, membership_id)
    membership = await db.get(Membership, membership_id)
    assert membership is not None

    if not body.enabled:
        was_enabled = profile.login_enabled
        profile.login_enabled = False
        profile.username_normalised = None
        profile.pin_hash = None
        profile.login_updated_at = datetime.now(UTC)
        if was_enabled:
            await _revoke_user_access(db, membership.user_id)
        audit(
            db, request, "child.login_disabled", auth.user.id, group_id, "membership", membership_id
        )
        await db.commit()
        return await _child_response(db, profile)

    username_changed = False
    if body.username is not None:
        normalised = normalise_child_username(body.username)
        if not is_valid_child_username(normalised):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Choose a username between 2 and 24 characters, using only letters, "
                "numbers, dots, hyphens or underscores.",
            )
        if await _child_username_taken(db, group_id, normalised, profile.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "That username is already in use in this Home."
            )
        username_changed = normalised != profile.username_normalised
        profile.username_normalised = normalised
    elif profile.username_normalised is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a username before enabling sign-in."
        )

    pin_changed = False
    if body.pin is not None:
        if not is_valid_child_pin(body.pin):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "PIN must be 4 to 6 digits.")
        profile.pin_hash = password_hash.hash(body.pin)
        pin_changed = True
    elif profile.pin_hash is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Set a PIN before enabling sign-in."
        )

    was_enabled = profile.login_enabled
    profile.login_enabled = True
    profile.login_updated_at = datetime.now(UTC)

    # A username or PIN change invalidates any device signed in under the old
    # credential — matches the existing pattern for a permission change.
    if pin_changed or username_changed:
        await _revoke_user_access(db, membership.user_id)

    audit(
        db,
        request,
        "child.login_enabled" if not was_enabled else "child.login_updated",
        auth.user.id,
        group_id,
        "membership",
        membership_id,
        {"username_changed": username_changed, "pin_changed": pin_changed},
    )
    try:
        await db.commit()
    except IntegrityError as cause:
        # The pre-check in _child_username_taken narrows this to a genuine race —
        # two concurrent requests both passing that check before either committed.
        # The uq_child_login_username_per_home constraint is the real guarantee;
        # this just turns the loser's crash into the same clean 409 the pre-check
        # gives everyone else, instead of a raw 500.
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That username is already in use in this Home."
        ) from cause
    return await _child_response(db, profile)


@router.post("/{membership_id}/login/revoke-sessions", response_model=ChildResponse)
async def revoke_child_sessions(
    group_id: uuid.UUID,
    membership_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ChildResponse:
    require_adult_session(auth)
    await require_capability(group_id, Capability.child_manage, auth, db)
    profile = await _profile_for_group(db, group_id, membership_id)
    membership = await db.get(Membership, membership_id)
    assert membership is not None
    await _revoke_user_access(db, membership.user_id)
    audit(
        db,
        request,
        "child.sessions_revoked",
        auth.user.id,
        group_id,
        "membership",
        membership_id,
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
    await _revoke_user_access(db, user.id)
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
