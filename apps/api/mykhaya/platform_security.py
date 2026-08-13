import hashlib
import hmac
import ipaddress
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.models import (
    AdminWebAuthnCredential,
    PlatformAdministrator,
    PlatformRole,
    PlatformSession,
    PlatformSessionStatus,
    PlatformSetting,
)
from mykhaya.security import hash_secret, resolve_client_ip

MFA_POLICY_SETTING_KEY = "admin_mfa_required"

ADMIN_SESSION_COOKIE = "mk_admin_session"
ADMIN_CSRF_COOKIE = "mk_admin_csrf"


def _in_any(address: ipaddress.IPv4Address | ipaddress.IPv6Address, networks: list[str]) -> bool:
    return any(address in ipaddress.ip_network(network, strict=False) for network in networks)


def enforce_admin_network(request: Request, settings: Settings) -> str:
    client = resolve_client_ip(request, settings)
    address = ipaddress.ip_address(client)
    if not settings.admin_allowed_networks or not _in_any(address, settings.admin_allowed_networks):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return client


def enforce_admin_host(request: Request, settings: Settings) -> None:
    expected = settings.admin_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    received = request.url.hostname or ""
    if received.casefold() != expected.casefold():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def set_admin_cookies(response: Response, raw: str, csrf: str, settings: Settings) -> None:
    max_age = settings.admin_session_absolute_minutes * 60
    for name, value, httponly in (
        (ADMIN_SESSION_COOKIE, raw, True),
        (ADMIN_CSRF_COOKIE, csrf, False),
    ):
        response.set_cookie(
            name,
            value,
            httponly=httponly,
            secure=settings.cookie_secure,
            samesite="strict",
            path="/",
            max_age=max_age,
        )


def clear_admin_cookies(response: Response) -> None:
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    response.delete_cookie(ADMIN_CSRF_COOKIE, path="/")


def require_admin_csrf(request: Request, settings: Settings) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != settings.admin_url.rstrip("/"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request origin is not allowed")
    cookie = request.cookies.get(ADMIN_CSRF_COOKIE, "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not hmac.compare_digest(cookie, header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your secure session check failed.")


@dataclass(frozen=True)
class PlatformContext:
    administrator: PlatformAdministrator
    session: PlatformSession
    source_ip: str


async def resolve_admin_mfa_required(db: AsyncSession, settings: Settings) -> bool:
    """The environment variable is a floor, never a ceiling: if it's already
    True (the default, and hard-required in production — see
    Settings.secure_admin_production_defaults), no database setting can weaken
    it. The database-stored Platform Setting can only ever turn the requirement
    ON when the environment leaves it OFF, matching the SMTP/push
    "environment wins when set, database is the flexible fallback" precedent in
    mykhaya.mailer.resolve_smtp_config. See routers.platform's MFA-policy
    endpoint for the admin-facing toggle this backs."""
    if settings.admin_mfa_required:
        return True
    row = await db.scalar(
        select(PlatformSetting).where(PlatformSetting.key == MFA_POLICY_SETTING_KEY)
    )
    return bool(row is not None and row.value.get("required") is True)


async def administrator_has_mfa_enrolled(db: AsyncSession, administrator_id: object) -> bool:
    """The authoritative check — administrator.mfa_enrolled is a cached flag
    kept in sync by the enrollment/removal endpoints, but this is what actually
    decides access when it matters (e.g. re-evaluated at every login)."""
    if await db.scalar(
        select(PlatformAdministrator.totp_enabled).where(
            PlatformAdministrator.id == administrator_id
        )
    ):
        return True
    return (
        await db.scalar(
            select(AdminWebAuthnCredential.id).where(
                AdminWebAuthnCredential.administrator_id == administrator_id
            )
        )
    ) is not None


async def _resolve_admin_session(
    request: Request, db: AsyncSession, settings: Settings
) -> tuple[PlatformAdministrator, PlatformSession, str]:
    enforce_admin_host(request, settings)
    source_ip = enforce_admin_network(request, settings)
    require_admin_csrf(request, settings)
    raw = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Administrator sign-in required.")
    digest = hash_secret(raw, settings.secret_key.get_secret_value())
    now = datetime.now(UTC)
    pair = (
        await db.execute(
            select(PlatformAdministrator, PlatformSession)
            .join(
                PlatformSession,
                PlatformSession.administrator_id == PlatformAdministrator.id,
            )
            .where(
                PlatformSession.token_hash == digest,
                PlatformSession.revoked_at.is_(None),
                PlatformSession.idle_expires_at > now,
                PlatformSession.absolute_expires_at > now,
                PlatformAdministrator.is_active.is_(True),
            )
        )
    ).one_or_none()
    if pair is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your administrator session has ended.")
    administrator, session = pair
    session.last_seen_at = now
    session.idle_expires_at = min(
        now + timedelta(minutes=settings.admin_session_idle_minutes),
        session.absolute_expires_at,
    )
    await db.commit()
    return administrator, session, source_ip


async def platform_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformContext:
    """The guard used by every ordinary Control Centre route. Requires a fully
    authenticated session — password *and* any required/enrolled second factor
    already verified. A session still mid-MFA-flow (pending_mfa or
    mfa_setup_required) is rejected here even though the cookie is valid; see
    platform_mfa_flow_context for the narrow set of MFA endpoints such a session
    *can* reach."""
    administrator, session, source_ip = await _resolve_admin_session(request, db, settings)
    if session.status != PlatformSessionStatus.full:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Additional authentication is required before this session can be used.",
        )
    # The authoritative check, not the cached administrator.mfa_enrolled flag —
    # this is the actual access decision, so it must reflect real credential
    # records even if the cache were ever wrong or stale. Re-checked on every
    # request (not just at login) so e.g. another admin resetting this one's
    # MFA takes effect immediately, not just on next sign-in.
    if await resolve_admin_mfa_required(db, settings) and not await administrator_has_mfa_enrolled(
        db, administrator.id
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Mandatory MFA enrolment is required before Control Centre access.",
        )
    return PlatformContext(administrator, session, source_ip)


async def platform_mfa_flow_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformContext:
    """The guard used only by the handful of MFA enrollment/verification
    endpoints, which must be reachable *before* a session reaches 'full' —
    otherwise an administrator could never complete the second factor that
    would let them reach it. Every other check (host, network, CSRF, valid
    non-expired non-revoked session, active administrator) is identical to
    platform_context; only the status==full requirement is dropped."""
    administrator, session, source_ip = await _resolve_admin_session(request, db, settings)
    return PlatformContext(administrator, session, source_ip)


def require_roles(
    *roles: PlatformRole,
) -> Callable[..., Awaitable[PlatformContext]]:
    async def dependency(context: PlatformContext = Depends(platform_context)) -> PlatformContext:
        if context.administrator.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This role cannot perform that action.")
        return context

    return dependency


def require_recent_auth(context: PlatformContext, settings: Settings) -> None:
    if context.session.authenticated_at < datetime.now(UTC) - timedelta(
        minutes=settings.admin_recent_auth_minutes
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Recent administrator authentication required."
        )


def new_admin_session(
    administrator: PlatformAdministrator,
    request: Request,
    settings: Settings,
    source_ip: str,
    status_: PlatformSessionStatus = PlatformSessionStatus.full,
) -> tuple[PlatformSession, str, str]:
    raw = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    session = PlatformSession(
        administrator_id=administrator.id,
        token_hash=hash_secret(raw, settings.secret_key.get_secret_value()),
        idle_expires_at=now + timedelta(minutes=settings.admin_session_idle_minutes),
        absolute_expires_at=now + timedelta(minutes=settings.admin_session_absolute_minutes),
        authenticated_at=now,
        last_seen_at=now,
        user_agent=request.headers.get("user-agent", "Unknown device")[:300],
        source_ip=source_ip,
        status=status_,
    )
    return session, raw, csrf


def safe_session_reference(session_id: object) -> str:
    return hashlib.sha256(str(session_id).encode()).hexdigest()[:16]
