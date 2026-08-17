import base64
import hashlib
import hmac
import ipaddress
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import ActionToken, Session, TokenPurpose, TrustedDevice, User

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("a-valid-dummy-password-value")


def normalise_email(email: str) -> str:
    return email.strip().casefold()


# Managed Child sign-in (see mykhaya.routers.auth's /child/login and
# mykhaya.routers.children's login-config endpoints). The PIN uses the exact same
# pwdlib hasher as adult passwords (`password_hash` below) — a secure salted hash
# with constant-time verification, not a bespoke scheme — deliberately, so low
# numeric-PIN entropy is never compensated for with a weaker hash, only with the
# rate limiting applied at the call site.

_HOME_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L — typed on a phone
_USERNAME_ALLOWED = set("abcdefghijklmnopqrstuvwxyz0123456789_.-")


def generate_home_code() -> str:
    return "".join(secrets.choice(_HOME_CODE_ALPHABET) for _ in range(8))


def normalise_home_code(value: str) -> str:
    return value.strip().upper()


def normalise_child_username(value: str) -> str:
    """Casefold + NFKC-normalise + strip, matching normalise_email's approach —
    keeps confusable Unicode/case variants from being treated as distinct
    usernames. Callers must separately validate the allowed character set."""
    return unicodedata.normalize("NFKC", value).strip().casefold()


def is_valid_child_username(normalised: str) -> bool:
    return 2 <= len(normalised) <= 24 and set(normalised) <= _USERNAME_ALLOWED


def is_valid_child_pin(pin: str) -> bool:
    return 4 <= len(pin) <= 6 and pin.isdigit()


def hash_secret(value: str, key: str) -> str:
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def derived_token(record_id: uuid.UUID, purpose: str, key: str) -> str:
    identifier = record_id.bytes
    signature = hmac.new(
        key.encode(), purpose.encode() + b":" + identifier, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(identifier + signature).rstrip(b"=").decode()


def decode_derived_token(token: str, purpose: str, key: str) -> uuid.UUID | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        if len(raw) != 48:
            return None
        record_id = uuid.UUID(bytes=raw[:16])
        expected = hmac.new(
            key.encode(), purpose.encode() + b":" + raw[:16], hashlib.sha256
        ).digest()
        return record_id if hmac.compare_digest(raw[16:], expected) else None
    except (ValueError, TypeError):
        return None


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return password_hash.verify(password, stored_hash)
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def set_auth_cookies(
    response: Response,
    token: str,
    csrf: str,
    settings: Settings,
    device_token: str | None = None,
    device_csrf: str | None = None,
) -> None:
    now = datetime.now(UTC)
    session_expires = now + timedelta(minutes=settings.session_minutes)
    device_expires = now + timedelta(days=settings.trusted_device_days)
    response.set_cookie(
        "mk_session",
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
        max_age=settings.session_minutes * 60,
        expires=session_expires,
    )
    response.set_cookie(
        "mk_csrf",
        csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
        max_age=settings.session_minutes * 60,
        expires=session_expires,
    )
    if device_token is not None and device_csrf is not None:
        max_age = settings.trusted_device_days * 24 * 60 * 60
        response.set_cookie(
            "mk_device",
            device_token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            domain=settings.cookie_domain,
            path="/",
            max_age=max_age,
            expires=device_expires,
        )
        response.set_cookie(
            "mk_device_csrf",
            device_csrf,
            httponly=False,
            secure=settings.cookie_secure,
            samesite="lax",
            domain=settings.cookie_domain,
            path="/",
            max_age=max_age,
            expires=device_expires,
        )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie("mk_session", path="/", domain=settings.cookie_domain)
    response.delete_cookie("mk_csrf", path="/", domain=settings.cookie_domain)
    response.delete_cookie("mk_device", path="/", domain=settings.cookie_domain)
    response.delete_cookie("mk_device_csrf", path="/", domain=settings.cookie_domain)


def require_csrf(request: Request, settings: Settings) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request origin is not allowed")
    cookie = request.cookies.get("mk_csrf", "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not hmac.compare_digest(cookie, header):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Your secure session check failed. Refresh and try again."
        )


def require_device_csrf(request: Request, settings: Settings) -> None:
    """CSRF protection for renewal, which intentionally runs without a valid
    short-lived application session. SameSite is defense in depth; the explicit
    origin and double-submit check are the authorization boundary."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request origin is not allowed")
    cookie = request.cookies.get("mk_device_csrf", "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not hmac.compare_digest(cookie, header):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Your secure session check failed. Refresh and try again."
        )


async def create_action_token(
    db: AsyncSession, user_id: uuid.UUID, purpose: TokenPurpose, settings: Settings, minutes: int
) -> ActionToken:
    row = ActionToken(
        user_id=user_id,
        purpose=purpose,
        token_hash=hash_secret(secrets.token_urlsafe(32), settings.secret_key.get_secret_value()),
        expires_at=datetime.now(UTC) + timedelta(minutes=minutes),
    )
    db.add(row)
    await db.flush()
    raw = derived_token(row.id, purpose.value, settings.secret_key.get_secret_value())
    row.token_hash = hash_secret(raw, settings.secret_key.get_secret_value())
    return row


async def consume_action_token(
    db: AsyncSession, raw: str, purpose: TokenPurpose, settings: Settings
) -> ActionToken:
    identifier = decode_derived_token(raw, purpose.value, settings.secret_key.get_secret_value())
    if identifier is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")
    row = await db.scalar(
        select(ActionToken)
        .where(ActionToken.id == identifier, ActionToken.purpose == purpose)
        .with_for_update()
    )
    expected = hash_secret(raw, settings.secret_key.get_secret_value())
    if (
        row is None
        or row.consumed_at is not None
        or row.expires_at <= datetime.now(UTC)
        or not hmac.compare_digest(row.token_hash, expected)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")
    row.consumed_at = datetime.now(UTC)
    return row


EXPIRED_SESSION_MESSAGE = "Your session has ended. Please sign in again."


async def _session_for_token(
    db: AsyncSession, raw: str, settings: Settings, message: str
) -> tuple[User, Session]:
    digest = hash_secret(raw, settings.secret_key.get_secret_value())
    now = datetime.now(UTC)
    result = await db.execute(
        select(User, Session, TrustedDevice)
        .join(Session, Session.user_id == User.id)
        .outerjoin(TrustedDevice, Session.trusted_device_id == TrustedDevice.id)
        .where(
            Session.token_hash == digest,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
            or_(
                Session.trusted_device_id.is_(None),
                (
                    TrustedDevice.revoked_at.is_(None)
                    & (TrustedDevice.expires_at > now)
                ),
            ),
            User.is_active.is_(True),
        )
    )
    pair = result.one_or_none()
    if pair is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, message)
    pair[1].last_seen_at = now
    if pair[2] is not None and now - pair[2].last_used_at >= timedelta(
        hours=settings.trusted_device_activity_update_hours
    ):
        pair[2].last_used_at = now
        pair[2].expires_at = now + timedelta(days=settings.trusted_device_days)
    return pair[0], pair[1]


async def current_user(
    request: Request, db: AsyncSession, settings: Settings
) -> tuple[User, Session]:
    raw = request.cookies.get("mk_session")
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to continue.")
    return await _session_for_token(db, raw, settings, EXPIRED_SESSION_MESSAGE)


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    session: Session
    transport: Literal["cookie", "bearer"]


async def resolve_session(
    request: Request, db: AsyncSession, settings: Settings
) -> AuthenticatedSession:
    """The single place that inspects the Authorization header or the session cookie.

    An Authorization header, once present, is authoritative for the request: a
    malformed or invalid bearer token returns 401 and never falls back to
    checking the cookie, even if a valid one is also present.
    """
    header = request.headers.get("authorization")
    if header is not None:
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session could not be verified.")
        user, session = await _session_for_token(db, token, settings, EXPIRED_SESSION_MESSAGE)
        return AuthenticatedSession(user, session, "bearer")
    user, session = await current_user(request, db, settings)
    return AuthenticatedSession(user, session, "cookie")


def _forwarded_scheme_is_trusted(request: Request, settings: Settings) -> bool:
    peer_text = request.client.host if request.client else ""
    try:
        peer = ipaddress.ip_address(peer_text)
    except ValueError:
        return False
    return bool(settings.trusted_proxy_cidrs) and any(
        peer in ipaddress.ip_network(cidr, strict=False) for cidr in settings.trusted_proxy_cidrs
    )


def _in_any(address: ipaddress.IPv4Address | ipaddress.IPv6Address, networks: list[str]) -> bool:
    return any(address in ipaddress.ip_network(network, strict=False) for network in networks)


def resolve_client_ip(request: Request, settings: Settings) -> str:
    """Resolve a client only through a configured trusted proxy chain.

    X-Forwarded-For is ignored unless the socket peer is trusted. When it is trusted,
    the chain is walked from right to left until the first untrusted address. Shared by
    mykhaya.platform_security (admin network allowlisting) and mykhaya.rate_limit (so
    rate-limit identity uses the same trust boundary as everything else, instead of the
    raw, potentially proxy-rewritten socket peer)."""
    peer_text = request.client.host if request.client else "192.0.2.0"
    try:
        peer = ipaddress.ip_address(peer_text)
    except ValueError:
        return "192.0.2.0"
    if not settings.trusted_proxy_cidrs or not _in_any(peer, settings.trusted_proxy_cidrs):
        return str(peer)
    forwarded = request.headers.get("x-forwarded-for", "")
    chain: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for item in forwarded.split(","):
        try:
            chain.append(ipaddress.ip_address(item.strip()))
        except ValueError:
            continue
    current = peer
    for candidate in reversed(chain):
        if not _in_any(current, settings.trusted_proxy_cidrs):
            break
        current = candidate
    return str(current)


def resolve_forwarded_proto(request: Request, settings: Settings) -> str:
    """Mirrors ADR 0008: X-Forwarded-Proto is trusted only from a configured proxy CIDR."""
    if _forwarded_scheme_is_trusted(request, settings):
        forwarded = request.headers.get("x-forwarded-proto", "")
        first = forwarded.split(",")[0].strip().lower()
        if first:
            return first
    return request.url.scheme


def require_secure_transport(request: Request, settings: Settings) -> None:
    """Bearer token issuance must happen over HTTPS outside development/test.

    Gated on `environment == "production"`, matching the existing convention in
    Settings (see cookie_secure / admin production defaults) rather than
    "!= development", so the automated test suite (MYKHAYA_ENVIRONMENT=test)
    continues to run over plain HTTP via the ASGI test transport.
    """
    if settings.environment != "production":
        return
    if resolve_forwarded_proto(request, settings) != "https":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A secure connection is required.")
