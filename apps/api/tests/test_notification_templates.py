"""Tests for Stage 9: Platform Admin notification templates. Override-only storage —
mykhaya/notifications/default_templates.py remains the source of truth; a DB row exists
only once an admin has actually customised a template, and deleting it resets to the
built-in default rather than the frontend/backend ever copying defaults into the
database. See docs/architecture/notification-engine.md.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    NotificationChannel,
    NotificationTemplate,
    NotificationTemplateRevision,
    OutboxEvent,
    PlatformAdministrator,
    PlatformRole,
)
from mykhaya.notifications.default_templates import DEFAULT_TEMPLATE_VERSION, TEMPLATES
from mykhaya.notifications.templates import render_notification
from mykhaya.routers import platform as platform_router
from mykhaya.security import password_hash

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
        transport=ASGITransport(app=app, client=("127.0.0.1", 44220)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    ) as value:
        yield value


@pytest.fixture
async def admin_factory() -> AsyncIterator[AdminFactory]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        suffix = datetime.now(UTC).strftime("%H%M%S%f")
        async with SessionFactory() as db:
            row = PlatformAdministrator(
                email=f"template-operator-{suffix}@example.com",
                display_name="Test Operator",
                password_hash=password_hash.hash(ADMIN_PASSWORD),
                role=role,
                mfa_enrolled=True,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            identifiers.append(row.id)
            return row

    yield factory
    if identifiers:
        async with SessionFactory() as db:
            await db.execute(
                delete(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id.in_(identifiers)
                )
            )
            await db.execute(
                delete(PlatformAdministrator).where(PlatformAdministrator.id.in_(identifiers))
            )
            await db.commit()


async def admin_login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_admin_csrf") or client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


@pytest.fixture(autouse=True)
async def clean_template_overrides() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        overrides = (
            await db.scalars(
                select(NotificationTemplate).where(
                    NotificationTemplate.template_type.in_(TEMPLATES.keys())
                )
            )
        ).all()
        for override in overrides:
            await db.execute(
                delete(NotificationTemplateRevision).where(
                    NotificationTemplateRevision.template_id == override.id
                )
            )
            await db.delete(override)
        await db.commit()


def test_registry_matches_migration_version() -> None:
    assert DEFAULT_TEMPLATE_VERSION >= 1
    assert set(TEMPLATES) == {"email_verification", "password_reset", "household_invitation"}


@pytest.mark.asyncio
async def test_list_templates_shows_defaults_with_no_overrides(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await admin_client.get("/api/v1/platform/notification-templates")
    assert response.status_code == 200
    items = {row["template_type"]: row for row in response.json()}
    assert set(items) == set(TEMPLATES)
    invitation = items["household_invitation"]
    assert invitation["is_override"] is False
    assert invitation["subject"] == TEMPLATES["household_invitation"].subject
    assert invitation["is_stale"] is False


@pytest.mark.asyncio
async def test_unknown_template_type_404s(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await admin_client.get("/api/v1/platform/notification-templates/not-a-template")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_save_override_rejects_unknown_variable(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/household_invitation",
        json={
            "subject": "Join {{home_name}}",
            "body": "Click {{secret_admin_token}} to join.",
            "enabled": True,
            "reason": "Testing invalid variable rejection.",
            "confirmed": True,
        },
    )
    assert response.status_code == 422
    assert "secret_admin_token" in response.text


@pytest.mark.asyncio
async def test_save_and_reset_override_round_trips(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)

    saved = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/household_invitation",
        json={
            "subject": "Come join {{home_name}}!",
            "body": "{{inviter_display_name}} wants you in {{home_name}}. Link: {{link}}",
            "enabled": True,
            "reason": "Customising the invitation wording for our tone of voice.",
            "confirmed": True,
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["is_override"] is True
    assert body["subject"] == "Come join {{home_name}}!"
    assert body["is_stale"] is False

    listed = await admin_client.get("/api/v1/platform/notification-templates")
    invitation = next(
        row for row in listed.json() if row["template_type"] == "household_invitation"
    )
    assert invitation["is_override"] is True

    reset = await unsafe(
        admin_client, "DELETE", "/api/v1/platform/notification-templates/household_invitation"
    )
    assert reset.status_code == 200
    assert reset.json()["is_override"] is False
    assert reset.json()["subject"] == TEMPLATES["household_invitation"].subject


@pytest.mark.asyncio
async def test_second_save_creates_a_revision_of_the_first(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)

    first = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/household_invitation",
        json={
            "subject": "First version",
            "body": "Join {{home_name}} via {{link}}.",
            "enabled": True,
            "reason": "First customisation.",
            "confirmed": True,
        },
    )
    assert first.status_code == 200

    second = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/household_invitation",
        json={
            "subject": "Second version",
            "body": "Join {{home_name}} via {{link}}.",
            "enabled": True,
            "reason": "Refining the wording again.",
            "confirmed": True,
        },
    )
    assert second.status_code == 200

    async with SessionFactory() as db:
        override = await db.scalar(
            select(NotificationTemplate).where(
                NotificationTemplate.template_type == "household_invitation"
            )
        )
        assert override is not None
        revisions = (
            await db.scalars(
                select(NotificationTemplateRevision).where(
                    NotificationTemplateRevision.template_id == override.id
                )
            )
        ).all()
        assert len(revisions) == 1
        assert revisions[0].subject == "First version"


@pytest.mark.asyncio
async def test_preview_renders_with_sample_variables(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/notification-templates/household_invitation/preview",
        json={"subject": "Join {{home_name}}", "body": "From {{inviter_display_name}}: {{link}}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["subject"] == "Join The Example Family"
    assert "Jamie Example" in body["body"]


@pytest.mark.asyncio
async def test_preview_rejects_unknown_variable(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/notification-templates/password_reset/preview",
        json={"subject": "Reset", "body": "{{not_a_real_variable}}"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_test_send_uses_saved_override(
    admin_client: AsyncClient, admin_factory: AdminFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    smtp_configured = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/mail/smtp-settings",
        json={
            "enabled": True,
            "host": "smtp.example.com",
            "port": 587,
            "connection_security": "starttls",
            "auth_enabled": True,
            "username": "mailer",
            "password": "correct horse battery staple",
            "sender_name": "MyKhaya",
            "sender_email": "hello@mykhaya.example",
            "reply_to": None,
            "timeout_seconds": 10,
            "reason": "Configuring SMTP for the template test-send check.",
            "confirmed": True,
        },
    )
    assert smtp_configured.status_code == 200, smtp_configured.text
    await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/password_reset",
        json={
            "subject": "Custom reset subject",
            "body": "Custom reset body: {{link}}",
            "enabled": True,
            "reason": "Customising the reset email wording.",
            "confirmed": True,
        },
    )

    captured: dict[str, object] = {}

    def fake_send_email(config: object, recipient: str, subject: str, text: str) -> None:
        captured["subject"] = subject
        captured["body"] = text

    monkeypatch.setattr(platform_router, "send_email", fake_send_email)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/notification-templates/password_reset/test",
        json={
            "recipient": admin.email,
            "reason": "Confirming the override is actually used for real sends.",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    assert captured["subject"] == "Custom reset subject"
    assert "Custom reset body" in str(captured["body"])


@pytest.mark.asyncio
async def test_render_notification_falls_back_when_override_disabled() -> None:
    async with SessionFactory() as db:
        override = NotificationTemplate(
            template_type="password_reset",
            channel=NotificationChannel.email,
            subject="Disabled override subject",
            body_text="Disabled override body {{link}}",
            enabled=False,
        )
        db.add(override)
        await db.commit()
        try:
            subject, body = await render_notification(
                db, "password_reset", {"link": "https://example.com/x"}
            )
            assert subject == TEMPLATES["password_reset"].subject
            assert "Disabled override" not in body
        finally:
            await db.delete(override)
            await db.commit()


@pytest.mark.asyncio
async def test_registration_email_uses_saved_override(client: AsyncClient) -> None:
    """End-to-end proof that an admin override actually changes what a real user
    receives — not just what the preview shows."""
    async with SessionFactory() as db:
        override = NotificationTemplate(
            template_type="email_verification",
            channel=NotificationChannel.email,
            subject="Custom verify subject",
            body_text="Custom verify body: {{link}}",
            enabled=True,
        )
        db.add(override)
        await db.commit()

    try:
        email = unique_email("overridetest")
        response = await unsafe(
            client,
            "POST",
            "/api/v1/auth/register",
            json={"email": email, "display_name": "Override Test", "password": PASSWORD},
        )
        assert response.status_code == 202

        async with SessionFactory() as db:
            rows = (
                await db.scalars(
                    select(OutboxEvent).where(OutboxEvent.topic == "notification.email")
                )
            ).all()
            matching = [row for row in rows if row.payload.get("recipient_email") == email]
            assert len(matching) == 1
            assert matching[0].payload["subject"] == "Custom verify subject"
            assert "Custom verify body" in matching[0].payload["body"]
    finally:
        async with SessionFactory() as db:
            row = await db.scalar(
                select(NotificationTemplate).where(
                    NotificationTemplate.template_type == "email_verification"
                )
            )
            if row is not None:
                await db.delete(row)
                await db.commit()


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/platform/notification-templates")
    assert response.status_code in (401, 403, 404)
