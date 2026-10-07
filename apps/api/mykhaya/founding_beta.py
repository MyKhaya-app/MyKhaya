"""Server-authoritative Founding Beta rules and the atomic join operation."""

from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.calendar_provisioning import ensure_personal_calendar
from mykhaya.colour_palette import PALETTE_HEX, ColourToken
from mykhaya.entitlements import ensure_home_subscription, record_subscription_event
from mykhaya.member_colours import assign_member_colour
from mykhaya.models import (
    BetaEnrollment,
    BetaInvitation,
    BetaInvitationStatus,
    BetaProgramme,
    BetaProgrammeStatus,
    BetaWaitlistEntry,
    BetaWaitlistStatus,
    Group,
    HomeCalendar,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    PlatformSetting,
    Role,
    SignupMode,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
)
from mykhaya.platform_runtime import (
    invite_only_enabled,
    registration_enabled,
    require_home_capacity_for_user,
)
from mykhaya.security import generate_home_code, normalise_email

FOUNDING_BETA_SLUG = "founding-beta"
SIGNUP_MODE_SETTING = "signup_mode"
FOUNDING_BETA_SOURCE = "founding_beta_lifetime"

DEFAULT_LABELS = [
    ("Family", ColourToken.teal),
    ("School", ColourToken.purple),
    ("Work", ColourToken.emerald),
    ("Appointment", ColourToken.orange),
    ("Birthday", ColourToken.rose),
    ("Activity", ColourToken.blue),
    ("Other", ColourToken.slate),
]


def invitation_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def signup_mode(db: AsyncSession, deployment_mode: str) -> SignupMode:
    row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == SIGNUP_MODE_SETTING))
    if row is not None:
        value = row.value.get("value")
        try:
            return SignupMode(str(value))
        except ValueError:
            return SignupMode.closed
    # Bootstrap only: once the migration's row exists, deployment configuration
    # is no longer consulted. The legacy invitation_only gate remains an
    # independent invitation constraint, not a competing Signup Mode.
    return {"open": SignupMode.normal, "closed": SignupMode.closed}.get(
        deployment_mode, SignupMode.normal
    )


async def beta_invitation_valid(db: AsyncSession, token: str, email: str) -> bool:
    """Whether `token` is a live (reserved, unexpired) Beta invitation issued to
    `email` for the active programme. Read-only: the invitation is consumed
    later, inside join_beta, under the programme lock."""
    invitation = await db.scalar(
        select(BetaInvitation)
        .join(BetaProgramme, BetaProgramme.id == BetaInvitation.programme_id)
        .where(
            BetaInvitation.token_hash == invitation_token_hash(token),
            BetaProgramme.slug == FOUNDING_BETA_SLUG,
            BetaProgramme.status == BetaProgrammeStatus.active,
        )
    )
    return (
        invitation is not None
        and invitation.status == BetaInvitationStatus.reserved
        and invitation.expires_at > datetime.now(UTC)
        and normalise_email(invitation.email) == normalise_email(email)
    )


async def current_programme(db: AsyncSession, *, for_update: bool = False) -> BetaProgramme:
    query = select(BetaProgramme).where(
        BetaProgramme.slug == FOUNDING_BETA_SLUG,
        BetaProgramme.status == BetaProgrammeStatus.active,
    )
    if for_update:
        query = query.with_for_update()
    programme = await db.scalar(query)
    if programme is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The Founding Beta programme is unavailable."
        )
    return programme


async def programme_for_admin(db: AsyncSession, *, for_update: bool = False) -> BetaProgramme:
    query = select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
    if for_update:
        query = query.with_for_update()
    programme = await db.scalar(query)
    if programme is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "The Founding Beta programme could not be found."
        )
    return programme


async def capacity(db: AsyncSession, programme: BetaProgramme) -> dict[str, int]:
    now = datetime.now(UTC)
    joined = await db.scalar(
        select(func.count(BetaEnrollment.id)).where(
            BetaEnrollment.programme_id == programme.id,
            BetaEnrollment.capacity_exempt.is_(False),
        )
    )
    reserved = await db.scalar(
        select(func.count(BetaInvitation.id)).where(
            BetaInvitation.programme_id == programme.id,
            BetaInvitation.status == BetaInvitationStatus.reserved,
            BetaInvitation.expires_at > now,
        )
    )
    waiting = await db.scalar(
        select(func.count(BetaWaitlistEntry.id)).where(
            BetaWaitlistEntry.programme_id == programme.id,
            BetaWaitlistEntry.status == BetaWaitlistStatus.waiting,
        )
    )
    joinable = max(0, programme.max_homes - (joined or 0) - (reserved or 0))
    return {
        "max_homes": programme.max_homes,
        "joined": joined or 0,
        "reserved": reserved or 0,
        "waiting": waiting or 0,
        "joinable": joinable,
    }


async def expire_invitations(db: AsyncSession, programme: BetaProgramme | None = None) -> int:
    """Materialise elapsed reservations without ever counting them as active."""
    now = datetime.now(UTC)
    query = (
        select(BetaInvitation)
        .where(
            BetaInvitation.status == BetaInvitationStatus.reserved,
            BetaInvitation.expires_at <= now,
        )
        .with_for_update()
    )
    if programme is not None:
        query = query.where(BetaInvitation.programme_id == programme.id)
    invitations = list(await db.scalars(query))
    for invitation in invitations:
        invitation.status = BetaInvitationStatus.expired
        if invitation.waitlist_entry_id:
            entry = await db.get(
                BetaWaitlistEntry, invitation.waitlist_entry_id, with_for_update=True
            )
            if entry and entry.status == BetaWaitlistStatus.invited:
                entry.status = BetaWaitlistStatus.expired
    if invitations:
        await db.flush()
    return len(invitations)


async def lock_programme(db: AsyncSession, programme: BetaProgramme) -> None:
    # The hash input is stable and includes the programme UUID, so separate
    # programmes do not serialize one another. This lock is advisory only for
    # the transaction; row locks and uniqueness constraints remain the guards.
    await db.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(f"mykhaya:beta:{programme.id}")))
    )


async def create_beta_home(db: AsyncSession, user_id: Any, name: str) -> Group:
    from mykhaya.models import CalendarEventLabel

    group = Group(name=name, created_by=user_id, child_login_code=generate_home_code())
    db.add(group)
    await db.flush()
    db.add(
        Membership(
            group_id=group.id,
            user_id=user_id,
            role=Role.owner,
            relationship=HouseholdRelationship.home_admin,
            permission_profile=PermissionProfile.home_admin,
            colour=await assign_member_colour(db, group.id),
        )
    )
    db.add(HomeCalendar(group_id=group.id, name="Home Calendar"))
    await ensure_home_subscription(db, group.id)
    for index, (label, colour) in enumerate(DEFAULT_LABELS):
        db.add(
            CalendarEventLabel(
                group_id=group.id,
                name=label,
                color=PALETTE_HEX[colour],
                is_system=True,
                sort_order=(index + 1) * 10,
                is_active=index == 0,
            )
        )
    await ensure_personal_calendar(db, group.id, user_id)
    await db.flush()
    return group


async def join_beta(
    db: AsyncSession,
    *,
    user: Any,
    home_name: str | None,
    terms_version: str,
    invitation_token: str | None = None,
    invitation_token_hash_value: str | None = None,
    programme: BetaProgramme | None = None,
    failure_injector: Any | None = None,
) -> Group:
    if user.email_verified_at is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Verify your email before joining the Founding Beta."
        )
    programme = programme or await current_programme(db, for_update=True)
    await lock_programme(db, programme)
    await expire_invitations(db, programme)
    mode = await signup_mode(db, "open")
    if mode not in (SignupMode.beta_only, SignupMode.mixed) or not await registration_enabled(db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Founding Beta joining is not open.")
    if terms_version != programme.terms_version:
        raise HTTPException(status.HTTP_409_CONFLICT, "The Founding Beta terms have changed.")

    normalized = normalise_email(user.email)
    prior = await db.scalar(
        select(BetaEnrollment.id).where(
            BetaEnrollment.programme_id == programme.id,
            (BetaEnrollment.joined_user_id == user.id)
            | (BetaEnrollment.normalized_email == normalized),
        )
    )
    if prior is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This person has already claimed a Founding Beta Home."
        )

    invitation = None
    if invitation_token or invitation_token_hash_value:
        token_hash = invitation_token_hash_value or invitation_token_hash(invitation_token or "")
        invitation = await db.scalar(
            select(BetaInvitation)
            .where(
                BetaInvitation.token_hash == token_hash,
                BetaInvitation.programme_id == programme.id,
            )
            .with_for_update()
        )
        if (
            invitation is None
            or invitation.status != BetaInvitationStatus.reserved
            or invitation.expires_at <= datetime.now(UTC)
            or normalise_email(invitation.email) != normalized
        ):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This Beta invitation is invalid or expired."
            )

    if invitation is None and await invite_only_enabled(db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Founding Beta joining is invitation-only.")

    owned = list(
        await db.scalars(
            select(Group)
            .where(Group.created_by == user.id, Group.is_active.is_(True))
            .with_for_update()
        )
    )
    from mykhaya.models import HomeSubscription

    subscriptions = (
        {
            row.group_id: row
            for row in await db.scalars(
                select(HomeSubscription)
                .where(HomeSubscription.group_id.in_([g.id for g in owned]))
                .with_for_update()
            )
        }
        if owned
        else {}
    )
    paid = [row for row in subscriptions.values() if row.plan != SubscriptionPlan.free]
    if paid:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A paid Home cannot be converted through public Founding Beta joining.",
        )
    if len(owned) > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Founding Beta joining is limited to one eligible Free Home."
        )

    state = await capacity(db, programme)
    if state["waiting"] and invitation is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The waitlist has priority for the next available place."
        )
    if invitation is None and state["joinable"] <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "The Founding Beta is currently full.")

    if owned:
        home = owned[0]
    else:
        new_home_name = (home_name or "").strip()
        if not new_home_name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Please give your Home a name."
            )
        await require_home_capacity_for_user(db, user.id)
        home = await create_beta_home(db, user.id, new_home_name)
    if failure_injector:
        result = failure_injector("home_creation")
        if inspect.isawaitable(result):
            await result
    subscription = subscriptions.get(home.id) or await ensure_home_subscription(db, home.id)
    previous_plan = subscription.plan
    previous_provider = subscription.provider
    subscription.plan = SubscriptionPlan.ultimate
    subscription.provider = SubscriptionProvider.complimentary
    subscription.status = SubscriptionStatus.active
    subscription.complimentary_source = FOUNDING_BETA_SOURCE
    subscription.complimentary_reason = "Founding Beta lifetime"
    subscription.complimentary_expires_at = None
    if failure_injector:
        result = failure_injector("terms_persistence")
        if inspect.isawaitable(result):
            await result
    await record_subscription_event(
        db,
        home.id,
        event_type="founding_beta_granted",
        from_plan=previous_plan,
        to_plan=SubscriptionPlan.ultimate,
        from_provider=previous_provider,
        to_provider=SubscriptionProvider.complimentary,
        to_status=SubscriptionStatus.active,
        reason=FOUNDING_BETA_SOURCE,
    )
    enrollment = BetaEnrollment(
        programme_id=programme.id,
        home_id=home.id,
        joined_user_id=user.id,
        normalized_email=normalized,
        joined_by_user_id=user.id,
        terms_version=programme.terms_version,
        source_invitation_id=invitation.id if invitation else None,
        capacity_exempt=False,
    )
    db.add(enrollment)
    await db.flush()
    if failure_injector:
        result = failure_injector("enrollment_creation")
        if inspect.isawaitable(result):
            await result
        result = failure_injector("entitlement_grant")
        if inspect.isawaitable(result):
            await result
    if invitation is not None:
        invitation.status = BetaInvitationStatus.redeemed
        invitation.accepted_home_id = home.id
        if invitation.waitlist_entry_id:
            entry = await db.get(
                BetaWaitlistEntry, invitation.waitlist_entry_id, with_for_update=True
            )
            if entry:
                entry.status = BetaWaitlistStatus.joined
        if failure_injector:
            result = failure_injector("invitation_redemption")
            if inspect.isawaitable(result):
                await result
    await db.flush()
    return home
