"""Request error-rate and latency counters for the API and Authentication
monitors.

Recording is in-process and synchronous (a dict update), so a request never
waits on Redis. Counters are flushed to Redis at most every
``FLUSH_INTERVAL_SECONDS`` by a background task, which lets the scheduler's
monitor read a combined view across every API process. Any Redis problem is
swallowed: metrics are best-effort and must never fail or slow a request.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast

import structlog
from redis.asyncio import Redis

log = structlog.get_logger()

FLUSH_INTERVAL_SECONDS = 10
KEY_TTL_SECONDS = 1800
_KEY_PREFIX = "mykhaya:monitoring:http"

# (area, minute) -> [requests, server_errors, latency_ms_total]
_pending: defaultdict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0, 0])
_last_flush = 0.0
_flush_task: asyncio.Task[None] | None = None
_redis: Redis | None = None


def area_for_path(path: str) -> str | None:
    """Only consumer API traffic is counted. Health/status probes are
    excluded so monitoring's own requests never inflate the sample, and the
    Control Centre is excluded because its traffic says nothing about
    customer-facing availability."""
    if not path.startswith("/api/v1/"):
        return None
    rest = path[len("/api/v1/") :]
    if rest.startswith(("health", "status", "platform", "version")):
        return None
    if rest.startswith("auth/") or rest == "auth":
        return "auth"
    return "api"


def record(path: str, status_code: int, duration_ms: float, *, now: float | None = None) -> None:
    area = area_for_path(path)
    if area is None:
        return
    minute = int((now if now is not None else time.time()) // 60)
    bucket = _pending[(area, minute)]
    bucket[0] += 1
    if status_code >= 500:
        bucket[1] += 1
    bucket[2] += int(duration_ms)


def schedule_flush(redis_url: str) -> None:
    """Called from the request middleware after recording. Starts at most one
    background flush per interval; never awaited by the request."""
    global _last_flush, _flush_task
    now = time.monotonic()
    if now - _last_flush < FLUSH_INTERVAL_SECONDS:
        return
    if _flush_task is not None and not _flush_task.done():
        return
    _last_flush = now
    _flush_task = asyncio.get_running_loop().create_task(flush(redis_url))


def _client(redis_url: str) -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(redis_url, socket_timeout=2, decode_responses=True)
    return _redis


async def flush(redis_url: str) -> None:
    if not _pending:
        return
    snapshot = dict(_pending)
    _pending.clear()
    try:
        pipe = _client(redis_url).pipeline(transaction=False)
        for (area, minute), (requests, errors, latency) in snapshot.items():
            key = f"{_KEY_PREFIX}:{area}:{minute}"
            pipe.hincrby(key, "requests", requests)
            pipe.hincrby(key, "errors", errors)
            pipe.hincrby(key, "latency_ms", latency)
            pipe.expire(key, KEY_TTL_SECONDS)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001 - metrics are best-effort by design
        log.warning("monitoring.http_metrics_flush_failed", error=type(exc).__name__)


@dataclass(frozen=True)
class WindowTotals:
    requests: int
    errors: int
    latency_ms: int

    @property
    def error_ratio(self) -> float:
        return self.errors / self.requests if self.requests else 0.0

    @property
    def average_latency_ms(self) -> int | None:
        return round(self.latency_ms / self.requests) if self.requests else None


async def read_window(
    redis: Redis, area: str, *, minutes: int = 5, now: float | None = None
) -> WindowTotals:
    """Totals for the last ``minutes`` complete-or-current minutes."""
    current = int((now if now is not None else time.time()) // 60)
    pipe = redis.pipeline(transaction=False)
    for minute in range(current - minutes + 1, current + 1):
        pipe.hgetall(f"{_KEY_PREFIX}:{area}:{minute}")
    rows = await pipe.execute()
    requests = errors = latency = 0
    for raw in rows:
        # Tolerate clients created with or without decode_responses.
        row = {
            (key.decode() if isinstance(key, bytes) else key): value for key, value in raw.items()
        }
        requests += int(row.get("requests", 0) or 0)
        errors += int(row.get("errors", 0) or 0)
        latency += int(row.get("latency_ms", 0) or 0)
    return WindowTotals(requests=requests, errors=errors, latency_ms=latency)


async def write_bucket(
    redis: Redis,
    area: str,
    *,
    requests: int,
    errors: int,
    latency_ms: int,
    now: float | None = None,
) -> None:
    """Test/DEV helper: write a minute bucket directly."""
    minute = int((now if now is not None else time.time()) // 60)
    key = f"{_KEY_PREFIX}:{area}:{minute}"
    mapping = {"requests": requests, "errors": errors, "latency_ms": latency_ms}
    await cast("Awaitable[int]", redis.hset(key, mapping=mapping))
    await redis.expire(key, KEY_TTL_SECONDS)


async def clear(redis: Redis, area: str, *, minutes: int = 10, now: float | None = None) -> None:
    current = int((now if now is not None else time.time()) // 60)
    keys = [f"{_KEY_PREFIX}:{area}:{minute}" for minute in range(current - minutes, current + 2)]
    await redis.delete(*keys)
