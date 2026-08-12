"""Platform Administrator invitations — the normal, ongoing way to add a new
Platform Administrator through the Control Centre. See
mykhaya.routers.platform's /administrators/invitations endpoints.

Reuses the admin_client/admin_factory/login/unsafe fixtures and ADMIN_ORIGIN
from test_platform_control_centre.py.
"""

import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update
from test_platform_control_centre import (  # noqa: F401
    ADMIN_ORIGIN,
    admin_client,
    admin_factory,
    login,
    unsafe,
)

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    PlatformAdministrator,
    PlatformAdministratorInvitation,
    PlatformRole,
    PlatformSession,
)
from mykhaya.security import hash_secret, normalise_email


def new_admin_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44000)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    )


async def _force_recent_auth(admin_id: uuid.UUID) -> None:
    async with SessionFactory() as db:
        await db.execute(
            update(PlatformSession)
            .where(PlatformSession.administrator_id == admin_id)
            .values(authenticated_at=datetime.now(UTC))
        )
        await db.commit()


async def _create_invitation(
    email: str,
    *,
    role: PlatformRole = PlatformRole.administrator,
    invited_by: uuid.UUID | None = None,
    expires_delta: timedelta = timedelta(hours=24),
    revoked: bool = False,
    accepted: bool = False,
) -> tuple[PlatformAdministratorInvitation, str]:
    """Bypasses the create endpoint to get a known raw token — platform
    invitation tokens are genuinely random (not derivable from the row id the
    way household invitation tokens are), so tests that only care about the
    accept/preview side construct the row directly, exactly the way
    test_platform_control_centre.py constructs a PlatformAdministrator
    directly rather than always going through /auth/login first."""
    raw = secrets.token_urlsafe(32)
    async with SessionFactory() as db:
        row = PlatformAdministratorInvitation(
            email=normalise_email(email),
            display_name="Invited Person",
            role=role,
            token_hash=hash_secret(raw, get_settings().secret_key.get_secret_value()),
            invited_by=invited_by,
            expires_at=datetime.now(UTC) + expires_delta,
            revoked_at=datetime.now(UTC) if revoked else None,
            accepted_at=datetime.now(UTC) if accepted else None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row, raw


async def _cleanup(*emails: str) -> None:
    async with SessionFactory() as db:
        await db.execute(
            delete(PlatformAdministratorInvitation).where(
                PlatformAdministratorInvitation.email.in_([normalise_email(e) for e in emails])
            )
        )
        await db.execute(
            delete(PlatformAdministrator).where(
                PlatformAdministrator.email.in_([normalise_email(e) for e in emails])
            )
        )
        await db.commit()


def unique_email(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"


@pytest.mark.asyncio
async def test_non_owner_cannot_create_invitation(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.administrator)
    await login(admin_client, admin)
    email = unique_email("non-owner-invite")
    try:
        response = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/administrators/invitations",
            json={
                "email": email,
                "display_name": "New Admin",
                "role": "platform_administrator",
                "reason": "Testing non-owner cannot invite",
                "confirmed": True,
            },
        )
        assert response.status_code == 403
    finally:
        await _cleanup(email)


@pytest.mark.asyncio
async def test_owner_can_create_invitation_and_it_is_audited(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _force_recent_auth(admin.id)
    email = unique_email("owner-invite")
    try:
        response = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/administrators/invitations",
            json={
                "email": email,
                "display_name": "New Admin",
                "role": "platform_administrator",
                "reason": "Bringing on a new operator",
                "confirmed": True,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["email"] == email
        assert body["state"] == "pending"
        assert "token" not in response.text

        async with SessionFactory() as db:
            row = await db.scalar(
                select(PlatformAdministratorInvitation).where(
                    PlatformAdministratorInvitation.email == normalise_email(email)
                )
            )
            assert row is not None
            event = await db.scalar(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.action == "platform_administrator_invitation.created",
                    AdministrativeAuditEvent.target_id == row.id,
                )
            )
            assert event is not None
    finally:
        await _cleanup(email)


@pytest.mark.asyncio
async def test_invalid_role_is_rejected(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    await _force_recent_auth(admin.id)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/administrators/invitations",
        json={
            "email": unique_email("bad-role"),
            "display_name": "New Admin",
            "role": "super_admin",
            "reason": "Trying an invalid role",
            "confirmed": True,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_token_is_stored_hashed_not_plaintext() -> None:
    email = unique_email("hashed-token")
    try:
        row, raw = await _create_invitation(email)
        assert row.token_hash != raw
        assert raw not in row.token_hash
    finally:
        await _cleanup(email)


@pytest.mark.asyncio
async def test_valid_invitation_is_accepted_and_assigns_the_correct_role() -> None:
    email = unique_email("accept-me")
    try:
        _row, raw = await _create_invitation(email, role=PlatformRole.security)
        async with new_admin_client() as client:
            preview = await client.get(
                "/api/v1/platform/administrators/invitations/preview", params={"token": raw}
            )
            assert preview.status_code == 200
            assert preview.json()["role"] == "security_operator"

            accepted = await unsafe(
                client,
                "POST",
                "/api/v1/platform/administrators/invitations/accept",
                json={"token": raw, "password": "A brand new operator password!"},
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["role"] == "security_operator"

        async with SessionFactory() as db:
            created = await db.scalar(
                select(PlatformAdministrator).where(
                    PlatformAdministrator.email == normalise_email(email)
                )
            )
            assert created is not None
            assert created.role == PlatformRole.security
    finally:
        await _cleanup(email)


@pytest.mark.asyncio
async def test_accepted_account_enters_mfa_setup_required_when_policy_demands_it() -> None:
    email = unique_email("mfa-required-accept")
    try:
        _row, raw = await _create_invitation(email)
        forced_mfa = get_settings().model_copy(update={"admin_mfa_required": True})
        app.dependency_overrides[get_settings] = lambda: forced_mfa
        try:
            async with new_admin_client() as client:
                accepted = await unsafe(
                    client,
                    "POST",
                    "/api/v1/platform/administrators/invitations/accept",
                    json={"token": raw, "password": "Another brand new password!"},
                )
                assert accepted.status_code == 200
                assert accepted.json()["session_status"] == "mfa_setup_required"

                blocked = await client.get("/api/v1/platform/overview")
                assert blocked.status_code == 403
        finally:
            app.dependency_overrides.pop(get_settings, None)
    finally:
        await _cleanup(email)


@pytest.mark.asyncio
async def test_expired_invitation_is_rejected() -> None:
    email = unique_email("expired")
    try:
        _row, raw = await _create_invitation(email, expires_delta=timedelta(hours=-1))
        async with new_admin_client() as client:
            preview = await client.get(
                "/api/v1/platform/administrators/invitations/preview", params={"token": raw}
            )
            assert preview.status_code == 400
            accepted = await unsafe(
                client,
                "POST",
                "/api/v1/platform/administrators/invitations/accept",
                json={"token": raw, "password": "Should never be used at all!"},
            )
            assert accepted.status_code == 400
        async with SessionFactory() as db:
            created = await db.scalar(
                select(PlatformAdministrator).where(
                    PlatformAdministrator.email == normalise_email(email)
                )
            )
            assert created is None
    finally:
        await _cleanup(email)


@pytest.mark.asyncio
async def test_revoked_invitation_is_rejected() -> None:
    email = unique_email("revoked")
    try:
        _row, raw = await _create_invitation(email, revoked=True)
        async with new_admin_client() as client:
            accepted = await unsafe(
                client,
                "POST",
                "/api/v1/platform/administrators/invitations/accept",
                json={"token": raw, "password": "Should never be used either!"},
            )
            assert accepted.status_code == 400
    finally:
        await _cleanup(email)


@pytest.mark.asyncio
async def test_invitation_token_is_single_use() -> None:
    email = unique_email("single-use")
    try:
        _row, raw = await _create_invitation(email)
        async with new_admin_client() as first:
            first_accept = await unsafe(
                first,
                "POST",
                "/api/v1/platform/administrators/invitations/accept",
                json={"token": raw, "password": "The first and only valid use!"},
            )
            assert first_accept.status_code == 200
        async with new_admin_client() as second:
            second_accept = await unsafe(
                second,
                "POST",
                "/api/v1/platform/administrators/invitations/accept",
                json={"token": raw, "password": "This must never succeed at all!"},
            )
            assert second_accept.status_code == 400
    finally:
        await _cleanup(email)


@pytest.mark.asyncio
async def test_reissuing_invalidates_the_previous_token(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await login(admin_client, owner)
    await _force_recent_auth(owner.id)
    email = unique_email("reissue")
    try:
        row, old_raw = await _create_invitation(email, invited_by=owner.id)
        resend = await unsafe(
            admin_client,
            "POST",
            f"/api/v1/platform/administrators/invitations/{row.id}/resend",
        )
        assert resend.status_code == 200

        async with new_admin_client() as client:
            old_token_attempt = await unsafe(
                client,
                "POST",
                "/api/v1/platform/administrators/invitations/accept",
                json={"token": old_raw, "password": "Using the stale old token here!"},
            )
            assert old_token_attempt.status_code == 400
    finally:
        await _cleanup(email)


@pytest.mark.asyncio
async def test_creating_an_invitation_for_an_existing_administrator_email_conflicts(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    target = await admin_factory(PlatformRole.administrator)
    await login(admin_client, owner)
    await _force_recent_auth(owner.id)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/administrators/invitations",
        json={
            "email": target.email,
            "display_name": "Duplicate",
            "role": "platform_administrator",
            "reason": "Trying to invite an existing administrator",
            "confirmed": True,
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_revoking_an_invitation_is_audited_and_blocks_acceptance(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await login(admin_client, owner)
    await _force_recent_auth(owner.id)
    email = unique_email("revoke-flow")
    try:
        row, raw = await _create_invitation(email, invited_by=owner.id)
        revoke = await unsafe(
            admin_client,
            "POST",
            f"/api/v1/platform/administrators/invitations/{row.id}/revoke",
        )
        assert revoke.status_code == 200
        assert revoke.json()["state"] == "revoked"

        async with SessionFactory() as db:
            event = await db.scalar(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.action == "platform_administrator_invitation.revoked",
                    AdministrativeAuditEvent.target_id == row.id,
                )
            )
            assert event is not None

        async with new_admin_client() as client:
            accepted = await unsafe(
                client,
                "POST",
                "/api/v1/platform/administrators/invitations/accept",
                json={"token": raw, "password": "Must be blocked by revocation!"},
            )
            assert accepted.status_code == 400
    finally:
        await _cleanup(email)
