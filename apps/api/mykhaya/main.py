import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from mykhaya.config import get_settings
from mykhaya.routers import (
    auth,
    billing,
    birthdays,
    calendar,
    children,
    communications_admin,
    features,
    groups,
    health,
    household_routines,
    invitations,
    notifications,
    platform,
    users,
)
from mykhaya.routers import (
    status as status_router,
)

settings = get_settings()
log = structlog.get_logger()
app = FastAPI(
    title="MyKhaya API",
    version=settings.version,
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
)


@app.middleware("http")
async def security_and_limits(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:80]
    request.state.request_id = request_id
    started = time.monotonic()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin not in settings.cors_origins:
            return JSONResponse(
                {"detail": "Request origin is not allowed"}, status_code=status.HTTP_403_FORBIDDEN
            )
        # The avatar upload carries an image (up to avatar_max_upload_bytes), well
        # above the general JSON body limit — everything else keeps the tight default.
        body_limit = (
            settings.avatar_max_upload_bytes
            if request.method == "POST" and request.url.path == "/api/v1/users/me/avatar"
            else settings.request_body_limit
        )
        length = request.headers.get("content-length")
        if length and int(length) > body_limit:
            return JSONResponse(
                {"detail": "The request is too large."},
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Endpoints that intentionally set their own Cache-Control (e.g. the avatar image
    # route, served under a versioned filename) keep it; everything else defaults to
    # not being cached, since API responses generally carry signed-in, per-user data.
    if "cache-control" not in response.headers:
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/v1/") else "no-cache"
        )
    await log.ainfo(
        "request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return response


for router in (
    health.router,
    auth.router,
    users.router,
    groups.router,
    invitations.router,
    calendar.router,
    children.router,
    features.router,
    household_routines.router,
    birthdays.router,
    notifications.router,
    platform.router,
    communications_admin.router,
    billing.router,
    billing.group_router,
    status_router.router,
):
    app.include_router(router, prefix="/api/v1")
