import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.models import FeatureFlag, FeatureKey, FeatureOverride
from mykhaya.platform_schemas import FeatureEvaluationResponse

router = APIRouter(prefix="/features", tags=["features"])


@router.get("/{group_id}/{feature}", response_model=FeatureEvaluationResponse)
async def evaluate_feature(
    group_id: uuid.UUID,
    feature: FeatureKey,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> FeatureEvaluationResponse:
    await membership_for(group_id, auth, db)
    override = await db.scalar(
        select(FeatureOverride).where(
            FeatureOverride.group_id == group_id,
            FeatureOverride.feature_key == feature,
        )
    )
    global_flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == feature))
    enabled = (
        override.enabled if override is not None else bool(global_flag and global_flag.enabled)
    )
    return FeatureEvaluationResponse(feature=feature, enabled=enabled)
