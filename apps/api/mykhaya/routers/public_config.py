from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.features import platform_feature_enabled
from mykhaya.models import FeatureKey, PlatformSetting
from mykhaya.platform_settings import SETTINGS_SCHEMA, resolve_environment_fallback

router = APIRouter(prefix="/config", tags=["public-config"])


@router.get("/public")
async def public_config(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    """The one consumer-safe window into platform_settings: a brand-new dict
    built exclusively from SETTINGS_SCHEMA keys marked consumer_visible=True —
    never the full schema filtered client-side, never a caller-supplied key
    list. Unauthenticated by design (mirrors /health/build), and every
    /api/v1/* response already gets Cache-Control: no-store from
    mykhaya.main's security_and_limits middleware, so a Platform Control
    Centre change is visible on the very next request.

    `support_enabled` (Phase 2D) is the one deliberate exception to
    "exclusively SETTINGS_SCHEMA keys": Support isn't a PlatformSetting, it's
    a FeatureFlag (mykhaya.features.platform_feature_enabled), and the
    Help & Support hub needs a truthful, public way to know whether it's on
    before showing Report a bug as usable — see routers.support's own
    require_support_feature, which reads the exact same flag. This is a UX
    signal only: it never becomes the access control, which stays entirely
    with require_support_feature on the real /support/* routes regardless of
    what this endpoint says. Deliberately just the boolean — no override
    internals, no admin/config metadata, no reason.
    """
    consumer_visible_keys = [
        key for key, definition in SETTINGS_SCHEMA.items() if definition.consumer_visible
    ]
    rows: dict[str, PlatformSetting] = {}
    if consumer_visible_keys:
        rows = {
            row.key: row
            for row in (
                await db.scalars(
                    select(PlatformSetting).where(PlatformSetting.key.in_(consumer_visible_keys))
                )
            ).all()
        }
    payload: dict[str, Any] = {
        key: (
            rows[key].value.get("value")
            if key in rows
            else resolve_environment_fallback(key, settings)
        )
        for key in consumer_visible_keys
    }
    payload["support_enabled"] = await platform_feature_enabled(db, FeatureKey.support)
    return payload
