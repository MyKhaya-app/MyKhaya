"""Best-effort transactional email notifications for SupportTicket events.

Tickets and messages remain authoritative. Email is queued through the existing
Notification Engine and never makes a support state change fail.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import SupportMessageVisibility, SupportTicket, SupportTicketStatus, User
from mykhaya.notifications.deep_links import DeepLinkTarget, target
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


async def _notify_reply_in_app_and_push(
    db: AsyncSession,
    settings: Settings,
    ticket: SupportTicket,
    requester: User,
    message_id: uuid.UUID,
) -> None:
    """Mandatory service notification (in-app + native/web push) for a
    customer-visible staff reply — see notifications.engine.MANDATORY_CHANNEL_TYPES.
    Deliberately a SEPARATE notify() call from the transactional reply email
    above: the email's title/body legitimately contains the reply text, but
    a push/lock-screen notification must never expose it (privacy — see
    docs/architecture/notification-engine.md), so this call uses its own
    fixed, concise copy and notification_type, and allow_email=False so it
    never queues a second, redundant email."""
    deep_link: DeepLinkTarget = target("support_ticket", ticket.id)
    await notify(
        db,
        settings=settings,
        recipient_user_id=requester.id,
        notification_type="support.ticket.reply_notice",
        title="MyKhaya Support replied",
        body=f"There's a new reply on your support ticket '{ticket.subject}'.",
        idempotency_key=f"support.ticket.reply_notice:{ticket.id}:{message_id}",
        group_id=ticket.group_id,
        related_entity_type="support_ticket",
        related_entity_id=ticket.id,
        deep_link=deep_link,
        is_critical=True,
        allow_email=False,
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
    *,
    visibility: SupportMessageVisibility = SupportMessageVisibility.requester,
) -> None:
    """Called for a staff reply on a support ticket. Only a customer-visible
    (`SupportMessageVisibility.requester`) reply notifies the requester —
    an internal/private note (structurally supported by the model for a
    possible future notes feature; no code path creates one yet) must never
    reach the requester by email, in-app, or push."""
    if visibility != SupportMessageVisibility.requester:
        return
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

    try:
        await _notify_reply_in_app_and_push(db, settings, ticket, requester, message_id)
        log.info(
            "support.notification_reply",
            ticket_id=str(ticket.id),
            delivery_type="in_app+push",
            outcome="queued",
        )
    except Exception:
        log.exception(
            "support.notification_reply",
            ticket_id=str(ticket.id),
            delivery_type="in_app+push",
            outcome="failed",
        )


async def ticket_follow_up(
    db: AsyncSession,
    settings: Settings,
    ticket: SupportTicket,
    reply_text: str,
    message_id: uuid.UUID,
) -> None:
    """Team-only notification for a requester's own follow-up reply — never
    sent to the requester (they just wrote it). Skipped entirely, same as
    ticket_received's team copy, when no support_notification_email is
    configured; a requester reply sitting unseen in PCC with no team
    destination configured is a deployment/config gap, not something this
    function can fix, so it logs and returns rather than failing the reply."""
    if not settings.support_notification_email:
        log.info("support.notification_destination_missing", ticket_id=str(ticket.id))
        return
    try:
        await _queue(
            db,
            settings,
            recipient_user_id=None,
            recipient_email=settings.support_notification_email,
            notification_type="support.ticket.follow_up",
            ticket=ticket,
            idempotency_key=f"support.ticket.follow_up:{ticket.id}:{message_id}",
            reply_text=reply_text,
        )
    except Exception:
        log.exception("support.ticket_follow_up_email_queue_failed", ticket_id=str(ticket.id))


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
