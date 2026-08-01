import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import FeatureFlag, FeatureFlagHomeOverride, FeatureFlagKey

FEATURE_KEYS: tuple[FeatureFlagKey, ...] = tuple(FeatureFlagKey)


async def is_feature_enabled(
    db: AsyncSession, feature_key: str, home_id: uuid.UUID | None = None
) -> bool:
    """Return whether a feature is enabled, failing closed for unknown keys."""
    try:
        typed_key = FeatureFlagKey(feature_key)
    except ValueError:
        return False

    global_flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == typed_key))
    if global_flag is None:
        return False
    if home_id is None:
        return bool(global_flag.enabled)

    override = await db.scalar(
        select(FeatureFlagHomeOverride.enabled)
        .join(FeatureFlag, FeatureFlag.id == FeatureFlagHomeOverride.feature_flag_id)
        .where(FeatureFlag.key == typed_key, FeatureFlagHomeOverride.group_id == home_id)
    )
    if override is None:
        return bool(global_flag.enabled)
    return bool(override)


async def home_feature_matrix(
    db: AsyncSession, home_id: uuid.UUID
) -> list[tuple[FeatureFlagKey, bool, str]]:
    rows = (
        await db.execute(
            select(
                FeatureFlag.key,
                FeatureFlag.enabled,
                FeatureFlagHomeOverride.enabled,
            )
            .outerjoin(
                FeatureFlagHomeOverride,
                (FeatureFlagHomeOverride.feature_flag_id == FeatureFlag.id)
                & (FeatureFlagHomeOverride.group_id == home_id),
            )
            .order_by(FeatureFlag.key)
        )
    ).all()

    result: list[tuple[FeatureFlagKey, bool, str]] = []
    for key, global_enabled, home_override in rows:
        if home_override is None:
            result.append((key, bool(global_enabled), "global"))
        else:
            result.append((key, bool(home_override), "home_override"))

    existing = {key for key, _, _ in result}
    for key in FEATURE_KEYS:
        if key not in existing:
            result.append((key, False, "global"))
    result.sort(key=lambda item: item[0].value)
    return result
