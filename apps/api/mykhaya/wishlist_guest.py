"""Guest access to a shared Wishlist via link + PIN — deliberately parallel
to, but independent from, mykhaya.dependencies.auth_context. A guest is not
a User row and must never touch Session/AuthContext machinery; this mirrors
the *shape* of that machinery (hashed bearer token in an HttpOnly/Secure
cookie, checked against a short-lived, independently-revocable row) without
reusing it. See WishlistGuestSession's docstring in models.py.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.models import WishlistGuestSession, WishlistShare
from mykhaya.security import hash_secret

GUEST_COOKIE_NAME = "mk_wishlist_guest"
GUEST_CSRF_COOKIE_NAME = "mk_wishlist_guest_csrf"
# 30 days: long enough to cover a whole gift-buying season (e.g. a Christmas
# list shared in November) without repeated PIN re-entry, while still being
# fully and immediately revocable — see require_guest_csrf/verify_guest below
# and WishlistShare.revoked_at, which this dependency checks on every request
# rather than only at issuance.
GUEST_SESSION_DAYS = 30


@dataclass(frozen=True)
class WishlistGuestContext:
    share: WishlistShare
    session: WishlistGuestSession


async def wishlist_guest_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WishlistGuestContext:
    raw = request.cookies.get(GUEST_COOKIE_NAME)
    if not raw:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Please verify the wishlist link and PIN again."
        )
    digest = hash_secret(raw, settings.secret_key.get_secret_value())
    now = datetime.now(UTC)
    pair = (
        await db.execute(
            select(WishlistGuestSession, WishlistShare)
            .join(WishlistShare, WishlistShare.id == WishlistGuestSession.share_id)
            .where(
                WishlistGuestSession.token_hash == digest,
                WishlistGuestSession.expires_at > now,
                # Checked live on every request (not only at issuance) so a
                # revoke immediately cuts off any already-issued guest
                # session, even one the revoke endpoint's own cleanup missed.
                WishlistShare.revoked_at.is_(None),
            )
        )
    ).one_or_none()
    if pair is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Please verify the wishlist link and PIN again."
        )
    session, share = pair
    return WishlistGuestContext(share=share, session=session)


def require_guest_csrf(request: Request, settings: Settings) -> None:
    """Full double-submit CSRF for the guest cookie pair, mirroring
    security.require_csrf's shape. Guests are lower-privileged than a real
    Session but still perform state changes (reserve/release/mark-bought),
    so this gets the same protection rather than a reduced one."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request origin is not allowed")
    cookie = request.cookies.get(GUEST_CSRF_COOKIE_NAME, "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not hmac.compare_digest(cookie, header):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Your secure session check failed. Refresh and try again."
        )


def set_guest_cookies(response: Response, token: str, csrf: str, settings: Settings) -> None:
    now = datetime.now(UTC)
    expires = now + timedelta(days=GUEST_SESSION_DAYS)
    max_age = GUEST_SESSION_DAYS * 24 * 60 * 60
    response.set_cookie(
        GUEST_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
        max_age=max_age,
        expires=expires,
    )
    response.set_cookie(
        GUEST_CSRF_COOKIE_NAME,
        csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
        max_age=max_age,
        expires=expires,
    )


def clear_guest_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(GUEST_COOKIE_NAME, path="/", domain=settings.cookie_domain)
    response.delete_cookie(GUEST_CSRF_COOKIE_NAME, path="/", domain=settings.cookie_domain)
