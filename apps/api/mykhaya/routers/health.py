from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
async def ready(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
        redis = Redis.from_url(settings.redis_url, socket_timeout=2)
        await redis.ping()
        await redis.aclose()
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "A required service is unavailable."
        ) from exc
    return {"status": "ready"}


@router.get("/version")
async def version(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {"version": settings.version}


@router.get("/health/build", include_in_schema=False)
async def build(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "version": settings.version,
        "commit": settings.commit_sha,
        "build_time": settings.build_time,
        "environment": settings.environment,
        "channel": settings.build_channel,
    }
