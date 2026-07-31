import hashlib

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from mykhaya.config import Settings


async def enforce_rate_limit(
    request: Request, settings: Settings, bucket: str, limit: int, window: int = 60
) -> None:
    """Fixed-window limiter. Client identity uses the socket peer unless a trusted proxy set it."""
    peer = request.client.host if request.client else "unknown"
    identity = hashlib.sha256(peer.encode()).hexdigest()[:24]
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    key = f"rate:{bucket}:{identity}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
    finally:
        await redis.aclose()
    if count > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Please wait a moment and try again.",
            headers={"Retry-After": str(window)},
        )
