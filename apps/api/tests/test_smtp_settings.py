"""Tests for Platform-Admin-managed SMTP configuration: access control, validation,
secret handling, environment precedence, test-email delivery, and audit records.

No fake SMTP transport exists in the repo yet (test_worker.py relies on
email_delivery_configured being false by default rather than mocking smtplib), so this
file adds two independent stand-ins: a monkeypatched mykhaya.routers.platform.send_email
for API-level tests, and a monkeypatched smtplib.SMTP/SMTP_SSL for a direct mailer unit
test that exercises the real connection-security branches.
"""

import hashlib
import smtplib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.mailer import SmtpConfig, send_email
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    PlatformAdministrator,
    PlatformRole,
    PlatformSmtpSettings,
)
from mykhaya.routers import platform as platform_router
from mykhaya.secrets_crypto import decrypt_secret
from mykhaya.security import password_hash

ADMIN_ORIGIN = "http://admin.localhost:8080"
PASSWORD = "A separate operator password!"
AdminFactory = Callable[[PlatformRole], Awaitable[PlatformAdministrator]]


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44100)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    ) as value:
        yield value


async def create_admin(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with SessionFactory() as db:
        row = PlatformAdministrator(
            email=f"smtp-operator-{suffix}@example.com",
            display_name="Test Operator",
            password_hash=password_hash.hash(PASSWORD),
            role=role,
            mfa_enrolled=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


@pytest.fixture
async def admin_factory() -> AsyncIterator[AdminFactory]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        row = await create_admin(role)
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


async def login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login", json={"email": admin.email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_admin_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


@pytest.fixture(autouse=True)
async def clean_smtp_row() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        await db.execute(delete(PlatformSmtpSettings))
        await db.commit()


async def reset_rate_limit(bucket: str, peer: str) -> None:
    """Clear a rate-limit bucket so reruns within the same window don't flake — the
    limiter (mykhaya.rate_limit.enforce_rate_limit) uses live Redis with no per-test
    isolation."""
    identity = hashlib.sha256(peer.encode()).hexdigest()[:24]
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.delete(f"rate:{bucket}:{identity}")
    finally:
        await redis.aclose()


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
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
        "reason": "Configuring SMTP for the dev server test suite.",
        "confirmed": True,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_owner_can_write_and_read_back_smtp_settings_without_password(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    written = await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload()
    )
    assert written.status_code == 200, written.text

    read = await admin_client.get("/api/v1/platform/mail")
    assert read.status_code == 200
    body = read.json()["smtp_settings"]
    assert body["host"] == "smtp.example.com"
    assert body["password_configured"] is True
    assert "password" not in body
    assert "encrypted_password" not in body
    assert "correct horse battery staple" not in read.text


@pytest.mark.asyncio
async def test_support_role_can_read_but_not_write(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.support)
    await login(admin_client, admin)
    assert (await admin_client.get("/api/v1/platform/mail")).status_code == 200
    denied = await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload()
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_readonly_role_cannot_write(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.readonly)
    await login(admin_client, admin)
    denied = await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload()
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_household_session_has_no_platform_access() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44101)),
        base_url="http://localhost:8080",
        cookies={"mk_session": "household-session", "mk_admin_session": "invented"},
    ) as client:
        response = await client.get("/api/v1/platform/mail")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_missing_csrf_token_is_rejected(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    response = await admin_client.put("/api/v1/platform/mail/smtp-settings", json=valid_payload())
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_host_required_when_enabled(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings",
        json=valid_payload(host=""),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bad_port_is_rejected(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings",
        json=valid_payload(port=70000),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bad_sender_email_is_rejected(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings",
        json=valid_payload(sender_email="not-an-email"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_auth_enabled_requires_a_password_on_first_save(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    response = await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings",
        json=valid_payload(password=None),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_password_is_encrypted_at_rest(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await unsafe(admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload())

    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformSmtpSettings).limit(1))
        assert row is not None
        assert row.encrypted_password is not None
        assert "correct horse battery staple" not in row.encrypted_password
        decrypted = decrypt_secret(get_settings(), row.encrypted_password)
        assert decrypted == "correct horse battery staple"


@pytest.mark.asyncio
async def test_empty_password_on_update_retains_existing_secret(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await unsafe(admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload())
    await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings",
        json=valid_payload(password=None, host="smtp2.example.com"),
    )
    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformSmtpSettings).limit(1))
        assert row is not None
        assert row.host == "smtp2.example.com"
        decrypted = decrypt_secret(get_settings(), row.encrypted_password)
        assert decrypted == "correct horse battery staple"


@pytest.mark.asyncio
async def test_password_replacement_works(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await unsafe(admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload())
    await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings",
        json=valid_payload(password="a brand new secret"),
    )
    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformSmtpSettings).limit(1))
        assert row is not None
        assert decrypt_secret(get_settings(), row.encrypted_password) == "a brand new secret"


@pytest.mark.asyncio
async def test_clear_password_endpoint_removes_stored_credential(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await unsafe(admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload())
    response = await unsafe(
        admin_client, "POST", "/api/v1/platform/mail/smtp-settings/clear-password",
        json={"reason": "Rotating the compromised credential.", "confirmed": True},
    )
    assert response.status_code == 200
    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformSmtpSettings).limit(1))
        assert row is not None
        assert row.encrypted_password is None
        assert row.username is None


@pytest.mark.asyncio
async def test_disabled_smtp_reports_unconfigured_even_with_fields_populated(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings",
        json=valid_payload(enabled=False),
    )
    read = await admin_client.get("/api/v1/platform/mail")
    assert read.json()["configured"] is False
    assert read.json()["managed_by"] == "unconfigured"


@pytest.mark.asyncio
async def test_undecryptable_password_degrades_gracefully_instead_of_crashing(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    """Simulates a MYKHAYA_SECRET_KEY rotation: the stored ciphertext can no longer be
    decrypted. GET /mail must still respond (as "not configured"), not 500."""
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await unsafe(admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload())
    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformSmtpSettings).limit(1))
        assert row is not None
        row.encrypted_password = "not-valid-ciphertext"
        await db.commit()

    read = await admin_client.get("/api/v1/platform/mail")
    assert read.status_code == 200
    assert read.json()["configured"] is False

    test_email = await unsafe(
        admin_client, "POST", "/api/v1/platform/mail/test",
        json={
            "recipient": admin.email,
            "reason": "Probing rotated-secret behaviour.",
            "confirmed": True,
        },
    )
    assert test_email.status_code == 409


@pytest.mark.asyncio
async def test_environment_managed_smtp_rejects_writes_and_reports_source(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    configured = get_settings().model_copy(
        update={
            "email_delivery_configured": True,
            "smtp_host": "env-smtp.example.com",
            "email_from": "env@mykhaya.example",
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        read = await admin_client.get("/api/v1/platform/mail")
        assert read.json()["managed_by"] == "environment"
        assert read.json()["smtp_settings"]["editable"] is False
        write = await unsafe(
            admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload()
        )
        assert write.status_code == 409
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_settings_changed_and_credentials_replaced_are_audited_without_secrets(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await unsafe(admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload())
    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent)
                .where(AdministrativeAuditEvent.administrator_id == admin.id)
                .order_by(AdministrativeAuditEvent.created_at.asc())
            )
        ).all()
    actions = [event.action for event in events]
    assert "smtp.settings_changed" in actions
    assert "smtp.credentials_replaced" in actions
    for event in events:
        assert "correct horse battery staple" not in str(event.new_values)
        assert "correct horse battery staple" not in str(event.previous_values)


@pytest.mark.asyncio
async def test_disabling_smtp_is_audited(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await unsafe(admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload())
    await unsafe(
        admin_client, "PUT", "/api/v1/platform/mail/smtp-settings",
        json=valid_payload(enabled=False),
    )
    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == admin.id,
                    AdministrativeAuditEvent.action == "smtp.disabled",
                )
            )
        ).all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_send_test_email_success_and_failure_are_audited(
    admin_client: AsyncClient,
    admin_factory: AdminFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await unsafe(admin_client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload())
    await reset_rate_limit("platform-test-email", "127.0.0.1")

    monkeypatch.setattr(platform_router, "send_email", lambda *args, **kwargs: None)
    ok = await unsafe(
        admin_client, "POST", "/api/v1/platform/mail/test",
        json={"recipient": admin.email, "reason": "Confirming delivery works.", "confirmed": True},
    )
    assert ok.status_code == 200

    def fail(*args: object, **kwargs: object) -> None:
        raise smtplib.SMTPException("boom")

    monkeypatch.setattr(platform_router, "send_email", fail)
    failed = await unsafe(
        admin_client, "POST", "/api/v1/platform/mail/test",
        json={"recipient": admin.email, "reason": "Confirming failure path.", "confirmed": True},
    )
    assert failed.status_code == 502
    assert "boom" not in failed.text

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == admin.id,
                    AdministrativeAuditEvent.action.in_(["email.test_sent", "email.test_failed"]),
                )
            )
        ).all()
    actions = {event.action for event in events}
    assert actions == {"email.test_sent", "email.test_failed"}
    assert all(admin.email not in str(event.new_values) for event in events)


@pytest.mark.asyncio
async def test_send_test_email_is_rate_limited(
    admin_factory: AdminFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The limiter buckets by source IP (mykhaya.rate_limit.enforce_rate_limit), so this
    # test uses a dedicated client/peer address rather than the shared admin_client
    # fixture, to avoid sharing a rate-limit bucket with other tests in this file.
    admin = await admin_factory(PlatformRole.owner)
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.50", 44199)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    ) as client:
        await login(client, admin)
        await unsafe(client, "PUT", "/api/v1/platform/mail/smtp-settings", json=valid_payload())
        await reset_rate_limit("platform-test-email", "127.0.0.50")
        monkeypatch.setattr(platform_router, "send_email", lambda *args, **kwargs: None)

        statuses = []
        for _ in range(4):
            response = await unsafe(
                client, "POST", "/api/v1/platform/mail/test",
                json={"recipient": admin.email, "reason": "Rate limit probe.", "confirmed": True},
            )
            statuses.append(response.status_code)
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429


def test_send_email_uses_starttls_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeSmtp:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls["connect"] = (host, port, timeout)

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def starttls(self) -> None:
            calls["starttls"] = True

        def login(self, username: str, password: str) -> None:
            calls["login"] = (username, password)

        def send_message(self, message: object) -> None:
            calls["sent"] = True

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    config = SmtpConfig(
        source="platform_admin",
        configured=True,
        host="smtp.example.com",
        port=587,
        connection_security="starttls",
        username="mailer",
        password="secret",  # noqa: S106 - test fixture, not a real credential
        sender="MyKhaya <hello@mykhaya.example>",
        timeout_seconds=10,
    )
    send_email(config, "someone@example.com", "Subject", "Body")
    assert calls["connect"] == ("smtp.example.com", 587, 10)
    assert calls["starttls"] is True
    assert calls["login"] == ("mailer", "secret")
    assert calls["sent"] is True


def test_send_email_raises_when_unconfigured() -> None:
    with pytest.raises(RuntimeError):
        send_email(SmtpConfig(source="unconfigured", configured=False), "a@b.com", "S", "B")
