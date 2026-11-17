"""Deployment-wide safeguards for explicit DVLA refresh requests."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

from mykhaya.config import Settings

log = logging.getLogger(__name__)

RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class DvlaRedisUnavailable(Exception):
    pass


class DvlaBudgetExceeded(Exception):
    pass


def _redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)


def _namespace(settings: Settings) -> str:
    # The deployment environment is part of every key, so a shared Redis
    # service cannot make DEV and PROD contend with or release one another's
    # locks and budgets.
    return f"mykhaya:{settings.environment}:driveway:dvla"


@asynccontextmanager
async def refresh_lock(settings: Settings, vehicle_id: uuid.UUID) -> AsyncIterator[bool]:
    redis = _redis(settings)
    key = f"{_namespace(settings)}:refresh:{vehicle_id}"
    token = uuid.uuid4().hex
    acquired = False
    try:
        try:
            acquired = await redis.set(key, token, nx=True, ex=settings.dvla_refresh_lock_seconds)
        except Exception as exc:
            raise DvlaRedisUnavailable from exc
        if not acquired:
            yield False
            return
        try:
            yield True
        finally:
            try:
                await redis.eval(RELEASE_LOCK_SCRIPT, 1, key, token)
            except Exception:
                log.debug("DVLA refresh lock cleanup was unavailable", exc_info=True)
    finally:
        await redis.aclose()


async def enforce_request_budget(settings: Settings) -> None:
    redis = _redis(settings)
    key = f"{_namespace(settings)}:budget:{int(time.time())}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 2)
        if count > settings.dvla_request_budget_per_second:
            raise DvlaBudgetExceeded
    except DvlaBudgetExceeded:
        raise
    except Exception as exc:
        raise DvlaRedisUnavailable from exc
    finally:
        await redis.aclose()


async def mark_failure(settings: Settings, vehicle_id: uuid.UUID) -> None:
    redis = _redis(settings)
    try:
        await redis.set(
            f"{_namespace(settings)}:failure:{vehicle_id}",
            "1",
            ex=settings.dvla_refresh_failure_backoff_seconds,
        )
    except Exception as exc:
        raise DvlaRedisUnavailable from exc
    finally:
        await redis.aclose()


async def failure_is_recent(settings: Settings, vehicle_id: uuid.UUID) -> bool:
    redis = _redis(settings)
    try:
        return bool(await redis.exists(f"{_namespace(settings)}:failure:{vehicle_id}"))
    except Exception as exc:
        raise DvlaRedisUnavailable from exc
    finally:
        await redis.aclose()
