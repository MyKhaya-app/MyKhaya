"""Central "was this authenticated request genuine MyKhaya usage" tracking for
User.last_activity_at — see auth_context in dependencies.py, the one place
almost every authenticated request (web cookie, native bearer, managed Child,
PWA, and any future Android client) already passes through.

Deliberately separate from:
- User.last_login_at, set only at genuine session establishment (password
  login, passkey login, Child PIN login, mobile login — see routers.auth).
  This module never touches it.
- Session.last_seen_at, set unconditionally on every session lookup (see
  security._session_for_token) but — like any other ORM attribute write —
  only actually persisted if the request's own handler happens to call
  db.commit() for unrelated reasons; a pure read-only GET can silently lose
  it. That existing behaviour is out of scope here; last_activity_at gets
  its own explicit, always-committed write path instead of inheriting that
  gap.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import Request
from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import User

log = structlog.get_logger("activity")

# How often last_activity_at is allowed to advance. A qualifying request
# inside this window is a no-op; the product requirement is "approximately
# 5 minutes" resolution, not per-request precision.
ACTIVITY_THROTTLE = timedelta(minutes=5)

# Exact request.url.path values that must NEVER count as evidence of
# meaningful interactive use, even though they are cookie/bearer
# authenticated as a real User. Centralised here — one policy, one place —
# rather than scattered path checks in unrelated routers.
#
# - /users/me: the app-bootstrap "am I still signed in" check
#   (apps/web/components/auth-provider.tsx) — fires on every app
#   foreground/page load regardless of whether the user does anything, so
#   it can never be allowed to look like activity on its own.
# - /auth/sessions/rotate, /auth/mobile/sessions/rotate: deliberate but
#   automatic credential-rotation calls (see native-client.ts's `rotate()`
#   docstring: "not triggered automatically by request()" — but also never
#   user-initiated; it's session plumbing, not product usage).
# - /auth/renew, /auth/mobile/sessions/renew: listed defensively even
#   though neither currently reaches auth_context at all (they authenticate
#   via the rotating device credential, not a live Session) — if that ever
#   changes, this list already covers them.
# - /notifications/push/public-key: a static VAPID key fetch, not usage.
_EXCLUDED_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/users/me",
        "/api/v1/auth/renew",
        "/api/v1/auth/sessions/rotate",
        "/api/v1/auth/mobile/sessions/rotate",
        "/api/v1/auth/mobile/sessions/renew",
        "/api/v1/notifications/push/public-key",
    }
)

# Path prefixes excluded for the same reason as above, where the real path
# carries a variable id (e.g. .../native-devices/{id}) an exact-match set
# can't express. Both are background device/push-token registration that
# can happen automatically (app launch, silent push refresh) with no
# interactive action behind it. /health is listed defensively — those routes
# are unauthenticated and never reach auth_context, but excluding them here
# too costs nothing and documents the intent.
_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "/api/v1/notifications/native-devices",
    "/api/v1/notifications/push-subscriptions",
    "/api/v1/health",
)


def is_excluded_activity_path(path: str) -> bool:
    """True if a request to `path`, even though authenticated, must never be
    treated as evidence of interactive MyKhaya use. Exported so tests (and
    any future router-level special case) can assert against the same
    single source of truth this module and auth_context both use."""
    if path in _EXCLUDED_PATHS:
        return True
    return path.startswith(_EXCLUDED_PREFIXES)


async def record_authenticated_activity(db: AsyncSession, user: User, request: Request) -> None:
    """Advance `user.last_activity_at` to "now", throttled to at most once
    per ACTIVITY_THROTTLE, for a qualifying authenticated request only.

    `user` must always be the resolved AuthContext subject (the session
    owner) — never a path/target id read off the endpoint — so a request
    that merely *reads* someone else's data (an avatar, a shared calendar)
    can never mark that other person active, and a managed Child's own
    activity is never misattributed to the parent/admin whose Home it lives
    in. A PCC admin operation never reaches this function at all: the
    Platform Control Centre authenticates through the separate
    PlatformContext dependency, which never calls auth_context.

    Never raises: a failure here must not turn an otherwise successful
    request into a 500. Any exception is logged and the session is rolled
    back so the endpoint that follows still gets a clean, usable
    AsyncSession — activity telemetry can never break the user's actual
    request.
    """
    if is_excluded_activity_path(request.url.path):
        return
    now = datetime.now(UTC)
    # Cheap in-memory check first: for the common "still inside the
    # throttle window" case this issues zero extra queries — this is what
    # keeps activity tracking from becoming a DB write on every
    # authenticated request.
    last = user.last_activity_at
    if last is not None and now - last < ACTIVITY_THROTTLE:
        return
    try:
        # A conditional UPDATE, not a blind ORM attribute write + commit:
        # two concurrent requests for the same user (web + native, or two
        # browser tabs) can both pass the in-memory check above at once —
        # this WHERE guard is what keeps that safe. Each write only takes
        # effect if the row is still actually stale by the time it runs, so
        # neither request can clobber a fresher timestamp the other just
        # committed.
        await db.execute(
            update(User)
            .where(
                User.id == user.id,
                or_(
                    User.last_activity_at.is_(None),
                    User.last_activity_at < now - ACTIVITY_THROTTLE,
                ),
            )
            .values(last_activity_at=now)
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - activity telemetry must never break the request
        log.warning("activity_update_failed", user_id=str(user.id))
        await db.rollback()
