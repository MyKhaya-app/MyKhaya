import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import FeatureFlag, FeatureKey, FeatureOverride


async def is_feature_enabled(
    db: AsyncSession,
    feature_key: FeatureKey | str,
    home_id: uuid.UUID | None = None,
) -> bool:
    """Evaluate Home override, then global state, failing closed for unknown keys."""
    try:
        key = feature_key if isinstance(feature_key, FeatureKey) else FeatureKey(feature_key)
    except ValueError:
        return False

    if home_id is not None:
        override = await db.scalar(
            select(FeatureOverride.enabled).where(
                FeatureOverride.group_id == home_id,
                FeatureOverride.feature_key == key,
            )
        )
        if override is not None:
            return bool(override)

    global_value = await db.scalar(select(FeatureFlag.enabled).where(FeatureFlag.key == key))
    return bool(global_value) if global_value is not None else False


async def feature_matrix(db: AsyncSession, home_id: uuid.UUID) -> dict[FeatureKey, bool]:
    flags = {row.key: bool(row.enabled) for row in (await db.scalars(select(FeatureFlag))).all()}
    overrides = {
        row.feature_key: bool(row.enabled)
        for row in (
            await db.scalars(select(FeatureOverride).where(FeatureOverride.group_id == home_id))
        ).all()
    }
    return {key: overrides.get(key, flags.get(key, False)) for key in FeatureKey}


async def require_feature(
    db: AsyncSession,
    feature_key: FeatureKey,
    home_id: uuid.UUID,
) -> None:
    if not await is_feature_enabled(db, feature_key, home_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
