"""Consumer-facing MyKhaya Support routes (Phase 2A backend foundation).

MyKhaya/PCC is the system of record for support tickets — email is a
notification/communication mechanism layered on top via the existing
Notification Engine, added in a later phase, never the underlying store.

PRIVACY (Phase 2A decision 5, load-bearing throughout this file): a ticket
is visible only to its own requester. Every route below filters exclusively
on `SupportTicket.requester_user_id == auth.user.id` — never on `group_id`,
never on Home role/membership. A ticket's `group_id` is contextual metadata
only. See tests/test_support_tickets.py's cross-user isolation tests, which
exist specifically to keep this true even for a same-Home Owner/Admin.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mykhaya.attachments.processing import (
    OUTPUT_CONTENT_TYPE,
    AttachmentResourceError,
    UnsupportedImageError,
    process_attachment_upload,
)
from mykhaya.attachments.storage import attachment_filename, get_attachment_storage
from mykhaya.audit import audit
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.features import platform_feature_enabled
from mykhaya.models import (
    FeatureKey,
    SupportMessageVisibility,
    SupportTicket,
    SupportTicketAttachment,
    SupportTicketDiagnostic,
    SupportTicketMessage,
)
from mykhaya.notifications.visibility import active_membership
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.schemas import (
    SupportTicketAttachmentResponse,
    SupportTicketCreate,
    SupportTicketDiagnosticResponse,
    SupportTicketListResponse,
    SupportTicketMessageCreate,
    SupportTicketMessageResponse,
    SupportTicketResponse,
    SupportTicketSummaryResponse,
)
from mykhaya.support_reference import next_support_reference

MAX_ATTACHMENTS_PER_TICKET = 5


async def require_support_feature(
    db: AsyncSession = Depends(get_db),
) -> None:
    # Support is a per-user capability, not a per-Home module (Phase 2A
    # decision 5 — a ticket belongs to its requester, not a Home), so this
    # checks only the platform-global FeatureFlag, never a per-Home
    # FeatureOverride the way require_feature(...) would. See
    # module_registry's "support" ModuleDefinition docstring.
    if not await platform_feature_enabled(db, FeatureKey.support):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


router = APIRouter(
    prefix="/support",
    tags=["support"],
    dependencies=[Depends(require_support_feature)],
)


async def _owned_ticket(
    ticket_id: uuid.UUID, auth: AuthContext, db: AsyncSession, *, for_update: bool = False
) -> SupportTicket:
    query = (
        select(SupportTicket)
        .options(
            selectinload(SupportTicket.messages),
            selectinload(SupportTicket.attachments),
            selectinload(SupportTicket.diagnostic),
        )
        .where(
            SupportTicket.id == ticket_id,
            SupportTicket.requester_user_id == auth.user.id,
        )
    )
    if for_update:
        query = query.with_for_update()
    ticket = await db.scalar(query)
    # Deliberately the same response whether the ticket doesn't exist or
    # belongs to someone else — never distinguish "not found" from
    # "not yours" (same convention as membership_for).
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That support ticket could not be found.")
    return ticket


def _diagnostic_response(
    diagnostic: SupportTicketDiagnostic | None,
) -> SupportTicketDiagnosticResponse | None:
    if diagnostic is None:
        return None
    return SupportTicketDiagnosticResponse(
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


def _message_response(message: SupportTicketMessage) -> SupportTicketMessageResponse:
    return SupportTicketMessageResponse(
        id=message.id,
        author="admin" if message.author_admin_id else "requester",
        message=message.message,
        created_at=message.created_at,
    )


def _ticket_response(ticket: SupportTicket) -> SupportTicketResponse:
    return SupportTicketResponse(
        id=ticket.id,
        reference=ticket.reference,
        type=ticket.type,
        status=ticket.status,
        priority=ticket.priority,
        subject=ticket.subject,
        description=ticket.description,
        source=ticket.source,
        app_area=ticket.app_area,
        group_id=ticket.group_id,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
        messages=[
            _message_response(message)
            for message in sorted(ticket.messages, key=lambda row: row.created_at)
            if message.visibility == SupportMessageVisibility.requester
        ],
        attachments=[
            SupportTicketAttachmentResponse(
                id=attachment.id,
                original_filename=attachment.original_filename,
                content_type=attachment.content_type,
                size_bytes=attachment.size_bytes,
                created_at=attachment.created_at,
            )
            for attachment in ticket.attachments
        ],
        diagnostics=_diagnostic_response(ticket.diagnostic),
    )


@router.post("/tickets", response_model=SupportTicketResponse, status_code=201)
async def create_ticket(
    body: SupportTicketCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SupportTicketResponse:
    await enforce_rate_limit(request, settings, "support-ticket-create", 20, 3600)

    if body.group_id is not None:
        membership = await active_membership(db, body.group_id, auth.user.id)
        if membership is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "That Home could not be found."
            )

    reference = await next_support_reference(db)
    ticket = SupportTicket(
        reference=reference,
        requester_user_id=auth.user.id,
        group_id=body.group_id,
        type=body.type,
        subject=body.subject,
        description=body.description,
        source=body.source,
        app_area=body.app_area,
    )
    db.add(ticket)
    await db.flush()

    if body.diagnostics is not None:
        db.add(
            SupportTicketDiagnostic(
                ticket_id=ticket.id,
                app_version=body.diagnostics.app_version,
                build_number=body.diagnostics.build_number,
                platform=body.diagnostics.platform,
                os_version=body.diagnostics.os_version,
                runtime=body.diagnostics.runtime,
                notification_permission=body.diagnostics.notification_permission,
                push_registration_state=body.diagnostics.push_registration_state,
                api_connectivity=body.diagnostics.api_connectivity,
                network_state=body.diagnostics.network_state,
                background_refresh_state=body.diagnostics.background_refresh_state,
                client_timestamp=body.diagnostics.client_timestamp,
            )
        )
        audit(
            db,
            request,
            "support.diagnostics.shared",
            auth.user.id,
            body.group_id,
            "support_ticket",
            ticket.id,
        )

    audit(
        db,
        request,
        "support.ticket.created",
        auth.user.id,
        body.group_id,
        "support_ticket",
        ticket.id,
        metadata={"reference": reference, "type": body.type.value},
    )
    await db.commit()
    created = await _owned_ticket(ticket.id, auth, db)
    return _ticket_response(created)


@router.get("/tickets", response_model=SupportTicketListResponse)
async def list_tickets(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> SupportTicketListResponse:
    tickets = (
        await db.scalars(
            select(SupportTicket)
            .where(SupportTicket.requester_user_id == auth.user.id)
            .order_by(SupportTicket.created_at.desc())
            .limit(200)
        )
    ).all()
    return SupportTicketListResponse(
        items=[
            SupportTicketSummaryResponse(
                id=ticket.id,
                reference=ticket.reference,
                type=ticket.type,
                status=ticket.status,
                priority=ticket.priority,
                subject=ticket.subject,
                created_at=ticket.created_at,
                updated_at=ticket.updated_at,
                resolved_at=ticket.resolved_at,
            )
            for ticket in tickets
        ]
    )


@router.get("/tickets/{ticket_id}", response_model=SupportTicketResponse)
async def get_ticket(
    ticket_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> SupportTicketResponse:
    ticket = await _owned_ticket(ticket_id, auth, db)
    return _ticket_response(ticket)


@router.post(
    "/tickets/{ticket_id}/messages", response_model=SupportTicketMessageResponse, status_code=201
)
async def add_message(
    ticket_id: uuid.UUID,
    body: SupportTicketMessageCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> SupportTicketMessageResponse:
    ticket = await _owned_ticket(ticket_id, auth, db)
    message = SupportTicketMessage(
        ticket_id=ticket.id,
        author_user_id=auth.user.id,
        message=body.message,
        # Never accepted from the request body — see
        # schemas.SupportTicketMessageCreate, which has no such field.
        visibility=SupportMessageVisibility.requester,
    )
    db.add(message)
    audit(
        db,
        request,
        "support.ticket.message_added",
        auth.user.id,
        ticket.group_id,
        "support_ticket",
        ticket.id,
    )
    await db.commit()
    await db.refresh(message)
    return _message_response(message)


@router.post(
    "/tickets/{ticket_id}/attachments",
    response_model=SupportTicketAttachmentResponse,
    status_code=201,
)
async def upload_attachment(
    ticket_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SupportTicketAttachmentResponse:
    await enforce_rate_limit(request, settings, "support-attachment-upload", 20, 3600)
    ticket = await _owned_ticket(ticket_id, auth, db)

    attachment_count = len(
        (
            await db.scalars(
                select(SupportTicketAttachment.id).where(
                    SupportTicketAttachment.ticket_id == ticket.id
                )
            )
        ).all()
    )
    if attachment_count >= MAX_ATTACHMENTS_PER_TICKET:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"A ticket can have at most {MAX_ATTACHMENTS_PER_TICKET} attachments.",
        )

    raw = await file.read(settings.support_attachment_max_upload_bytes + 1)
    if len(raw) > settings.support_attachment_max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That file is too large. Please choose one under "
            f"{settings.support_attachment_max_upload_bytes // (1024 * 1024)} MB.",
        )
    if not raw:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No file was uploaded.")

    # Decoding (never trusting the client's Content-Type or filename) is the
    # real validation here — mirrors avatars' upload route.
    try:
        processed = process_attachment_upload(raw)
    except AttachmentResourceError as cause:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That image is too large to process. Please choose another image.",
        ) from cause
    except UnsupportedImageError as cause:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(cause)) from cause

    storage = get_attachment_storage(settings)
    key = attachment_filename()
    await storage.save(key, processed)

    attachment = SupportTicketAttachment(
        ticket_id=ticket.id,
        storage_key=key,
        # Display-only — never used to build a filesystem path (see
        # AttachmentStorage._path_for). Truncated defensively.
        original_filename=(file.filename or "attachment")[:255],
        content_type=OUTPUT_CONTENT_TYPE,
        size_bytes=len(processed),
        uploaded_by_user_id=auth.user.id,
    )
    db.add(attachment)
    audit(
        db,
        request,
        "support.attachment.uploaded",
        auth.user.id,
        ticket.group_id,
        "support_ticket",
        ticket.id,
        metadata={"content_type": OUTPUT_CONTENT_TYPE},
    )
    await db.commit()
    await db.refresh(attachment)
    return SupportTicketAttachmentResponse(
        id=attachment.id,
        original_filename=attachment.original_filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        created_at=attachment.created_at,
    )
