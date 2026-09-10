import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.entitlements import (
    CommercialRestrictionCode,
    commercial_restriction_error,
    has_entitlement,
)
from mykhaya.features import (
    enabled_dependents,
    feature_matrix,
    is_feature_enabled,
    platform_feature_enabled,
)
from mykhaya.household_permissions import (
    Capability,
    capabilities_for,
    require_capability,
)
from mykhaya.models import FeatureKey, FeatureOverride
from mykhaya.module_registry import (
    ModuleDefinition,
    ReleaseState,
    household_modules,
    module_definition,
)
from mykhaya.platform_schemas import FeatureEvaluationResponse, FeatureMatrixResponse
from mykhaya.schemas import HouseholdFeatureUpdate, HouseholdModuleResponse

router = APIRouter(prefix="/features", tags=["features"])

# Maps a module id to the boolean commercial-entitlement key that gates it,
# for modules that have one. A module absent here (Calendar, and every core
# module) is included on every plan — see docs/architecture/
# commercial-entitlements.md#plan-definitions. Kept here, not in
# mykhaya.module_registry, since the registry is platform/release-state
# only and must not know about commercial plans (see "Layering" in the
# architecture doc) — this is purely a display-time lookup for the Home
# Admin Module Management screen and the enable-request guard below.
_MODULE_ENTITLEMENT_KEYS: dict[str, str] = {
    FeatureKey.shopping.value: "lists.enabled",
    FeatureKey.meals.value: "meals.enabled",
    FeatureKey.wish_lists.value: "wishlists.enabled",
    FeatureKey.nudges.value: "nudges.enabled",
}


async def _module_state(
    db: AsyncSession, group_id: uuid.UUID, definition: ModuleDefinition
) -> tuple[bool, bool, bool, str | None]:
    """Returns (platform_ok, entitled, effective_enabled, blocked_by) for one
    module against one Home — the single place that combines the platform/
    Home feature-flag layer (mykhaya.features) with the commercial-
    entitlement layer (mykhaya.entitlements) for *display* purposes. Never
    used for API authorization itself — every router still calls
    require_feature/require_entitlement independently at its own boundary."""
    if definition.release_state == ReleaseState.core:
        return True, True, True, None
    platform_ok = await platform_feature_enabled(db, FeatureKey(definition.id))
    entitlement_key = _MODULE_ENTITLEMENT_KEYS.get(definition.id)
    entitled = (
        True if entitlement_key is None else await has_entitlement(db, group_id, entitlement_key)
    )
    home_state = await is_feature_enabled(db, definition.id, group_id)
    effective_enabled = entitled and home_state
    blocked_by = "platform" if not platform_ok else ("plan" if not entitled else None)
    return platform_ok, entitled, effective_enabled, blocked_by


@router.get("/{group_id}", response_model=FeatureMatrixResponse)
async def evaluate_features(
    group_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> FeatureMatrixResponse:
    await membership_for(group_id, auth, db)
    matrix = await feature_matrix(db, group_id)
    return FeatureMatrixResponse(
        features=[
            FeatureEvaluationResponse(feature=key, enabled=enabled)
            for key, enabled in matrix.items()
        ]
    )


@router.get("/{group_id}/{feature}", response_model=FeatureEvaluationResponse)
async def evaluate_feature(
    group_id: uuid.UUID,
    feature: FeatureKey,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> FeatureEvaluationResponse:
    await membership_for(group_id, auth, db)
    enabled = await is_feature_enabled(db, feature, group_id)
    return FeatureEvaluationResponse(feature=feature, enabled=enabled)


@router.get("/{group_id}/modules/management", response_model=list[HouseholdModuleResponse])
async def feature_management(
    group_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[HouseholdModuleResponse]:
    await require_capability(group_id, Capability.control_centre_access, auth, db)
    rows: list[HouseholdModuleResponse] = []
    for definition in household_modules():
        if not definition.home_admin_manageable:
            continue
        _platform_ok, entitled, enabled, blocked_by = await _module_state(db, group_id, definition)
        rows.append(
            HouseholdModuleResponse(
                id=definition.id,
                name=definition.name,
                description=definition.description,
                category=definition.category,
                release_state=definition.release_state.value,
                enabled=enabled,
                toggleable=definition.household_toggleable,
                introduced_version=definition.introduced_version,
                dependencies=list(definition.dependencies),
                permissions=list(definition.permissions),
                route=definition.route,
                entitled=entitled,
                blocked_by=blocked_by,
            )
        )
    return rows


@router.get("/{group_id}/modules/navigation", response_model=list[HouseholdModuleResponse])
async def navigation_modules(
    group_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[HouseholdModuleResponse]:
    membership = await membership_for(group_id, auth, db)
    capabilities = await capabilities_for(db, membership)
    required = {
        "household_members": Capability.members_view,
        FeatureKey.calendar.value: Capability.calendar_view,
    }
    rows: list[HouseholdModuleResponse] = []
    for definition in household_modules():
        if not definition.route or (
            definition.id in required and required[definition.id] not in capabilities
        ):
            continue
        # Phase 3A: this is a *consumer* navigation listing — Notifications
        # (core platform delivery infrastructure) and External sharing (a
        # Calendar capability, not a standalone destination) must never
        # appear here as if they were navigable modules in their own right,
        # exactly like the Home Admin Module Management listing above
        # already excludes them. household_modules() already excludes
        # hidden modules (Tasks/Plans) on its own.
        if not definition.home_admin_manageable:
            continue
        _platform_ok, entitled, enabled, _blocked_by = await _module_state(db, group_id, definition)
        if not enabled:
            continue
        rows.append(
            HouseholdModuleResponse(
                id=definition.id,
                name=definition.name,
                description=definition.description,
                category=definition.category,
                release_state=definition.release_state.value,
                enabled=True,
                toggleable=definition.household_toggleable,
                introduced_version=definition.introduced_version,
                dependencies=list(definition.dependencies),
                permissions=list(definition.permissions),
                route=definition.route,
                entitled=entitled,
                blocked_by=None,
            )
        )
    return rows


@router.put("/{group_id}/{feature}/household", response_model=HouseholdModuleResponse)
async def update_household_feature(
    group_id: uuid.UUID,
    feature: FeatureKey,
    body: HouseholdFeatureUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> HouseholdModuleResponse:
    await require_capability(group_id, Capability.features_manage, auth, db)
    definition = module_definition(feature.value)
    if not definition.household_toggleable:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not body.enabled:
        dependents = await enabled_dependents(db, group_id, definition.id)
        if dependents:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Disable dependent modules first: " + ", ".join(dependents),
            )
    else:
        # PCC platform availability is authoritative (see mykhaya.features):
        # a Home override can never make a module available that the
        # platform has disabled globally. Reject the enable attempt outright
        # rather than writing an override that would have no effect and
        # would misleadingly report success.
        if not await platform_feature_enabled(db, feature):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{definition.name} is currently unavailable platform-wide and cannot be "
                "enabled for this Home.",
            )
        # Commercial entitlement is a separate, independent layer from the
        # platform/Home feature flag above (see docs/architecture/
        # commercial-entitlements.md "Layering") — a Home FeatureOverride
        # must never bypass it. Checked after the platform gate, matching
        # the agreed authority order (platform, then plan, then Home Admin).
        entitlement_key = _MODULE_ENTITLEMENT_KEYS.get(feature.value)
        if entitlement_key is not None and not await has_entitlement(db, group_id, entitlement_key):
            raise commercial_restriction_error(
                CommercialRestrictionCode.plan_feature_unavailable,
                f"{definition.name} isn't included in your current plan.",
                entitlement=entitlement_key,
            )
        for dependency in definition.dependencies:
            dependency_definition = module_definition(dependency)
            if dependency_definition.release_state == ReleaseState.hidden:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "A required module is not available.",
                )
            if dependency not in {key.value for key in FeatureKey}:
                continue
            dependency_key = FeatureKey(dependency)
            if not await platform_feature_enabled(db, dependency_key):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "A required module is not available.",
                )
            if not await is_feature_enabled(db, dependency_key, group_id):
                dependency_row = await db.scalar(
                    select(FeatureOverride).where(
                        FeatureOverride.group_id == group_id,
                        FeatureOverride.feature_key == dependency_key,
                    )
                )
                if dependency_row is None:
                    db.add(
                        FeatureOverride(
                            group_id=group_id,
                            feature_key=dependency_key,
                            enabled=True,
                            updated_by_user_id=auth.user.id,
                        )
                    )
                else:
                    dependency_row.enabled = True
                    dependency_row.updated_by_user_id = auth.user.id
    row = await db.scalar(
        select(FeatureOverride)
        .where(
            FeatureOverride.group_id == group_id,
            FeatureOverride.feature_key == feature,
        )
        .with_for_update()
    )
    previous = row.enabled if row else None
    if row is None:
        row = FeatureOverride(
            group_id=group_id,
            feature_key=feature,
            enabled=body.enabled,
            updated_by_user_id=auth.user.id,
        )
        db.add(row)
    else:
        row.enabled = body.enabled
        row.updated_by_user_id = auth.user.id
    await db.flush()
    audit(
        db,
        request,
        "feature.enabled" if body.enabled else "feature.disabled",
        auth.user.id,
        group_id,
        "feature",
        row.id,
        {
            "feature": feature.value,
            "previous": previous,
            "enabled": body.enabled,
            "reason": body.reason,
        },
    )
    await db.commit()
    _platform_ok, entitled, effective_enabled, blocked_by = await _module_state(
        db, group_id, definition
    )
    return HouseholdModuleResponse(
        id=definition.id,
        name=definition.name,
        description=definition.description,
        category=definition.category,
        release_state=definition.release_state.value,
        enabled=effective_enabled,
        toggleable=True,
        introduced_version=definition.introduced_version,
        dependencies=list(definition.dependencies),
        permissions=list(definition.permissions),
        route=definition.route,
        entitled=entitled,
        blocked_by=blocked_by,
    )
