import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import (
    AuthContext,
    PlatformAuthContext,
    auth_context,
    membership_for,
    platform_auth_context,
    platform_membership_for,
)
from mykhaya.features import home_feature_matrix
from mykhaya.models import (
    FeatureFlag,
    FeatureFlagHomeOverride,
    FeatureFlagKey,
    PlatformRole,
)
from mykhaya.schemas import (
    HomeFeatureResponse,
    HomeFeaturesEnvelope,
    MessageResponse,
    PlatformFeatureOverrideResponse,
    PlatformFeatureOverrideUpdate,
    PlatformFeatureResponse,
    PlatformFeatureUpdate,
)

router = APIRouter(tags=["features"])
PLATFORM_MANAGERS = {PlatformRole.owner, PlatformRole.administrator}


@router.get("/homes/{home_id}/features", response_model=HomeFeaturesEnvelope)
async def home_features(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> HomeFeaturesEnvelope:
    await membership_for(home_id, auth, db)
    matrix = await home_feature_matrix(db, home_id)
    return HomeFeaturesEnvelope(
        home_id=home_id,
        features=[HomeFeatureResponse(key=key, enabled=enabled, source=source) for key, enabled, source in matrix],
    )


@router.get("/platform/features", response_model=list[PlatformFeatureResponse])
async def list_platform_features(
    platform_auth: PlatformAuthContext = Depends(platform_auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[PlatformFeatureResponse]:
    await platform_membership_for(platform_auth, db)
    rows = (await db.scalars(select(FeatureFlag).order_by(FeatureFlag.key))).all()
    return [
        PlatformFeatureResponse(
            key=row.key,
            display_name=row.display_name,
            description=row.description,
            globally_enabled=row.enabled,
        )
        for row in rows
    ]


@router.patch("/platform/features/{feature_key}", response_model=PlatformFeatureResponse)
async def update_platform_feature(
    feature_key: FeatureFlagKey,
    body: PlatformFeatureUpdate,
    request: Request,
    platform_auth: PlatformAuthContext = Depends(platform_auth_context),
    db: AsyncSession = Depends(get_db),
) -> PlatformFeatureResponse:
    manager = await platform_membership_for(platform_auth, db, PLATFORM_MANAGERS)
    row = await db.scalar(
        select(FeatureFlag).where(FeatureFlag.key == feature_key).with_for_update()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That feature flag does not exist.")
    row.enabled = body.enabled
    row.updated_by_platform_user_id = platform_auth.user.id
    audit(
        db,
        request,
        "feature.global_updated",
        platform_auth.user.id,
        target_type="feature_flag",
        target_id=row.id,
        metadata={
            "feature_key": feature_key.value,
            "enabled": body.enabled,
            "reason": body.reason,
            "platform_role": manager.role.value,
        },
    )
    await db.commit()
    return PlatformFeatureResponse(
        key=row.key,
        display_name=row.display_name,
        description=row.description,
        globally_enabled=row.enabled,
    )


@router.patch(
    "/platform/features/{feature_key}/homes/{home_id}",
    response_model=PlatformFeatureOverrideResponse,
)
async def update_home_feature_override(
    feature_key: FeatureFlagKey,
    home_id: uuid.UUID,
    body: PlatformFeatureOverrideUpdate,
    request: Request,
    platform_auth: PlatformAuthContext = Depends(platform_auth_context),
    db: AsyncSession = Depends(get_db),
) -> PlatformFeatureOverrideResponse:
    manager = await platform_membership_for(platform_auth, db, PLATFORM_MANAGERS)
    flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == feature_key))
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That feature flag does not exist.")

    row = await db.scalar(
        select(FeatureFlagHomeOverride)
        .where(
            FeatureFlagHomeOverride.feature_flag_id == flag.id,
            FeatureFlagHomeOverride.group_id == home_id,
        )
        .with_for_update()
    )
    if row is None:
        row = FeatureFlagHomeOverride(feature_flag_id=flag.id, group_id=home_id, enabled=body.enabled)
        db.add(row)
    else:
        row.enabled = body.enabled
    row.updated_by_platform_user_id = platform_auth.user.id

    audit(
        db,
        request,
        "feature.home_override_updated",
        platform_auth.user.id,
        group_id=home_id,
        target_type="feature_flag",
        target_id=flag.id,
        metadata={
            "feature_key": feature_key.value,
            "enabled": body.enabled,
            "reason": body.reason,
            "platform_role": manager.role.value,
        },
    )
    await db.commit()
    return PlatformFeatureOverrideResponse(
        key=feature_key,
        home_id=home_id,
        enabled=row.enabled,
        source="home_override",
    )


@router.delete(
    "/platform/features/{feature_key}/homes/{home_id}",
    response_model=MessageResponse,
)
async def clear_home_feature_override(
    feature_key: FeatureFlagKey,
    home_id: uuid.UUID,
    request: Request,
    platform_auth: PlatformAuthContext = Depends(platform_auth_context),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    manager = await platform_membership_for(platform_auth, db, PLATFORM_MANAGERS)
    flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == feature_key))
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That feature flag does not exist.")

    row = await db.scalar(
        select(FeatureFlagHomeOverride)
        .where(
            FeatureFlagHomeOverride.feature_flag_id == flag.id,
            FeatureFlagHomeOverride.group_id == home_id,
        )
        .with_for_update()
    )
    if row is not None:
        await db.delete(row)

    audit(
        db,
        request,
        "feature.home_override_cleared",
        platform_auth.user.id,
        group_id=home_id,
        target_type="feature_flag",
        target_id=flag.id,
        metadata={
            "feature_key": feature_key.value,
            "platform_role": manager.role.value,
        },
    )
    await db.commit()
    return MessageResponse(message="Home feature override removed.")
