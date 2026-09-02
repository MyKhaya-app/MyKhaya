from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.models import PlatformSetting
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
    Centre change is visible on the very next request."""
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
    return {
        key: (
            rows[key].value.get("value")
            if key in rows
            else resolve_environment_fallback(key, settings)
        )
        for key in consumer_visible_keys
    }
