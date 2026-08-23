"""External Calendar Sharing — the supported way to give someone outside a Home
(grandparents, friends, another family) access to one specific calendar, without ever
making them a Home member. See docs on the Connections/external-sharing model.

Route shape mirrors routers.wishlists' split for exactly the same reason: creating and
administering a share only makes sense in the context of the *source* Home
(`/homes/{home_id}/...` — capability + entitlement checks are Home-scoped), while
accepting/viewing/managing a share the caller *received* is top-level
(`/calendar-shares/...`), because the recipient may belong to a different Home, or none
at all, and must never need to know the sharer's home_id.

Token lifecycle (create -> [approve] -> preview -> accept/decline -> revoke/leave)
mirrors routers.invitations exactly, reusing the same `derived_token`/`hash_secret`
primitives with a distinct purpose string ("calendar_share") so a token can never be
replayed across the two flows.

Read/write access to the shared calendar's *events* is intentionally not exposed
through routers.calendar's `/homes/{home_id}/...` endpoints (an external recipient has
no Membership row for that Home, so `require_capability`/`membership_for` there would
always 404 them) — the `/calendar-shares/{share_id}/events...` endpoints below are the
external recipient's narrower, share-scoped equivalent: no member assignment, no
*creating/choosing* a category (a category is Home-owned structure the recipient isn't
authorised to manage — see SharedEventCreate/Update), no calendar settings, and never
any endpoint that lets them see another calendar or another Home's data. An existing
event's category *is* shown read-only when the calendar sharing it wasn't
category-scoped enough to already have filtered it out — see
CalendarShare.category_ids for the "share only these categories" filter, applied by
notifications.visibility.event_matches_share everywhere a shared event's visibility is
decided (list, view/notify, briefing).
"""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.calendar_occurrences import (
    MAX_RANGE_DAYS,
    expand_occurrences,
    recurrence_candidate_filter,
)
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for, require_adult_session
from mykhaya.entitlements import require_entitlement
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, capabilities_for, require_capability
from mykhaya.models import (
    CalendarEvent,
    CalendarEventLabel,
    CalendarShare,
    CalendarSharePermission,
    CalendarShareStatus,
    FeatureKey,
    Group,
    HomeCalendar,
    HouseholdRelationship,
    Membership,
    User,
)
from mykhaya.notifications.calendar_shares import notify_calendar_share_recipients
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification_email
from mykhaya.notifications.visibility import event_matches_share
from mykhaya.rate_limit import enforce_rate_limit

# Reused, not duplicated: these are the exact same event-response/activity-logging
# helpers routers.calendar's own event endpoints use — see that module's
# docstrings on _occurrence/_record_activity.
from mykhaya.routers.calendar import _label_map, _occurrence, _record_activity
from mykhaya.schemas import (
    CalendarShareAccept,
    CalendarShareCategoriesUpdate,
    CalendarShareCreate,
    CalendarShareDecline,
    CalendarShareListResponse,
    CalendarSharePermissionUpdate,
    CalendarSharePreferencesUpdate,
    CalendarSharePreview,
    CalendarShareResponse,
    EventListResponse,
    EventOccurrence,
    MessageResponse,
    SharedEventCreate,
    SharedEventUpdate,
)
from mykhaya.security import decode_derived_token, derived_token, hash_secret, normalise_email

_SHARE_TOKEN_PURPOSE = "calendar_share"
_SHARE_CREATE_RATE_LIMIT = 20
_SHARE_CREATE_RATE_WINDOW = 300

# Home-scoped: creating/administering a share belongs in the context of the source Home.
router = APIRouter(prefix="/homes/{home_id}/calendar-shares", tags=["calendar-sharing"])
# Top-level: accepting/viewing/managing a share the caller received, independent of any
# Home path — see module docstring.
shared_router = APIRouter(prefix="/calendar-shares", tags=["calendar-sharing"])


async def _require_calendar_sharing_feature(home_id: uuid.UUID, db: AsyncSession) -> None:
    await require_feature(db, FeatureKey.external_sharing, home_id)
    await require_feature(db, FeatureKey.calendar, home_id)


async def _get_calendar(
    db: AsyncSession, home_id: uuid.UUID, calendar_id: uuid.UUID
) -> HomeCalendar:
    calendar = await db.get(HomeCalendar, calendar_id)
    if calendar is None or calendar.group_id != home_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That calendar could not be found")
    return calendar


async def _validate_category_ids(
    db: AsyncSession,
    home_id: uuid.UUID,
    calendar: HomeCalendar,
    category_ids: list[uuid.UUID] | None,
) -> list[str] | None:
    """`None` (share the whole calendar) always passes straight through. A
    Personal Calendar has no categories at all, so any non-empty list there
    is rejected outright — matching create_event's own "Personal Calendar
    events are never categorised" rule. Otherwise every id must be a real,
    active category belonging to *this* Home — never another Home's, and
    never used to probe which ids exist elsewhere."""
    if category_ids is None:
        return None
    if calendar.owner_user_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A Personal Calendar has no categories to choose from.",
        )
    if not category_ids:
        return []
    rows = (
        await db.scalars(
            select(CalendarEventLabel.id).where(
                CalendarEventLabel.group_id == home_id,
                CalendarEventLabel.id.in_(category_ids),
            )
        )
    ).all()
    if set(rows) != set(category_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That category could not be found"
        )
    return [str(value) for value in category_ids]


def _has_authority_over_calendar(membership: Membership, calendar: HomeCalendar) -> bool:
    """A Personal Calendar's privacy boundary is absolute everywhere else in
    this app (routers.calendar never lets even a Home Admin/calendar_view_all
    holder see another member's Personal Calendar events — see
    _personal_calendar_visibility_filter) — sharing authority must respect
    that same boundary: only the calendar's own owner may ever request,
    send, approve, change the permission of, or revoke a share of it, Home
    Admin or not. For a shared/Home calendar (owner_user_id is None), the
    Home Admin holds that authority instead."""
    if calendar.owner_user_id is not None:
        return calendar.owner_user_id == membership.user_id
    return membership.relationship == HouseholdRelationship.home_admin


def _has_direct_send_authority(membership: Membership, calendar: HomeCalendar) -> bool:
    """Whoever has authority over the calendar may send an invitation
    immediately (their own approval is implicit). Anyone else with
    Capability.sharing_external may only *request* one — see
    CalendarShareStatus's docstring."""
    return _has_authority_over_calendar(membership, calendar)


async def _require_source_authority(
    db: AsyncSession, share: CalendarShare, auth: AuthContext
) -> Membership:
    """Who may approve/change-permission/revoke a share this Home sent — the
    same authority that could have sent it directly (see
    _has_authority_over_calendar). Deliberately narrower than "whoever
    requested it": a request only grants the ability to ask, not to
    administer the resulting share."""
    membership = await membership_for(share.source_group_id, auth, db)
    calendar = await db.get(HomeCalendar, share.calendar_id)
    if calendar is not None and _has_authority_over_calendar(membership, calendar):
        return membership
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a Home Admin or this calendar's owner can do that.",
    )


async def _share_response(db: AsyncSession, share: CalendarShare) -> CalendarShareResponse:
    calendar = await db.get(HomeCalendar, share.calendar_id)
    home = await db.get(Group, share.source_group_id)
    requester = await db.get(User, share.requested_by_user_id)
    now = datetime.now(UTC)
    return CalendarShareResponse(
        id=share.id,
        calendar_id=share.calendar_id,
        calendar_name=calendar.name if calendar is not None else "Deleted calendar",
        calendar_color=calendar.color if calendar is not None else None,
        source_group_id=share.source_group_id,
        source_group_name=home.name if home is not None else "",
        recipient_email=share.recipient_email,
        recipient_user_id=share.recipient_user_id,
        permission=share.permission,
        status=share.status,
        expired=share.expires_at <= now
        and share.status
        in {CalendarShareStatus.pending_admin_approval, CalendarShareStatus.pending_recipient},
        requested_by_display_name=requester.display_name if requester is not None else "",
        expires_at=share.expires_at,
        accepted_at=share.accepted_at,
        declined_at=share.declined_at,
        revoked_at=share.revoked_at,
        notification_preference=share.notification_preference,
        include_in_briefing=share.include_in_briefing,
        category_ids=[uuid.UUID(value) for value in share.category_ids]
        if share.category_ids is not None
        else None,
        created_at=share.created_at,
    )


# ---------------------------------------------------------------------------
# Home-scoped: create / approve / administer
# ---------------------------------------------------------------------------


@router.post("", response_model=CalendarShareResponse, status_code=status.HTTP_201_CREATED)
async def create_share(
    home_id: uuid.UUID,
    body: CalendarShareCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CalendarShareResponse:
    require_adult_session(auth)
    await _require_calendar_sharing_feature(home_id, db)
    membership = await require_capability(home_id, Capability.sharing_external, auth, db)
    calendar = await _get_calendar(db, home_id, body.calendar_id)
    if calendar.owner_user_id is not None and calendar.owner_user_id != auth.user.id:
        # Absolute Personal Calendar boundary (see _has_authority_over_calendar):
        # behaves as if another member's Personal Calendar doesn't exist, the
        # same 404 (not 403) routers.calendar uses for the same case.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That calendar could not be found")
    if calendar.owner_user_id is None and Capability.calendar_view not in await capabilities_for(
        db, membership
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That calendar could not be found")
    await enforce_rate_limit(
        request,
        settings,
        "calendar-share-create",
        _SHARE_CREATE_RATE_LIMIT,
        _SHARE_CREATE_RATE_WINDOW,
    )
    # Only the *source* Home's plan gates creating a share — a Free recipient
    # must never be blocked from receiving/accepting one (see routers on
    # entitlements: accept()/decline()/mine() below call no entitlement
    # check at all).
    await require_entitlement(db, home_id, "members.external_invites.enabled")

    recipient_email = normalise_email(str(body.recipient_email))
    existing_member = await db.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.group_id == home_id,
            Membership.removed_at.is_(None),
            User.email == recipient_email,
        )
    )
    if existing_member is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That person is already a member of this Home.",
        )

    # Race-safe: serialises concurrent share-creation attempts for the same
    # (calendar, recipient) pair — identical pattern to routers.invitations'
    # home.max_members lock.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"calendar_share:{calendar.id}:{recipient_email}"},
    )
    active = await db.scalar(
        select(CalendarShare).where(
            CalendarShare.calendar_id == calendar.id,
            CalendarShare.recipient_email == recipient_email,
            CalendarShare.status.in_(
                [
                    CalendarShareStatus.pending_admin_approval,
                    CalendarShareStatus.pending_recipient,
                    CalendarShareStatus.accepted,
                ]
            ),
            CalendarShare.expires_at > datetime.now(UTC),
        )
    )
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An active or pending share already exists for that address.",
        )

    category_ids = await _validate_category_ids(db, home_id, calendar, body.category_ids)

    direct = _has_direct_send_authority(membership, calendar)
    share = CalendarShare(
        calendar_id=calendar.id,
        source_group_id=home_id,
        requested_by_user_id=auth.user.id,
        approved_by_user_id=auth.user.id if direct else None,
        recipient_email=recipient_email,
        permission=body.permission,
        status=CalendarShareStatus.pending_recipient
        if direct
        else CalendarShareStatus.pending_admin_approval,
        token_hash=hash_secret(str(uuid.uuid4()), settings.secret_key.get_secret_value()),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        category_ids=category_ids,
    )
    db.add(share)
    await db.flush()
    raw = derived_token(share.id, _SHARE_TOKEN_PURPOSE, settings.secret_key.get_secret_value())
    share.token_hash = hash_secret(raw, settings.secret_key.get_secret_value())

    audit(
        db,
        request,
        "calendar_share.requested",
        auth.user.id,
        home_id,
        "calendar_share",
        share.id,
        {"calendar_id": str(calendar.id), "permission": share.permission.value, "direct": direct},
    )
    if direct:
        await _send_invitation_email(db, settings, share, calendar, auth.user.display_name)
        audit(
            db, request, "calendar_share.invited", auth.user.id, home_id, "calendar_share", share.id
        )
    await db.commit()
    return await _share_response(db, share)


async def _send_invitation_email(
    db: AsyncSession,
    settings: Settings,
    share: CalendarShare,
    calendar: HomeCalendar,
    inviter_display_name: str,
) -> None:
    home = await db.get(Group, share.source_group_id)
    assert home is not None
    raw = derived_token(share.id, _SHARE_TOKEN_PURPOSE, settings.secret_key.get_secret_value())
    permission_label = (
        "Can add & edit" if share.permission == CalendarSharePermission.manage else "Can view"
    )
    subject, message, html = await render_notification_email(
        db,
        settings,
        "calendar_share_invitation",
        {
            "inviter_display_name": inviter_display_name,
            "home_name": home.name,
            "calendar_name": calendar.name,
            "permission": permission_label,
            "link": f"{settings.public_web_url}/calendar-shares/accept?token={raw}",
            "expires_at": share.expires_at.isoformat(),
        },
    )
    await notify(
        db,
        settings=settings,
        recipient_email=share.recipient_email,
        notification_type="calendar_share_invitation",
        title=subject,
        body=message,
        idempotency_key=f"calendar_share_invitation:{share.id}:{share.expires_at.isoformat()}",
        html_body=html,
    )


@router.post("/{share_id}/approve", response_model=CalendarShareResponse)
async def approve_share(
    home_id: uuid.UUID,
    share_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CalendarShareResponse:
    await _require_calendar_sharing_feature(home_id, db)
    share = await db.scalar(
        select(CalendarShare)
        .where(CalendarShare.id == share_id, CalendarShare.source_group_id == home_id)
        .with_for_update()
    )
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That share could not be found")
    await _require_source_authority(db, share, auth)
    if share.status != CalendarShareStatus.pending_admin_approval:
        raise HTTPException(status.HTTP_409_CONFLICT, "This share is not awaiting approval.")
    calendar = await db.get(HomeCalendar, share.calendar_id)
    if calendar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That calendar could not be found")

    share.status = CalendarShareStatus.pending_recipient
    share.approved_by_user_id = auth.user.id
    share.expires_at = datetime.now(UTC) + timedelta(days=7)
    requester = await db.get(User, share.requested_by_user_id)
    await _send_invitation_email(
        db,
        settings,
        share,
        calendar,
        requester.display_name if requester is not None else "A Home member",
    )
    audit(db, request, "calendar_share.approved", auth.user.id, home_id, "calendar_share", share.id)
    audit(db, request, "calendar_share.invited", auth.user.id, home_id, "calendar_share", share.id)
    await db.commit()
    return await _share_response(db, share)


@router.get("/calendar/{calendar_id}", response_model=CalendarShareListResponse)
async def list_shares_for_calendar(
    home_id: uuid.UUID,
    calendar_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> CalendarShareListResponse:
    await _require_calendar_sharing_feature(home_id, db)
    await require_capability(home_id, Capability.calendar_view, auth, db)
    calendar = await _get_calendar(db, home_id, calendar_id)
    if calendar.owner_user_id is not None and calendar.owner_user_id != auth.user.id:
        # Same absolute Personal Calendar boundary as create_share — another
        # member's list of who they've shared their Personal Calendar with
        # is exactly the kind of thing calendar_view_all must never expose.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That calendar could not be found")
    shares = (
        await db.scalars(
            select(CalendarShare)
            .where(
                CalendarShare.calendar_id == calendar_id, CalendarShare.source_group_id == home_id
            )
            .order_by(CalendarShare.created_at.desc())
        )
    ).all()
    return CalendarShareListResponse(items=[await _share_response(db, share) for share in shares])


@router.post("/{share_id}/permission", response_model=CalendarShareResponse)
async def change_permission(
    home_id: uuid.UUID,
    share_id: uuid.UUID,
    body: CalendarSharePermissionUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> CalendarShareResponse:
    await _require_calendar_sharing_feature(home_id, db)
    share = await db.scalar(
        select(CalendarShare)
        .where(CalendarShare.id == share_id, CalendarShare.source_group_id == home_id)
        .with_for_update()
    )
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That share could not be found")
    await _require_source_authority(db, share, auth)
    if share.status in {CalendarShareStatus.declined, CalendarShareStatus.revoked}:
        raise HTTPException(status.HTTP_409_CONFLICT, "This share is no longer active.")
    old = share.permission
    share.permission = body.permission
    audit(
        db,
        request,
        "calendar_share.permission_changed",
        auth.user.id,
        home_id,
        "calendar_share",
        share.id,
        {"old_permission": old.value, "new_permission": body.permission.value},
    )
    await db.commit()
    return await _share_response(db, share)


@router.post("/{share_id}/categories", response_model=CalendarShareResponse)
async def change_categories(
    home_id: uuid.UUID,
    share_id: uuid.UUID,
    body: CalendarShareCategoriesUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> CalendarShareResponse:
    """Changes which categories a share exposes — takes effect immediately,
    the same as change_permission, and never requires a new invitation."""
    await _require_calendar_sharing_feature(home_id, db)
    share = await db.scalar(
        select(CalendarShare)
        .where(CalendarShare.id == share_id, CalendarShare.source_group_id == home_id)
        .with_for_update()
    )
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That share could not be found")
    await _require_source_authority(db, share, auth)
    if share.status in {CalendarShareStatus.declined, CalendarShareStatus.revoked}:
        raise HTTPException(status.HTTP_409_CONFLICT, "This share is no longer active.")
    calendar = await db.get(HomeCalendar, share.calendar_id)
    if calendar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That calendar could not be found")
    old = share.category_ids
    share.category_ids = await _validate_category_ids(db, home_id, calendar, body.category_ids)
    audit(
        db,
        request,
        "calendar_share.categories_changed",
        auth.user.id,
        home_id,
        "calendar_share",
        share.id,
        {"old_category_ids": old, "new_category_ids": share.category_ids},
    )
    await db.commit()
    return await _share_response(db, share)


@router.post("/{share_id}/revoke", response_model=MessageResponse)
async def revoke_share(
    home_id: uuid.UUID,
    share_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    await _require_calendar_sharing_feature(home_id, db)
    share = await db.scalar(
        select(CalendarShare)
        .where(CalendarShare.id == share_id, CalendarShare.source_group_id == home_id)
        .with_for_update()
    )
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That share could not be found")
    await _require_source_authority(db, share, auth)
    if share.status in {CalendarShareStatus.declined, CalendarShareStatus.revoked}:
        raise HTTPException(status.HTTP_409_CONFLICT, "This share is already inactive.")
    was_accepted = share.status == CalendarShareStatus.accepted
    share.status = CalendarShareStatus.revoked
    share.revoked_at = datetime.now(UTC)
    audit(db, request, "calendar_share.revoked", auth.user.id, home_id, "calendar_share", share.id)
    if was_accepted and share.recipient_user_id is not None:
        calendar = await db.get(HomeCalendar, share.calendar_id)
        home = await db.get(Group, home_id)
        if calendar is not None and home is not None:
            subject, message, _html = await render_notification_email(
                db,
                settings,
                "calendar_share_revoked",
                {"home_name": home.name, "calendar_name": calendar.name},
            )
            await notify(
                db,
                settings=settings,
                recipient_user_id=share.recipient_user_id,
                notification_type="calendar_share_revoked",
                title=subject,
                body=message,
                idempotency_key=f"calendar_share_revoked:{share.id}",
                deep_link=target("calendar_share"),
            )
    await db.commit()
    return MessageResponse(message="Sharing has been turned off for that calendar.")


# ---------------------------------------------------------------------------
# Top-level: accept / decline / view / manage a share the caller received
# ---------------------------------------------------------------------------


@shared_router.get("/preview", response_model=CalendarSharePreview)
async def preview_share(
    token: str = Query(min_length=30, max_length=500),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CalendarSharePreview:
    identifier = decode_derived_token(
        token, _SHARE_TOKEN_PURPOSE, settings.secret_key.get_secret_value()
    )
    share = (
        await db.scalar(select(CalendarShare).where(CalendarShare.id == identifier))
        if identifier
        else None
    )
    if (
        share is None
        or share.status != CalendarShareStatus.pending_recipient
        or share.expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invitation is invalid or has expired."
        )
    calendar = await db.get(HomeCalendar, share.calendar_id)
    home = await db.get(Group, share.source_group_id)
    inviter = await db.get(User, share.approved_by_user_id or share.requested_by_user_id)
    if calendar is None or home is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invitation is invalid or has expired."
        )
    category_names: list[str] | None = None
    if share.category_ids is not None:
        rows = (
            await db.scalars(
                select(CalendarEventLabel.name).where(CalendarEventLabel.id.in_(share.category_ids))
            )
        ).all()
        category_names = list(rows)
    return CalendarSharePreview(
        calendar_name=calendar.name,
        source_group_name=home.name,
        invited_by_display_name=inviter.display_name if inviter is not None else "",
        permission=share.permission,
        recipient_email=share.recipient_email,
        expires_at=share.expires_at,
        category_names=category_names,
    )


def _decode_share(db_result: CalendarShare | None, expected_hash: str) -> CalendarShare:
    if db_result is None or not hmac.compare_digest(db_result.token_hash, expected_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invitation is invalid or has expired."
        )
    return db_result


@shared_router.post("/accept", response_model=MessageResponse)
async def accept_share(
    body: CalendarShareAccept,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    identifier = decode_derived_token(
        body.token, _SHARE_TOKEN_PURPOSE, settings.secret_key.get_secret_value()
    )
    share = (
        await db.scalar(
            select(CalendarShare).where(CalendarShare.id == identifier).with_for_update()
        )
        if identifier
        else None
    )
    expected = hash_secret(body.token, settings.secret_key.get_secret_value())
    share = _decode_share(share, expected)
    if share.status != CalendarShareStatus.pending_recipient or share.expires_at <= datetime.now(
        UTC
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invitation is invalid or has expired."
        )
    if share.recipient_email != auth.user.email:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Sign in with the email address that was invited."
        )
    share.recipient_user_id = auth.user.id
    share.status = CalendarShareStatus.accepted
    share.accepted_at = datetime.now(UTC)
    share.notification_preference = body.notification_preference
    share.include_in_briefing = body.include_in_briefing
    audit(
        db,
        request,
        "calendar_share.accepted",
        auth.user.id,
        share.source_group_id,
        "calendar_share",
        share.id,
    )

    calendar = await db.get(HomeCalendar, share.calendar_id)
    sharer_ids = {uid for uid in (share.requested_by_user_id, share.approved_by_user_id) if uid}
    if calendar is not None:
        for sharer_id in sharer_ids:
            subject, message, _html = await render_notification_email(
                db,
                settings,
                "calendar_share_accepted",
                {"recipient_display_name": auth.user.display_name, "calendar_name": calendar.name},
            )
            await notify(
                db,
                settings=settings,
                recipient_user_id=sharer_id,
                notification_type="calendar_share_accepted",
                title=subject,
                body=message,
                idempotency_key=f"calendar_share_accepted:{share.id}:{sharer_id}",
            )
    await db.commit()
    return MessageResponse(message="You're connected. The calendar is now in your list.")


@shared_router.post("/decline", response_model=MessageResponse)
async def decline_share(
    body: CalendarShareDecline,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    identifier = decode_derived_token(
        body.token, _SHARE_TOKEN_PURPOSE, settings.secret_key.get_secret_value()
    )
    share = (
        await db.scalar(
            select(CalendarShare).where(CalendarShare.id == identifier).with_for_update()
        )
        if identifier
        else None
    )
    expected = hash_secret(body.token, settings.secret_key.get_secret_value())
    share = _decode_share(share, expected)
    if share.status != CalendarShareStatus.pending_recipient or share.expires_at <= datetime.now(
        UTC
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invitation is invalid or has expired."
        )
    if share.recipient_email != auth.user.email:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Sign in with the email address that was invited."
        )
    share.status = CalendarShareStatus.declined
    share.declined_at = datetime.now(UTC)
    audit(
        db,
        request,
        "calendar_share.declined",
        auth.user.id,
        share.source_group_id,
        "calendar_share",
        share.id,
    )
    calendar = await db.get(HomeCalendar, share.calendar_id)
    sharer_ids = {uid for uid in (share.requested_by_user_id, share.approved_by_user_id) if uid}
    if calendar is not None:
        for sharer_id in sharer_ids:
            subject, message, _html = await render_notification_email(
                db,
                settings,
                "calendar_share_declined",
                {"recipient_display_name": auth.user.display_name, "calendar_name": calendar.name},
            )
            await notify(
                db,
                settings=settings,
                recipient_user_id=sharer_id,
                notification_type="calendar_share_declined",
                title=subject,
                body=message,
                idempotency_key=f"calendar_share_declined:{share.id}:{sharer_id}",
            )
    await db.commit()
    return MessageResponse(message="Invitation declined.")


@shared_router.get("/mine", response_model=CalendarShareListResponse)
async def shares_shared_with_me(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> CalendarShareListResponse:
    shares = (
        await db.scalars(
            select(CalendarShare)
            .where(
                CalendarShare.recipient_user_id == auth.user.id,
                CalendarShare.status == CalendarShareStatus.accepted,
                CalendarShare.revoked_at.is_(None),
            )
            .order_by(CalendarShare.created_at.desc())
        )
    ).all()
    return CalendarShareListResponse(items=[await _share_response(db, share) for share in shares])


async def _require_my_share(
    db: AsyncSession, share_id: uuid.UUID, auth: AuthContext, *, need_manage: bool = False
) -> CalendarShare:
    share = await db.scalar(
        select(CalendarShare).where(
            CalendarShare.id == share_id,
            CalendarShare.recipient_user_id == auth.user.id,
            CalendarShare.status == CalendarShareStatus.accepted,
            CalendarShare.revoked_at.is_(None),
        )
    )
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That shared calendar could not be found")
    if need_manage and share.permission != CalendarSharePermission.manage:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You only have view access to this shared calendar."
        )
    return share


@shared_router.patch("/{share_id}", response_model=CalendarShareResponse)
async def update_my_preferences(
    share_id: uuid.UUID,
    body: CalendarSharePreferencesUpdate,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> CalendarShareResponse:
    share = await _require_my_share(db, share_id, auth)
    if body.notification_preference is not None:
        share.notification_preference = body.notification_preference
    if body.include_in_briefing is not None:
        share.include_in_briefing = body.include_in_briefing
    await db.commit()
    return await _share_response(db, share)


@shared_router.post("/{share_id}/leave", response_model=MessageResponse)
async def leave_share(
    share_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    share = await _require_my_share(db, share_id, auth)
    share.status = CalendarShareStatus.revoked
    share.revoked_at = datetime.now(UTC)
    audit(
        db,
        request,
        "calendar_share.left",
        auth.user.id,
        share.source_group_id,
        "calendar_share",
        share.id,
    )
    await db.commit()
    return MessageResponse(message="You've left that shared calendar.")


# ---------------------------------------------------------------------------
# Top-level: events on a calendar shared with the caller
# ---------------------------------------------------------------------------


@shared_router.get("/{share_id}/events", response_model=EventListResponse)
async def list_shared_events(
    share_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> EventListResponse:
    share = await _require_my_share(db, share_id, auth)
    if end_at <= start_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid date range")
    if end_at - start_at > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Date range is too large")
    calendar = await db.get(HomeCalendar, share.calendar_id)
    if calendar is None:
        return EventListResponse(items=[], next_page=None)

    events = (
        await db.scalars(
            select(CalendarEvent).where(
                and_(
                    CalendarEvent.calendar_id == share.calendar_id,
                    CalendarEvent.deleted_at.is_(None),
                    recurrence_candidate_filter(start_at, end_at),
                )
            )
        )
    ).all()
    label_by_id = await _label_map(db, share.source_group_id)
    items: list[EventOccurrence] = []
    for event in events:
        # The category-scoped sharing filter (see CalendarShare.category_ids'
        # docstring) — a `None` filter (share the whole calendar) matches
        # everything, unchanged from before this filter existed.
        if not event_matches_share(event, share):
            continue
        # No member assignment is ever shown/edited externally — an external
        # recipient sees the same events as a Home member with
        # calendar_view_all, but never the Home's own member list. The
        # category *is* shown, when one is set, matching the "Category:"
        # line on the event-detail screen.
        label = label_by_id.get(event.label_id) if event.label_id else None
        for occurrence_start, occurrence_end in expand_occurrences(event, start_at, end_at):
            items.append(
                _occurrence(event, occurrence_start, occurrence_end, label, [], calendar.color)
            )
    items.sort(key=lambda item: item.start_at)
    return EventListResponse(items=items, next_page=None)


@shared_router.post("/{share_id}/events", response_model=EventOccurrence, status_code=201)
async def create_shared_event(
    share_id: uuid.UUID,
    body: SharedEventCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EventOccurrence:
    share = await _require_my_share(db, share_id, auth, need_manage=True)
    if body.end_at <= body.start_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "End must be after start")
    calendar = await db.get(HomeCalendar, share.calendar_id)
    if calendar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That calendar could not be found")

    event = CalendarEvent(
        group_id=share.source_group_id,
        calendar_id=calendar.id,
        title=" ".join(body.title.strip().split()),
        description=body.description,
        start_at=body.start_at,
        end_at=body.end_at,
        is_all_day=body.is_all_day,
        timezone=body.timezone,
        location_text=body.location_text,
        reminder_minutes=body.reminder_minutes,
        recurrence=body.recurrence,
        recurrence_interval=body.recurrence_interval,
        recurrence_until=body.recurrence_until,
        recurrence_end_date=body.recurrence_end_date,
        recurrence_count=body.recurrence_count,
        created_by=auth.user.id,
        last_edited_by=auth.user.id,
    )
    db.add(event)
    await db.flush()
    await _record_activity(db, event, auth.user.id, "event.created", "created this event")
    audit(
        db,
        request,
        "calendar.event.created",
        auth.user.id,
        share.source_group_id,
        "event",
        event.id,
    )
    await notify_calendar_share_recipients(
        db,
        settings,
        event,
        actor_user_id=auth.user.id,
        actor_name=auth.user.display_name,
        action="created",
        version_marker=event.version,
    )
    await db.commit()
    await db.refresh(event)
    return _occurrence(event, event.start_at, event.end_at, None, [], calendar.color)


@shared_router.patch("/{share_id}/events/{event_id}", response_model=EventOccurrence)
async def update_shared_event(
    share_id: uuid.UUID,
    event_id: uuid.UUID,
    body: SharedEventUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EventOccurrence:
    share = await _require_my_share(db, share_id, auth, need_manage=True)
    if body.end_at <= body.start_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "End must be after start")
    event = await db.scalar(
        select(CalendarEvent)
        .where(
            CalendarEvent.id == event_id,
            CalendarEvent.calendar_id == share.calendar_id,
            CalendarEvent.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That event could not be found")
    if event.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This event changed. Reload and try again.")
    calendar = await db.get(HomeCalendar, share.calendar_id)
    if calendar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That calendar could not be found")

    material_change = (
        event.start_at != body.start_at
        or event.end_at != body.end_at
        or event.is_all_day != body.is_all_day
        or event.location_text != body.location_text
    )
    event.title = " ".join(body.title.strip().split())
    event.description = body.description
    event.start_at = body.start_at
    event.end_at = body.end_at
    event.is_all_day = body.is_all_day
    event.timezone = body.timezone
    event.location_text = body.location_text
    event.reminder_minutes = body.reminder_minutes
    event.recurrence = body.recurrence
    event.recurrence_interval = body.recurrence_interval
    event.recurrence_until = body.recurrence_until
    event.recurrence_end_date = body.recurrence_end_date
    event.recurrence_count = body.recurrence_count
    event.last_edited_by = auth.user.id
    event.version += 1

    await _record_activity(db, event, auth.user.id, "event.updated", "updated this event")
    audit(
        db,
        request,
        "calendar.event.updated",
        auth.user.id,
        share.source_group_id,
        "event",
        event.id,
    )
    if material_change:
        await notify_calendar_share_recipients(
            db,
            settings,
            event,
            actor_user_id=auth.user.id,
            actor_name=auth.user.display_name,
            action="updated",
            version_marker=event.version,
        )
    await db.commit()
    await db.refresh(event)
    return _occurrence(event, event.start_at, event.end_at, None, [], calendar.color)


@shared_router.delete("/{share_id}/events/{event_id}", status_code=204)
async def delete_shared_event(
    share_id: uuid.UUID,
    event_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    share = await _require_my_share(db, share_id, auth, need_manage=True)
    event = await db.scalar(
        select(CalendarEvent)
        .where(
            CalendarEvent.id == event_id,
            CalendarEvent.calendar_id == share.calendar_id,
            CalendarEvent.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That event could not be found")
    event.deleted_at = datetime.now(UTC)
    event.deleted_by = auth.user.id
    event.last_edited_by = auth.user.id
    await _record_activity(db, event, auth.user.id, "event.deleted", "deleted this event")
    audit(
        db,
        request,
        "calendar.event.deleted",
        auth.user.id,
        share.source_group_id,
        "event",
        event.id,
    )
    await notify_calendar_share_recipients(
        db,
        settings,
        event,
        actor_user_id=auth.user.id,
        actor_name=auth.user.display_name,
        action="cancelled",
    )
    await db.commit()
