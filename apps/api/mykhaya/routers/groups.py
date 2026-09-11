import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.avatars.processing import (
    AvatarResourceError,
    UnsupportedImageError,
    process_avatar_upload,
)
from mykhaya.avatars.storage import get_avatar_storage
from mykhaya.calendar_provisioning import ensure_personal_calendar
from mykhaya.colour_palette import PALETTE_HEX, ColourToken
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for, require_adult_session
from mykhaya.entitlements import (
    ensure_home_subscription,
    explain_user_entitlement,
    grant_home_family_sponsorship,
    has_entitlement,
    require_within_limit,
    revoke_home_family_sponsorship,
)
from mykhaya.household_permissions import (
    DELEGATABLE_CAPABILITIES,
    Capability,
    capabilities_for,
    default_profile,
    ensure_can_assign_relationship,
    home_admin_count,
    legacy_role,
    require_capability,
)
from mykhaya.member_colours import assign_member_colour
from mykhaya.models import (
    CalendarEventLabel,
    ChildProfile,
    Group,
    HomeCalendar,
    HomeEntitlementGrant,
    HomeJoinRequest,
    HomeJoinRequestStatus,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    User,
)
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.schemas import (
    FamilySponsorshipChange,
    GroupCreate,
    GroupResponse,
    GroupUpdate,
    HomeJoinCodeResponse,
    HomeJoinRequestApprove,
    HomeJoinRequestDecline,
    HomeJoinRequestListItem,
    MemberColourUpdate,
    MemberRelationshipUpdate,
    MemberResponse,
)
from mykhaya.secrets_crypto import decrypt_home_join_code, encrypt_home_join_code
from mykhaya.security import (
    format_home_join_code,
    generate_home_code,
    generate_home_join_code,
    hash_secret,
)

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


def _avatar_filename() -> str:
    return f"{uuid.uuid4()}.webp"


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
    await ensure_home_subscription(db, group.id)
    await db.flush()
    for index, (name, color) in enumerate(DEFAULT_LABELS):
        db.add(
            CalendarEventLabel(
                group_id=group.id,
                name=name,
                color=PALETTE_HEX[color],
                is_system=True,
                sort_order=(index + 1) * 10,
                # This is the actual, user-facing "event category" resource
                # (see Settings -> Home settings "Calendars & categories" —
                # every event belongs to one of these) and calendar.max_categories
                # is enforced against its active count (routers.calendar's
                # create_label/update_label). A brand-new Home is always Free
                # at creation time, so only the first seeded label starts
                # active; the rest stay available to activate once/if the
                # Home is on Family, rather than all appearing active
                # immediately. See docs/architecture/commercial-entitlements.md
                # "Event categories are CalendarEventLabel, not HomeCalendar".
                is_active=index == 0,
            )
        )
    # The creating home_admin is always an adult — give them their Personal
    # Calendar up front rather than relying solely on list_calendars' lazy
    # fallback. See mykhaya.calendar_provisioning.
    await ensure_personal_calendar(db, group.id, auth.user.id)
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
    home = await db.get(Group, group_id)
    home_owner_id = home.created_by if home is not None else None
    rows = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.group_id == group_id, Membership.removed_at.is_(None))
            .order_by(User.display_name)
            .limit(200)
        )
    ).all()
    sponsored_ids = set(
        await db.scalars(
            select(HomeEntitlementGrant.recipient_user_id).where(
                HomeEntitlementGrant.source_group_id == group_id,
                HomeEntitlementGrant.entitlement_key == "family",
                HomeEntitlementGrant.revoked_at.is_(None),
            )
        )
    )
    result = []
    for membership, user in rows:
        decision = (
            await explain_user_entitlement(db, user.id, group_id, "family_plans.enabled")
            if membership.relationship != HouseholdRelationship.child
            else None
        )
        result.append(MemberResponse(
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
            family_sponsored=(
                user.id != home_owner_id
                and membership.relationship != HouseholdRelationship.home_admin
                and user.id in sponsored_ids
            ),
            family_access=decision is not None,
        ))
    return result


async def _member_response_for_user(
    db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> MemberResponse:
    membership = await db.scalar(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
            Membership.removed_at.is_(None),
        )
    )
    user = await db.get(User, user_id)
    if membership is None or user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person could not be found.")
    home = await db.get(Group, group_id)
    home_derived_access = (
        home is not None
        and (user.id == home.created_by or membership.relationship == HouseholdRelationship.home_admin)
    )
    sponsored = await db.scalar(
        select(HomeEntitlementGrant.id).where(
            HomeEntitlementGrant.source_group_id == group_id,
            HomeEntitlementGrant.recipient_user_id == user_id,
            HomeEntitlementGrant.entitlement_key == "family",
            HomeEntitlementGrant.revoked_at.is_(None),
        )
    )
    decision = (
        await explain_user_entitlement(db, user_id, group_id, "family_plans.enabled")
        if membership.relationship != HouseholdRelationship.child
        else None
    )
    return MemberResponse(
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
        family_sponsored=not home_derived_access and sponsored is not None,
        family_access=decision is not None,
    )


@router.post(
    "/{group_id}/members/{user_id}/family-sponsorship",
    response_model=MemberResponse,
)
async def grant_family_sponsorship(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    body: FamilySponsorshipChange,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    await require_capability(group_id, Capability.members_manage_relationships, auth, db)
    grant = await grant_home_family_sponsorship(db, group_id, user_id, auth.user.id)
    audit(
        db, request, "membership.family_sponsorship_granted", auth.user.id,
        group_id, "user", user_id, {"reason": body.reason, "grant_id": str(grant.id)},
    )
    await db.commit()
    return await _member_response_for_user(db, group_id, user_id)


@router.delete(
    "/{group_id}/members/{user_id}/family-sponsorship",
    response_model=MemberResponse,
)
async def revoke_family_sponsorship(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    body: FamilySponsorshipChange,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    await require_capability(group_id, Capability.members_manage_relationships, auth, db)
    changed = await revoke_home_family_sponsorship(db, group_id, user_id)
    if not changed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Family sponsorship was not found.")
    audit(
        db, request, "membership.family_sponsorship_revoked", auth.user.id,
        group_id, "user", user_id, {"reason": body.reason},
    )
    await db.commit()
    return await _member_response_for_user(db, group_id, user_id)


@router.post("/{group_id}/members/{user_id}/avatar", response_model=MemberResponse)
async def upload_child_member_avatar(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MemberResponse:
    """Replace a managed child's avatar from an authorised adult member flow.

    This deliberately uses member-management authority rather than the child's
    optional ``photo_upload`` setting: the setting controls child self-service,
    while this route is an adult managing a child profile.
    """
    require_adult_session(auth)
    await require_capability(group_id, Capability.members_manage_relationships, auth, db)
    target = await db.scalar(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
            Membership.relationship == HouseholdRelationship.child,
            Membership.removed_at.is_(None),
        )
    )
    if target is None or await db.scalar(
        select(ChildProfile.id).where(ChildProfile.membership_id == target.id)
    ) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That managed child could not be found.")
    user = await db.get(User, user_id)
    assert user is not None
    await enforce_rate_limit(request, settings, "child-avatar-upload", 20, 3600)
    raw = await file.read(settings.avatar_max_upload_bytes + 1)
    if len(raw) > settings.avatar_max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That photo is too large. Please choose one under "
            f"{settings.avatar_max_upload_bytes // (1024 * 1024)} MB.",
        )
    if not raw:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No file was uploaded.")
    try:
        processed = process_avatar_upload(raw)
    except AvatarResourceError as cause:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That photo is too large to process. Please choose another image.",
        ) from cause
    except UnsupportedImageError as cause:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(cause)) from cause

    storage = get_avatar_storage(settings)
    new_key = _avatar_filename()
    await storage.save(new_key, processed)
    previous_key = user.avatar_key
    user.avatar_key = new_key
    user.avatar_updated_at = datetime.now(UTC)
    db.add(user)
    audit(
        db,
        request,
        "child.avatar_replaced" if previous_key else "child.avatar_uploaded",
        auth.user.id,
        group_id,
        "membership",
        target.id,
        {"target_user_id": str(user_id)},
    )
    await db.commit()
    if previous_key:
        try:
            await storage.delete(previous_key)
        except OSError:
            pass
    return MemberResponse(
        membership_id=target.id,
        user_id=user.id,
        display_name=user.display_name,
        email=None,
        role=target.role,
        relationship=target.relationship,
        permission_profile=target.permission_profile,
        permission_overrides=target.permission_overrides,
        shared_resources=target.shared_resources,
        colour=target.colour,
        avatar_version=user.avatar_key,
    )


@router.delete("/{group_id}/members/{user_id}/avatar", response_model=MemberResponse)
async def remove_child_member_avatar(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MemberResponse:
    require_adult_session(auth)
    await require_capability(group_id, Capability.members_manage_relationships, auth, db)
    target = await db.scalar(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
            Membership.relationship == HouseholdRelationship.child,
            Membership.removed_at.is_(None),
        )
    )
    if target is None or await db.scalar(
        select(ChildProfile.id).where(ChildProfile.membership_id == target.id)
    ) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That managed child could not be found.")
    user = await db.get(User, user_id)
    assert user is not None
    previous_key = user.avatar_key
    if previous_key:
        user.avatar_key = None
        user.avatar_updated_at = None
        db.add(user)
        audit(
            db, request, "child.avatar_removed", auth.user.id, group_id,
            "membership", target.id, {"target_user_id": str(user_id)},
        )
        await db.commit()
        try:
            await get_avatar_storage(settings).delete(previous_key)
        except OSError:
            pass
    return MemberResponse(
        membership_id=target.id,
        user_id=user.id,
        display_name=user.display_name,
        email=None,
        role=target.role,
        relationship=target.relationship,
        permission_profile=target.permission_profile,
        permission_overrides=target.permission_overrides,
        shared_resources=target.shared_resources,
        colour=target.colour,
        avatar_version=user.avatar_key,
    )


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
    # Extended Family/Friend as a Home-member relationship is retired in
    # favour of external Calendar Sharing (mykhaya.routers.calendar_sharing)
    # — see routers.invitations' matching block. An existing external member
    # keeps working normally (transition-safe, untouched by this check); this
    # only blocks a *fresh* transition of some other member into that state,
    # the PATCH-endpoint equivalent of invitations.py no longer accepting it
    # for new invitations.
    was_external = target.relationship in {
        HouseholdRelationship.extended_family,
        HouseholdRelationship.friend,
    }
    will_be_external = body.relationship in {
        HouseholdRelationship.extended_family,
        HouseholdRelationship.friend,
    }
    if will_be_external and not was_external:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Extended Family and Friends are no longer added as Home members. "
            "Use calendar sharing to give someone outside the Home access instead.",
        )
    if (
        body.permission_profile == PermissionProfile.home_admin
        and body.relationship != HouseholdRelationship.home_admin
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Home Admin permissions require the Home Admin relationship.",
        )
    invalid_overrides = sorted(
        raw
        for raw in body.permission_overrides
        if raw not in {cap.value for cap in DELEGATABLE_CAPABILITIES}
    )
    if invalid_overrides:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {
                "message": "These capabilities cannot be configured as member overrides.",
                "capabilities": invalid_overrides,
            },
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


async def _unique_join_code_hash(db: AsyncSession, settings: Settings) -> tuple[str, str]:
    """Returns (raw_code, digest) for a freshly generated, collision-checked
    join code — mirrors _unique_home_code's retry loop above, against the
    separate join_code_hash column rather than child_login_code."""
    for _ in range(10):
        raw = generate_home_join_code()
        digest = hash_secret(raw, settings.secret_key.get_secret_value())
        if await db.scalar(select(Group.id).where(Group.join_code_hash == digest)) is None:
            return raw, digest
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create a join code.")


@router.get("/{group_id}/join-code", response_model=HomeJoinCodeResponse)
async def get_join_code(
    group_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HomeJoinCodeResponse:
    membership = await require_capability(group_id, Capability.members_invite, auth, db)
    group = membership.group
    if group.join_code_encrypted is None:
        return HomeJoinCodeResponse(code=None, generated_at=None)
    raw = decrypt_home_join_code(settings, group.join_code_encrypted)
    return HomeJoinCodeResponse(
        code=format_home_join_code(raw), generated_at=group.join_code_generated_at
    )


@router.post("/{group_id}/join-code/regenerate", response_model=HomeJoinCodeResponse)
async def regenerate_join_code(
    group_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HomeJoinCodeResponse:
    require_adult_session(auth)
    await require_capability(group_id, Capability.members_invite, auth, db)
    # Matches invitations.invite()'s "household-invitation" bucket shape
    # (20/3600) — generous enough for legitimate re-shares/regenerations,
    # nowhere near enough to matter for abuse (this endpoint doesn't try
    # codes, it only mints new ones).
    await enforce_rate_limit(request, settings, "home-join-code-regenerate", 20, 3600)
    group = await db.get(Group, group_id, with_for_update=True)
    assert group is not None
    raw, digest = await _unique_join_code_hash(db, settings)
    # Regenerating immediately invalidates the previous code — overwriting
    # both columns means the old raw code can no longer be looked up
    # (digest changed) or re-displayed (old ciphertext is gone).
    group.join_code_hash = digest
    group.join_code_encrypted = encrypt_home_join_code(settings, raw)
    group.join_code_generated_at = datetime.now(UTC)
    audit(db, request, "home.join_code_regenerated", auth.user.id, group_id, "group", group_id)
    await db.commit()
    return HomeJoinCodeResponse(
        code=format_home_join_code(raw), generated_at=group.join_code_generated_at
    )


@router.get("/{group_id}/join-requests", response_model=list[HomeJoinRequestListItem])
async def list_join_requests(
    group_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[HomeJoinRequestListItem]:
    await require_capability(group_id, Capability.members_invite, auth, db)
    rows = (
        await db.execute(
            select(HomeJoinRequest, User)
            .join(User, User.id == HomeJoinRequest.user_id)
            .where(
                HomeJoinRequest.group_id == group_id,
                HomeJoinRequest.status == HomeJoinRequestStatus.pending,
            )
            .order_by(HomeJoinRequest.created_at)
            .limit(100)
        )
    ).all()
    return [
        HomeJoinRequestListItem(
            id=row.id,
            user_id=user.id,
            display_name=user.display_name,
            email=user.email,
            status=row.status,
            method=row.method,
            created_at=row.created_at,
        )
        for row, user in rows
    ]


_ALLOWED_JOIN_APPROVAL_RELATIONSHIPS = {
    HouseholdRelationship.home_admin,
    HouseholdRelationship.partner,
    HouseholdRelationship.adult,
}


@router.post("/{group_id}/join-requests/{request_id}/approve", response_model=MemberResponse)
async def approve_join_request(
    group_id: uuid.UUID,
    request_id: uuid.UUID,
    body: HomeJoinRequestApprove,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    approver = await require_capability(group_id, Capability.members_invite, auth, db)
    ensure_can_assign_relationship(approver, body.relationship)
    if body.relationship not in _ALLOWED_JOIN_APPROVAL_RELATIONSHIPS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Choose Home Admin, Partner or Adult for a join-code request.",
        )
    join_request = await db.scalar(
        select(HomeJoinRequest)
        .where(
            HomeJoinRequest.id == request_id,
            HomeJoinRequest.group_id == group_id,
            HomeJoinRequest.status == HomeJoinRequestStatus.pending,
        )
        .with_for_update()
    )
    if join_request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That join request could not be found.")

    # Same race-safe Free-Home member-limit check invitations.accept() uses,
    # under the same per-Home advisory lock/bucket — see that function's
    # docstring for why the lock matters even though a fresh join request
    # always increases membership (never a no-op re-accept).
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

    existing = await db.scalar(
        select(Membership)
        .where(Membership.group_id == group_id, Membership.user_id == join_request.user_id)
        .with_for_update()
    )
    if existing is not None and existing.removed_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That person is already a member of this Home."
        )

    role = legacy_role(body.relationship)
    permission_profile = default_profile(body.relationship)
    if existing is None:
        membership = Membership(
            group_id=group_id,
            user_id=join_request.user_id,
            role=role,
            relationship=body.relationship,
            permission_profile=permission_profile,
            family_sponsorship_decided=body.family_sponsorship,
            colour=await assign_member_colour(db, group_id),
        )
        db.add(membership)
    else:
        existing.removed_at = None
        existing.role = role
        existing.relationship = body.relationship
        existing.permission_profile = permission_profile
        existing.family_sponsorship_decided = body.family_sponsorship
        if existing.colour is None:
            existing.colour = await assign_member_colour(db, group_id)
        membership = existing
    await ensure_personal_calendar(db, group_id, join_request.user_id)
    if body.family_sponsorship and await has_entitlement(
        db, group_id, "family_plans.enabled"
    ):
        await grant_home_family_sponsorship(
            db, group_id, join_request.user_id, auth.user.id
        )

    join_request.status = HomeJoinRequestStatus.approved
    join_request.relationship = body.relationship
    join_request.decided_by = auth.user.id
    join_request.decided_at = datetime.now(UTC)
    await db.flush()

    user = await db.get(User, join_request.user_id)
    assert user is not None
    audit(
        db,
        request,
        "home_join_request.approved",
        auth.user.id,
        group_id,
        "home_join_request",
        join_request.id,
        {"relationship": body.relationship.value, "reason": body.reason},
    )
    await db.commit()
    return await _member_response_for_user(db, group_id, user.id)


@router.post(
    "/{group_id}/join-requests/{request_id}/decline", status_code=status.HTTP_204_NO_CONTENT
)
async def decline_join_request(
    group_id: uuid.UUID,
    request_id: uuid.UUID,
    body: HomeJoinRequestDecline,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_capability(group_id, Capability.members_invite, auth, db)
    join_request = await db.scalar(
        select(HomeJoinRequest)
        .where(
            HomeJoinRequest.id == request_id,
            HomeJoinRequest.group_id == group_id,
            HomeJoinRequest.status == HomeJoinRequestStatus.pending,
        )
        .with_for_update()
    )
    if join_request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That join request could not be found.")
    join_request.status = HomeJoinRequestStatus.declined
    join_request.decided_by = auth.user.id
    join_request.decided_at = datetime.now(UTC)
    audit(
        db,
        request,
        "home_join_request.declined",
        auth.user.id,
        group_id,
        "home_join_request",
        join_request.id,
        {"reason": body.reason},
    )
    await db.commit()
