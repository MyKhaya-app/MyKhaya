"""Regression coverage for mykhaya.support_notifications: the thin,
best-effort email layer over SupportTicket events (ticket_received,
ticket_reply, ticket_resolved). Calls the module's functions directly
against a real DB session (SessionFactory), following the same pattern as
test_email_notifications.py's email_outbox_rows helper — inspecting the
`notification.email` OutboxEvent rows notify() enqueues, rather than
mocking notify() itself, so real idempotency/dedup behaviour is exercised.

The one place this file does mock is the failure-isolation tests, where
mykhaya.support_notifications.notify is monkeypatched to raise — that is
the dispatch boundary these helpers are meant to shield the caller from.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import (
    OutboxEvent,
    PlatformAdministrator,
    PlatformRole,
    SupportTicket,
    SupportTicketAttachment,
    SupportTicketDiagnostic,
    SupportTicketMessage,
    SupportTicketSource,
    SupportTicketStatus,
    SupportTicketType,
    User,
)
from mykhaya.security import password_hash
from mykhaya.support_notifications import (
    ticket_follow_up,
    ticket_received,
    ticket_reply,
    ticket_resolved,
)
from mykhaya.support_reference import next_support_reference


def unique_email(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"


async def _create_user(display_name: str = "Requester") -> User:
    async with SessionFactory() as db:
        user = User(email=unique_email("support-notif"), display_name=display_name)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _create_admin(display_name: str = "Assigned Admin") -> PlatformAdministrator:
    async with SessionFactory() as db:
        admin = PlatformAdministrator(
            email=unique_email("support-admin"),
            display_name=display_name,
            password_hash=password_hash.hash("A very secret operator password!"),
            role=PlatformRole.support,
            mfa_enrolled=True,
        )
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        return admin


async def _create_ticket(
    db: AsyncSession,
    requester: User,
    **overrides: object,
) -> SupportTicket:
    reference = await next_support_reference(db)
    ticket = SupportTicket(
        reference=reference,
        requester_user_id=requester.id,
        type=overrides.get("type", SupportTicketType.bug),
        status=overrides.get("status", SupportTicketStatus.open),
        subject=overrides.get("subject", "Calendar save fails"),
        description=overrides.get("description", "The event disappears after saving."),
        source=overrides.get("source", SupportTicketSource.web),
        group_id=overrides.get("group_id"),
        assigned_admin_id=overrides.get("assigned_admin_id"),
        resolved_at=overrides.get("resolved_at"),
    )
    db.add(ticket)
    await db.flush()
    return ticket


async def _reload_ticket(db: AsyncSession, ticket_id: uuid.UUID) -> SupportTicket:
    ticket = await db.get(SupportTicket, ticket_id)
    assert ticket is not None
    return ticket


async def _outbox_rows_for(recipient_email: str) -> list[OutboxEvent]:
    async with SessionFactory() as db:
        rows = (
            await db.scalars(select(OutboxEvent).where(OutboxEvent.topic == "notification.email"))
        ).all()
        return [row for row in rows if row.payload.get("recipient_email") == recipient_email]


async def _all_support_outbox_payloads() -> list[dict[str, Any]]:
    async with SessionFactory() as db:
        rows = (
            await db.scalars(select(OutboxEvent).where(OutboxEvent.topic == "notification.email"))
        ).all()
        return [
            row.payload
            for row in rows
            if str(row.payload.get("notification_type", "")).startswith("support.ticket.")
        ]


# --------------------------------------------------------------------------
# ticket_received
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_received_notifies_requester_with_correct_content() -> None:
    requester = await _create_user()
    settings = get_settings().model_copy(update={"support_notification_email": None})
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester, subject="Widget crashes on launch")
        await db.commit()

        rows_before = await _outbox_rows_for(requester.email)
        await ticket_received(db, settings, ticket, requester)
        await db.commit()

    rows = await _outbox_rows_for(requester.email)
    assert len(rows) == len(rows_before) + 1
    payload = rows[-1].payload
    assert payload["notification_type"] == "support.ticket.received"
    assert ticket.reference in payload["body"]
    assert "bug report" in payload["subject"] or "bug report" in payload["body"]
    # No diagnostics, attachment, or internal-id content ever reaches the
    # notify() variables dict for this template — see support_notifications._queue.
    assert "diagnostic" not in payload["body"].lower()
    assert "attachment" not in payload["body"].lower()
    assert str(ticket.id) not in payload["body"]


@pytest.mark.asyncio
async def test_ticket_received_sends_team_copy_when_configured() -> None:
    requester = await _create_user()
    team_email = unique_email("support-team")
    settings = get_settings().model_copy(update={"support_notification_email": team_email})
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester)
        await db.commit()
        await ticket_received(db, settings, ticket, requester)
        await db.commit()

    requester_rows = await _outbox_rows_for(requester.email)
    team_rows = await _outbox_rows_for(team_email)
    assert len(requester_rows) == 1
    assert len(team_rows) == 1
    assert team_rows[0].payload["notification_type"] == "support.ticket.received"
    assert ticket.reference in team_rows[0].payload["body"]


@pytest.mark.asyncio
async def test_ticket_received_skips_team_copy_and_does_not_raise_when_not_configured() -> None:
    requester = await _create_user()
    settings = get_settings().model_copy(update={"support_notification_email": None})
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester)
        await db.commit()
        # Must complete without raising even though no team destination is configured.
        await ticket_received(db, settings, ticket, requester)
        await db.commit()

    payloads = [p for p in await _all_support_outbox_payloads() if ticket.reference in p["body"]]
    assert len(payloads) == 1
    assert payloads[0]["recipient_email"] == requester.email


# --------------------------------------------------------------------------
# ticket_reply
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_reply_notifies_requester_only_with_reply_text() -> None:
    requester = await _create_user()
    other_user = await _create_user(display_name="Unrelated User")
    settings = get_settings()
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester)
        message = SupportTicketMessage(
            ticket_id=ticket.id,
            author_admin_id=None,
            message="We've reproduced this and are working on a fix.",
        )
        db.add(message)
        await db.flush()
        message_id = message.id
        await ticket_reply(db, settings, ticket, requester, message.message, message_id)
        await db.commit()

    requester_rows = await _outbox_rows_for(requester.email)
    other_user_rows = await _outbox_rows_for(other_user.email)
    assert len(requester_rows) == 1
    assert len(other_user_rows) == 0
    payload = requester_rows[0].payload
    assert payload["notification_type"] == "support.ticket.reply"
    assert ticket.reference in payload["body"]
    assert "We've reproduced this and are working on a fix." in payload["body"]


@pytest.mark.asyncio
async def test_ticket_reply_idempotency_key_is_stable_per_message_id() -> None:
    requester = await _create_user()
    settings = get_settings()
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester)
        message = SupportTicketMessage(
            ticket_id=ticket.id, author_admin_id=None, message="First reply."
        )
        db.add(message)
        await db.flush()
        message_id = message.id
        await db.commit()

    async with SessionFactory() as db:
        ticket = await _reload_ticket(db, ticket.id)
        # A second call with the same persisted message id (e.g. a retried
        # request) must not enqueue a second email.
        await ticket_reply(db, settings, ticket, requester, "First reply.", message_id)
        await ticket_reply(db, settings, ticket, requester, "First reply.", message_id)
        await db.commit()

    rows = await _outbox_rows_for(requester.email)
    reply_rows = [r for r in rows if r.payload["notification_type"] == "support.ticket.reply"]
    assert len(reply_rows) == 1


# --------------------------------------------------------------------------
# ticket_follow_up (requester's own reply — team-only, never to the requester)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_follow_up_notifies_team_only_when_configured() -> None:
    requester = await _create_user()
    team_email = unique_email("support-team")
    settings = get_settings().model_copy(update={"support_notification_email": team_email})
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester)
        message = SupportTicketMessage(
            ticket_id=ticket.id,
            author_user_id=requester.id,
            message="Still happening — any update?",
        )
        db.add(message)
        await db.flush()
        await ticket_follow_up(db, settings, ticket, message.message, message.id)
        await db.commit()

    team_rows = await _outbox_rows_for(team_email)
    requester_rows = await _outbox_rows_for(requester.email)
    assert len(team_rows) == 1
    assert len(requester_rows) == 0
    payload = team_rows[0].payload
    assert payload["notification_type"] == "support.ticket.follow_up"
    assert ticket.reference in payload["body"]
    assert "Still happening — any update?" in payload["body"]


@pytest.mark.asyncio
async def test_ticket_follow_up_does_not_raise_when_team_email_is_not_configured() -> None:
    requester = await _create_user()
    settings = get_settings().model_copy(update={"support_notification_email": None})
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester)
        message = SupportTicketMessage(
            ticket_id=ticket.id, author_user_id=requester.id, message="Following up."
        )
        db.add(message)
        await db.flush()
        await ticket_follow_up(db, settings, ticket, message.message, message.id)  # must not raise
        await db.commit()

    payloads = [p for p in await _all_support_outbox_payloads() if ticket.reference in p["body"]]
    follow_up_rows = [p for p in payloads if p["notification_type"] == "support.ticket.follow_up"]
    assert len(follow_up_rows) == 0


@pytest.mark.asyncio
async def test_ticket_follow_up_idempotency_key_is_stable_per_message_id() -> None:
    requester = await _create_user()
    team_email = unique_email("support-team")
    settings = get_settings().model_copy(update={"support_notification_email": team_email})
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester)
        message = SupportTicketMessage(
            ticket_id=ticket.id, author_user_id=requester.id, message="Repeated follow-up."
        )
        db.add(message)
        await db.flush()
        message_id = message.id
        # A second call with the same persisted message id (e.g. a retried
        # request) must not enqueue a second email.
        await ticket_follow_up(db, settings, ticket, message.message, message_id)
        await ticket_follow_up(db, settings, ticket, message.message, message_id)
        await db.commit()

    team_rows = await _outbox_rows_for(team_email)
    follow_up_rows = [
        r for r in team_rows if r.payload["notification_type"] == "support.ticket.follow_up"
    ]
    assert len(follow_up_rows) == 1


@pytest.mark.asyncio
async def test_ticket_follow_up_email_failure_does_not_abort_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requester = await _create_user()
    team_email = unique_email("support-team")
    settings = get_settings().model_copy(update={"support_notification_email": team_email})
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester)
        await db.commit()

    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("smtp exploded")

    monkeypatch.setattr("mykhaya.support_notifications.notify", boom)

    async with SessionFactory() as db:
        ticket = await _reload_ticket(db, ticket.id)
        message = SupportTicketMessage(
            ticket_id=ticket.id, author_user_id=requester.id, message="Reply text."
        )
        db.add(message)
        await db.flush()
        # Must not raise, despite the patched notify() below.
        await ticket_follow_up(db, settings, ticket, message.message, message.id)
        await db.commit()  # must succeed despite the notify failure above
        message_id = message.id

    monkeypatch.undo()
    async with SessionFactory() as db:
        reloaded = await db.get(SupportTicketMessage, message_id)
        assert reloaded is not None


# --------------------------------------------------------------------------
# ticket_resolved
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_resolved_notifies_requester_and_dedupes_same_resolution_occurrence() -> None:
    requester = await _create_user()
    settings = get_settings()
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester, status=SupportTicketStatus.resolved)
        await db.commit()

    resolution_key = "2026-01-01T00:00:00+00:00"
    async with SessionFactory() as db:
        ticket = await _reload_ticket(db, ticket.id)
        await ticket_resolved(db, settings, ticket, requester, resolution_key)
        # Same resolution occurrence (e.g. a retried PATCH) — must not
        # duplicate the email.
        await ticket_resolved(db, settings, ticket, requester, resolution_key)
        await db.commit()

    rows = await _outbox_rows_for(requester.email)
    resolved_rows = [r for r in rows if r.payload["notification_type"] == "support.ticket.resolved"]
    assert len(resolved_rows) == 1
    assert ticket.reference in resolved_rows[0].payload["body"]


@pytest.mark.asyncio
async def test_ticket_resolved_new_resolution_occurrence_sends_a_new_email() -> None:
    requester = await _create_user()
    settings = get_settings()
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester, status=SupportTicketStatus.resolved)
        await db.commit()

    async with SessionFactory() as db:
        ticket = await _reload_ticket(db, ticket.id)
        await ticket_resolved(db, settings, ticket, requester, "resolution-1")
        await db.commit()

    async with SessionFactory() as db:
        ticket = await _reload_ticket(db, ticket.id)
        # A genuine re-open -> re-resolve cycle gets its own resolution_key
        # (routers.platform_support derives it from the fresh resolved_at),
        # so it must be treated as a new occurrence, not a duplicate.
        await ticket_resolved(db, settings, ticket, requester, "resolution-2")
        await db.commit()

    rows = await _outbox_rows_for(requester.email)
    resolved_rows = [r for r in rows if r.payload["notification_type"] == "support.ticket.resolved"]
    assert len(resolved_rows) == 2


@pytest.mark.asyncio
async def test_ticket_resolved_is_a_no_op_when_ticket_is_not_resolved() -> None:
    requester = await _create_user()
    settings = get_settings()
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester, status=SupportTicketStatus.open)
        await db.commit()
        await ticket_resolved(db, settings, ticket, requester, "should-not-fire")
        await db.commit()

    rows = await _outbox_rows_for(requester.email)
    resolved_rows = [r for r in rows if r.payload["notification_type"] == "support.ticket.resolved"]
    assert len(resolved_rows) == 0


# --------------------------------------------------------------------------
# Failure isolation — a notify() failure must never abort the caller's
# ticket transaction (create / reply / resolve).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_received_email_failure_does_not_abort_ticket_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requester = await _create_user()
    settings = get_settings()

    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("smtp exploded")

    monkeypatch.setattr("mykhaya.support_notifications.notify", boom)

    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester, subject="Survives a notify failure")
        await ticket_received(db, settings, ticket, requester)  # must not raise
        await db.commit()  # must succeed despite the notify failure above
        ticket_id = ticket.id

    monkeypatch.undo()
    async with SessionFactory() as db:
        reloaded = await db.get(SupportTicket, ticket_id)
        assert reloaded is not None
        assert reloaded.subject == "Survives a notify failure"


@pytest.mark.asyncio
async def test_ticket_reply_email_failure_does_not_abort_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requester = await _create_user()
    settings = get_settings()
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester)
        await db.commit()

    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("smtp exploded")

    monkeypatch.setattr("mykhaya.support_notifications.notify", boom)

    async with SessionFactory() as db:
        ticket = await _reload_ticket(db, ticket.id)
        message = SupportTicketMessage(
            ticket_id=ticket.id, author_admin_id=None, message="Reply text."
        )
        db.add(message)
        await db.flush()
        # Must not raise, despite the patched notify() below.
        await ticket_reply(db, settings, ticket, requester, message.message, message.id)
        await db.commit()  # must succeed despite the notify failure above
        message_id = message.id

    monkeypatch.undo()
    async with SessionFactory() as db:
        reloaded = await db.get(SupportTicketMessage, message_id)
        assert reloaded is not None


@pytest.mark.asyncio
async def test_ticket_resolved_email_failure_does_not_abort_the_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requester = await _create_user()
    settings = get_settings()
    async with SessionFactory() as db:
        ticket = await _create_ticket(db, requester, status=SupportTicketStatus.resolved)
        await db.commit()

    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("smtp exploded")

    monkeypatch.setattr("mykhaya.support_notifications.notify", boom)

    async with SessionFactory() as db:
        ticket = await _reload_ticket(db, ticket.id)
        await ticket_resolved(db, settings, ticket, requester, "resolution-x")  # must not raise
        await db.commit()  # must succeed despite the notify failure above
        ticket_id = ticket.id

    monkeypatch.undo()
    async with SessionFactory() as db:
        reloaded = await db.get(SupportTicket, ticket_id)
        assert reloaded is not None
        assert reloaded.status == SupportTicketStatus.resolved


# --------------------------------------------------------------------------
# Privacy: diagnostics, attachments, admin/Home internals, and auth
# material must never reach a Support notification email.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_support_emails_never_include_diagnostics_attachments_or_internal_ids() -> None:
    requester = await _create_user(display_name="Privacy Requester")
    admin = await _create_admin(display_name="Internal Reviewer Name")
    team_email = unique_email("support-team")
    settings = get_settings().model_copy(update={"support_notification_email": team_email})

    async with SessionFactory() as db:
        ticket = await _create_ticket(
            db,
            requester,
            subject="Account sync issue",
            assigned_admin_id=admin.id,
        )
        db.add(
            SupportTicketDiagnostic(
                ticket_id=ticket.id,
                app_version="9.9.9-canary",
                build_number="123456-canary",
                platform="ios",
                os_version="iOS 99.9-canary-build",
                runtime="native",
                notification_permission="granted",
                push_registration_state="registered",
                api_connectivity="connected",
                network_state="wifi",
                background_refresh_state="available",
                client_timestamp=datetime.now(UTC),
            )
        )
        db.add(
            SupportTicketAttachment(
                ticket_id=ticket.id,
                storage_key="a1b2c3d4e5f6-storage-key-never-emailed",
                original_filename="private-screenshot-do-not-leak.png",
                content_type="image/png",
                size_bytes=12345,
                uploaded_by_user_id=requester.id,
            )
        )
        await db.commit()

        message = SupportTicketMessage(
            ticket_id=ticket.id, author_admin_id=admin.id, message="Reply body content."
        )
        db.add(message)
        await db.flush()

        ticket.status = SupportTicketStatus.resolved
        await db.flush()

        follow_up_message = SupportTicketMessage(
            ticket_id=ticket.id, author_user_id=requester.id, message="Requester follow-up content."
        )
        db.add(follow_up_message)
        await db.flush()

        await ticket_received(db, settings, ticket, requester)
        await ticket_reply(db, settings, ticket, requester, message.message, message.id)
        await ticket_follow_up(
            db, settings, ticket, follow_up_message.message, follow_up_message.id
        )
        await ticket_resolved(db, settings, ticket, requester, "privacy-resolution")
        await db.commit()

    payloads = [p for p in await _all_support_outbox_payloads() if ticket.reference in p["body"]]
    # requester received + team received + requester reply + team follow_up + requester resolved
    assert len(payloads) == 5
    assert {p["notification_type"] for p in payloads} == {
        "support.ticket.received",
        "support.ticket.reply",
        "support.ticket.follow_up",
        "support.ticket.resolved",
    }

    forbidden = [
        "9.9.9-canary",
        "123456-canary",
        "iOS 99.9-canary-build",
        "a1b2c3d4e5f6-storage-key-never-emailed",
        "private-screenshot-do-not-leak.png",
        str(admin.id),
        "Internal Reviewer Name",
        str(requester.id),
    ]
    for payload in payloads:
        haystack = " ".join(
            str(payload.get(field, "")) for field in ("subject", "body", "html_body")
        )
        for banned in forbidden:
            assert banned not in haystack, f"{banned!r} leaked into {payload['notification_type']}"

    # No copy was ever sent to a Home member / other user — only the
    # requester's own address and (for ticket_received) the configured
    # support-team address ever appear as a recipient.
    recipients = {p["recipient_email"] for p in payloads}
    assert recipients <= {requester.email, team_email}
    reply_and_resolved_types = ("support.ticket.reply", "support.ticket.resolved")
    reply_and_resolved = [p for p in payloads if p["notification_type"] in reply_and_resolved_types]
    assert {p["recipient_email"] for p in reply_and_resolved} == {requester.email}
