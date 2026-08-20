import structlog
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db

router = APIRouter(tags=["health"])
log = structlog.get_logger()


@router.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


def _expected_alembic_head() -> str | None:
    """The migration head baked into *this* running image's own alembic.ini
    + migrations/ (both shipped in the runtime image alongside the app —
    see apps/api/Dockerfile). Returns None (check skipped, never fails
    readiness) if alembic.ini isn't found at the process's working
    directory — e.g. under pytest, which never copies it into the test
    image; only the real deployed image layout has it."""
    try:
        script = ScriptDirectory.from_config(Config("alembic.ini"))
        return script.get_current_head()
    except Exception:  # noqa: BLE001 - a missing/unreadable alembic.ini must never break readiness
        return None


async def _actual_db_revision(db: AsyncSession) -> str | None:
    try:
        return (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    except Exception:  # noqa: BLE001 - table missing entirely reads the same as "can't tell"
        return None


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

    # A stale `migrate` image can silently no-op instead of upgrading (see
    # docs/architecture/meal-plans.md "Migration-head safety") — this is the
    # deliberate, proportionate guard: fail readiness loudly with a clear
    # message rather than quietly serving requests against a schema several
    # migrations behind. Skipped (never fails) when either side can't be
    # determined, so this only ever adds a new failure mode in the one
    # deployed layout it's designed for.
    expected_head = _expected_alembic_head()
    actual_revision = await _actual_db_revision(db)
    schema_mismatch = (
        expected_head is not None
        and actual_revision is not None
        and actual_revision != expected_head
    )
    if schema_mismatch:
        log.critical(
            "database_schema_behind_expected_head",
            expected_head=expected_head,
            actual_revision=actual_revision,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Database schema is at {actual_revision}, expected {expected_head}. "
            "Run migrations before serving traffic.",
        )
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
