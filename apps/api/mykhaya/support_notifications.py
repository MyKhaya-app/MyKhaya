"""Best-effort transactional email notifications for SupportTicket events.

Tickets and messages remain authoritative. Email is queued through the existing
Notification Engine and never makes a support state change fail.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import SupportTicket, SupportTicketStatus, User
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification_email

log = structlog.get_logger()


def _ticket_type(ticket: SupportTicket) -> str:
    return "bug report" if ticket.type.value == "bug" else "support request"


async def _queue(
    db: AsyncSession,
    settings: Settings,
    *,
    recipient_user_id: uuid.UUID | None,
    recipient_email: str | None,
    notification_type: str,
    ticket: SupportTicket,
    idempotency_key: str,
    reply_text: str | None = None,
) -> None:
    variables = {
        "reference": ticket.reference,
        "subject": ticket.subject,
        "ticket_type": _ticket_type(ticket),
        "reply_text": reply_text or "",
    }
    subject, body, html = await render_notification_email(
        db, settings, notification_type, variables
    )
    await notify(
        db,
        settings=settings,
        recipient_user_id=recipient_user_id,
        recipient_email=recipient_email,
        notification_type=notification_type,
        title=subject,
        body=body,
        html_body=html,
        idempotency_key=idempotency_key,
        group_id=ticket.group_id,
        related_entity_type="support_ticket",
        related_entity_id=ticket.id,
        allow_email=True,
    )


async def ticket_received(
    db: AsyncSession, settings: Settings, ticket: SupportTicket, requester: User
) -> None:
    try:
        await _queue(
            db,
            settings,
            recipient_user_id=requester.id,
            recipient_email=requester.email,
            notification_type="support.ticket.received",
            ticket=ticket,
            idempotency_key=f"support.ticket.received:{ticket.id}:requester",
        )
        if settings.support_notification_email:
            await _queue(
                db,
                settings,
                recipient_user_id=None,
                recipient_email=settings.support_notification_email,
                notification_type="support.ticket.received",
                ticket=ticket,
                idempotency_key=f"support.ticket.received:{ticket.id}:team",
            )
        else:
            log.info("support.notification_destination_missing", ticket_id=str(ticket.id))
    except Exception:
        log.exception("support.ticket_received_email_queue_failed", ticket_id=str(ticket.id))


async def ticket_reply(
    db: AsyncSession,
    settings: Settings,
    ticket: SupportTicket,
    requester: User,
    reply_text: str,
    message_id: uuid.UUID,
) -> None:
    try:
        await _queue(
            db,
            settings,
            recipient_user_id=requester.id,
            recipient_email=requester.email,
            notification_type="support.ticket.reply",
            ticket=ticket,
            idempotency_key=f"support.ticket.reply:{ticket.id}:{message_id}",
            reply_text=reply_text,
        )
    except Exception:
        log.exception("support.ticket_reply_email_queue_failed", ticket_id=str(ticket.id))


async def ticket_resolved(
    db: AsyncSession,
    settings: Settings,
    ticket: SupportTicket,
    requester: User,
    resolution_key: str,
) -> None:
    if ticket.status != SupportTicketStatus.resolved:
        return
    try:
        await _queue(
            db,
            settings,
            recipient_user_id=requester.id,
            recipient_email=requester.email,
            notification_type="support.ticket.resolved",
            ticket=ticket,
            idempotency_key=f"support.ticket.resolved:{ticket.id}:{resolution_key}",
        )
    except Exception:
        log.exception("support.ticket_resolved_email_queue_failed", ticket_id=str(ticket.id))
