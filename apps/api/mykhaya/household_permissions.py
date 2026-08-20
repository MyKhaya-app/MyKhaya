import uuid
from enum import StrEnum

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.dependencies import AuthContext, membership_for
from mykhaya.models import (
    ChildProfile,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
)


class Capability(StrEnum):
    household_manage = "household.manage"
    members_view = "members.view"
    members_invite = "members.invite"
    members_manage_relationships = "members.manage_relationships"
    calendar_view = "calendar.view"
    calendar_view_all = "calendar.view_all"
    calendar_create = "calendar.create"
    calendar_edit_own = "calendar.edit_own"
    calendar_edit_all = "calendar.edit_all"
    calendar_delete = "calendar.delete"
    features_manage = "features.manage"
    control_centre_access = "control_centre.access"
    child_manage = "child.manage"
    child_permissions_manage = "child.permissions.manage"
    sharing_external = "sharing.external"
    household_export = "household.export"
    security_manage = "security.manage"
    household_manage_routines = "household.manage_routines"
    # Starting Stripe Checkout, opening the Customer Portal, and (future)
    # cancellation actions — home_admin only, matching household.manage and
    # features.manage. A standard_partner belonging to the Home is not
    # automatically trusted with payment-method management just by being a
    # member; billing decisions stay with whoever administers the Home. See
    # docs/security/platform-administration-security.md#billing-manage.
    billing_manage = "billing.manage"
    # Meal Plans (mykhaya.routers.meal_plans) — shared household structure,
    # the same "view vs manage" split calendar categories use, not a
    # per-person ownership model. See docs/architecture/meal-plans.md.
    meals_view = "meals.view"
    meals_manage = "meals.manage"


ALL_CAPABILITIES = frozenset(Capability)
PROFILE_CAPABILITIES: dict[PermissionProfile, frozenset[Capability]] = {
    PermissionProfile.home_admin: ALL_CAPABILITIES,
    PermissionProfile.standard_partner: frozenset(
        {
            Capability.members_view,
            Capability.calendar_view,
            Capability.calendar_view_all,
            Capability.calendar_create,
            Capability.calendar_edit_own,
            Capability.calendar_edit_all,
            Capability.calendar_delete,
            Capability.household_manage_routines,
            Capability.meals_view,
            Capability.meals_manage,
        }
    ),
    PermissionProfile.child_restricted: frozenset(),
    PermissionProfile.explicit_sharing: frozenset(),
    PermissionProfile.review_required: frozenset({Capability.members_view}),
}

CHILD_PERMISSION_CAPABILITIES = {
    "calendar_view": Capability.calendar_view,
    "calendar_create": Capability.calendar_create,
    "calendar_edit_own": Capability.calendar_edit_own,
    "view_other_members_events": Capability.calendar_view_all,
    "external_sharing": Capability.sharing_external,
}

SAFE_CHILD_DEFAULTS: dict[str, bool] = {
    "calendar_view": False,
    "calendar_create": False,
    "calendar_edit_own": False,
    "view_other_members_events": False,
    "tasks_access": False,
    "shopping_access": False,
    "shopping_add": False,
    "photo_upload": False,
    "selected_albums_view": False,
    "chat_access": False,
    "push_notifications": False,
    "location_share": False,
    "location_view_others": False,
    "wish_lists_access": False,
    "selected_documents_view": False,
    "external_sharing": False,
}


def default_profile(relationship: HouseholdRelationship) -> PermissionProfile:
    return {
        HouseholdRelationship.home_admin: PermissionProfile.home_admin,
        HouseholdRelationship.partner: PermissionProfile.standard_partner,
        HouseholdRelationship.child: PermissionProfile.child_restricted,
        HouseholdRelationship.extended_family: PermissionProfile.explicit_sharing,
        HouseholdRelationship.friend: PermissionProfile.explicit_sharing,
        HouseholdRelationship.review_required: PermissionProfile.review_required,
    }[relationship]


def legacy_role(relationship: HouseholdRelationship) -> Role:
    return {
        HouseholdRelationship.home_admin: Role.administrator,
        HouseholdRelationship.partner: Role.adult_member,
        HouseholdRelationship.child: Role.member,
        HouseholdRelationship.extended_family: Role.guest,
        HouseholdRelationship.friend: Role.guest,
        HouseholdRelationship.review_required: Role.member,
    }[relationship]


async def capabilities_for(db: AsyncSession, membership: Membership) -> set[Capability]:
    capabilities = set(PROFILE_CAPABILITIES[membership.permission_profile])
    if (
        membership.relationship
        in {
            HouseholdRelationship.extended_family,
            HouseholdRelationship.friend,
        }
        and "calendar" in membership.shared_resources
    ):
        capabilities.add(Capability.calendar_view)
        capabilities.add(Capability.calendar_view_all)
    if membership.relationship == HouseholdRelationship.child:
        profile = await db.scalar(
            select(ChildProfile).where(ChildProfile.membership_id == membership.id)
        )
        child_permissions = SAFE_CHILD_DEFAULTS | (profile.permissions if profile else {})
        for setting, capability in CHILD_PERMISSION_CAPABILITIES.items():
            if child_permissions.get(setting, False):
                capabilities.add(capability)
    for raw, enabled in membership.permission_overrides.items():
        try:
            capability = Capability(raw)
        except ValueError:
            continue
        if enabled:
            capabilities.add(capability)
        else:
            capabilities.discard(capability)
    return capabilities


async def require_capability(
    group_id: uuid.UUID,
    capability: Capability,
    auth: AuthContext,
    db: AsyncSession,
) -> Membership:
    membership = await membership_for(group_id, auth, db)
    if capability not in await capabilities_for(db, membership):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You do not have permission to perform that action.",
        )
    return membership


async def home_admin_count(db: AsyncSession, group_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.group_id == group_id,
                Membership.relationship == HouseholdRelationship.home_admin,
                Membership.removed_at.is_(None),
            )
        )
        or 0
    )
