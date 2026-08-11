"""Tests for Stage 8: email as a real notify() channel. Every outbound email — account
verification, password reset, household invitations, and any future optional
notification type — now goes through mykhaya.notifications.engine.notify() and is
delivered by exactly one worker handler (notification.email), never a module calling
mykhaya.mailer.send_email directly. See docs/architecture/notification-engine.md.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationPreferences,
    OutboxEvent,
    PlatformAdministrator,
    PlatformRole,
    TokenPurpose,
    User,
    WorkerJobRecord,
)
from mykhaya.notifications.engine import MANDATORY_EMAIL_TYPES, notify
from mykhaya.security import derived_token, password_hash

ORIGIN = "http://localhost:8080"
ADMIN_ORIGIN = "http://admin.localhost:8080"
PASSWORD = "Correct horse battery staple!"
ADMIN_PASSWORD = "A separate operator password!"
AdminFactory = Callable[[PlatformRole], Awaitable[PlatformAdministrator]]


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44210)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    ) as value:
        yield value


@pytest.fixture
async def admin_factory() -> AsyncIterator[AdminFactory]:
    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        suffix = datetime.now(UTC).strftime("%H%M%S%f")
        async with SessionFactory() as db:
            row = PlatformAdministrator(
                email=f"email-operator-{suffix}@example.com",
                display_name="Test Operator",
                password_hash=password_hash.hash(ADMIN_PASSWORD),
                role=role,
                mfa_enrolled=True,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row

    yield factory


async def admin_login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf") or client.cookies.get("mk_admin_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


async def email_outbox_rows(recipient_email: str) -> list[OutboxEvent]:
    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(OutboxEvent).where(OutboxEvent.topic == "notification.email")
            )
        ).all()
        return [row for row in rows if row.payload.get("recipient_email") == recipient_email]


def test_mandatory_email_types_are_registered() -> None:
    assert {"email_verification", "password_reset", "household_invitation"} == (
        MANDATORY_EMAIL_TYPES
    )


@pytest.mark.asyncio
async def test_register_enqueues_verification_email_via_notify(client: AsyncClient) -> None:
    email = unique_email("verify")
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Verify Me", "password": PASSWORD},
    )
    assert response.status_code == 202

    rows = await email_outbox_rows(email)
    assert len(rows) == 1
    assert rows[0].payload["subject"] == "Verify your MyKhaya email"
    assert "/verify-email?token=" in rows[0].payload["body"]

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        delivery = await db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.recipient_user_id == user.id,
                NotificationDelivery.notification_type == "email_verification",
            )
        )
        assert delivery is not None
        assert delivery.channel.value == "email"


@pytest.mark.asyncio
async def test_verification_email_bypasses_email_enabled_preference(client: AsyncClient) -> None:
    """Mandatory system email must never be suppressed by an (impossible at this point,
    but defensively tested) disabled email preference."""
    email = unique_email("mandatory")
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Mandatory Test", "password": PASSWORD},
    )
    assert response.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        prefs = await db.scalar(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user.id)
        )
        assert prefs is not None
        assert prefs.email_enabled is False  # confirms the opt-in default didn't leak through
    rows = await email_outbox_rows(email)
    assert len(rows) == 1  # sent anyway, despite email_enabled defaulting False


@pytest.mark.asyncio
async def test_forgot_password_enqueues_reset_email(client: AsyncClient) -> None:
    email = unique_email("forgot")
    await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Forgot Owner", "password": PASSWORD},
    )
    async with SessionFactory() as db:
        token = await db.scalar(
            select(ActionToken)
            .join(User, User.id == ActionToken.user_id)
            .where(User.email == email, ActionToken.purpose == TokenPurpose.verify_email)
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})

    response = await unsafe(
        client, "POST", "/api/v1/auth/forgot-password", json={"email": email}
    )
    assert response.status_code == 202

    all_rows = await email_outbox_rows(email)
    rows = [row for row in all_rows if row.payload.get("notification_type") == "password_reset"]
    assert len(rows) == 1
    assert rows[0].payload["subject"] == "Reset your MyKhaya password"
    assert "/reset-password?token=" in rows[0].payload["body"]


@pytest.mark.asyncio
async def test_invitation_email_sent_with_no_account(client: AsyncClient) -> None:
    """A household invitation goes to a raw email address with no User row yet —
    notify() must support this without requiring an account to attach an in-app
    notification or push subscription to."""
    owner_email = unique_email("owner")
    registered = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": owner_email, "display_name": "Home Owner", "password": PASSWORD},
    )
    assert registered.status_code == 202
    async with SessionFactory() as db:
        token = await db.scalar(
            select(ActionToken)
            .join(User, User.id == ActionToken.user_id)
            .where(User.email == owner_email, ActionToken.purpose == TokenPurpose.verify_email)
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": owner_email, "password": PASSWORD}
    )

    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Invite Test Home"})
    assert group.status_code == 201
    home_id = group.json()["id"]

    invitee_email = unique_email("invitee")
    invited = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": home_id, "email": invitee_email, "relationship": "partner"},
    )
    assert invited.status_code == 201, invited.text

    rows = await email_outbox_rows(invitee_email)
    assert len(rows) == 1
    assert rows[0].payload["subject"] == "You are invited to a MyKhaya Home"
    assert "/register?invitation=" in rows[0].payload["body"]
    assert "Home Owner invited you to join Invite Test Home" in rows[0].payload["body"]

    async with SessionFactory() as db:
        delivery = await db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.idempotency_key == rows[0].payload["delivery_idempotency_key"]
            )
        )
        assert delivery is not None
        assert delivery.recipient_user_id is None  # no account exists yet


@pytest.mark.asyncio
async def test_notify_email_only_raises_without_recipient_email(client: AsyncClient) -> None:
    settings = get_settings()
    async with SessionFactory() as db:
        with pytest.raises(ValueError):
            await notify(
                db,
                settings=settings,
                notification_type="household_invitation",
                title="x",
                body="y",
                idempotency_key="test:no-recipient",
            )


@pytest.mark.asyncio
async def test_notify_raises_for_non_mandatory_type_without_user(client: AsyncClient) -> None:
    settings = get_settings()
    async with SessionFactory() as db:
        with pytest.raises(ValueError):
            await notify(
                db,
                settings=settings,
                recipient_email="someone@example.com",
                notification_type="daily_briefing",
                title="x",
                body="y",
                idempotency_key="test:not-mandatory",
            )


@pytest.mark.asyncio
async def test_optional_notification_respects_email_enabled_toggle(client: AsyncClient) -> None:
    settings = get_settings()
    async with SessionFactory() as db:
        user = User(email=unique_email("opt"), display_name="Opt User")
        db.add(user)
        await db.commit()
        await db.refresh(user)

        await notify(
            db,
            settings=settings,
            recipient_user_id=user.id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Don't forget",
            idempotency_key=f"test:opt-default:{user.id}",
        )
        await db.commit()
        rows = await email_outbox_rows(user.email)
        assert rows == []  # email_enabled defaults False — no email sent

        prefs = await db.scalar(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user.id)
        )
        assert prefs is not None
        prefs.email_enabled = True
        await db.commit()

        await notify(
            db,
            settings=settings,
            recipient_user_id=user.id,
            notification_type="household_routine_reminder",
            title="Bins out",
            body="Don't forget",
            idempotency_key=f"test:opt-enabled:{user.id}",
        )
        await db.commit()
        rows_after = await email_outbox_rows(user.email)
        assert len(rows_after) == 1


@pytest.mark.asyncio
async def test_admin_resend_verification_routes_through_notify(
    client: AsyncClient, admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    email = unique_email("adminresend")
    await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Admin Resend Target", "password": PASSWORD},
    )
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        user_id = user.id

    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/users/{user_id}/resend-verification",
        json={"reason": "Confirming the resend path still works.", "confirmed": True},
    )
    assert response.status_code == 200, response.text

    rows = await email_outbox_rows(email)
    # One from registration, one from the admin resend — each has its own token id, so
    # its own idempotency key, so both persist as distinct sends.
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_worker_delivers_queued_email(client: AsyncClient) -> None:
    from mykhaya.worker import process

    email = unique_email("workerdeliver")
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Worker Delivered", "password": PASSWORD},
    )
    assert response.status_code == 202
    rows = await email_outbox_rows(email)
    assert len(rows) == 1
    event_id = rows[0].id

    # SMTP is unconfigured in the test environment, so delivery fails — this still
    # proves the single notification.email handler is reached and the diagnostic
    # NotificationDelivery row is updated, without needing a real mail server.
    try:
        with pytest.raises(RuntimeError):
            await process(event_id)

        async with SessionFactory() as db:
            delivery = await db.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.idempotency_key
                    == rows[0].payload["delivery_idempotency_key"]
                )
            )
            assert delivery is not None
            assert delivery.status == NotificationDeliveryStatus.failed
    finally:
        # process() deliberately leaves the OutboxEvent unprocessed (eligible for
        # retry — that's the behaviour under test), which also leaves a genuinely
        # "failed and actionable" WorkerJobRecord behind. Without this cleanup it
        # persists for the rest of the test run and is picked up by anything else
        # that checks the platform overview's actionable-failed-jobs count (e.g.
        # test_platform_control_centre.py::
        # test_historical_failed_job_does_not_degrade_current_overview), which has
        # nothing to do with this test.
        async with SessionFactory() as db:
            await db.execute(
                delete(WorkerJobRecord).where(WorkerJobRecord.outbox_event_id == event_id)
            )
            await db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
            await db.commit()
