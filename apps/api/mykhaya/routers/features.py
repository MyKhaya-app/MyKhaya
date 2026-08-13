import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.features import (
    enabled_dependents,
    feature_matrix,
    is_feature_enabled,
)
from mykhaya.household_permissions import (
    Capability,
    capabilities_for,
    require_capability,
)
from mykhaya.models import FeatureKey, FeatureOverride
from mykhaya.module_registry import ReleaseState, household_modules, module_definition
from mykhaya.platform_schemas import FeatureEvaluationResponse, FeatureMatrixResponse
from mykhaya.schemas import HouseholdFeatureUpdate, HouseholdModuleResponse

router = APIRouter(prefix="/features", tags=["features"])


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
        enabled = (
            True
            if definition.release_state == ReleaseState.core
            else await is_feature_enabled(db, definition.id, group_id)
        )
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
        enabled = (
            True
            if definition.release_state == ReleaseState.core
            else await is_feature_enabled(db, definition.id, group_id)
        )
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
        for dependency in definition.dependencies:
            dependency_definition = module_definition(dependency)
            if dependency_definition.release_state == ReleaseState.hidden:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "A required module is not available.",
                )
            if dependency in {key.value for key in FeatureKey} and not await is_feature_enabled(
                db, dependency, group_id
            ):
                dependency_key = FeatureKey(dependency)
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
    return HouseholdModuleResponse(
        id=definition.id,
        name=definition.name,
        description=definition.description,
        category=definition.category,
        release_state=definition.release_state.value,
        enabled=body.enabled,
        toggleable=True,
        introduced_version=definition.introduced_version,
        dependencies=list(definition.dependencies),
        permissions=list(definition.permissions),
        route=definition.route,
    )
