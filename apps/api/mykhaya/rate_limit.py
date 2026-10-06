import hashlib

import structlog
from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from mykhaya.config import Settings
from mykhaya.security import resolve_client_ip

log = structlog.get_logger()


async def enforce_rate_limit(
    request: Request, settings: Settings, bucket: str, limit: int, window: int = 60
) -> None:
    """Fixed-window limiter. Client identity is resolve_client_ip's result — the
    same trusted-proxy-aware resolution used for the admin network allowlist
    (mykhaya.security.resolve_client_ip) — not the raw ASGI socket peer, so a
    forwarded address is only trusted when it actually came from a configured
    trusted proxy (MYKHAYA_TRUSTED_PROXY_CIDRS), the same boundary every other
    IP-sensitive check in the app already uses."""
    peer = resolve_client_ip(request, settings)
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
        # Operational diagnostics for "why was this client throttled?". Only
        # non-secret routing facts: the bucket, the resolved client IP the
        # bucket is keyed on, the socket peer and the forwarded chain that
        # produced it, and the counter state. If `client_ip` equals a proxy
        # address here, forwarded-client resolution is not working and every
        # user is sharing one bucket.
        await log.awarning(
            "rate_limited",
            bucket=bucket,
            client_ip=peer,
            socket_peer=request.client.host if request.client else None,
            forwarded_for=request.headers.get("x-forwarded-for"),
            count=count,
            limit=limit,
            window_seconds=window,
        )
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Please wait a moment and try again.",
            headers={"Retry-After": str(window)},
        )
