import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import ActionToken, Session, TokenPurpose, User

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("a-valid-dummy-password-value")


def normalise_email(email: str) -> str:
    return email.strip().casefold()


def hash_secret(value: str, key: str) -> str:
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def derived_token(record_id: uuid.UUID, purpose: str, key: str) -> str:
    identifier = record_id.bytes
    signature = hmac.new(key.encode(), purpose.encode() + b":" + identifier, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(identifier + signature).rstrip(b"=").decode()


def decode_derived_token(token: str, purpose: str, key: str) -> uuid.UUID | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        if len(raw) != 48:
            return None
        record_id = uuid.UUID(bytes=raw[:16])
        expected = hmac.new(key.encode(), purpose.encode() + b":" + raw[:16], hashlib.sha256).digest()
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


def set_auth_cookies(response: Response, token: str, csrf: str, settings: Settings) -> None:
    common = dict(
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
        max_age=settings.session_minutes * 60,
    )
    response.set_cookie("mk_session", token, httponly=True, **common)
    response.set_cookie("mk_csrf", csrf, httponly=False, **common)


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie("mk_session", path="/", domain=settings.cookie_domain)
    response.delete_cookie("mk_csrf", path="/", domain=settings.cookie_domain)


def require_csrf(request: Request, settings: Settings) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request origin is not allowed")
    cookie = request.cookies.get("mk_csrf", "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not hmac.compare_digest(cookie, header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your secure session check failed. Refresh and try again.")


async def create_action_token(db: AsyncSession, user_id: uuid.UUID, purpose: TokenPurpose, settings: Settings, minutes: int) -> ActionToken:
    row = ActionToken(user_id=user_id, purpose=purpose, token_hash="pending", expires_at=datetime.now(UTC) + timedelta(minutes=minutes))
    db.add(row)
    await db.flush()
    raw = derived_token(row.id, purpose.value, settings.secret_key.get_secret_value())
    row.token_hash = hash_secret(raw, settings.secret_key.get_secret_value())
    return row


async def consume_action_token(db: AsyncSession, raw: str, purpose: TokenPurpose, settings: Settings) -> ActionToken:
    identifier = decode_derived_token(raw, purpose.value, settings.secret_key.get_secret_value())
    if identifier is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")
    row = await db.scalar(select(ActionToken).where(ActionToken.id == identifier, ActionToken.purpose == purpose).with_for_update())
    expected = hash_secret(raw, settings.secret_key.get_secret_value())
    if row is None or row.consumed_at is not None or row.expires_at <= datetime.now(UTC) or not hmac.compare_digest(row.token_hash, expected):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")
    row.consumed_at = datetime.now(UTC)
    return row


async def current_user(request: Request, db: AsyncSession, settings: Settings) -> tuple[User, Session]:
    raw = request.cookies.get("mk_session")
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to continue.")
    digest = hash_secret(raw, settings.secret_key.get_secret_value())
    result = await db.execute(select(User, Session).join(Session, Session.user_id == User.id).where(Session.token_hash == digest, Session.revoked_at.is_(None), Session.expires_at > datetime.now(UTC), User.is_active.is_(True)))
    pair = result.one_or_none()
    if pair is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Please sign in again.")
    return pair

