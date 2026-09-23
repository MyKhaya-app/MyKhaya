"""Platform Control Centre Support routes (Phase 2A backend foundation).

PCC is the internal support console/system of record — see
mykhaya.routers.support's module docstring for the consumer side of this
same feature. Access uses the existing platform-admin security model
(require_roles(*SUPPORT), the same tuple communications_admin.py already
uses) — no new platform role is introduced for this phase (Phase 2A decision
6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mykhaya.attachments.storage import get_attachment_storage
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.models import (
    Group,
    PlatformAdministrator,
    SupportMessageVisibility,
    SupportTicket,
    SupportTicketAppArea,
    SupportTicketAttachment,
    SupportTicketMessage,
    SupportTicketPriority,
    SupportTicketSource,
    SupportTicketStatus,
    SupportTicketType,
    User,
)
from mykhaya.platform_audit import platform_audit
from mykhaya.platform_schemas import (
    PlatformSupportTicketAttachmentResponse,
    PlatformSupportTicketDetailResponse,
    PlatformSupportTicketDiagnosticResponse,
    PlatformSupportTicketListResponse,
    PlatformSupportTicketMessageCreate,
    PlatformSupportTicketMessageResponse,
    PlatformSupportTicketSummaryResponse,
    PlatformSupportTicketUpdate,
)
from mykhaya.platform_security import PlatformContext, require_roles
from mykhaya.routers.platform import SUPPORT

router = APIRouter(prefix="/platform/support", tags=["platform-support"])

PAGE_SIZE = 30


async def _load_ticket(db: AsyncSession, ticket_id: uuid.UUID) -> SupportTicket:
    ticket = await db.scalar(
        select(SupportTicket)
        .options(
            selectinload(SupportTicket.messages),
            selectinload(SupportTicket.attachments),
            selectinload(SupportTicket.diagnostic),
        )
        .where(SupportTicket.id == ticket_id)
    )
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That support ticket could not be found.")
    return ticket


async def _display_names(
    db: AsyncSession, user_ids: set[uuid.UUID], admin_ids: set[uuid.UUID]
) -> tuple[dict[uuid.UUID, User], dict[uuid.UUID, PlatformAdministrator]]:
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        user_rows = (await db.scalars(select(User).where(User.id.in_(user_ids)))).all()
        users = {row.id: row for row in user_rows}
    admins: dict[uuid.UUID, PlatformAdministrator] = {}
    if admin_ids:
        admin_rows = (
            await db.scalars(
                select(PlatformAdministrator).where(PlatformAdministrator.id.in_(admin_ids))
            )
        ).all()
        admins = {row.id: row for row in admin_rows}
    return users, admins


def _message_response(
    message: SupportTicketMessage,
    users: dict[uuid.UUID, User],
    admins: dict[uuid.UUID, PlatformAdministrator],
) -> PlatformSupportTicketMessageResponse:
    if message.author_admin_id is not None:
        admin = admins.get(message.author_admin_id)
        display_name = admin.display_name if admin else "Former administrator"
    elif message.author_user_id is not None:
        user = users.get(message.author_user_id)
        display_name = user.display_name if user else "Former user"
    else:
        # Both FKs are null: only reachable if the row a message pointed to
        # was hard-deleted (author_user_id/author_admin_id are both
        # `ondelete="SET NULL"`) — in practice this never happens in
        # production (PlatformAdministrator/User rows are deactivated or
        # anonymised, never hard-deleted; the only place this repo does
        # hard-delete a PlatformAdministrator is a test cleanup fixture).
        # Genuinely unknown at this point, so this deliberately does NOT
        # default to "Former user" (which would misattribute a possible
        # admin message to the requester side) — see the Phase 2B
        # instruction this addresses.
        display_name = "Former participant"
    return PlatformSupportTicketMessageResponse(
        id=message.id,
        author_user_id=message.author_user_id,
        author_admin_id=message.author_admin_id,
        author_display_name=display_name,
        message=message.message,
        visibility=message.visibility.value,
        created_at=message.created_at,
    )


async def _detail_response(
    db: AsyncSession, ticket: SupportTicket
) -> PlatformSupportTicketDetailResponse:
    requester = await db.get(User, ticket.requester_user_id)
    group = await db.get(Group, ticket.group_id) if ticket.group_id else None
    assigned_admin = (
        await db.get(PlatformAdministrator, ticket.assigned_admin_id)
        if ticket.assigned_admin_id
        else None
    )
    user_ids = {message.author_user_id for message in ticket.messages if message.author_user_id}
    admin_ids = {message.author_admin_id for message in ticket.messages if message.author_admin_id}
    users, admins = await _display_names(db, user_ids, admin_ids)
    diagnostic = ticket.diagnostic
    return PlatformSupportTicketDetailResponse(
        id=ticket.id,
        reference=ticket.reference,
        type=ticket.type,
        status=ticket.status,
        priority=ticket.priority,
        subject=ticket.subject,
        description=ticket.description,
        source=ticket.source,
        app_area=ticket.app_area,
        requester_user_id=ticket.requester_user_id,
        requester_display_name=requester.display_name if requester else "Former user",
        requester_email=requester.email if requester else "unknown@mykhaya.app",
        group_id=ticket.group_id,
        group_name=group.name if group else None,
        assigned_admin_id=ticket.assigned_admin_id,
        assigned_admin_display_name=assigned_admin.display_name if assigned_admin else None,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
        messages=[
            _message_response(message, users, admins)
            for message in sorted(ticket.messages, key=lambda row: row.created_at)
        ],
        attachments=[
            PlatformSupportTicketAttachmentResponse(
                id=attachment.id,
                original_filename=attachment.original_filename,
                content_type=attachment.content_type,
                size_bytes=attachment.size_bytes,
                created_at=attachment.created_at,
            )
            for attachment in ticket.attachments
        ],
        diagnostics=(
            PlatformSupportTicketDiagnosticResponse(
                app_version=diagnostic.app_version,
                build_number=diagnostic.build_number,
                platform=diagnostic.platform,
                os_version=diagnostic.os_version,
                runtime=diagnostic.runtime,
                notification_permission=diagnostic.notification_permission,
                push_registration_state=diagnostic.push_registration_state,
                api_connectivity=diagnostic.api_connectivity,
                network_state=diagnostic.network_state,
                background_refresh_state=diagnostic.background_refresh_state,
                client_timestamp=diagnostic.client_timestamp,
            )
            if diagnostic is not None
            else None
        ),
    )


@router.get("/tickets", response_model=PlatformSupportTicketListResponse)
async def list_tickets(
    page: int = Query(default=1, ge=1, le=1000),
    ticket_status: SupportTicketStatus | None = Query(default=None, alias="status"),
    ticket_type: SupportTicketType | None = Query(default=None, alias="type"),
    priority: SupportTicketPriority | None = None,
    source: SupportTicketSource | None = None,
    app_area: SupportTicketAppArea | None = None,
    assigned_admin_id: uuid.UUID | None = None,
    query: str | None = Query(default=None, max_length=200),
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> PlatformSupportTicketListResponse:
    statement = select(SupportTicket)
    if ticket_status is not None:
        statement = statement.where(SupportTicket.status == ticket_status)
    if ticket_type is not None:
        statement = statement.where(SupportTicket.type == ticket_type)
    if priority is not None:
        statement = statement.where(SupportTicket.priority == priority)
    if source is not None:
        statement = statement.where(SupportTicket.source == source)
    if app_area is not None:
        statement = statement.where(SupportTicket.app_area == app_area)
    if assigned_admin_id is not None:
        statement = statement.where(SupportTicket.assigned_admin_id == assigned_admin_id)

    needle = (query or "").strip()
    if needle:
        matching_user_ids = (
            await db.scalars(
                select(User.id).where(
                    or_(
                        User.display_name.ilike(f"%{needle}%"),
                        User.email.ilike(f"%{needle}%"),
                    )
                )
            )
        ).all()
        requester_match = (
            SupportTicket.requester_user_id.in_(matching_user_ids) if matching_user_ids else false()
        )
        statement = statement.where(
            or_(
                SupportTicket.reference.ilike(f"%{needle}%"),
                SupportTicket.subject.ilike(f"%{needle}%"),
                requester_match,
            )
        )

    offset = (page - 1) * PAGE_SIZE
    rows = (
        await db.scalars(
            statement.order_by(SupportTicket.created_at.desc()).offset(offset).limit(PAGE_SIZE + 1)
        )
    ).all()
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    requester_ids = {row.requester_user_id for row in rows}
    group_ids = {row.group_id for row in rows if row.group_id is not None}
    admin_ids = {row.assigned_admin_id for row in rows if row.assigned_admin_id is not None}
    users, admins = await _display_names(db, requester_ids, admin_ids)
    groups: dict[uuid.UUID, Group] = {}
    if group_ids:
        group_rows = (await db.scalars(select(Group).where(Group.id.in_(group_ids)))).all()
        groups = {row.id: row for row in group_rows}

    items = [
        PlatformSupportTicketSummaryResponse(
            id=row.id,
            reference=row.reference,
            type=row.type,
            status=row.status,
            priority=row.priority,
            subject=row.subject,
            source=row.source,
            app_area=row.app_area,
            requester_display_name=(
                users[row.requester_user_id].display_name
                if row.requester_user_id in users
                else "Former user"
            ),
            requester_email=(
                users[row.requester_user_id].email
                if row.requester_user_id in users
                else "unknown@mykhaya.app"
            ),
            group_id=row.group_id,
            group_name=groups[row.group_id].name if row.group_id in groups else None,
            assigned_admin_id=row.assigned_admin_id,
            assigned_admin_display_name=(
                admins[row.assigned_admin_id].display_name
                if row.assigned_admin_id in admins
                else None
            ),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return PlatformSupportTicketListResponse(items=items, next_page=page + 1 if has_more else None)


@router.get("/tickets/{ticket_id}", response_model=PlatformSupportTicketDetailResponse)
async def get_ticket(
    ticket_id: uuid.UUID,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> PlatformSupportTicketDetailResponse:
    ticket = await _load_ticket(db, ticket_id)
    platform_audit(
        db, request, context, "support.ticket.viewed_by_admin", "support_ticket", ticket.id
    )
    if ticket.diagnostic is not None:
        platform_audit(
            db, request, context, "support.diagnostics.viewed", "support_ticket", ticket.id
        )
    if ticket.attachments:
        platform_audit(
            db,
            request,
            context,
            "support.attachment.viewed",
            "support_ticket",
            ticket.id,
            new={"attachment_count": len(ticket.attachments)},
        )
    response = await _detail_response(db, ticket)
    await db.commit()
    return response


@router.patch("/tickets/{ticket_id}", response_model=PlatformSupportTicketDetailResponse)
async def update_ticket(
    ticket_id: uuid.UUID,
    body: PlatformSupportTicketUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> PlatformSupportTicketDetailResponse:
    ticket = await _load_ticket(db, ticket_id)
    changes = body.model_dump(exclude_unset=True)

    if "status" in changes and body.status is not None and body.status != ticket.status:
        previous_status = ticket.status
        ticket.status = body.status
        if body.status in (SupportTicketStatus.resolved, SupportTicketStatus.closed):
            ticket.resolved_at = datetime.now(UTC)
        elif body.status in (SupportTicketStatus.open, SupportTicketStatus.in_progress):
            ticket.resolved_at = None
        platform_audit(
            db,
            request,
            context,
            "support.ticket.status_changed",
            "support_ticket",
            ticket.id,
            previous={"status": previous_status.value},
            new={"status": ticket.status.value},
        )
        if ticket.status == SupportTicketStatus.resolved:
            platform_audit(
                db, request, context, "support.ticket.resolved", "support_ticket", ticket.id
            )

    if "priority" in changes and body.priority is not None and body.priority != ticket.priority:
        previous_priority = ticket.priority
        ticket.priority = body.priority
        platform_audit(
            db,
            request,
            context,
            "support.ticket.status_changed",
            "support_ticket",
            ticket.id,
            previous={"priority": previous_priority.value},
            new={"priority": ticket.priority.value},
        )

    if "assigned_admin_id" in changes and changes["assigned_admin_id"] != ticket.assigned_admin_id:
        if body.assigned_admin_id is not None:
            assignee = await db.get(PlatformAdministrator, body.assigned_admin_id)
            if assignee is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, "That administrator could not be found."
                )
        previous_assignee = ticket.assigned_admin_id
        ticket.assigned_admin_id = body.assigned_admin_id
        new_assignee = body.assigned_admin_id
        platform_audit(
            db,
            request,
            context,
            "support.ticket.assigned",
            "support_ticket",
            ticket.id,
            previous={"assigned_admin_id": str(previous_assignee) if previous_assignee else None},
            new={"assigned_admin_id": str(new_assignee) if new_assignee else None},
        )

    await db.commit()
    await db.refresh(ticket)
    ticket = await _load_ticket(db, ticket_id)
    return await _detail_response(db, ticket)


@router.post(
    "/tickets/{ticket_id}/messages",
    response_model=PlatformSupportTicketMessageResponse,
    status_code=201,
)
async def reply_to_ticket(
    ticket_id: uuid.UUID,
    body: PlatformSupportTicketMessageCreate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> PlatformSupportTicketMessageResponse:
    ticket = await _load_ticket(db, ticket_id)
    message = SupportTicketMessage(
        ticket_id=ticket.id,
        author_admin_id=context.administrator.id,
        message=body.message,
        # An admin reply is always requester-visible — Phase 2A's structural
        # 'internal' visibility exists for a possible future notes feature,
        # not for replies (see models.SupportTicketMessage's docstring).
        visibility=SupportMessageVisibility.requester,
    )
    db.add(message)
    platform_audit(db, request, context, "support.ticket.replied", "support_ticket", ticket.id)
    await db.commit()
    await db.refresh(message)
    return PlatformSupportTicketMessageResponse(
        id=message.id,
        author_user_id=message.author_user_id,
        author_admin_id=message.author_admin_id,
        author_display_name=context.administrator.display_name,
        message=message.message,
        visibility=message.visibility.value,
        created_at=message.created_at,
    )


def _safe_content_disposition_filename(original_filename: str) -> str:
    # ASCII-only, no quotes/control characters — the original filename is
    # display text a consumer chose (see SupportTicketAttachment's
    # docstring), never trusted for a filesystem path and, here, not
    # trusted raw inside an HTTP header either. Falls back to a fixed name
    # rather than trying to preserve anything from an unsafe original.
    cleaned = "".join(
        char for char in original_filename if char.isascii() and char not in '"\\\r\n'
    ).strip()
    return cleaned[:120] or "attachment"


@router.get("/tickets/{ticket_id}/attachments/{attachment_id}")
async def get_attachment(
    ticket_id: uuid.UUID,
    attachment_id: uuid.UUID,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    # Ticket existence and attachment-belongs-to-ticket are checked
    # together, and both a missing ticket and a missing/foreign attachment
    # return the same 404 — never distinguish "no such ticket" from
    # "that attachment isn't on this ticket" (same convention as
    # routers.support's _owned_ticket and dependencies.membership_for).
    attachment = await db.scalar(
        select(SupportTicketAttachment).where(
            SupportTicketAttachment.id == attachment_id,
            SupportTicketAttachment.ticket_id == ticket_id,
        )
    )
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That attachment could not be found.")

    storage = get_attachment_storage(settings)
    data = await storage.load(attachment.storage_key)
    if data is None:
        # The DB row exists but the bytes are gone (e.g. manual ops
        # cleanup) — still a 404, not a 500: from the caller's point of
        # view there is simply no attachment to show.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That attachment could not be found.")

    platform_audit(
        db, request, context, "support.attachment.viewed", "support_ticket_attachment",
        attachment.id, new={"ticket_id": str(ticket_id)},
    )
    await db.commit()

    filename = _safe_content_disposition_filename(attachment.original_filename)
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={
            # Inline, not attachment — this is a screenshot preview, meant
            # to render in the PCC page (<img>) or open in a new tab, not
            # force-download. Never cached beyond this response: an admin
            # session's own authorization is what gates every fetch, so a
            # shared/proxy cache must not retain a copy.
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )
