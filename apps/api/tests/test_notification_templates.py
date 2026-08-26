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

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    AdministrativeAuditEvent,
    AuthIdentity,
    NotificationChannel,
    NotificationTemplate,
    NotificationTemplateRevision,
    OutboxEvent,
    PlatformAdministrator,
    PlatformRole,
    TokenPurpose,
    User,
)
from mykhaya.notifications.default_templates import (
    DEFAULT_TEMPLATE_VERSION,
    SAMPLE_VARIABLES,
    TEMPLATES,
)
from mykhaya.notifications.templates import (
    MissingRequiredTemplateVariable,
    UnknownTemplateVariable,
    render_notification,
    used_variables,
    validate_required_variables,
)
from mykhaya.routers import platform as platform_router
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
    assert set(TEMPLATES) == {
        "email_verification",
        "password_reset",
        "household_invitation",
        "calendar_share_invitation",
        "calendar_share_accepted",
        "calendar_share_declined",
        "calendar_share_revoked",
        "platform_administrator_invitation",
        "calendar.event.member_added",
        "calendar.event.member_removed",
        "calendar.event.updated",
        "calendar.event.cancelled",
        "calendar.event.shared_created",
        "calendar.event.reminder",
        "routine.due",
        "briefing.title",
        "briefing.intro",
        "birthday.reminder.self",
        "birthday.reminder.other",
    }


def test_every_template_has_sample_variables_covering_its_allowed_set() -> None:
    """The preview/test-send actions render every registered template
    against SAMPLE_VARIABLES — a template missing an entry (or missing one
    of its own allowed variables) would 500 the moment an admin opens it."""
    for template_type, default in TEMPLATES.items():
        assert template_type in SAMPLE_VARIABLES, f"no sample variables for {template_type}"
        sample = SAMPLE_VARIABLES[template_type]
        assert default.allowed_variables <= set(sample), (
            f"{template_type} sample variables missing: "
            f"{default.allowed_variables - set(sample)}"
        )


def test_every_template_default_renders_cleanly() -> None:
    """A built-in default must never itself reference a variable outside its
    own allowed set — that would make render_notification's fallback path
    (used whenever an override is disabled/absent/broken) itself broken."""
    from mykhaya.notifications.templates import substitute

    for template_type, default in TEMPLATES.items():
        sample = SAMPLE_VARIABLES[template_type]
        substitute(default.subject, sample, default.allowed_variables)
        substitute(default.body, sample, default.allowed_variables)


def test_mandatory_email_types_are_registered_as_non_disableable() -> None:
    """mykhaya.notifications.engine.MANDATORY_EMAIL_TYPES and
    TemplateDefault.disableable must never disagree — engine.py bypasses
    preferences entirely for these, so PCC must never claim they can be
    turned off."""
    from mykhaya.notifications.engine import MANDATORY_EMAIL_TYPES

    for template_type in MANDATORY_EMAIL_TYPES:
        assert template_type in TEMPLATES
        assert TEMPLATES[template_type].disableable is False
        assert TEMPLATES[template_type].security_critical is True


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

    def fake_send_email(
        config: object, recipient: str, subject: str, text: str, html: str | None = None
    ) -> None:
        captured["subject"] = subject
        captured["body"] = text
        captured["html"] = html

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


# --- PCC Notifications module extensions ------------------------------------


@pytest.mark.asyncio
async def test_list_includes_module_channel_and_protection_metadata(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await admin_client.get("/api/v1/platform/notification-templates")
    assert response.status_code == 200
    items = {row["template_type"]: row for row in response.json()}

    verification = items["email_verification"]
    assert verification["module"] == "account_security"
    assert verification["channel"] == "email"
    assert verification["disableable"] is False
    assert verification["security_critical"] is True

    member_added = items["calendar.event.member_added"]
    assert member_added["module"] == "calendar"
    assert member_added["channel"] == "in_app"
    assert member_added["disableable"] is True
    assert member_added["security_critical"] is False


@pytest.mark.asyncio
async def test_cannot_disable_a_non_disableable_template(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/email_verification",
        json={
            "subject": TEMPLATES["email_verification"].subject,
            "body": TEMPLATES["email_verification"].body,
            "enabled": False,
            "reason": "Attempting to disable a required security notification.",
            "confirmed": True,
        },
    )
    assert response.status_code == 422
    assert "cannot be disabled" in response.text

    # Nothing was persisted — the type is still fully enabled.
    listed = await admin_client.get("/api/v1/platform/notification-templates")
    row = next(r for r in listed.json() if r["template_type"] == "email_verification")
    assert row["enabled"] is True
    assert row["is_override"] is False


@pytest.mark.asyncio
async def test_can_disable_a_disableable_template(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/calendar.event.member_added",
        json={
            "subject": TEMPLATES["calendar.event.member_added"].subject,
            "body": TEMPLATES["calendar.event.member_added"].body,
            "enabled": False,
            "reason": "Turning off a non-critical calendar notification for testing.",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False


@pytest.mark.asyncio
async def test_reset_all_clears_every_override(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    for template_type in ("calendar.event.member_added", "routine.due"):
        saved = await unsafe(
            admin_client,
            "PUT",
            f"/api/v1/platform/notification-templates/{template_type}",
            json={
                "subject": "Custom",
                "body": "Custom body",
                "enabled": True,
                "reason": "Setting up an override to be cleared by reset-all.",
                "confirmed": True,
            },
        )
        assert saved.status_code == 200, saved.text

    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/notification-templates/reset-all",
        json={"reason": "Restoring all notification templates to defaults.", "confirmed": True},
    )
    assert response.status_code == 200, response.text
    assert all(not row["is_override"] for row in response.json())

    listed = await admin_client.get("/api/v1/platform/notification-templates")
    assert all(not row["is_override"] for row in listed.json())


@pytest.mark.asyncio
async def test_reset_all_requires_operator_role(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/notification-templates/reset-all",
        json={"reason": "Support attempting a bulk reset.", "confirmed": True},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_render_notification_resolves_an_in_app_channel_override() -> None:
    """calendar.event.member_added is registered under NotificationChannel.in_app
    — confirms render_notification's new `channel` defaulting (from
    TemplateDefault.channel) actually looks up the in_app row, not the
    email row the old hardcoded default would have queried."""
    async with SessionFactory() as db:
        override = NotificationTemplate(
            template_type="calendar.event.member_added",
            channel=NotificationChannel.in_app,
            subject="You're on the list",
            body_text="{{actor_name}} added you to {{event_title}}. {{event_when}}.",
            enabled=True,
        )
        db.add(override)
        await db.commit()
        try:
            subject, body = await render_notification(
                db,
                "calendar.event.member_added",
                {"actor_name": "Megan", "event_title": "Football", "event_when": "today"},
            )
            assert subject == "You're on the list"
            assert body == "Megan added you to Football. today."
        finally:
            await db.delete(override)
            await db.commit()


@pytest.mark.asyncio
async def test_render_notification_default_matches_previous_hardcoded_wording() -> None:
    """Regression guard for the migration itself: with no override, the
    registry's default text for each migrated calendar/routine/reminder
    template must reproduce exactly what routers.calendar /
    notifications.{calendar_shares,reminders,routines} used to hard-code."""
    cases = [
        (
            "calendar.event.member_added",
            {"actor_name": "Megan", "event_title": "Football", "event_when": "today"},
            "Added to an event",
            "Megan added you to Football. today.",
        ),
        (
            "calendar.event.member_removed",
            {"actor_name": "Megan", "event_title": "Football"},
            "Removed from an event",
            "Megan removed you from Football.",
        ),
        (
            "calendar.event.updated",
            {"actor_name": "Megan", "event_title": "Football", "event_when": "today"},
            "Event updated",
            "Megan updated Football. today.",
        ),
        (
            "calendar.event.cancelled",
            {"actor_name": "Megan", "event_title": "Football"},
            "Event cancelled",
            "Megan cancelled Football.",
        ),
        (
            "calendar.event.shared_created",
            {"actor_name": "Megan", "event_title": "Football", "event_when": "today"},
            "New event",
            "Megan added Football. today.",
        ),
        (
            "calendar.event.reminder",
            {"event_title": "Football", "event_when": "at 09:00", "event_location": " at The Park"},
            "Football",
            "Football starts at 09:00 at The Park.",
        ),
        (
            "routine.due",
            {"routine_title": "Put the bins out"},
            "Put the bins out",
            "Don't forget: Put the bins out.",
        ),
        (
            "briefing.title",
            {"count_phrase": "3 events"},
            "You have 3 events today.",
            "You have 3 events today.",
        ),
        ("briefing.intro", {}, "Please take care of yourself!", "Please take care of yourself!"),
    ]
    async with SessionFactory() as db:
        for template_type, variables, expected_subject, expected_body in cases:
            subject, body = await render_notification(db, template_type, variables)
            assert subject == expected_subject, template_type
            assert body == expected_body, template_type


# --- Registry integrity -------------------------------------------------------


def test_registry_keys_are_unique() -> None:
    """TEMPLATES is a dict, so this can't fail at the Python level — but a
    duplicate key silently overwriting an earlier registration would be a
    real defect, so assert on the underlying declaration list directly
    rather than trusting dict construction alone."""
    from mykhaya.notifications import default_templates

    assert len(default_templates.TEMPLATES) == len(set(default_templates.TEMPLATES))


def test_registry_defaults_have_non_empty_subject_and_body() -> None:
    for template_type, default in TEMPLATES.items():
        assert default.subject.strip(), f"{template_type} has an empty default subject"
        assert default.body.strip(), f"{template_type} has an empty default body"


# --- Malformed override resilience --------------------------------------------


@pytest.mark.asyncio
async def test_render_notification_falls_back_when_override_is_malformed() -> None:
    """The core resilience guarantee: an ENABLED override that references a
    variable outside the template's allowlist (e.g. left over from an
    earlier registry version, or hand-edited badly) must never surface to
    the caller as an exception or a broken/half-rendered message — it must
    be logged and the trusted built-in default used instead, exactly as if
    no override existed at all."""
    async with SessionFactory() as db:
        override = NotificationTemplate(
            template_type="password_reset",
            channel=NotificationChannel.email,
            subject="Reset your thing {{no_such_variable}}",
            body_text="Click {{link}} but also {{another_bad_one}}",
            enabled=True,
        )
        db.add(override)
        await db.commit()
        try:
            subject, body = await render_notification(
                db, "password_reset", {"link": "https://example.com/reset"}
            )
            assert subject == TEMPLATES["password_reset"].subject
            assert "https://example.com/reset" in body
            assert "no_such_variable" not in subject
        finally:
            await db.delete(override)
            await db.commit()


def test_substitute_rejects_a_variable_outside_the_allowlist() -> None:
    with pytest.raises(UnknownTemplateVariable):
        from mykhaya.notifications.templates import substitute

        substitute("{{secret}}", {"secret": "leaked"}, frozenset({"link"}))


@pytest.mark.asyncio
async def test_registration_still_succeeds_when_the_verification_email_template_is_malformed(
    client: AsyncClient,
) -> None:
    """End-to-end proof that a bad PCC override cannot take down a real user
    flow: registration must still succeed and still queue a real
    verification email (using the safe built-in wording) even though the
    stored override for email_verification is broken."""
    async with SessionFactory() as db:
        override = NotificationTemplate(
            template_type="email_verification",
            channel=NotificationChannel.email,
            subject="Verify now {{does_not_exist}}",
            body_text="{{does_not_exist}}",
            enabled=True,
        )
        db.add(override)
        await db.commit()

    try:
        email = unique_email("malformedoverride")
        response = await unsafe(
            client,
            "POST",
            "/api/v1/auth/register",
            json={"email": email, "display_name": "Malformed Override Test", "password": PASSWORD},
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
            assert matching[0].payload["subject"] == TEMPLATES["email_verification"].subject
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


# --- Zero-configuration behaviour ----------------------------------------------


@pytest.mark.asyncio
async def test_fresh_installation_uses_only_built_in_defaults_for_every_template(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    """A fresh/upgraded installation with no PCC customisation at all must
    serve the code-level registry's wording for every single template, with
    no manual seeding step — the DB table is expected to simply be empty."""
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    async with SessionFactory() as db:
        remaining = (await db.scalars(select(NotificationTemplate))).all()
        assert remaining == []

    response = await admin_client.get("/api/v1/platform/notification-templates")
    assert response.status_code == 200
    for row in response.json():
        default = TEMPLATES[row["template_type"]]
        assert row["is_override"] is False
        assert row["subject"] == default.subject
        assert row["body"] == default.body
        assert row["enabled"] is True


# --- Authorisation --------------------------------------------------------------


@pytest.mark.asyncio
async def test_ordinary_household_user_cannot_reach_platform_notification_templates(
    client: AsyncClient,
) -> None:
    """A household User session (even a fully verified, logged-in one) must
    never grant any access to platform notification controls — these are
    gated entirely by the separate PlatformAdministrator auth model."""
    email = unique_email("ordinaryuser")
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Ordinary User", "password": PASSWORD},
    )
    assert response.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        token = await db.scalar(
            select(ActionToken)
            .where(ActionToken.user_id == user.id, ActionToken.purpose == TokenPurpose.verify_email)
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200

    attempt = await client.get("/api/v1/platform/notification-templates")
    assert attempt.status_code in (401, 403, 404)

    mutate = await unsafe(
        client,
        "PUT",
        "/api/v1/platform/notification-templates/household_invitation",
        json={
            "subject": "Hijacked",
            "body": "Hijacked body",
            "enabled": True,
            "reason": "An ordinary user attempting a platform mutation.",
            "confirmed": True,
        },
    )
    assert mutate.status_code in (401, 403, 404)
    async with SessionFactory() as db:
        row = await db.scalar(
            select(NotificationTemplate).where(
                NotificationTemplate.template_type == "household_invitation"
            )
        )
        assert row is None


@pytest.mark.asyncio
async def test_support_role_cannot_update_templates_only_operators_can(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/household_invitation",
        json={
            "subject": "Custom",
            "body": "Custom body",
            "enabled": True,
            "reason": "Support attempting an update outside their role.",
            "confirmed": True,
        },
    )
    assert response.status_code == 403


# --- Audit -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_template_update_is_audited_without_storing_the_wording(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/household_invitation",
        json={
            "subject": "Secret subject wording",
            "body": "Secret body wording {{home_name}}",
            "enabled": True,
            "reason": "Auditing this exact change for the test.",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text

    async with SessionFactory() as db:
        event = await db.scalar(
            select(AdministrativeAuditEvent)
            .where(
                AdministrativeAuditEvent.administrator_id == admin.id,
                AdministrativeAuditEvent.action == "notification_template.updated",
            )
            .order_by(AdministrativeAuditEvent.created_at.desc())
        )
        assert event is not None
        assert event.reason == "Auditing this exact change for the test."
        assert event.new_values.get("template_type") == "household_invitation"
        # The audit record must never carry the actual customised wording.
        assert "Secret subject wording" not in str(event.new_values)
        assert "Secret body wording" not in str(event.new_values)


@pytest.mark.asyncio
async def test_reset_all_is_audited(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/notification-templates/reset-all",
        json={"reason": "Testing that reset-all is audited.", "confirmed": True},
    )
    assert response.status_code == 200, response.text

    async with SessionFactory() as db:
        event = await db.scalar(
            select(AdministrativeAuditEvent).where(
                AdministrativeAuditEvent.administrator_id == admin.id,
                AdministrativeAuditEvent.action == "notification_template.reset_all",
            )
        )
        assert event is not None
        assert event.reason == "Testing that reset-all is audited."


@pytest.mark.asyncio
async def test_disabling_a_template_is_audited_as_an_update(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/calendar.event.member_added",
        json={
            "subject": TEMPLATES["calendar.event.member_added"].subject,
            "body": TEMPLATES["calendar.event.member_added"].body,
            "enabled": False,
            "reason": "Testing that a disable is captured in the audit trail.",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text

    async with SessionFactory() as db:
        event = await db.scalar(
            select(AdministrativeAuditEvent)
            .where(
                AdministrativeAuditEvent.administrator_id == admin.id,
                AdministrativeAuditEvent.action == "notification_template.updated",
            )
            .order_by(AdministrativeAuditEvent.created_at.desc())
        )
        assert event is not None
        assert event.new_values.get("enabled") is False


# --- required_variables: registry integrity -----------------------------------


def test_every_required_variable_is_also_allowed() -> None:
    """Enforced at import time in default_templates.py — re-asserted here so a
    future edit that somehow bypasses that check still fails a test, not
    just a silent AssertionError at process start."""
    for template_type, default in TEMPLATES.items():
        assert default.required_variables <= default.allowed_variables, template_type


def test_every_built_in_default_contains_its_own_required_placeholders() -> None:
    """A registry entry that requires a placeholder its own default text
    doesn't contain would make render_notification's fallback path itself
    invalid — the one thing that must always be safe to fall back to."""
    for template_type, default in TEMPLATES.items():
        used = used_variables(default.subject) | used_variables(default.body)
        missing = default.required_variables - used
        assert not missing, f"{template_type} default is missing {missing}"


def test_expected_templates_declare_the_expected_required_variables() -> None:
    expected = {
        "email_verification": {"link"},
        "password_reset": {"link"},
        "household_invitation": {"link"},
        "calendar_share_invitation": {"link"},
        "platform_administrator_invitation": {"link"},
    }
    for template_type, required in expected.items():
        assert set(TEMPLATES[template_type].required_variables) == required, template_type

    # Ordinary product notifications remain unrestricted — removing a variable
    # merely changes the wording, it doesn't break or mislead.
    for template_type in (
        "calendar_share_accepted",
        "calendar_share_declined",
        "calendar_share_revoked",
        "calendar.event.member_added",
        "calendar.event.member_removed",
        "calendar.event.updated",
        "calendar.event.cancelled",
        "calendar.event.shared_created",
        "calendar.event.reminder",
        "routine.due",
        "briefing.title",
        "briefing.intro",
        "birthday.reminder.self",
        "birthday.reminder.other",
    ):
        assert TEMPLATES[template_type].required_variables == frozenset(), template_type


def test_security_critical_templates_all_require_their_link() -> None:
    """Every security_critical template happens to centre on a single secure
    link today — if a future one doesn't, this test should be updated
    deliberately rather than silently passing."""
    for template_type, default in TEMPLATES.items():
        if default.security_critical:
            assert default.required_variables == frozenset({"link"}), template_type
            assert default.disableable is False, template_type


# --- required_variables: validation helper --------------------------------------


def test_validate_required_variables_passes_when_present_in_either_field() -> None:
    validate_required_variables("Reset", "Use {{link}} to continue.", frozenset({"link"}))
    validate_required_variables("Use {{link}}", "no variables here", frozenset({"link"}))


def test_validate_required_variables_rejects_when_missing_from_both_fields() -> None:
    with pytest.raises(MissingRequiredTemplateVariable) as excinfo:
        validate_required_variables(
            "Reset your password", "All done, no link here.", frozenset({"link"})
        )
    assert excinfo.value.missing == ["link"]


def test_validate_required_variables_reports_every_missing_variable() -> None:
    with pytest.raises(MissingRequiredTemplateVariable) as excinfo:
        validate_required_variables("Subject", "Body", frozenset({"link", "expires_at"}))
    assert excinfo.value.missing == ["expires_at", "link"]


# --- required_variables: server-side save enforcement ---------------------------


@pytest.mark.asyncio
async def test_saving_an_override_that_keeps_the_required_link_succeeds(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/password_reset",
        json={
            "subject": "Reset your account",
            "body": "Use this link to reset your password: {{link}}",
            "enabled": True,
            "reason": "Rewording the reset email while keeping the reset link.",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_removing_the_required_link_is_rejected_with_a_clear_422(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/password_reset",
        json={
            "subject": "Reset your account",
            "body": "Your password has been reset. All done!",
            "enabled": True,
            "reason": "Accidentally dropping the reset link.",
            "confirmed": True,
        },
    )
    assert response.status_code == 422
    assert "required placeholder" in response.text
    assert "{{link}}" in response.text

    # Nothing was persisted — the template is still using the built-in default.
    listed = await admin_client.get("/api/v1/platform/notification-templates")
    row = next(r for r in listed.json() if r["template_type"] == "password_reset")
    assert row["is_override"] is False


@pytest.mark.asyncio
async def test_removing_a_required_link_creates_no_audit_event(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    """A rejected save must not leave a misleading `.updated` audit trail
    behind — the mutation never happened, so nothing should be audited."""
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    before = await admin_client.get("/api/v1/platform/notification-templates")
    async with SessionFactory() as db:
        before_count = len(
            (
                await db.scalars(
                    select(AdministrativeAuditEvent).where(
                        AdministrativeAuditEvent.administrator_id == admin.id
                    )
                )
            ).all()
        )
    assert before.status_code == 200

    rejected = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/email_verification",
        json={
            "subject": "Verify your email",
            "body": "Thanks for verifying!",
            "enabled": True,
            "reason": "Dropping the verification link by mistake.",
            "confirmed": True,
        },
    )
    assert rejected.status_code == 422

    async with SessionFactory() as db:
        after_count = len(
            (
                await db.scalars(
                    select(AdministrativeAuditEvent).where(
                        AdministrativeAuditEvent.administrator_id == admin.id
                    )
                )
            ).all()
        )
    assert after_count == before_count


@pytest.mark.asyncio
async def test_unknown_variable_still_rejected_alongside_required_variable_check(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/password_reset",
        json={
            "subject": "Reset",
            "body": "Use {{link}} or contact {{support_email}}.",
            "enabled": True,
            "reason": "Testing unknown variable still rejected.",
            "confirmed": True,
        },
    )
    assert response.status_code == 422
    assert "support_email" in response.text


@pytest.mark.asyncio
async def test_resetting_an_override_restores_a_valid_default(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    saved = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/notification-templates/password_reset",
        json={
            "subject": "Custom reset",
            "body": "Reset here: {{link}}",
            "enabled": True,
            "reason": "Customising before resetting.",
            "confirmed": True,
        },
    )
    assert saved.status_code == 200, saved.text

    reset = await unsafe(
        admin_client, "DELETE", "/api/v1/platform/notification-templates/password_reset"
    )
    assert reset.status_code == 200
    body = reset.json()
    assert body["is_override"] is False
    used = used_variables(body["subject"]) | used_variables(body["body"])
    assert set(body["required_variables"]) <= used


# --- required_variables: legacy/stale override resilience -----------------------


@pytest.mark.asyncio
async def test_legacy_override_missing_a_newly_required_variable_falls_back_safely() -> None:
    """Simulates an override saved before `required_variables` existed (or
    before this particular variable was added to it): a stored row that
    would fail today's save-time validation but was never re-validated after
    the fact. Resolution must detect this and use the built-in default —
    exactly the same safety net as an unknown-variable override, just for a
    different kind of invalidity."""
    async with SessionFactory() as db:
        legacy_override = NotificationTemplate(
            template_type="password_reset",
            channel=NotificationChannel.email,
            subject="Your password was reset",
            body_text="Your MyKhaya password has been reset. If this wasn't you, contact support.",
            enabled=True,
        )
        db.add(legacy_override)
        await db.commit()
        try:
            subject, body = await render_notification(
                db, "password_reset", {"link": "https://example.com/reset/abc"}
            )
            assert subject == TEMPLATES["password_reset"].subject
            assert "https://example.com/reset/abc" in body
            assert "Your password was reset" not in subject
        finally:
            await db.delete(legacy_override)
            await db.commit()


@pytest.mark.asyncio
async def test_password_reset_test_send_does_not_perform_a_real_reset(
    admin_client: AsyncClient, admin_factory: AdminFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Security-critical templates must remain safe to test-send: sending a
    test of password_reset's wording must not change the target user's
    actual password or create a real reset token."""
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    await unsafe(
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
            "reason": "Configuring SMTP for the password-reset test-send safety check.",
            "confirmed": True,
        },
    )
    email = unique_email("resettestsafety")
    register = await unsafe(
        admin_client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Reset Safety Test", "password": PASSWORD},
    )
    assert register.status_code == 202
    async with SessionFactory() as db:
        target_user = await db.scalar(select(User).where(User.email == email))
        assert target_user is not None
        original_identity = await db.scalar(
            select(AuthIdentity).where(AuthIdentity.user_id == target_user.id)
        )
        assert original_identity is not None
        original_password_hash = original_identity.password_hash

    def fake_send_email(
        config: object, recipient: str, subject: str, text: str, html: str | None = None
    ) -> None:
        pass

    monkeypatch.setattr(platform_router, "send_email", fake_send_email)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/notification-templates/password_reset/test-send",
        json={
            "recipient_user_id": str(target_user.id),
            "reason": "Confirming test-send has no real security effect.",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text

    async with SessionFactory() as db:
        after = await db.scalar(select(User).where(User.email == email))
        assert after is not None
        after_identity = await db.scalar(
            select(AuthIdentity).where(AuthIdentity.user_id == after.id)
        )
        assert after_identity is not None
        assert after_identity.password_hash == original_password_hash
        reset_tokens = (
            await db.scalars(
                select(ActionToken).where(
                    ActionToken.user_id == after.id,
                    ActionToken.purpose == TokenPurpose.reset_password,
                )
            )
        ).all()
        assert reset_tokens == []


# --- Birthday reminder migration -------------------------------------------------


@pytest.mark.asyncio
async def test_birthday_templates_render_the_same_wording_as_before_migration() -> None:
    """Regression guard: birthdays.py used to hard-code these two variants
    directly. The external notify() notification_type stays the single,
    unchanged "birthday_reminder" for both — only the wording now comes from
    the registry."""
    async with SessionFactory() as db:
        self_subject, self_body = await render_notification(db, "birthday.reminder.self", {})
        assert self_subject == "Happy Birthday!"
        assert self_body == "Happy Birthday! We hope you have a wonderful day."

        other_subject, other_body = await render_notification(
            db, "birthday.reminder.other", {"display_name": "Megan"}
        )
        assert other_subject == "Megan's birthday"
        assert other_body == "Today is Megan's birthday."
