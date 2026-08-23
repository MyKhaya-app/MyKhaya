import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.calendar_provisioning import ensure_personal_calendar
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, require_adult_session
from mykhaya.entitlements import require_within_limit
from mykhaya.household_permissions import (
    Capability,
    default_profile,
    legacy_role,
    require_capability,
)
from mykhaya.member_colours import assign_member_colour
from mykhaya.models import Group, HouseholdRelationship, Invitation, Membership, User
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification_email
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.schemas import (
    InvitationAccept,
    InvitationCreate,
    InvitationListItem,
    InvitationResend,
    InvitationResponse,
    InvitationRevoke,
    InvitationTokenPreview,
    MessageResponse,
)
from mykhaya.security import decode_derived_token, derived_token, hash_secret, normalise_email

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def invite(
    body: InvitationCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InvitationResponse:
    require_adult_session(auth)
    await require_capability(body.group_id, Capability.members_invite, auth, db)
    await enforce_rate_limit(request, settings, "household-invitation", 20, 3600)
    if body.relationship == HouseholdRelationship.child:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Use the child setup flow instead of sending an adult invitation.",
        )
    if body.relationship == HouseholdRelationship.review_required:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a relationship.")

    # Extended Family / Friend as a *Home member* relationship is retired in
    # favour of external Calendar Sharing (mykhaya.routers.calendar_sharing)
    # — see docs on the Connections/external-sharing model. This blocks only
    # *new* invitations; existing accepted Memberships with either
    # relationship (and their shared_resources) keep working completely
    # unchanged — capabilities_for() and default_profile() are untouched for
    # them. No migration/backfill is needed or attempted here.
    if body.relationship in {HouseholdRelationship.extended_family, HouseholdRelationship.friend}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Extended Family and Friends are no longer added as Home members. "
            "Use calendar sharing to give someone outside the Home access instead.",
        )

    # Race-safe Free-Home member limit — same per-Home advisory-lock pattern
    # as routers.calendar's calendar-creation endpoint (see
    # mykhaya.entitlements.require_within_limit's docstring). A Free Home's
    # limit (1) is already met by its creator at Home-creation time, so
    # there is no realistic race window today, but the lock keeps this
    # endpoint correct if a future plan ever allows more than one but not
    # unlimited members.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"members:{body.group_id}"}
    )
    member_count = (
        await db.scalar(
            select(func.count(Membership.id)).where(
                Membership.group_id == body.group_id, Membership.removed_at.is_(None)
            )
        )
        or 0
    )
    await require_within_limit(db, body.group_id, "home.max_members", member_count)

    active = await db.scalar(
        select(Invitation).where(
            Invitation.group_id == body.group_id,
            Invitation.email == normalise_email(str(body.email)),
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > datetime.now(UTC),
        )
    )
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An active invitation already exists for that address.",
        )

    row = Invitation(
        group_id=body.group_id,
        email=normalise_email(str(body.email)),
        role=legacy_role(body.relationship),
        relationship=body.relationship,
        permission_profile=default_profile(body.relationship),
        shared_resources=body.shared_resources
        if body.relationship
        in {HouseholdRelationship.extended_family, HouseholdRelationship.friend}
        else [],
        token_hash=hash_secret(secrets.token_urlsafe(32), settings.secret_key.get_secret_value()),
        invited_by=auth.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(row)
    await db.flush()
    raw = derived_token(row.id, "invitation", settings.secret_key.get_secret_value())
    row.token_hash = hash_secret(raw, settings.secret_key.get_secret_value())
    home = await db.get(Group, row.group_id)
    assert home is not None
    subject, message, html = await render_notification_email(
        db,
        settings,
        "household_invitation",
        {
            "inviter_display_name": auth.user.display_name,
            "home_name": home.name,
            "link": f"{settings.public_web_url}/register?invitation={raw}",
            "expires_at": row.expires_at.isoformat(),
        },
    )
    await notify(
        db,
        settings=settings,
        recipient_email=row.email,
        notification_type="household_invitation",
        title=subject,
        body=message,
        idempotency_key=f"household_invitation:{row.id}:{row.expires_at.isoformat()}",
        html_body=html,
    )
    audit(
        db,
        request,
        "invitation.created",
        auth.user.id,
        body.group_id,
        "invitation",
        row.id,
        {"relationship": row.relationship.value},
    )
    await db.commit()
    return InvitationResponse(
        id=row.id,
        group_id=row.group_id,
        email=row.email,
        role=row.role,
        relationship=row.relationship,
        permission_profile=row.permission_profile,
        shared_resources=row.shared_resources,
        expires_at=row.expires_at,
    )


@router.get("/group/{group_id}", response_model=list[InvitationListItem])
async def list_invitations(
    group_id: uuid.UUID,
    include_revoked: bool = False,
    include_accepted: bool = False,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[InvitationListItem]:
    """The Family page's "Pending invitations" list — its only real caller — so the
    default here excludes both revoked *and* accepted invitations, not just revoked.
    An accepted invitation is no longer pending; it must never be returned here
    alongside the active membership it created.

    Belt-and-braces: an invitation is also excluded whenever an active (non-removed)
    membership already exists for the same group and email, even if accepted_at is
    for some reason unset — e.g. a membership created by a path other than this
    accept() endpoint. This is a read-only suppression, not a write, so it never
    mutates the invitation row and never discards audit history.
    """
    await require_capability(group_id, Capability.members_invite, auth, db)
    filters = [Invitation.group_id == group_id]
    if not include_revoked:
        filters.append(Invitation.revoked_at.is_(None))
    if not include_accepted:
        filters.append(Invitation.accepted_at.is_(None))
        filters.append(
            ~(
                select(Membership.id)
                .join(User, User.id == Membership.user_id)
                .where(
                    Membership.group_id == Invitation.group_id,
                    Membership.removed_at.is_(None),
                    User.email == Invitation.email,
                )
                .exists()
            )
        )
    rows = (
        await db.execute(
            select(Invitation, User)
            .join(User, User.id == Invitation.invited_by)
            .where(*filters)
            .order_by(Invitation.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        InvitationListItem(
            id=invitation.id,
            group_id=invitation.group_id,
            email=invitation.email,
            role=invitation.role,
            relationship=invitation.relationship,
            permission_profile=invitation.permission_profile,
            shared_resources=invitation.shared_resources,
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
            revoked_at=invitation.revoked_at,
            inviter_display_name=inviter.display_name,
            join_link=None,
        )
        for invitation, inviter in rows
    ]


@router.post("/resend", response_model=InvitationResponse)
async def resend_invitation(
    body: InvitationResend,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InvitationResponse:
    row = await db.scalar(
        select(Invitation).where(Invitation.id == body.invitation_id).with_for_update()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That invitation could not be found.")
    await require_capability(row.group_id, Capability.members_invite, auth, db)
    if row.accepted_at is not None or row.revoked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invitation is no longer active.")
    row.expires_at = datetime.now(UTC) + timedelta(days=7)
    raw = derived_token(row.id, "invitation", settings.secret_key.get_secret_value())
    home = await db.get(Group, row.group_id)
    assert home is not None
    subject, message, html = await render_notification_email(
        db,
        settings,
        "household_invitation",
        {
            "inviter_display_name": auth.user.display_name,
            "home_name": home.name,
            "link": f"{settings.public_web_url}/register?invitation={raw}",
            "expires_at": row.expires_at.isoformat(),
        },
    )
    await notify(
        db,
        settings=settings,
        recipient_email=row.email,
        notification_type="household_invitation",
        title=subject,
        body=message,
        idempotency_key=f"household_invitation:{row.id}:{row.expires_at.isoformat()}",
        html_body=html,
    )
    audit(db, request, "invitation.resent", auth.user.id, row.group_id, "invitation", row.id)
    await db.commit()
    return InvitationResponse(
        id=row.id,
        group_id=row.group_id,
        email=row.email,
        role=row.role,
        relationship=row.relationship,
        permission_profile=row.permission_profile,
        shared_resources=row.shared_resources,
        expires_at=row.expires_at,
    )


@router.post("/revoke", response_model=MessageResponse)
async def revoke_invitation(
    body: InvitationRevoke,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    row = await db.scalar(
        select(Invitation).where(Invitation.id == body.invitation_id).with_for_update()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That invitation could not be found.")
    await require_capability(row.group_id, Capability.members_invite, auth, db)
    if row.accepted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Accepted invitations cannot be revoked.")
    row.revoked_at = datetime.now(UTC)
    audit(db, request, "invitation.revoked", auth.user.id, row.group_id, "invitation", row.id)
    await db.commit()
    return MessageResponse(message="Invitation revoked.")


@router.get("/preview", response_model=InvitationTokenPreview)
async def preview_invitation(
    token: str = Query(min_length=30, max_length=500),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InvitationTokenPreview:
    identifier = decode_derived_token(token, "invitation", settings.secret_key.get_secret_value())
    row = (
        await db.scalar(select(Invitation).where(Invitation.id == identifier))
        if identifier
        else None
    )
    if (
        row is None
        or row.accepted_at is not None
        or row.revoked_at is not None
        or row.expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This invitation is invalid or has expired.",
        )
    group = await db.get(Group, row.group_id)
    inviter = await db.get(User, row.invited_by)
    assert group is not None and inviter is not None
    return InvitationTokenPreview(
        group_id=row.group_id,
        group_name=group.name,
        invited_by_display_name=inviter.display_name,
        email=row.email,
        role=row.role,
        relationship=row.relationship,
        expires_at=row.expires_at,
    )


@router.post("/accept", response_model=MessageResponse)
async def accept(
    body: InvitationAccept,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    identifier = decode_derived_token(
        body.token, "invitation", settings.secret_key.get_secret_value()
    )
    row = (
        await db.scalar(select(Invitation).where(Invitation.id == identifier).with_for_update())
        if identifier
        else None
    )
    expected = hash_secret(body.token, settings.secret_key.get_secret_value())
    if (
        row is None
        or row.accepted_at is not None
        or row.revoked_at is not None
        or row.expires_at <= datetime.now(UTC)
        or not hmac.compare_digest(row.token_hash, expected)
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invitation is invalid or has expired."
        )
    if row.email != auth.user.email:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Sign in with the email address that was invited."
        )
    existing = await db.scalar(
        select(Membership)
        .where(Membership.group_id == row.group_id, Membership.user_id == auth.user.id)
        .with_for_update()
    )
    # A Home's effective plan can change between an invitation being sent
    # (checked against the limit at the time, in invite() above) and it
    # being accepted — e.g. a Family Home invites several people then
    # downgrades before they respond. Re-check here, under the same
    # advisory lock invite() uses, so acceptance can never grow membership
    # past the Home's current plan limit; a no-op re-accept of an already
    # active membership is exempt since it doesn't increase the count.
    will_increase_membership = existing is None or existing.removed_at is not None
    if will_increase_membership:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"members:{row.group_id}"},
        )
        member_count = (
            await db.scalar(
                select(func.count(Membership.id)).where(
                    Membership.group_id == row.group_id, Membership.removed_at.is_(None)
                )
            )
            or 0
        )
        await require_within_limit(db, row.group_id, "home.max_members", member_count)
    if existing is None:
        db.add(
            Membership(
                group_id=row.group_id,
                user_id=auth.user.id,
                role=row.role,
                relationship=row.relationship,
                permission_profile=row.permission_profile,
                shared_resources=row.shared_resources,
                colour=await assign_member_colour(db, row.group_id),
            )
        )
    else:
        existing.removed_at = None
        existing.role = row.role
        existing.relationship = row.relationship
        existing.permission_profile = row.permission_profile
        existing.shared_resources = row.shared_resources
        if existing.colour is None:
            existing.colour = await assign_member_colour(db, row.group_id)
    # Give the new/returning adult member their Personal Calendar up front —
    # idempotent, so re-accepting an existing membership is safe too. Skips
    # managed children (see mykhaya.calendar_provisioning); invitations are
    # always for adult accounts in practice, but this stays correct even if
    # that ever changes.
    if row.relationship != HouseholdRelationship.child:
        await ensure_personal_calendar(db, row.group_id, auth.user.id)
    row.accepted_at = datetime.now(UTC)
    audit(db, request, "invitation.accepted", auth.user.id, row.group_id, "invitation", row.id)
    await db.commit()
    return MessageResponse(message="Welcome home. The Home is now in your list.")
