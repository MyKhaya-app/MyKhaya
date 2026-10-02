import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import FeatureFlag, FeatureKey, FeatureOverride
from mykhaya.module_registry import ReleaseState, feature_modules, module_definition


async def platform_feature_enabled(db: AsyncSession, feature_key: FeatureKey) -> bool:
    """The PCC global FeatureFlag state alone — the top of the authority
    hierarchy (see docs/architecture/feature-flags.md). A Home override can
    never make a feature available when this is False; it can only opt a
    Home *out* of a feature the platform has made available. Hidden modules
    are not consulted here — callers that need the hidden-fails-closed rule
    should go through is_feature_enabled, which checks it first."""
    global_value = await db.scalar(
        select(FeatureFlag.enabled).where(FeatureFlag.key == feature_key)
    )
    return bool(global_value)


async def is_feature_enabled(
    db: AsyncSession,
    feature_key: FeatureKey | str,
    home_id: uuid.UUID | None = None,
) -> bool:
    """Evaluate platform availability first, then the Home override, failing
    closed for unknown/hidden keys. PCC platform availability is
    authoritative: when the global FeatureFlag is disabled (or missing), the
    feature is disabled everywhere and no Home override can re-enable it. A
    Home override only ever narrows access further (disable) or opts back
    in to what the platform already allows (enable) — it is never absolute.
    See docs/architecture/feature-flags.md."""
    try:
        key = feature_key if isinstance(feature_key, FeatureKey) else FeatureKey(feature_key)
    except ValueError:
        return False

    definition = module_definition(key.value)
    if definition.release_state == ReleaseState.hidden:
        return False

    if not await platform_feature_enabled(db, key):
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

    return True


async def feature_matrix(db: AsyncSession, home_id: uuid.UUID) -> dict[FeatureKey, bool]:
    flags = {row.key: bool(row.enabled) for row in (await db.scalars(select(FeatureFlag))).all()}
    overrides = {
        row.feature_key: bool(row.enabled)
        for row in (
            await db.scalars(select(FeatureOverride).where(FeatureOverride.group_id == home_id))
        ).all()
    }
    return {
        # Platform-authoritative: a disabled/missing global flag means
        # disabled regardless of any Home override — see is_feature_enabled.
        key: (overrides.get(key, True) if flags.get(key, False) else False)
        for key in FeatureKey
        if module_definition(key.value).release_state != ReleaseState.hidden
    }


async def enabled_dependents(db: AsyncSession, home_id: uuid.UUID, module_id: str) -> list[str]:
    result: list[str] = []
    for definition in feature_modules():
        if module_id in definition.dependencies and await is_feature_enabled(
            db, definition.id, home_id
        ):
            result.append(definition.id)
    return result


async def require_feature(
    db: AsyncSession,
    feature_key: FeatureKey,
    home_id: uuid.UUID,
) -> None:
    if not await is_feature_enabled(db, feature_key, home_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
