import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TypedDict

import structlog
from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Message

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory, get_db
from mykhaya.models import PlatformSetting
from mykhaya.platform_runtime import require_not_in_maintenance
from mykhaya.routers import (
    activity,
    auth,
    billing,
    birthdays,
    budget,
    calendar,
    calendar_highlights,
    calendar_sharing,
    children,
    communications_admin,
    driveway,
    features,
    founding_beta,
    groups,
    health,
    home_join,
    household_routines,
    invitations,
    legal,
    lists,
    meal_plans,
    notifications,
    platform,
    platform_compliance,
    platform_legal,
    platform_support,
    public_config,
    reminders,
    support,
    todos,
    usage,
    usage_admin,
    users,
    wishlists,
)
from mykhaya.routers import (
    status as status_router,
)
from mykhaya.syslog_forwarding import (
    SyslogConfig,
    SyslogDispatcher,
    configure_structlog_forwarding,
    syslog_config_from_platform_value,
)

settings = get_settings()
log = structlog.get_logger()


async def _load_syslog_config() -> SyslogConfig:
    async with SessionFactory() as db:
        row = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == "central_syslog")
        )
    return syslog_config_from_platform_value(row.value if row else {}, settings.environment)


syslog_dispatcher = SyslogDispatcher(
    settings, service="mykhaya-api", config_loader=_load_syslog_config
)
configure_structlog_forwarding(syslog_dispatcher)


class ApiDocumentationUrls(TypedDict):
    docs_url: str | None
    redoc_url: str | None
    openapi_url: str | None


def api_documentation_urls(environment: str) -> ApiDocumentationUrls:
    """Keep interactive/API schema documentation out of production."""
    if environment == "production":
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": None, "openapi_url": "/openapi.json"}


documentation_urls = api_documentation_urls(settings.environment)
app = FastAPI(
    title="MyKhaya API",
    version=settings.version,
    docs_url=documentation_urls["docs_url"],
    redoc_url=documentation_urls["redoc_url"],
    openapi_url=documentation_urls["openapi_url"],
)


@app.exception_handler(Exception)
async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Forward an operationally useful, non-sensitive record for uncaught errors."""
    await log.aerror(
        "unhandled_exception",
        request_id=getattr(request.state, "request_id", None),
        method=request.method,
        path=request.url.path,
        exception_type=type(exc).__name__,
    )
    return JSONResponse(
        {"detail": "An unexpected error occurred."},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


@app.on_event("startup")
async def start_syslog_forwarder() -> None:
    await syslog_dispatcher.start()


@app.on_event("shutdown")
async def stop_syslog_forwarder() -> None:
    await syslog_dispatcher.stop()


app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # X-MyKhaya-Client/-Platform/-App-Version: the native-shell "session
    # metadata" headers NativeMyKhayaClient attaches to every bearer-transport
    # request (see packages/api-client/src/native-client.ts's clientHeaders
    # option and apps/web/components/native-auth.ts's clientHeaders()). The
    # Capacitor iOS shell is a *live-frontend* WKWebView — it loads the real
    # dev.mykhaya.app/mykhaya.app page and that page's own JS calls
    # api.dev.mykhaya.app/api.mykhaya.app directly (ADR 0010), which is a
    # genuine cross-origin fetch from a loaded web page and therefore fully
    # subject to CORS/preflight, same as any browser tab — not exempt from it
    # (see the now-corrected comment on Settings.native_api_url). Without
    # these three headers allow-listed, the browser's CORS preflight for
    # every native login/session request silently failed and the actual
    # POST never reached the server at all, surfacing in the app only as a
    # generic "We couldn't sign you in" — this was the confirmed root cause
    # of native iOS login failing with valid credentials.
    allow_headers=[
        "Accept",
        "Content-Type",
        "Authorization",
        "X-CSRF-Token",
        "X-Request-ID",
        "X-MyKhaya-Client",
        "X-MyKhaya-Platform",
        "X-MyKhaya-App-Version",
    ],
)


class RequestBodyTooLarge(Exception):
    pass


AVATAR_MULTIPART_OVERHEAD_BYTES = 64 * 1024
ATTACHMENT_MULTIPART_OVERHEAD_BYTES = 64 * 1024
VEHICLE_PHOTO_MULTIPART_OVERHEAD_BYTES = 64 * 1024
MEAL_IMAGE_MULTIPART_OVERHEAD_BYTES = 64 * 1024


def _is_support_attachment_upload(request: Request) -> bool:
    path = request.url.path
    return (
        request.method == "POST"
        and path.startswith("/api/v1/support/tickets/")
        and path.endswith("/attachments")
    )


def _is_vehicle_photo_upload(request: Request) -> bool:
    path = request.url.path
    return (
        request.method == "POST" and path.startswith("/api/v1/homes/") and path.endswith("/photo")
    )


def _is_meal_image_upload(request: Request) -> bool:
    path = request.url.path
    return (
        request.method == "POST"
        and path.startswith("/api/v1/homes/")
        and path.endswith("/meals/image")
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
        # Multipart framing is bounded overhead outside the uploaded file itself;
        # leave room for it so a file at the documented limit reaches the route.
        if request.method == "POST" and request.url.path == "/api/v1/users/me/avatar":
            body_limit = settings.avatar_max_upload_bytes + AVATAR_MULTIPART_OVERHEAD_BYTES
        elif _is_support_attachment_upload(request):
            body_limit = (
                settings.support_attachment_max_upload_bytes + ATTACHMENT_MULTIPART_OVERHEAD_BYTES
            )
        elif _is_vehicle_photo_upload(request):
            body_limit = (
                settings.vehicle_photo_max_upload_bytes + VEHICLE_PHOTO_MULTIPART_OVERHEAD_BYTES
            )
        elif _is_meal_image_upload(request):
            body_limit = settings.meal_image_max_upload_bytes + MEAL_IMAGE_MULTIPART_OVERHEAD_BYTES
        else:
            body_limit = settings.request_body_limit
        length = request.headers.get("content-length")
        if length is not None:
            try:
                parsed_length = int(length)
            except (TypeError, ValueError):
                return JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
            if parsed_length < 0:
                return JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
        else:
            parsed_length = None
        if parsed_length is not None and parsed_length > body_limit:
            return JSONResponse(
                {"detail": "The request is too large."},
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        original_receive = request.receive
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await original_receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"")
                received += len(chunk)
                if received > body_limit:
                    raise RequestBodyTooLarge
            return message

        request = Request(request.scope, limited_receive)
    try:
        response = await call_next(request)
    except RequestBodyTooLarge:
        return JSONResponse(
            {"detail": "The request is too large."},
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
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
    log_request = log.aerror if response.status_code >= 500 else log.ainfo
    await log_request(
        "request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return response


async def maintenance_gate(db: AsyncSession = Depends(get_db)) -> None:
    """Router dependency, not middleware: it runs inside CORSMiddleware, so the
    503 carries CORS headers and the browser/native client can read its
    structured `maintenance_mode` error rather than seeing an opaque network
    failure. The setting is read from the database on every request, so toggling
    it in PCC takes effect immediately and on every API worker."""
    await require_not_in_maintenance(db)


# Routers that stay reachable during maintenance so it can be observed and
# switched off: health/readiness probes, the public config + status surfaces
# the maintenance screen itself reads, and every Platform Control Centre
# (operator-authenticated) router. Everything else is consumer functionality.
MAINTENANCE_EXEMPT_ROUTERS = (
    health.router,
    public_config.router,
    status_router.router,
    platform.router,
    platform_support.router,
    platform_compliance.router,
    platform_legal.router,
    communications_admin.router,
    founding_beta.platform_router,
    usage_admin.router,
)


def include_with_maintenance_gate(api_router: APIRouter) -> None:
    exempt = any(api_router is item for item in MAINTENANCE_EXEMPT_ROUTERS)
    app.include_router(
        api_router,
        prefix="/api/v1",
        dependencies=[] if exempt else [Depends(maintenance_gate)],
    )


for router in (
    health.router,
    auth.router,
    activity.router,
    usage.router,
    users.router,
    groups.router,
    home_join.router,
    invitations.router,
    calendar.router,
    calendar_highlights.router,
    calendar_sharing.router,
    calendar_sharing.shared_router,
    children.router,
    features.router,
    household_routines.router,
    reminders.router,
    todos.router,
    meal_plans.router,
    lists.router,
    wishlists.router,
    wishlists.shared_router,
    wishlists.guest_router,
    birthdays.router,
    budget.router,
    driveway.router,
    notifications.router,
    platform.router,
    platform_support.router,
    platform_compliance.router,
    platform_legal.router,
    legal.router,
    public_config.router,
    communications_admin.router,
    support.router,
    billing.router,
    billing.group_router,
    status_router.router,
):
    include_with_maintenance_gate(router)
include_with_maintenance_gate(founding_beta.public_router)
include_with_maintenance_gate(founding_beta.router)
include_with_maintenance_gate(founding_beta.platform_router)
include_with_maintenance_gate(usage_admin.router)
