"""Best-effort transactional email notifications for SupportTicket events.

Tickets and messages remain authoritative. Email is queued through the existing
Notification Engine and never makes a support state change fail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import (
    PlatformAdministrator,
    PlatformRole,
    PlatformSetting,
    SupportMessageVisibility,
    SupportTicket,
    SupportTicketStatus,
    User,
)
from mykhaya.notifications.deep_links import DeepLinkTarget, target
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification_email

log = structlog.get_logger()

# PCC Support settings: who is emailed when a new ticket is created. Stored as
# a PlatformSetting in this environment's own database (DEV and PROD are
# independent). Defaults keep the original behaviour (see
# load_new_ticket_settings) until an administrator saves it.
NEW_TICKET_SETTINGS_KEY = "support_ticket_notifications"
NEW_TICKET_TEAM_TYPE = "support.ticket.new_for_team"
DEFAULT_NEW_TICKET_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "roles": [],
    "include_support_inbox": True,
}
PRIORITY_LABELS = {"normal": "Normal", "elevated": "Elevated", "blocking": "Blocking"}


def _environment_label(settings: Settings) -> str:
    return {"production": "PROD", "development": "DEV"}.get(
        settings.environment, settings.environment.upper()
    )


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


async def load_new_ticket_settings(db: AsyncSession) -> tuple[bool, dict[str, Any]]:
    """(configured, values). Not configured means no administrator has saved
    the setting yet, and the original behaviour applies unchanged: the
    deployment's support inbox (MYKHAYA_SUPPORT_NOTIFICATION_EMAIL) gets its
    copy of support.ticket.received, and no PCC role is emailed."""
    row = await db.scalar(
        select(PlatformSetting).where(PlatformSetting.key == NEW_TICKET_SETTINGS_KEY)
    )
    stored = dict((row.value if row else {}).get("value") or {})
    return row is not None, {**DEFAULT_NEW_TICKET_SETTINGS, **stored}


async def resolve_new_ticket_recipients(
    db: AsyncSession, settings: Settings, values: dict[str, Any]
) -> list[tuple[str, str]]:
    """(stable recipient key, email): every active PCC administrator in the
    selected roles who has an email address, plus the support inbox when
    included. Resolved at send time, so role changes and deactivations apply
    immediately. Deduplicated case-insensitively, so someone in several
    selected roles, or whose address is also the inbox, gets one email."""
    recipients: dict[str, tuple[str, str]] = {}
    roles = [PlatformRole(value) for value in values.get("roles", []) if value]
    if roles:
        admins = await db.scalars(
            select(PlatformAdministrator)
            .where(
                PlatformAdministrator.is_active.is_(True),
                PlatformAdministrator.role.in_(roles),
            )
            .order_by(PlatformAdministrator.created_at)
        )
        for admin in admins:
            if admin.email and "@" in admin.email:
                recipients.setdefault(admin.email.casefold(), (f"admin:{admin.id}", admin.email))
    inbox = settings.support_notification_email
    if values.get("include_support_inbox") and inbox and "@" in inbox:
        recipients.setdefault(inbox.casefold(), ("inbox", inbox))
    return list(recipients.values())


async def _notify_team_of_new_ticket(
    db: AsyncSession, settings: Settings, ticket: SupportTicket
) -> None:
    configured, values = await load_new_ticket_settings(db)
    if not configured:
        # Original behaviour, kept until an administrator saves the setting.
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
        return
    if not values.get("enabled"):
        log.info("support.new_ticket_notifications_disabled", ticket_id=str(ticket.id))
        return
    recipients = await resolve_new_ticket_recipients(db, settings, values)
    if not recipients:
        log.info("support.new_ticket_notifications_no_recipients", ticket_id=str(ticket.id))
        return
    submitted = datetime.now(UTC)
    variables = {
        "environment": _environment_label(settings),
        "reference": ticket.reference,
        "subject": ticket.subject,
        "ticket_type": _ticket_type(ticket),
        "priority": PRIORITY_LABELS.get(ticket.priority.value, ticket.priority.value),
        "submitted_at": f"{submitted.day} {submitted:%B %Y, %H:%M} UTC",
        "link": f"{settings.admin_url.rstrip('/')}/support/tickets/{ticket.id}",
    }
    subject, body, html = await render_notification_email(
        db, settings, NEW_TICKET_TEAM_TYPE, variables
    )
    for recipient_key, email in recipients:
        await notify(
            db,
            settings=settings,
            recipient_email=email,
            notification_type=NEW_TICKET_TEAM_TYPE,
            title=subject,
            body=body,
            html_body=html,
            idempotency_key=f"{NEW_TICKET_TEAM_TYPE}:{ticket.id}:{recipient_key}",
        )
    log.info(
        "support.new_ticket_notifications_queued",
        ticket_id=str(ticket.id),
        recipients=len(recipients),
    )


async def ticket_received(
    db: AsyncSession, settings: Settings, ticket: SupportTicket, requester: User
) -> None:
    """Queue the requester's confirmation and the team's new-ticket emails.
    Each runs in its own savepoint: a failure (including a database error)
    rolls back only that notification's writes, never the ticket, which the
    caller then commits as normal."""
    try:
        async with db.begin_nested():
            await _queue(
                db,
                settings,
                recipient_user_id=requester.id,
                recipient_email=requester.email,
                notification_type="support.ticket.received",
                ticket=ticket,
                idempotency_key=f"support.ticket.received:{ticket.id}:requester",
            )
    except Exception:
        log.exception("support.ticket_received_email_queue_failed", ticket_id=str(ticket.id))
    try:
        async with db.begin_nested():
            await _notify_team_of_new_ticket(db, settings, ticket)
    except Exception:
        log.exception("support.new_ticket_team_email_queue_failed", ticket_id=str(ticket.id))


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
