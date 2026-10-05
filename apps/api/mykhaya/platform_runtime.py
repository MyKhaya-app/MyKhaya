"""Runtime consumption of Platform Control Centre operational settings.

Every PCC setting that gates access, security or availability is read here, per
request, from the `platform_settings` table — never cached in-process and never
copied into `Settings` — so a change saved in PCC applies on the very next
request on every API worker with no redeploy or restart. The environment-only
`Settings` values remain *deployment bootstrap/hard limits* (see the precedence
notes on `evaluate_signup_policy`); PCC can only ever make things stricter than
a hard environment limit, never looser.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import Membership, PlatformSetting, SignupMode

DEFAULT_INVITATION_EXPIRY_DAYS = 7

MAINTENANCE_CODE = "maintenance_mode"
MAINTENANCE_MESSAGE = "MyKhaya is undergoing scheduled maintenance. Please try again shortly."
MAINTENANCE_RETRY_AFTER_SECONDS = "300"


async def get_platform_setting(db: AsyncSession, key: str) -> Any | None:
    """The stored PCC value for `key`, or None when no row exists yet. Callers
    own the default so each setting's "unset" meaning stays next to its use."""
    value = await db.scalar(select(PlatformSetting.value).where(PlatformSetting.key == key))
    if value is None:
        return None
    return value.get("value")


async def _flag(db: AsyncSession, key: str, default: bool) -> bool:
    value = await get_platform_setting(db, key)
    return value if isinstance(value, bool) else default


async def registration_enabled(db: AsyncSession) -> bool:
    return await _flag(db, "registration_enabled", True)


async def invite_only_enabled(db: AsyncSession) -> bool:
    return await _flag(db, "invite_only_mode", False)


# ---------------------------------------------------------------- maintenance


async def maintenance_active(db: AsyncSession) -> bool:
    return await _flag(db, "maintenance_mode", False)


def maintenance_error() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        {"code": MAINTENANCE_CODE, "message": MAINTENANCE_MESSAGE},
        headers={"Retry-After": MAINTENANCE_RETRY_AFTER_SECONDS},
    )


async def require_not_in_maintenance(db: AsyncSession) -> None:
    if await maintenance_active(db):
        raise maintenance_error()


# --------------------------------------------------------------------- signup


@dataclass(frozen=True)
class SignupPolicy:
    """The single, resolved answer to "may a new account be created, and how?".

    Precedence (most restrictive wins; no combination can be looser than any
    one of its inputs):

    1. maintenance_mode — the whole consumer API answers 503 (a router
       dependency, evaluated before any signup logic ever runs).
    2. Deployment hard limit `Settings.registration_mode == "closed"`.
    3. PCC `registration_enabled == False` — master switch for *every* new
       account path (password, Founding Beta, Apple).
    4. PCC `signup_mode == "closed"` — the Beta/normal selector's own "none".
    5. PCC `signup_mode` picks which path(s) remain: normal → ordinary
       signup only; beta_only → Founding Beta only; mixed → both.
    6. Invitation requirement = deployment `registration_mode ==
       "invitation_only"` OR PCC `invite_only_mode`. It narrows whichever path
       step 5 left open: ordinary signup then needs a valid Home invitation,
       Founding Beta then needs a valid Beta (waitlist) invitation.
    7. PCC `allowed_registration_domains`, when non-empty, applies to every
       path regardless of invitation.

    Existing users are never evaluated here: sign-in does not consult it.
    """

    mode: SignupMode
    open: bool
    normal_path: bool
    beta_path: bool
    invitation_required: bool
    allowed_domains: tuple[str, ...]

    def domain_allowed(self, email: str) -> bool:
        if not self.allowed_domains:
            return True
        return email.rpartition("@")[2].strip().casefold() in self.allowed_domains


async def _stored_signup_mode(db: AsyncSession, deployment_mode: str) -> SignupMode:
    # Imported lazily: founding_beta imports models/entitlements, which import
    # this module for the Home-limit caps.
    from mykhaya.founding_beta import signup_mode

    return await signup_mode(db, deployment_mode)


async def evaluate_signup_policy(db: AsyncSession, settings: Settings) -> SignupPolicy:
    mode = await _stored_signup_mode(db, settings.registration_mode)
    enabled = await registration_enabled(db)
    is_open = enabled and settings.registration_mode != "closed" and mode != SignupMode.closed
    invitation_required = (
        settings.registration_mode == "invitation_only" or await invite_only_enabled(db)
    )
    raw_domains = await get_platform_setting(db, "allowed_registration_domains")
    domains = tuple(
        sorted(
            {
                item.strip().casefold().lstrip("@")
                for item in (raw_domains if isinstance(raw_domains, list) else [])
                if isinstance(item, str) and item.strip()
            }
        )
    )
    return SignupPolicy(
        mode=mode,
        open=is_open,
        normal_path=is_open and mode in (SignupMode.normal, SignupMode.mixed),
        beta_path=is_open and mode in (SignupMode.beta_only, SignupMode.mixed),
        invitation_required=invitation_required,
        allowed_domains=domains,
    )


# ---------------------------------------------------------- email verification


async def email_verification_required(db: AsyncSession, settings: Settings) -> bool:
    """PCC `email_verification_required`, bounded by the deployment value.

    No stored value → the deployment default (`email_verification_enabled`).
    A stored value is honoured, except that in production verification can
    never be switched off from PCC (the update endpoint rejects it, and this
    resolver also refuses to relax it — defence in depth against a row written
    some other way)."""
    stored = await get_platform_setting(db, "email_verification_required")
    if not isinstance(stored, bool):
        return settings.email_verification_enabled
    if settings.environment == "production":
        return settings.email_verification_enabled or stored
    return stored


# ----------------------------------------------------------------- invitations


async def invitation_expiry(db: AsyncSession) -> timedelta:
    value = await get_platform_setting(db, "invitation_expiry_days")
    days = value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
    return timedelta(days=days or DEFAULT_INVITATION_EXPIRY_DAYS)


# ---------------------------------------------------------------------- limits


async def _positive_int(db: AsyncSession, key: str) -> int | None:
    value = await get_platform_setting(db, key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


async def members_per_home_cap(db: AsyncSession) -> int | None:
    return await _positive_int(db, "maximum_members_per_home")


async def require_home_capacity_for_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Refuses to put `user_id` in one more Home than `maximum_homes_per_user`
    allows. The cap counts current (not removed) memberships. Unset → no cap."""
    cap = await _positive_int(db, "maximum_homes_per_user")
    if cap is None:
        return
    current = (
        await db.scalar(
            select(func.count(Membership.id)).where(
                Membership.user_id == user_id, Membership.removed_at.is_(None)
            )
        )
        or 0
    )
    if current >= cap:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You have reached the maximum number of Homes allowed for one account.",
        )
