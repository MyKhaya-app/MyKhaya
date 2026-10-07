import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, require_adult_session
from mykhaya.founding_beta import (
    FOUNDING_BETA_SOURCE,
    capacity,
    current_programme,
    expire_invitations,
    invitation_token_hash,
    join_beta,
    programme_for_admin,
    signup_mode,
)
from mykhaya.founding_beta_schemas import (
    BetaCapacityExemptionUpdate,
    BetaEligibilityResponse,
    BetaInvitationItem,
    BetaInvitationResponse,
    BetaInvitationResponsePage,
    BetaInviteCreate,
    BetaInviteResponse,
    BetaJoinRequest,
    BetaJoinResponse,
    BetaOverviewResponse,
    BetaPendingResponse,
    BetaProgrammeResponse,
    BetaProgrammeUpdate,
    BetaWaitlistCreate,
    BetaWaitlistItem,
    BetaWaitlistResponse,
    BetaWaitlistResponsePage,
    SignupStateResponse,
)
from mykhaya.legal import current_published_version
from mykhaya.models import (
    BetaEnrollment,
    BetaInvitation,
    BetaInvitationStatus,
    BetaProgramme,
    BetaWaitlistEntry,
    BetaWaitlistStatus,
    Group,
    HomeSubscription,
    LegalAcceptance,
    LegalAcceptanceContext,
    LegalActionVerb,
    LegalDocument,
    LegalDocumentScope,
    LegalPlatform,
    LegalRecordType,
    PlatformRole,
    SubscriptionPlan,
)
from mykhaya.platform_audit import platform_audit
from mykhaya.platform_runtime import evaluate_signup_policy, registration_enabled
from mykhaya.platform_security import PlatformContext, require_recent_auth, require_roles
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.security import normalise_email, resolve_client_ip

public_router = APIRouter(prefix="/public", tags=["founding-beta-public"])
router = APIRouter(prefix="/beta", tags=["founding-beta"])
platform_router = APIRouter(prefix="/platform/beta", tags=["founding-beta-platform"])


@public_router.get("/signup-state", response_model=SignupStateResponse)
async def public_signup_state(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> SignupStateResponse:
    return await resolve_signup_state(db, settings)


async def resolve_signup_state(db: AsyncSession, settings: Settings) -> SignupStateResponse:
    policy = await evaluate_signup_policy(db, settings)
    mode = policy.mode
    programme = await current_programme(db)
    await expire_invitations(db, programme)
    await db.commit()
    state = await capacity(db, programme)
    beta_available = policy.beta_path and state["joinable"] > 0 and state["waiting"] == 0
    return SignupStateResponse(
        signup_mode=mode,
        registration_open=policy.open,
        invitation_required=policy.invitation_required,
        normal_signup_available=policy.normal_path,
        beta_joining_available=beta_available,
        waitlist_available=(
            programme.waitlist_enabled
            and (policy.beta_path or (policy.mode.value == "closed" and policy.open is False))
            and settings.registration_mode != "closed"
            and (await registration_enabled(db))
            and (not beta_available)
        ),
        joinable_count=state["joinable"] if programme.show_remaining_publicly else None,
        beta_terms_version=programme.terms_version if policy.beta_path else None,
    )


@public_router.post(
    "/beta/waitlist", response_model=BetaWaitlistResponse, status_code=status.HTTP_202_ACCEPTED
)
async def join_waitlist(
    body: BetaWaitlistCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BetaWaitlistResponse:
    await enforce_rate_limit(request, settings, "beta-waitlist", 10, 3600)
    programme = await current_programme(db)
    await expire_invitations(db, programme)
    policy = await evaluate_signup_policy(db, settings)
    state = await capacity(db, programme)
    if (
        not programme.waitlist_enabled
        or not (policy.beta_path or (policy.mode.value == "closed" and policy.open is False))
        or settings.registration_mode == "closed"
        or not await registration_enabled(db)
        or (state["joinable"] > 0 and state["waiting"] == 0)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The Founding Beta waitlist is not currently available."
        )
    email = normalise_email(str(body.email))
    existing = await db.scalar(
        select(BetaWaitlistEntry).where(
            BetaWaitlistEntry.programme_id == programme.id,
            BetaWaitlistEntry.normalized_email == email,
        )
    )
    if existing is not None:
        return BetaWaitlistResponse(accepted=True, status=existing.status.value)
    db.add(
        BetaWaitlistEntry(
            programme_id=programme.id,
            name=body.name,
            email=email,
            normalized_email=email,
            country=body.country.upper(),
            household_size=body.household_size,
            use_case=body.use_case,
            marketing_consent=body.marketing_consent,
        )
    )
    await db.commit()
    return BetaWaitlistResponse(accepted=True, status=BetaWaitlistStatus.waiting.value)


@public_router.get("/beta/invitations/{token}", response_model=BetaInvitationResponse)
async def inspect_invitation(
    token: str, db: AsyncSession = Depends(get_db)
) -> BetaInvitationResponse:
    invitation = await db.scalar(
        select(BetaInvitation).where(BetaInvitation.token_hash == invitation_token_hash(token))
    )
    if (
        invitation is None
        or invitation.status != BetaInvitationStatus.reserved
        or invitation.expires_at <= datetime.now(UTC)
    ):
        return BetaInvitationResponse(valid=False)
    programme = await db.get(BetaProgramme, invitation.programme_id)
    return BetaInvitationResponse(
        valid=True,
        programme=programme.name if programme else None,
        expires_at=invitation.expires_at.isoformat(),
    )


@router.post("/join", response_model=BetaJoinResponse)
async def join(
    body: BetaJoinRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BetaJoinResponse:
    require_adult_session(auth)
    home = await join_beta(
        db,
        user=auth.user,
        home_name=body.home_name,
        terms_version=body.terms_version,
        invitation_token=body.invitation_token,
    )
    beta_document = await db.scalar(
        select(LegalDocument).where(
            LegalDocument.key == "founding_beta_terms",
            LegalDocument.scope == LegalDocumentScope.founding_beta,
            LegalDocument.archived_at.is_(None),
        )
    )
    if beta_document is not None:
        version = await current_published_version(db, beta_document)
        if version is None or version.version != body.terms_version:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The Founding Beta terms have changed. Please review them again.",
            )
        db.add(
            LegalAcceptance(
                record_type=(
                    LegalRecordType.user_acceptance
                    if beta_document.action_verb == LegalActionVerb.accept
                    else LegalRecordType.user_acknowledgement
                ),
                document_version_id=version.id,
                user_id=auth.user.id,
                context=LegalAcceptanceContext.beta_enrolment,
                platform=LegalPlatform.web,
                ip_address=resolve_client_ip(request, get_settings()),
                user_agent=request.headers.get("user-agent", "")[:300] or None,
            )
        )
    audit(
        db,
        request,
        "beta.joined",
        auth.user.id,
        home.id,
        "beta_enrollment",
        home.id,
        {"source": FOUNDING_BETA_SOURCE},
    )
    await db.commit()
    return BetaJoinResponse(home_id=home.id, entitlement_source=FOUNDING_BETA_SOURCE)


@router.get("/pending", response_model=BetaPendingResponse)
async def pending(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BetaPendingResponse:
    require_adult_session(auth)
    from mykhaya.models import BetaPendingRegistration

    row = await db.scalar(
        select(BetaPendingRegistration)
        .where(
            BetaPendingRegistration.user_id == auth.user.id,
            BetaPendingRegistration.consumed_at.is_(None),
            BetaPendingRegistration.expires_at > datetime.now(UTC),
        )
        .order_by(BetaPendingRegistration.created_at.desc())
    )
    return BetaPendingResponse(
        pending=row is not None,
        home_name=row.home_name if row else None,
        terms_version=row.terms_version if row else None,
    )


@router.get("/eligibility", response_model=BetaEligibilityResponse)
async def eligibility(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BetaEligibilityResponse:
    require_adult_session(auth)
    owned = list(
        await db.scalars(
            select(Group).where(Group.created_by == auth.user.id, Group.is_active.is_(True))
        )
    )
    if len(owned) > 1:
        return BetaEligibilityResponse(
            eligible=False,
            reason="Founding Beta joining is limited to one eligible Free Home.",
        )
    if owned:
        subscription = await db.scalar(
            select(HomeSubscription).where(HomeSubscription.group_id == owned[0].id)
        )
        if subscription is not None and subscription.plan != SubscriptionPlan.free:
            return BetaEligibilityResponse(
                eligible=False,
                home_id=owned[0].id,
                home_name=owned[0].name,
                reason="A paid Home cannot be enrolled through the Founding Beta.",
            )
        return BetaEligibilityResponse(eligible=True, home_id=owned[0].id, home_name=owned[0].name)
    return BetaEligibilityResponse(eligible=True)


@platform_router.get("/overview", response_model=BetaOverviewResponse)
async def overview(
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator, PlatformRole.support)
    ),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BetaOverviewResponse:
    del context
    programme = await programme_for_admin(db)
    if await expire_invitations(db, programme):
        await db.commit()
    state = await capacity(db, programme)
    return BetaOverviewResponse(
        signup_mode=await signup_mode(db, settings.registration_mode), **state
    )


@platform_router.get("/programme", response_model=BetaProgrammeResponse)
async def programme_settings(
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator, PlatformRole.support)
    ),
    db: AsyncSession = Depends(get_db),
) -> BetaProgrammeResponse:
    del context
    programme = await programme_for_admin(db)
    return BetaProgrammeResponse.model_validate(programme, from_attributes=True)


@platform_router.patch("/programme", response_model=BetaProgrammeResponse)
async def update_programme_settings(
    body: BetaProgrammeUpdate,
    request: Request,
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator)
    ),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BetaProgrammeResponse:
    require_recent_auth(context, settings)
    programme = await programme_for_admin(db, for_update=True)
    previous = {
        key: getattr(programme, key)
        for key in (
            "max_homes",
            "waitlist_enabled",
            "show_remaining_publicly",
            "invitation_ttl_days",
            "terms_version",
        )
    }
    for key in previous:
        setattr(programme, key, getattr(body, key))
    programme.updated_by = context.administrator.id
    platform_audit(
        db,
        request,
        context,
        "beta.programme_settings_changed",
        "beta_programme",
        programme.id,
        reason=body.reason,
        previous=previous,
        new={key: getattr(programme, key) for key in previous},
    )
    await db.commit()
    return BetaProgrammeResponse.model_validate(programme, from_attributes=True)


@platform_router.get("/waitlist", response_model=BetaWaitlistResponsePage)
async def waitlist(
    status_filter: BetaWaitlistStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=200),
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator, PlatformRole.support)
    ),
    db: AsyncSession = Depends(get_db),
) -> BetaWaitlistResponsePage:
    del context
    programme = await programme_for_admin(db)
    query = select(BetaWaitlistEntry).where(BetaWaitlistEntry.programme_id == programme.id)
    if status_filter is not None:
        query = query.where(BetaWaitlistEntry.status == status_filter)
    if search:
        needle = f"%{search.strip()}%"
        query = query.where(
            or_(BetaWaitlistEntry.name.ilike(needle), BetaWaitlistEntry.email.ilike(needle))
        )
    rows = list(await db.scalars(query.order_by(BetaWaitlistEntry.created_at.asc())))
    return BetaWaitlistResponsePage(
        items=[
            BetaWaitlistItem(
                id=row.id,
                name=row.name,
                email=row.email,
                country=row.country,
                household_size=row.household_size,
                joined_at=row.created_at.isoformat(),
                status=row.status.value,
            )
            for row in rows
        ],
        total=len(rows),
        status=status_filter.value if status_filter else None,
        search=search,
    )


@platform_router.get("/invitations", response_model=BetaInvitationResponsePage)
async def invitations(
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator, PlatformRole.support)
    ),
    db: AsyncSession = Depends(get_db),
) -> BetaInvitationResponsePage:
    del context
    programme = await programme_for_admin(db, for_update=True)
    if await expire_invitations(db, programme):
        await db.commit()
    rows = list(
        await db.scalars(
            select(BetaInvitation)
            .where(BetaInvitation.programme_id == programme.id)
            .order_by(BetaInvitation.created_at.desc())
        )
    )
    entries = {
        row.id: row
        for row in await db.scalars(
            select(BetaWaitlistEntry).where(BetaWaitlistEntry.programme_id == programme.id)
        )
    }
    return BetaInvitationResponsePage(
        items=[
            BetaInvitationItem(
                id=row.id,
                applicant=entries[row.waitlist_entry_id].name
                if row.waitlist_entry_id in entries
                else row.email,
                email=row.email,
                status=row.status.value,
                invited_at=row.created_at.isoformat(),
                expires_at=row.expires_at.isoformat(),
                reservation_state="active"
                if row.status == BetaInvitationStatus.reserved
                and row.expires_at > datetime.now(UTC)
                else row.status.value,
                accepted_home_id=row.accepted_home_id,
            )
            for row in rows
        ],
        total=len(rows),
    )


@platform_router.post("/waitlist/{entry_id}/remove", status_code=status.HTTP_204_NO_CONTENT)
async def remove_waitlist_entry(
    entry_id: uuid.UUID,
    request: Request,
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator)
    ),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    require_recent_auth(context, settings)
    entry = await db.scalar(
        select(BetaWaitlistEntry).where(BetaWaitlistEntry.id == entry_id).with_for_update()
    )
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That waitlist entry could not be found.")
    entry.status = BetaWaitlistStatus.removed
    platform_audit(
        db, request, context, "beta.waitlist_entry_removed", "beta_waitlist_entry", entry.id
    )
    await db.commit()


@platform_router.post(
    "/invitations", response_model=BetaInviteResponse, status_code=status.HTTP_201_CREATED
)
async def invite(
    body: BetaInviteCreate,
    request: Request,
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator)
    ),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BetaInviteResponse:
    require_recent_auth(context, settings)
    programme = await current_programme(db, for_update=True)
    from mykhaya.founding_beta import lock_programme

    await lock_programme(db, programme)
    state = await capacity(db, programme)
    if state["joinable"] <= 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No unreserved Founding Beta capacity is available."
        )
    entry = await db.scalar(
        select(BetaWaitlistEntry)
        .where(
            BetaWaitlistEntry.id == body.waitlist_entry_id,
            BetaWaitlistEntry.programme_id == programme.id,
            BetaWaitlistEntry.status == BetaWaitlistStatus.waiting,
        )
        .with_for_update()
    )
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That waitlist entry is unavailable.")
    raw = secrets.token_urlsafe(32)
    invitation = BetaInvitation(
        programme_id=programme.id,
        waitlist_entry_id=entry.id,
        email=entry.normalized_email,
        token_hash=invitation_token_hash(raw),
        expires_at=datetime.now(UTC) + timedelta(days=programme.invitation_ttl_days),
        invited_by=context.administrator.id,
    )
    db.add(invitation)
    entry.status = BetaWaitlistStatus.invited
    platform_audit(
        db,
        request,
        context,
        "beta.invitation_created",
        "beta_invitation",
        invitation.id,
        new={"programme": programme.slug},
    )
    await db.commit()
    return BetaInviteResponse(
        invitation_id=invitation.id, token=raw, expires_at=invitation.expires_at.isoformat()
    )


@platform_router.post("/invitations/{invitation_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invitation(
    invitation_id: uuid.UUID,
    request: Request,
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator)
    ),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    require_recent_auth(context, settings)
    invitation = await db.scalar(
        select(BetaInvitation).where(BetaInvitation.id == invitation_id).with_for_update()
    )
    if invitation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That invitation could not be found.")
    invitation.status = BetaInvitationStatus.cancelled
    if invitation.waitlist_entry_id:
        entry = await db.get(BetaWaitlistEntry, invitation.waitlist_entry_id, with_for_update=True)
        if entry and entry.status == BetaWaitlistStatus.invited:
            entry.status = BetaWaitlistStatus.waiting
    platform_audit(
        db, request, context, "beta.invitation_cancelled", "beta_invitation", invitation.id
    )
    await db.commit()


@platform_router.post(
    "/invitations/{invitation_id}/restore", status_code=status.HTTP_204_NO_CONTENT
)
async def restore_expired_invitation(
    invitation_id: uuid.UUID,
    request: Request,
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator)
    ),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    require_recent_auth(context, settings)
    invitation = await db.scalar(
        select(BetaInvitation).where(BetaInvitation.id == invitation_id).with_for_update()
    )
    if invitation is None or invitation.status != BetaInvitationStatus.expired:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only an expired invitation can be restored.")
    if invitation.waitlist_entry_id:
        entry = await db.get(BetaWaitlistEntry, invitation.waitlist_entry_id, with_for_update=True)
        if entry is not None:
            entry.status = BetaWaitlistStatus.waiting
    platform_audit(
        db, request, context, "beta.invitation_restored", "beta_invitation", invitation.id
    )
    await db.commit()


@platform_router.post("/homes/{home_id}/capacity-exemption", status_code=status.HTTP_204_NO_CONTENT)
async def set_capacity_exemption(
    home_id: uuid.UUID,
    body: BetaCapacityExemptionUpdate,
    request: Request,
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator)
    ),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    require_recent_auth(context, settings)
    programme = await current_programme(db, for_update=True)
    enrollment = await db.scalar(
        select(BetaEnrollment)
        .where(
            BetaEnrollment.programme_id == programme.id,
            BetaEnrollment.home_id == home_id,
        )
        .with_for_update()
    )
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Home has no Founding Beta enrollment.")
    enrollment.capacity_exempt = body.exempt
    platform_audit(
        db,
        request,
        context,
        "beta.capacity_exemption_changed",
        "beta_enrollment",
        enrollment.id,
        new={"capacity_exempt": body.exempt, "reason": body.reason},
    )
    await db.commit()
