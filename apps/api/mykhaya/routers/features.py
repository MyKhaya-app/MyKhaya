import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.features import feature_matrix, is_feature_enabled
from mykhaya.models import FeatureKey
from mykhaya.platform_schemas import FeatureEvaluationResponse, FeatureMatrixResponse

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
        features=[FeatureEvaluationResponse(feature=key, enabled=matrix[key]) for key in FeatureKey]
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
