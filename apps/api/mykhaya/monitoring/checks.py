"""Health check implementations.

Every check is read-only and side-effect free. None of them sends an email,
a push, a payment, a webhook, an OAuth sign-in or a DVSA/DVLA vehicle lookup:
external providers are checked with DNS/TLS handshakes, public key endpoints
and cheap authenticated reads, and real customer traffic is observed
passively from records the application already writes. Checks never raise
for an expected failure; they return a CheckResult with a sanitised detail.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
import socket
import ssl
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog
from redis.asyncio import Redis
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mykhaya.billing.config import resolve_stripe_config
from mykhaya.config import Settings
from mykhaya.mailer import SmtpConfig, resolve_smtp_config
from mykhaya.models import (
    NativePushDevice,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    OperationalHeartbeat,
    OutboxEvent,
    PlatformSetting,
    StripeWebhookFailure,
    WorkerJobRecord,
)
from mykhaya.monitoring import http_metrics
from mykhaya.monitoring.results import CheckResult

log = structlog.get_logger()

STRIPE_API_HEALTH_URL = "https://api.stripe.com/v1/balance"
APNS_PRODUCTION_HOST = "api.push.apple.com"
FCM_HOST = "fcm.googleapis.com"
WEB_LATENCY_DEGRADED_MS = 5000
API_LATENCY_DEGRADED_MS = 3000
CERTIFICATE_EXPIRY_WARNING_DAYS = 14


@dataclass
class CheckContext:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    http: httpx.AsyncClient
    redis: Redis
    timeout: float
    now: datetime
    # When this component last produced a conclusive result; passive checks
    # use it to look only at events that happened since.
    previous_checked_at: datetime | None = None


CheckFn = Callable[[CheckContext], Awaitable[CheckResult]]


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain and len(chain) < 10:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def classify_network_error(exc: BaseException) -> str:
    """Map a connection-level exception to a sanitised category without
    ever echoing the exception message (it can contain hosts or addresses)."""
    for item in _exception_chain(exc):
        if isinstance(item, socket.gaierror):
            return "dns"
        if isinstance(item, ssl.SSLCertVerificationError | ssl.SSLError):
            return "tls"
        if isinstance(item, TimeoutError | httpx.TimeoutException):
            return "timeout"
    lowered = " ".join(type(item).__name__.lower() for item in _exception_chain(exc))
    if "timeout" in lowered:
        return "timeout"
    for item in _exception_chain(exc):
        message = str(item).lower()
        if "name or service not known" in message or "getaddrinfo" in message:
            return "dns"
        if "nodename nor servname" in message or "temporary failure in name resolution" in message:
            return "dns"
        if "certificate" in message or "ssl" in message:
            return "tls"
    return "connectivity"


_NETWORK_DETAIL = {
    "dns": "DNS resolution failed for {target}.",
    "tls": "TLS handshake or certificate validation failed for {target}.",
    "timeout": "{target} did not respond within the timeout.",
    "connectivity": "Could not connect to {target}.",
}


def network_failure(exc: BaseException, target: str) -> CheckResult:
    category = classify_network_error(exc)
    return CheckResult.failure(category, _NETWORK_DETAIL[category].format(target=target))


def classify_http_status(status_code: int, target: str) -> CheckResult | None:
    """None means the status code itself is acceptable; callers then
    validate the body."""
    if status_code in (401, 403):
        return CheckResult.failure(
            "auth_config", f"{target} rejected MyKhaya's credentials (HTTP {status_code})."
        )
    if status_code == 429:
        return CheckResult.failure(
            "rate_limited", f"{target} is rate limiting MyKhaya (HTTP 429).", severity="degraded"
        )
    if status_code >= 500:
        return CheckResult.failure(
            "provider_outage", f"{target} returned a server error (HTTP {status_code})."
        )
    if status_code >= 400:
        return CheckResult.failure(
            "unexpected_response", f"{target} returned HTTP {status_code}.", severity="degraded"
        )
    return None


# --- Public routes behind Cloudflare ---------------------------------------------------------

_CLOUDFLARE_ORIGIN_UNREACHABLE = {520, 521, 522, 523, 524, 530}
_CLOUDFLARE_ORIGIN_TLS = {525, 526}
_CHALLENGE_MARKERS = (
    "challenge-platform",
    "cf-chl",
    "just a moment",
    "attention required",
    "you have been blocked",
    "cf-error-details",
)
_EDGE_ERROR_CODE = re.compile(r"error code:?\s*(\d{3,4})", re.IGNORECASE)


def _is_cloudflare(response: httpx.Response) -> bool:
    return "cf-ray" in response.headers or (
        response.headers.get("server", "").lower() == "cloudflare"
    )


def classify_public_route(response: httpx.Response, target: str) -> CheckResult | None:
    """Classify a response from a public, Cloudflare-fronted hostname so PCC
    and alerts say *where* the path failed rather than "it's down":

    - DNS and edge TLS failures never produce a response; they are classified
      by ``network_failure`` before this runs.
    - A Cloudflare security challenge or WAF block (bot protection, 1020
      access denied, 1015 rate limit) aimed at the monitor proves nothing
      about customers, so it is a monitor error (the check goes stale and
      Unknown), never a public outage.
    - 520-524/530: Cloudflare answered but could not reach the origin.
    - 525/526: Cloudflare could not establish TLS to the origin.
    - Anything else falls through to the ordinary HTTP status rules.
    Returns None when the response is acceptable so far."""
    if not _is_cloudflare(response):
        return classify_http_status(response.status_code, target)
    ray = response.headers.get("cf-ray", "")
    ray_note = f" (Cloudflare Ray ID {ray[:40]})" if ray else ""
    body = response.text[:4000].lower() if response.content else ""
    match = _EDGE_ERROR_CODE.search(body)
    edge_code = f", Cloudflare error {match.group(1)}" if match else ""
    # Cloudflare's own 1xxx errors on a 403/429 are edge security decisions
    # (1020 access denied by a WAF rule, 1015 rate limited, 1010/1012 blocked)
    # about *this client*, not the service's availability.
    edge_security_block = bool(
        match and len(match.group(1)) == 4 and match.group(1).startswith("1")
    ) and response.status_code in (403, 429)
    challenged = (
        response.headers.get("cf-mitigated", "").lower() == "challenge"
        or edge_security_block
        or (
            response.status_code in (403, 429, 503)
            and any(marker in body for marker in _CHALLENGE_MARKERS)
        )
    )
    if challenged:
        return CheckResult.monitor_error(
            f"Cloudflare challenged or blocked the monitor for {target}{edge_code}{ray_note}; "
            "availability cannot be verified. Allow the monitor through WAF/bot rules.",
            category="waf_challenge",
        )
    if response.status_code in _CLOUDFLARE_ORIGIN_UNREACHABLE:
        return CheckResult.failure(
            "edge_origin_unreachable",
            f"Cloudflare could not reach the origin for {target} "
            f"(HTTP {response.status_code}{edge_code}){ray_note}.",
        )
    if response.status_code in _CLOUDFLARE_ORIGIN_TLS:
        return CheckResult.failure(
            "edge_origin_tls",
            f"Cloudflare could not establish TLS to the origin for {target} "
            f"(HTTP {response.status_code}){ray_note}.",
        )
    return classify_http_status(response.status_code, target)


async def _get(
    ctx: CheckContext, url: str, target: str, **kwargs: Any
) -> tuple[httpx.Response | None, int, CheckResult | None]:
    started = time.monotonic()
    try:
        response = await ctx.http.get(url, timeout=ctx.timeout, **kwargs)
    except httpx.HTTPError as exc:
        return None, _elapsed_ms(started), network_failure(exc, target)
    return response, _elapsed_ms(started), None


async def probe_tls(host: str, port: int, timeout_seconds: float) -> tuple[CheckResult, int | None]:
    """DNS + TCP + TLS handshake with full certificate validation. Returns
    the result and the days until the presented certificate expires."""
    started = time.monotonic()
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(loop.getaddrinfo(host, port), timeout_seconds)
    except (TimeoutError, OSError) as exc:
        if isinstance(exc, TimeoutError):
            return CheckResult.failure("timeout", f"DNS lookup for {host} timed out."), None
        return CheckResult.failure("dns", f"DNS resolution failed for {host}."), None
    context = ssl.create_default_context()
    writer = None
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host),
            timeout_seconds,
        )
        certificate = writer.get_extra_info("peercert") or {}
    except (TimeoutError, OSError, ssl.SSLError) as exc:
        return network_failure(exc, host), None
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except Exception as exc:  # noqa: BLE001 - closing a probe socket is best-effort
                log.debug("monitoring.tls_probe_close_failed", error=type(exc).__name__)
    latency = _elapsed_ms(started)
    days_left: int | None = None
    not_after = certificate.get("notAfter") if isinstance(certificate, dict) else None
    if isinstance(not_after, str):
        try:
            expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), UTC)
            days_left = (expires - datetime.now(UTC)).days
        except ValueError:
            days_left = None
    return (
        CheckResult.success(
            f"TLS handshake with {host} succeeded.", latency_ms=latency, confidence="limited"
        ),
        days_left,
    )


async def _probe_hosts(ctx: CheckContext, hosts: list[str], label: str) -> CheckResult:
    results = [await probe_tls(host, 443, ctx.timeout) for host in hosts if host]
    if not results:
        return CheckResult.not_applicable(f"{label} has no endpoint configured.")
    failures = [result for result, _ in results if result.outcome == "failure"]
    if failures:
        return failures[0]
    latency = max((result.latency_ms or 0) for result, _ in results)
    return CheckResult.success(
        f"{label}: DNS and TLS reachable ({len(results)} endpoint"
        f"{'s' if len(results) != 1 else ''}). Connectivity only; no API call is made.",
        latency_ms=latency,
        confidence="limited",
    )


async def _platform_toggle(ctx: CheckContext, key: str) -> bool:
    async with ctx.session_factory() as db:
        row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
    return bool(row and row.value.get("value") is True)


# --- MyKhaya Web Application ------------------------------------------------------------


def internal_note(what: str) -> str:
    return (
        f"{what} checked over the internal Docker network; this proves the service "
        "is running and answering, not that customers can reach it over the internet."
    )


async def check_web_http(ctx: CheckContext) -> CheckResult:
    """GET / on the web container exactly as Caddy forwards it: internal
    address, the public Host header the web app routes on, and
    X-Forwarded-Proto https. Redirects are never followed, so nothing can
    leave the internal network."""
    base = ctx.settings.monitoring_web_url.rstrip("/")
    public_host = urlsplit(ctx.settings.public_web_url).hostname or "localhost"
    target = "The web application"
    response, latency, error = await _get(
        ctx,
        f"{base}/",
        target,
        headers={"Host": public_host, "X-Forwarded-Proto": "https"},
        follow_redirects=False,
    )
    if error is not None:
        return error
    assert response is not None
    if 300 <= response.status_code < 400:
        return CheckResult.success(
            f"Answered with a redirect (HTTP {response.status_code}). "
            + internal_note("The web application"),
            latency_ms=latency,
        )
    status_failure = classify_http_status(response.status_code, target)
    if status_failure is not None:
        return status_failure
    if "text/html" not in response.headers.get("content-type", ""):
        return CheckResult.failure(
            "unexpected_response", "The web application did not return an HTML page."
        )
    if latency > WEB_LATENCY_DEGRADED_MS:
        return CheckResult.failure(
            "latency",
            f"The web application responded in {latency} ms.",
            severity="degraded",
            latency_ms=latency,
        )
    return CheckResult.success(
        "Home page served. " + internal_note("The web application"), latency_ms=latency
    )


# --- API ----------------------------------------------------------------------------------


async def check_database(ctx: CheckContext) -> CheckResult:
    started = time.monotonic()
    try:
        async with ctx.session_factory() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any failure here means the DB is unusable
        return CheckResult.failure(
            "connectivity", f"The database query failed ({type(exc).__name__})."
        )
    latency = _elapsed_ms(started)
    if latency > 2000:
        return CheckResult.failure(
            "latency",
            f"The database answered in {latency} ms.",
            severity="degraded",
            latency_ms=latency,
        )
    return CheckResult.success("The database answered a query.", latency_ms=latency)


async def check_redis(ctx: CheckContext) -> CheckResult:
    started = time.monotonic()
    try:
        await asyncio.wait_for(ctx.redis.ping(), ctx.timeout)
    except Exception as exc:  # noqa: BLE001
        return CheckResult.failure(
            "connectivity", f"Redis did not answer PING ({type(exc).__name__})."
        )
    return CheckResult.success("Redis answered PING.", latency_ms=_elapsed_ms(started))


def _api_base(ctx: CheckContext) -> str:
    """The API container's internal address (see Settings.monitoring_api_url)."""
    return ctx.settings.monitoring_api_url.rstrip("/")


async def check_api_ready(ctx: CheckContext) -> CheckResult:
    target = "The API readiness endpoint"
    response, latency, error = await _get(ctx, f"{_api_base(ctx)}/api/v1/health/ready", target)
    if error is not None:
        return error
    assert response is not None
    if response.status_code == 503:
        return CheckResult.failure(
            "provider_outage", "The API reports that a required dependency is unavailable."
        )
    status_failure = classify_http_status(response.status_code, target)
    if status_failure is not None:
        return status_failure
    try:
        ready = response.json().get("status") == "ready"
    except ValueError:
        ready = False
    if not ready:
        return CheckResult.failure("unexpected_response", "The API did not report ready.")
    if latency > API_LATENCY_DEGRADED_MS:
        return CheckResult.failure(
            "latency", f"The API answered in {latency} ms.", severity="degraded", latency_ms=latency
        )
    return CheckResult.success(
        "Readiness confirmed (database, Redis, schema). " + internal_note("The API"),
        latency_ms=latency,
    )


async def _error_rate(ctx: CheckContext, area: str, label: str, minimum: int) -> CheckResult:
    try:
        totals = await http_metrics.read_window(ctx.redis, area, minutes=5)
    except Exception as exc:  # noqa: BLE001
        return CheckResult.monitor_error(f"Request metrics unavailable ({type(exc).__name__}).")
    if totals.requests < minimum:
        if totals.errors >= 5:
            return CheckResult.failure(
                "error_rate",
                f"{label}: {totals.errors} server errors from {totals.requests} requests "
                "in the last 5 minutes.",
                severity="degraded",
            )
        if totals.errors == 0:
            return CheckResult.success(
                f"{label}: no server errors ({totals.requests} requests in 5 minutes; "
                "too little traffic for a confident error rate).",
                confidence="limited",
            )
        return CheckResult.inconclusive(
            f"{label}: too little traffic ({totals.requests} requests) to judge the error rate."
        )
    ratio = totals.error_ratio
    detail = (
        f"{label}: {totals.errors} of {totals.requests} requests failed with a server error "
        f"({ratio:.0%}) in the last 5 minutes."
    )
    if ratio >= 0.25:
        return CheckResult.failure("error_rate", detail)
    if ratio >= 0.05:
        return CheckResult.failure("error_rate", detail, severity="degraded")
    average = totals.average_latency_ms or 0
    if average > API_LATENCY_DEGRADED_MS:
        return CheckResult.failure(
            "latency",
            f"{label}: average response time {average} ms over the last 5 minutes.",
            severity="degraded",
            latency_ms=average,
        )
    return CheckResult.success(detail, latency_ms=totals.average_latency_ms)


async def check_api_error_rate(ctx: CheckContext) -> CheckResult:
    return await _error_rate(ctx, "api", "API", minimum=20)


# --- Authentication ---------------------------------------------------------------------------


async def check_auth_endpoint(ctx: CheckContext) -> CheckResult:
    """GET /auth/providers: a public, read-only status route that runs inside
    the authentication router. It never authenticates, creates an account or
    starts a sign-in."""
    target = "The authentication service"
    response, latency, error = await _get(ctx, f"{_api_base(ctx)}/api/v1/auth/providers", target)
    if error is not None:
        return error
    assert response is not None
    status_failure = classify_http_status(response.status_code, target)
    if status_failure is not None:
        return status_failure
    try:
        valid = isinstance(response.json().get("providers"), list)
    except ValueError:
        valid = False
    if not valid:
        return CheckResult.failure(
            "unexpected_response", "The authentication service returned an unexpected response."
        )
    return CheckResult.success(
        "Provider status returned. " + internal_note("The authentication service"),
        latency_ms=latency,
    )


async def check_auth_error_rate(ctx: CheckContext) -> CheckResult:
    return await _error_rate(ctx, "auth", "Authentication", minimum=10)


# --- Email Delivery ---------------------------------------------------------------------------


def _smtp_probe(config: SmtpConfig, timeout: float) -> None:
    """Connect, negotiate TLS, authenticate if configured, NOOP, QUIT. Never
    issues MAIL FROM/RCPT TO/DATA, so nothing is ever sent."""
    client: smtplib.SMTP
    if config.connection_security == "tls":
        client = smtplib.SMTP_SSL(
            config.host, config.port, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        client = smtplib.SMTP(config.host, config.port, timeout=timeout)
    with client:
        client.ehlo()
        if config.connection_security == "starttls":
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if config.username and config.password:
            client.login(config.username, config.password)
        code, _ = client.noop()
        if code >= 400:
            raise smtplib.SMTPResponseException(code, b"NOOP refused")


async def check_smtp(ctx: CheckContext) -> CheckResult:
    async with ctx.session_factory() as db:
        config = await resolve_smtp_config(ctx.settings, db)
    if not config.configured:
        return CheckResult.failure("not_configured", "No email transport is configured.")
    started = time.monotonic()
    try:
        await asyncio.wait_for(asyncio.to_thread(_smtp_probe, config, ctx.timeout), ctx.timeout + 2)
    except smtplib.SMTPAuthenticationError:
        return CheckResult.failure("auth_config", "The mail server rejected MyKhaya's credentials.")
    except smtplib.SMTPNotSupportedError:
        return CheckResult.failure("tls", "The mail server does not support STARTTLS.")
    except smtplib.SMTPResponseException as exc:
        if 400 <= exc.smtp_code < 500:
            return CheckResult.failure(
                "rate_limited" if exc.smtp_code == 421 else "provider_outage",
                f"The mail server answered with a temporary error ({exc.smtp_code}).",
                severity="degraded",
            )
        return CheckResult.failure(
            "provider_outage", f"The mail server answered with an error ({exc.smtp_code})."
        )
    except (TimeoutError, OSError, ssl.SSLError, smtplib.SMTPException) as exc:
        return network_failure(exc, "the mail server")
    return CheckResult.success(
        "Connected and authenticated to the mail server (no message sent).",
        latency_ms=_elapsed_ms(started),
        confidence="limited",
    )


async def check_email_delivery(ctx: CheckContext) -> CheckResult:
    window_start = ctx.now - timedelta(minutes=30)
    async with ctx.session_factory() as db:
        rows = (
            await db.execute(
                select(NotificationDelivery.status, func.count())
                .where(
                    NotificationDelivery.channel == NotificationChannel.email,
                    NotificationDelivery.attempted_at > window_start,
                    NotificationDelivery.status.in_(
                        [NotificationDeliveryStatus.sent, NotificationDeliveryStatus.failed]
                    ),
                )
                .group_by(NotificationDelivery.status)
            )
        ).all()
        stuck = int(
            await db.scalar(
                select(func.count())
                .select_from(NotificationDelivery)
                .where(
                    NotificationDelivery.channel == NotificationChannel.email,
                    NotificationDelivery.status == NotificationDeliveryStatus.queued,
                    NotificationDelivery.scheduled_at < ctx.now - timedelta(minutes=15),
                    NotificationDelivery.scheduled_at > ctx.now - timedelta(days=2),
                )
            )
            or 0
        )
    counts = {status: count for status, count in rows}
    sent = int(counts.get(NotificationDeliveryStatus.sent, 0))
    failed = int(counts.get(NotificationDeliveryStatus.failed, 0))
    attempts = sent + failed
    if failed >= 5 and attempts and failed / attempts >= 0.8:
        return CheckResult.failure(
            "delivery_failures",
            f"{failed} of {attempts} email delivery attempts failed in the last 30 minutes.",
        )
    if failed >= 3 and attempts and failed / attempts >= 0.2:
        return CheckResult.failure(
            "delivery_failures",
            f"{failed} of {attempts} email delivery attempts failed in the last 30 minutes.",
            severity="degraded",
        )
    if stuck:
        return CheckResult.failure(
            "backlog",
            f"{stuck} email{'s have' if stuck != 1 else ' has'} been queued for over 15 minutes.",
            severity="degraded",
        )
    if attempts == 0:
        return CheckResult.success(
            "No email delivery attempts in the last 30 minutes; nothing is stuck.",
            confidence="limited",
        )
    return CheckResult.success(f"{sent} of {attempts} emails delivered in the last 30 minutes.")


# --- Notifications ----------------------------------------------------------------------------


def _production_push_filter() -> Any:
    """Web Push, Android FCM and production APNs only. Sandbox (Xcode) and
    pre-migration "legacy" iOS registrations are excluded, exactly as the
    PCC Health push card excludes them from its top-level verdict."""
    return or_(
        NotificationDelivery.push_subscription_id.is_not(None),
        and_(
            NativePushDevice.disabled_at.is_(None),
            or_(
                NativePushDevice.platform == "android",
                NativePushDevice.apns_environment == "production",
            ),
        ),
    )


async def check_push_delivery(ctx: CheckContext) -> CheckResult:
    window_start = ctx.now - timedelta(minutes=60)
    async with ctx.session_factory() as db:
        rows = (
            await db.execute(
                select(NotificationDelivery.status, func.count())
                .select_from(NotificationDelivery)
                .outerjoin(
                    NativePushDevice,
                    NativePushDevice.id == NotificationDelivery.native_push_device_id,
                )
                .where(
                    NotificationDelivery.channel == NotificationChannel.push,
                    NotificationDelivery.attempted_at > window_start,
                    NotificationDelivery.status.in_(
                        [NotificationDeliveryStatus.sent, NotificationDeliveryStatus.failed]
                    ),
                    _production_push_filter(),
                )
                .group_by(NotificationDelivery.status)
            )
        ).all()
    counts = {status: count for status, count in rows}
    sent = int(counts.get(NotificationDeliveryStatus.sent, 0))
    failed = int(counts.get(NotificationDeliveryStatus.failed, 0))
    attempts = sent + failed
    detail = f"{failed} of {attempts} production push deliveries failed in the last hour."
    if failed >= 10 and attempts and failed / attempts >= 0.8:
        return CheckResult.failure("delivery_failures", detail)
    if failed >= 5 and attempts and failed / attempts >= 0.3:
        return CheckResult.failure("delivery_failures", detail, severity="degraded")
    if attempts == 0:
        return CheckResult.success(
            "No production push deliveries in the last hour.", confidence="limited"
        )
    return CheckResult.success(f"{sent} of {attempts} production push deliveries succeeded.")


async def _active_devices(ctx: CheckContext, *conditions: Any) -> int:
    async with ctx.session_factory() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(NativePushDevice)
                .where(NativePushDevice.disabled_at.is_(None), *conditions)
            )
            or 0
        )


async def check_apns_reachability(ctx: CheckContext) -> CheckResult:
    devices = await _active_devices(
        ctx,
        NativePushDevice.platform == "ios",
        NativePushDevice.apns_environment == "production",
    )
    if devices == 0:
        return CheckResult.not_applicable("No production iOS devices are registered.")
    return await _probe_hosts(ctx, [APNS_PRODUCTION_HOST], "Apple Push Notification service")


async def check_fcm_reachability(ctx: CheckContext) -> CheckResult:
    devices = await _active_devices(ctx, NativePushDevice.platform == "android")
    if devices == 0:
        return CheckResult.not_applicable("No Android devices are registered.")
    return await _probe_hosts(ctx, [FCM_HOST], "Firebase Cloud Messaging")


# --- Background Processing ----------------------------------------------------------------


async def check_worker_heartbeat(ctx: CheckContext) -> CheckResult:
    async with ctx.session_factory() as db:
        heartbeat = await db.get(OperationalHeartbeat, "worker")
    if heartbeat is None:
        return CheckResult.failure("heartbeat", "The worker has never recorded a heartbeat.")
    age = int((ctx.now - heartbeat.observed_at).total_seconds())
    if age > 300:
        return CheckResult.failure("heartbeat", f"The worker's last heartbeat was {age}s ago.")
    if age > 90:
        return CheckResult.failure(
            "heartbeat", f"The worker's last heartbeat was {age}s ago.", severity="degraded"
        )
    return CheckResult.success(f"The worker's heartbeat is current ({age}s ago).")


async def check_outbox_progress(ctx: CheckContext) -> CheckResult:
    """Work that is due (or leased to the worker) while no job has finished
    recently means background processing has stalled. Future-scheduled
    reminders are ignored: their available_at is in the future."""
    lease_horizon = ctx.now + timedelta(seconds=130)
    async with ctx.session_factory() as db:
        due = int(
            await db.scalar(
                select(func.count(OutboxEvent.id)).where(
                    OutboxEvent.processed_at.is_(None), OutboxEvent.available_at <= lease_horizon
                )
            )
            or 0
        )
        last_finished = await db.scalar(select(func.max(WorkerJobRecord.finished_at)))
    if due == 0:
        return CheckResult.success("No background work is waiting.")
    idle_seconds = (
        int((ctx.now - last_finished).total_seconds()) if last_finished is not None else None
    )
    if idle_seconds is None or idle_seconds > 900:
        return CheckResult.failure(
            "backlog",
            f"{due} background job{'s are' if due != 1 else ' is'} waiting and no job has "
            "finished in over 15 minutes.",
        )
    if idle_seconds > 300:
        return CheckResult.failure(
            "backlog",
            f"{due} background job{'s are' if due != 1 else ' is'} waiting and no job has "
            f"finished for {idle_seconds // 60} minutes.",
            severity="degraded",
        )
    return CheckResult.success(f"{due} job{'s' if due != 1 else ''} waiting; work is progressing.")


async def check_failed_jobs(ctx: CheckContext) -> CheckResult:
    async with ctx.session_factory() as db:
        failed = int(
            await db.scalar(
                select(func.count(WorkerJobRecord.id))
                .join(OutboxEvent, WorkerJobRecord.outbox_event_id == OutboxEvent.id)
                .where(WorkerJobRecord.status == "failed", OutboxEvent.processed_at.is_(None))
            )
            or 0
        )
    if failed >= 25:
        return CheckResult.failure("delivery_failures", f"{failed} jobs are failing and retrying.")
    if failed >= 5:
        return CheckResult.failure(
            "delivery_failures", f"{failed} jobs are failing and retrying.", severity="degraded"
        )
    return CheckResult.success(f"{failed} job{'s' if failed != 1 else ''} currently failing.")


# --- Billing & Subscriptions / Stripe -------------------------------------------------------


async def check_stripe_api(ctx: CheckContext) -> CheckResult:
    """One authenticated read of the account balance: free, read-only and
    well within Stripe's rate limits at a five-minute interval. Verifies
    reachability *and* that this environment's key is accepted."""
    async with ctx.session_factory() as db:
        config = await resolve_stripe_config(ctx.settings, db)
    if not config.configured or not config.secret_key:
        if config.source == "unconfigured":
            return CheckResult.not_applicable("Stripe is not configured in this environment.")
        return CheckResult.failure("auth_config", "Stripe is enabled but not fully configured.")
    target = "Stripe"
    response, latency, error = await _get(
        ctx,
        STRIPE_API_HEALTH_URL,
        target,
        headers={"Authorization": f"Bearer {config.secret_key}"},
    )
    if error is not None:
        return error
    assert response is not None
    if response.status_code == 403:
        # A restricted key without balance access still proves Stripe is
        # reachable and accepted the key; it just verifies less.
        return CheckResult.success(
            "Stripe accepted the key (restricted: balance not readable).",
            latency_ms=latency,
            confidence="limited",
        )
    status_failure = classify_http_status(response.status_code, target)
    if status_failure is not None:
        return status_failure
    return CheckResult.success(
        f"Stripe API answered an authenticated read ({config.mode} mode).", latency_ms=latency
    )


async def check_stripe_webhooks(ctx: CheckContext) -> CheckResult:
    async with ctx.session_factory() as db:
        config = await resolve_stripe_config(ctx.settings, db)
        if not config.configured or not config.webhook_secret:
            if config.source == "unconfigured":
                return CheckResult.not_applicable("Stripe is not configured in this environment.")
            return CheckResult.failure("auth_config", "Stripe is enabled but not fully configured.")
        failures = int(
            await db.scalar(
                select(func.count(StripeWebhookFailure.id)).where(
                    StripeWebhookFailure.occurred_at >= ctx.now - timedelta(hours=1)
                )
            )
            or 0
        )
    if failures >= 10:
        return CheckResult.failure(
            "delivery_failures", f"{failures} Stripe webhook processing failures in the last hour."
        )
    if failures >= 3:
        return CheckResult.failure(
            "delivery_failures",
            f"{failures} Stripe webhook processing failures in the last hour.",
            severity="degraded",
        )
    return CheckResult.success(
        f"{failures} webhook processing failure{'s' if failures != 1 else ''} in the last hour. "
        "(Absence of failures does not prove Stripe is sending events.)",
        confidence="limited",
    )


# --- External providers ---------------------------------------------------------------------


async def _dvsa_active(ctx: CheckContext) -> bool:
    settings = ctx.settings
    return bool(
        settings.dvsa_enabled
        and settings.dvsa_configured
        and await _platform_toggle(ctx, "driveway_dvsa_enabled")
    )


async def check_dvsa_connectivity(ctx: CheckContext) -> CheckResult:
    if not await _dvsa_active(ctx):
        return CheckResult.not_applicable("DVSA MOT History is not enabled in this environment.")
    hosts = [
        urlsplit(ctx.settings.dvsa_api_base_url).hostname or "",
        urlsplit(ctx.settings.dvsa_token_url or "").hostname or "",
    ]
    return await _probe_hosts(ctx, hosts, "DVSA MOT History")


_DVSA_CATEGORIES = {
    "auth_failed": ("auth_config", "unavailable"),
    "rate_limited": ("rate_limited", "degraded"),
}


async def check_dvsa_observed(ctx: CheckContext) -> CheckResult:
    """Passive: reads the outcome real customer MOT lookups already record
    (mykhaya.driveway_mot.record_provider_health). Fails only when a *new*
    failure happened since the previous check with no success after it, so
    three consecutive failing cycles means failures are recurring, not that
    one lookup failed once. Never performs a lookup itself."""
    if not await _dvsa_active(ctx):
        return CheckResult.not_applicable("DVSA MOT History is not enabled in this environment.")
    async with ctx.session_factory() as db:
        row = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == "driveway_dvsa_enabled")
        )
    health = dict((row.value if row else {}).get("health") or {})

    def parse(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    last_success = parse(health.get("last_success_at"))
    last_failure = parse(health.get("last_failure_at"))
    since = ctx.previous_checked_at or (ctx.now - timedelta(minutes=5))
    if last_failure and last_failure > since and (not last_success or last_failure > last_success):
        category, severity = _DVSA_CATEGORIES.get(
            str(health.get("last_failure_category")), ("provider_outage", "unavailable")
        )
        return CheckResult.failure(
            category,
            "Recent customer MOT lookups failed "
            f"({health.get('last_failure_category') or 'unavailable'}).",
            severity="degraded" if severity == "degraded" else "unavailable",
        )
    if last_success and ctx.now - last_success < timedelta(hours=24):
        return CheckResult.success("Recent customer MOT lookups succeeded.")
    return CheckResult.inconclusive("No recent customer MOT lookups to observe.")


async def check_dvla_connectivity(ctx: CheckContext) -> CheckResult:
    if not ctx.settings.dvla_configured or not await _platform_toggle(ctx, "driveway_dvla_enabled"):
        return CheckResult.not_applicable(
            "DVLA Vehicle Enquiry is not enabled in this environment."
        )
    host = urlsplit(ctx.settings.dvla_active_endpoint or "").hostname or ""
    return await _probe_hosts(ctx, [host], "DVLA Vehicle Enquiry")


async def _check_jwks(ctx: CheckContext, url: str, label: str) -> CheckResult:
    """Fetches the provider's public signing keys: the same document
    MyKhaya needs to verify a sign-in. No credentials, no quota, no sign-in."""
    response, latency, error = await _get(ctx, url, label)
    if error is not None:
        return error
    assert response is not None
    status_failure = classify_http_status(response.status_code, label)
    if status_failure is not None:
        return status_failure
    try:
        keys = response.json().get("keys")
    except ValueError:
        keys = None
    if not isinstance(keys, list) or not keys:
        return CheckResult.failure(
            "unexpected_response", f"{label} returned no signing keys.", severity="degraded"
        )
    return CheckResult.success(
        f"{label} signing keys are available ({len(keys)} keys). "
        "Proves the identity service is reachable, not a full sign-in.",
        latency_ms=latency,
        confidence="limited",
    )


async def check_apple_sign_in(ctx: CheckContext) -> CheckResult:
    if not ctx.settings.apple_sign_in_enabled:
        return CheckResult.not_applicable("Apple Sign-In is not enabled in this environment.")
    return await _check_jwks(ctx, ctx.settings.apple_jwks_url, "Apple Sign-In")


async def check_google_sign_in(ctx: CheckContext) -> CheckResult:
    if not ctx.settings.google_sign_in_enabled:
        return CheckResult.not_applicable("Google Sign-In is not enabled in this environment.")
    return await _check_jwks(ctx, ctx.settings.google_jwks_url, "Google Sign-In")


async def check_watchdog_managed(ctx: CheckContext) -> CheckResult:
    """Placeholder for components whose observations come from the worker
    watchdog rather than the scheduler's runner."""
    return CheckResult.inconclusive("Observed by the worker watchdog.")
