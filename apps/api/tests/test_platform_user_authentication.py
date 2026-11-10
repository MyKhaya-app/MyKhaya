"""PCC user Authentication tab: connected sign-in methods summary and the
administrative Apple/Google disconnect, which reuses the provider-neutral
mykhaya.external_identities service and its last-usable-sign-in guard.

These run against the test database only. They do not prove anything about
live Apple/Google configuration in DEV or PROD.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from test_platform_control_centre import admin_client, admin_factory, login, unsafe  # noqa: F401

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    AuditEvent,
    AuthIdentity,
    ExternalIdentity,
    ExternalIdentityProvider,
    NotificationDelivery,
    OutboxEvent,
    PlatformAdministrator,
    PlatformRole,
    Session,
    User,
)
from mykhaya.routers import platform as platform_router
from mykhaya.security import password_hash

APPLE_SUBJECT = "apple-subject-must-never-appear"
APPLE_EMAIL = "relay-secret@privaterelay.appleid.com"
REASON = "User cannot sign in with Apple; ticket MK-1234"

AdminFactory = Callable[[PlatformRole], Awaitable[PlatformAdministrator]]


@pytest.fixture
async def make_user() -> AsyncIterator[Callable[..., Awaitable[User]]]:
    created: list[uuid.UUID] = []

    async def factory(*, password: bool = True, apple: bool = True) -> User:
        async with SessionFactory() as db:
            user = User(
                email=f"pcc-auth-{uuid.uuid4().hex}@example.com",
                display_name="Support Subject",
            )
            db.add(user)
            await db.flush()
            if password:
                db.add(AuthIdentity(user_id=user.id, password_hash=password_hash.hash("x" * 16)))
            if apple:
                db.add(
                    ExternalIdentity(
                        user_id=user.id,
                        provider=ExternalIdentityProvider.apple,
                        provider_subject=f"{APPLE_SUBJECT}-{user.id}",
                        provider_email=APPLE_EMAIL,
                        provider_email_verified=True,
                        last_used_at=datetime.now(UTC),
                    )
                )
            db.add(
                Session(
                    user_id=user.id,
                    token_hash=secrets.token_hex(32),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                    user_agent="Test browser",
                )
            )
            await db.commit()
            await db.refresh(user)
            created.append(user.id)
            return user

    yield factory
    async with SessionFactory() as db:
        if created:
            deliveries = (
                await db.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.recipient_user_id.in_(created)
                    )
                )
            ).all()
            outbox_ids = [row.outbox_event_id for row in deliveries if row.outbox_event_id]
            await db.execute(
                delete(NotificationDelivery).where(
                    NotificationDelivery.recipient_user_id.in_(created)
                )
            )
            if outbox_ids:
                await db.execute(delete(OutboxEvent).where(OutboxEvent.id.in_(outbox_ids)))
            await db.execute(
                delete(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.target_id.in_(created)
                )
            )
            await db.execute(delete(AuditEvent).where(AuditEvent.target_id.in_(created)))
            await db.execute(delete(User).where(User.id.in_(created)))
        await db.commit()


def _path(user: User, suffix: str = "") -> str:
    return f"/api/v1/platform/users/{user.id}{suffix}"


async def _disconnect(client: AsyncClient, user: User, provider: str = "apple", **body: object):
    payload: dict[str, object] = {"reason": REASON, "confirmed": True, **body}
    return await unsafe(
        client, "POST", _path(user, f"/sign-in-methods/{provider}/disconnect"), json=payload
    )


async def _identities(user: User) -> list[ExternalIdentity]:
    async with SessionFactory() as db:
        rows = await db.scalars(select(ExternalIdentity).where(ExternalIdentity.user_id == user.id))
        return list(rows.all())


@pytest.mark.asyncio
async def test_summary_shows_status_without_provider_identity_data(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: AdminFactory,  # noqa: F811
    make_user: Callable[..., Awaitable[User]],
) -> None:
    user = await make_user()
    support = await admin_factory(PlatformRole.support)
    await login(admin_client, support)
    response = await admin_client.get(_path(user, "/authentication"))
    assert response.status_code == 200, response.text
    body = response.json()
    providers = {item["provider"]: item for item in body["providers"]}
    assert providers["apple"]["connected"] is True
    assert providers["apple"]["connected_at"] is not None
    assert providers["apple"]["last_used_at"] is not None
    assert providers["google"]["connected"] is False
    assert providers["google"]["connected_at"] is None
    assert body["password"]["available"] is True
    assert body["passkeys"] == {"count": 0, "last_used_at": None}
    assert body["sessions"]["active_sessions"] == 1
    assert {item["platform"] for item in body["native_apps"]} == {"ios", "android"}
    for forbidden in (APPLE_SUBJECT, APPLE_EMAIL, "provider_subject", "provider_email", "token"):
        assert forbidden not in response.text, forbidden

    detail = (await admin_client.get(_path(user))).json()
    assert detail["viewer_permissions"] == {
        "change_mfa_policy": False,
        "disconnect_sign_in_methods": False,
        "revoke_sessions": True,
    }


@pytest.mark.asyncio
async def test_readonly_and_security_roles_cannot_read_the_summary(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: AdminFactory,  # noqa: F811
    make_user: Callable[..., Awaitable[User]],
) -> None:
    user = await make_user()
    for role in (PlatformRole.readonly, PlatformRole.security):
        await login(admin_client, await admin_factory(role))
        assert (await admin_client.get(_path(user, "/authentication"))).status_code == 403


@pytest.mark.asyncio
async def test_administrator_disconnects_apple_and_it_is_audited(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: AdminFactory,  # noqa: F811
    make_user: Callable[..., Awaitable[User]],
) -> None:
    user = await make_user()
    administrator = await admin_factory(PlatformRole.administrator)
    await login(admin_client, administrator)
    response = await _disconnect(admin_client, user)
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True
    assert APPLE_SUBJECT not in response.text
    assert await _identities(user) == []

    async with SessionFactory() as db:
        admin_event = await db.scalar(
            select(AdministrativeAuditEvent).where(
                AdministrativeAuditEvent.target_id == user.id,
                AdministrativeAuditEvent.action == "user.external_identity_disconnected",
            )
        )
        user_event = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.target_id == user.id,
                AuditEvent.action == "external_identity.unlinked",
            )
        )
        session = await db.scalar(select(Session).where(Session.user_id == user.id))
        account = await db.get(User, user.id)
    assert admin_event is not None
    assert admin_event.administrator_id == administrator.id
    assert admin_event.outcome == "succeeded"
    assert admin_event.reason == REASON
    assert admin_event.new_values == {"provider": "apple", "connected": False}
    # The user's own audit trail does not claim the user did this.
    assert user_event is not None and user_event.actor_user_id is None
    # Nothing else about the account changes: sessions and the account remain.
    assert session is not None and session.revoked_at is None
    assert account is not None and account.is_active

    summary = (await admin_client.get(_path(user, "/authentication"))).json()
    apple = next(item for item in summary["providers"] if item["provider"] == "apple")
    assert apple["connected"] is False
    assert summary["recent_events"][0]["label"] == "Apple disconnected by an administrator"
    assert summary["recent_events"][0]["initiated_by"] == "administrator"


@pytest.mark.asyncio
async def test_disconnecting_an_already_disconnected_provider_is_safe(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: AdminFactory,  # noqa: F811
    make_user: Callable[..., Awaitable[User]],
) -> None:
    user = await make_user()
    await login(admin_client, await admin_factory(PlatformRole.owner))
    assert (await _disconnect(admin_client, user)).json()["changed"] is True
    again = await _disconnect(admin_client, user)
    assert again.status_code == 200
    assert again.json()["changed"] is False
    google = await _disconnect(admin_client, user, "google")
    assert google.status_code == 200 and google.json()["changed"] is False


@pytest.mark.asyncio
async def test_last_usable_sign_in_method_cannot_be_disconnected(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: AdminFactory,  # noqa: F811
    make_user: Callable[..., Awaitable[User]],
) -> None:
    user = await make_user(password=False)
    await login(admin_client, await admin_factory(PlatformRole.owner))
    response = await _disconnect(admin_client, user)
    assert response.status_code == 409
    assert "only way to sign in" in response.json()["detail"]
    assert len(await _identities(user)) == 1
    async with SessionFactory() as db:
        refused = await db.scalar(
            select(AdministrativeAuditEvent).where(
                AdministrativeAuditEvent.target_id == user.id,
                AdministrativeAuditEvent.action == "user.external_identity_disconnected",
            )
        )
    assert refused is not None
    assert refused.outcome == "failed"
    assert refused.failure_category == "last_sign_in_method"


@pytest.mark.asyncio
async def test_disconnect_requires_operator_role_reason_and_confirmation(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: AdminFactory,  # noqa: F811
    make_user: Callable[..., Awaitable[User]],
) -> None:
    user = await make_user()
    for role in (PlatformRole.support, PlatformRole.security, PlatformRole.readonly):
        await login(admin_client, await admin_factory(role))
        assert (await _disconnect(admin_client, user)).status_code == 403, role
    await login(admin_client, await admin_factory(PlatformRole.owner))
    assert (await _disconnect(admin_client, user, reason="short")).status_code == 422
    assert (await _disconnect(admin_client, user, confirmed=False)).status_code == 422
    assert (await _disconnect(admin_client, user, "facebook")).status_code == 422
    missing = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/users/{uuid.uuid4()}/sign-in-methods/apple/disconnect",
        json={"reason": REASON, "confirmed": True},
    )
    assert missing.status_code == 404
    assert len(await _identities(user)) == 1


async def _security_emails(user: User) -> list[NotificationDelivery]:
    async with SessionFactory() as db:
        rows = await db.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.recipient_user_id == user.id,
                NotificationDelivery.notification_type == "account.sign_in_method_disconnected",
            )
        )
        return list(rows.all())


@pytest.mark.asyncio
async def test_disconnect_queues_one_security_email_without_identity_details(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: AdminFactory,  # noqa: F811
    make_user: Callable[..., Awaitable[User]],
) -> None:
    user = await make_user()
    administrator = await admin_factory(PlatformRole.administrator)
    await login(admin_client, administrator)
    response = await _disconnect(admin_client, user)
    assert response.json()["user_notified"] is True
    assert "security email" in response.json()["message"]
    emails = await _security_emails(user)
    assert len(emails) == 1
    assert emails[0].channel.value == "email"
    async with SessionFactory() as db:
        event = await db.get(OutboxEvent, emails[0].outbox_event_id)
    assert event is not None
    payload = event.payload
    assert payload["recipient_email"] == user.email
    assert payload["subject"] == "Apple sign-in was removed from your MyKhaya account"
    assert "Settings > Security > Sign-in methods" in payload["body"]
    for forbidden in (APPLE_SUBJECT, APPLE_EMAIL, administrator.email, REASON):
        assert forbidden not in payload["body"], forbidden
        assert forbidden not in (payload["html_body"] or ""), forbidden

    # Repeating the request disconnects nothing and notifies no one.
    again = await _disconnect(admin_client, user)
    assert again.json()["changed"] is False
    assert len(await _security_emails(user)) == 1


@pytest.mark.asyncio
async def test_notification_failure_never_reverses_the_disconnection(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: AdminFactory,  # noqa: F811
    make_user: Callable[..., Awaitable[User]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_notify(*_: object, **__: object) -> None:
        raise RuntimeError("notification engine unavailable")

    monkeypatch.setattr(platform_router, "notify", broken_notify)
    user = await make_user()
    await login(admin_client, await admin_factory(PlatformRole.owner))
    response = await _disconnect(admin_client, user)
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True
    assert response.json()["user_notified"] is False
    assert await _identities(user) == []
    assert await _security_emails(user) == []
    async with SessionFactory() as db:
        audited = await db.scalar(
            select(AdministrativeAuditEvent).where(
                AdministrativeAuditEvent.target_id == user.id,
                AdministrativeAuditEvent.action == "user.external_identity_disconnected",
                AdministrativeAuditEvent.outcome == "succeeded",
            )
        )
    assert audited is not None


@pytest.mark.asyncio
async def test_a_provider_turned_off_here_does_not_count_as_another_way_in(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: AdminFactory,  # noqa: F811
    make_user: Callable[..., Awaitable[User]],
) -> None:
    """Apple + Google linked, no password, Google switched off in this
    environment: disconnecting Apple would leave only an
    unusable Google identity, so it is refused."""
    user = await make_user(password=False)
    async with SessionFactory() as db:
        db.add(
            ExternalIdentity(
                user_id=user.id,
                provider=ExternalIdentityProvider.google,
                provider_subject=f"google-{user.id}",
                provider_email=None,
                provider_email_verified=False,
            )
        )
        await db.commit()
    await login(admin_client, await admin_factory(PlatformRole.owner))
    google_off = get_settings().model_copy(update={"google_sign_in_enabled": False})
    app.dependency_overrides[get_settings] = lambda: google_off
    try:
        response = await _disconnect(admin_client, user)
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert response.status_code == 409
    assert len(await _identities(user)) == 2
    assert await _security_emails(user) == []
