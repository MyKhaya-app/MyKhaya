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
    household_manage_reminders = "household.manage_reminders"
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
    # Household Lists (mykhaya.routers.lists) — same shared-structure "view
    # vs manage" split as Meal Plans, reusing FeatureKey.shopping's release
    # slot and the pre-declared "lists.enabled" entitlement (see
    # entitlements.PLAN_DEFINITIONS) rather than adding a new feature key.
    lists_view = "lists.view"
    lists_manage = "lists.manage"
    # Wishlists (mykhaya.routers.wishlists) — "view" is the household-wide
    # capability that lets a member see the module and other members'
    # wishlists at all; "manage" lets them create/edit/delete wishlists —
    # but every create/edit/delete endpoint *also* requires the caller to be
    # that wishlist's own owner (or home_admin), since unlike Meals/Lists
    # this is a per-person module, not shared household structure. See
    # routers.wishlists._require_owner_or_admin.
    wishlists_view = "wishlists.view"
    wishlists_manage = "wishlists.manage"


ALL_CAPABILITIES = frozenset(Capability)
# This is intentionally an allow-list.  A capability added in the future is
# not delegatable until its authority and data boundary have been reviewed.
DELEGATABLE_CAPABILITIES = frozenset(
    {
        Capability.members_view,
        Capability.calendar_view,
        Capability.calendar_view_all,
        Capability.calendar_create,
        Capability.calendar_edit_own,
        Capability.calendar_edit_all,
        Capability.calendar_delete,
        Capability.household_manage_routines,
        Capability.household_manage_reminders,
        Capability.meals_view,
        Capability.meals_manage,
        Capability.lists_view,
        Capability.lists_manage,
        Capability.wishlists_view,
        Capability.wishlists_manage,
        Capability.sharing_external,
    }
)
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
            Capability.household_manage_reminders,
            Capability.meals_view,
            Capability.meals_manage,
            Capability.lists_view,
            Capability.lists_manage,
            Capability.wishlists_view,
            Capability.wishlists_manage,
            # A Partner/Adult may request an external calendar share (see
            # routers.calendar_sharing) — sending it outright vs. requiring
            # Home Admin approval is decided per-request there (whether the
            # caller is home_admin or the calendar's own personal owner),
            # not by this capability alone.
            Capability.sharing_external,
        }
    ),
    # Read-only baseline: a Child can always see today's household meals —
    # this is ordinary shared household information (like Routines, which
    # has no capability gate on its read endpoint at all — see
    # routers.household_routines.list_routines), not something that needs
    # parent configuration the way calendar visibility does. meals_manage
    # (create/edit/delete meals and plan entries) is deliberately NOT
    # included here — it stays out of reach for every Child regardless of
    # ChildProfile settings, since there is no child-facing "meals" toggle
    # in CHILD_PERMISSION_CAPABILITIES and none is being added.
    PermissionProfile.child_restricted: frozenset({Capability.meals_view}),
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
        # Adult reuses Partner's default profile — relationship describes who
        # someone is, not what they can do (see HouseholdRelationship.adult's
        # docstring). They stay a distinct relationship value; only the
        # *default* PermissionProfile is shared, and Advanced permissions
        # (permission_overrides) still apply independently per member.
        HouseholdRelationship.adult: PermissionProfile.standard_partner,
        HouseholdRelationship.child: PermissionProfile.child_restricted,
        HouseholdRelationship.extended_family: PermissionProfile.explicit_sharing,
        HouseholdRelationship.friend: PermissionProfile.explicit_sharing,
        HouseholdRelationship.review_required: PermissionProfile.review_required,
    }[relationship]


def legacy_role(relationship: HouseholdRelationship) -> Role:
    return {
        HouseholdRelationship.home_admin: Role.administrator,
        HouseholdRelationship.partner: Role.adult_member,
        HouseholdRelationship.adult: Role.adult_member,
        HouseholdRelationship.child: Role.member,
        HouseholdRelationship.extended_family: Role.guest,
        HouseholdRelationship.friend: Role.guest,
        HouseholdRelationship.review_required: Role.member,
    }[relationship]


async def capabilities_for(db: AsyncSession, membership: Membership) -> set[Capability]:
    # Administrative authority is bound to the trusted relationship/profile
    # state.  Do not let a stale or manually-corrupted profile value turn a
    # non-admin membership into a Home Admin.
    profile = membership.permission_profile
    if (
        profile == PermissionProfile.home_admin
        and membership.relationship != HouseholdRelationship.home_admin
    ):
        profile = default_profile(membership.relationship)
    capabilities = set(PROFILE_CAPABILITIES[profile])
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
        if capability not in DELEGATABLE_CAPABILITIES:
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
