"""Tests for the Platform Control Centre Support routes (Phase 2A).

Covers PCC list/filter/search, ticket detail, status/priority/assignment
PATCH, admin replies, the require_roles(*SUPPORT) gate (no new platform role
introduced), and that PCC-side reads/writes are audited via the existing
AdministrativeAuditEvent framework.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    AdministrativeAuditEvent,
    FeatureFlag,
    FeatureKey,
    PlatformAdministrator,
    PlatformRole,
    SupportTicket,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token, password_hash

CONSUMER_ORIGIN = "http://localhost:8080"
ADMIN_ORIGIN = "http://admin.localhost:8080"
PASSWORD = "Correct horse battery staple!"
ADMIN_PASSWORD = "A separate operator password!"
# See tests/test_support_tickets.py's identical constant for why: an
# ASGITransport client with no explicit `client=` peer resolves to this
# fixed rate-limit identity.
DEFAULT_TEST_PEER = "127.0.0.1"
AdminFactory = Callable[[PlatformRole], Awaitable[PlatformAdministrator]]


@pytest.fixture
async def consumer_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=CONSUMER_ORIGIN,
        headers={"Origin": CONSUMER_ORIGIN},
    ) as value:
        yield value


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("172.16.0.2", 44240)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN, "X-Forwarded-For": "127.0.0.1"},
    ) as value:
        yield value


@pytest.fixture
async def admin_factory() -> AsyncIterator[AdminFactory]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        suffix = datetime.now(UTC).strftime("%H%M%S%f")
        async with SessionFactory() as db:
            row = PlatformAdministrator(
                email=f"support-operator-{suffix}@example.com",
                display_name="Test Support Operator",
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


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def admin_unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_admin_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def create_verified_user(client: AsyncClient, email: str, name: str) -> uuid.UUID:
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": PASSWORD},
    )
    assert response.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        user_id = user.id
        token = await db.scalar(
            select(ActionToken)
            .where(
                ActionToken.user_id == user.id,
                ActionToken.purpose == TokenPurpose.verify_email,
            )
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    return user_id


async def create_ticket(client: AsyncClient, subject: str = "PCC test ticket") -> str:
    created = await unsafe(
        client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": subject,
            "description": "Details for PCC testing.",
            "source": "ios",
            "app_area": "calendar",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


@pytest.fixture(autouse=True)
async def enable_support_feature() -> AsyncIterator[None]:
    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.support))
        assert row is not None
        row.enabled = True
        await db.commit()
    yield
    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.support))
        if row is not None:
            row.enabled = False
            await db.commit()


@pytest.fixture(autouse=True)
async def _reset_support_rate_limits() -> None:
    identity = hashlib.sha256(DEFAULT_TEST_PEER.encode()).hexdigest()[:24]
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        for bucket in ("support-ticket-create", "support-attachment-upload"):
            await redis.delete(f"rate:{bucket}:{identity}")
    finally:
        await redis.aclose()


# --- role gate ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_role_cannot_access_support_queue(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.security)
    await admin_login(admin_client, admin)
    response = await admin_client.get("/api/v1/platform/support/tickets")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_support_operator_role_can_access_support_queue(
    admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, admin)
    response = await admin_client.get("/api/v1/platform/support/tickets")
    assert response.status_code == 200


# --- list / filter / search ---------------------------------------------------


@pytest.mark.asyncio
async def test_list_tickets_and_filter_by_status(
    consumer_client: AsyncClient, admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    await create_verified_user(consumer_client, unique_email("pcclist"), "PCC List User")
    ticket_id = await create_ticket(consumer_client, "Filterable bug")

    admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, admin)

    listed = await admin_client.get("/api/v1/platform/support/tickets", params={"status": "open"})
    assert listed.status_code == 200
    references = {item["id"] for item in listed.json()["items"]}
    assert ticket_id in references

    filtered_out = await admin_client.get(
        "/api/v1/platform/support/tickets", params={"status": "resolved"}
    )
    assert filtered_out.status_code == 200
    assert ticket_id not in {item["id"] for item in filtered_out.json()["items"]}


@pytest.mark.asyncio
async def test_search_by_reference(
    consumer_client: AsyncClient, admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    await create_verified_user(consumer_client, unique_email("pccsearch"), "PCC Search User")
    ticket_id = await create_ticket(consumer_client, "Searchable subject")

    ticket_uuid = uuid.UUID(ticket_id)
    async with SessionFactory() as db:
        ticket = await db.scalar(select(SupportTicket).where(SupportTicket.id == ticket_uuid))
        assert ticket is not None
        reference = ticket.reference

    admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, admin)
    found = await admin_client.get("/api/v1/platform/support/tickets", params={"query": reference})
    assert found.status_code == 200
    assert ticket_id in {item["id"] for item in found.json()["items"]}


# --- detail / audit ------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ticket_detail_includes_requester_info_and_audits_view(
    consumer_client: AsyncClient, admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    await create_verified_user(consumer_client, unique_email("pccdetail"), "PCC Detail User")
    ticket_id = await create_ticket(consumer_client, "Detail view ticket")

    admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, admin)
    detail = await admin_client.get(f"/api/v1/platform/support/tickets/{ticket_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["requester_display_name"] == "PCC Detail User"
    assert "@" in body["requester_email"]

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == admin.id,
                    AdministrativeAuditEvent.action == "support.ticket.viewed_by_admin",
                )
            )
        ).all()
        assert len(events) == 1


@pytest.mark.asyncio
async def test_diagnostics_view_is_audited_only_when_present(
    consumer_client: AsyncClient, admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    await create_verified_user(consumer_client, unique_email("pccdiag"), "PCC Diag User")
    created = await unsafe(
        consumer_client,
        "POST",
        "/api/v1/support/tickets",
        json={
            "type": "bug",
            "subject": "With diagnostics",
            "description": "Details.",
            "source": "ios",
            "diagnostics": {"app_version": "2.0.0"},
        },
    )
    ticket_id = created.json()["id"]

    admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, admin)
    detail = await admin_client.get(f"/api/v1/platform/support/tickets/{ticket_id}")
    assert detail.status_code == 200
    assert detail.json()["diagnostics"]["app_version"] == "2.0.0"

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == admin.id,
                    AdministrativeAuditEvent.action == "support.diagnostics.viewed",
                )
            )
        ).all()
        assert len(events) == 1


# --- status / priority / assignment --------------------------------------------


@pytest.mark.asyncio
async def test_update_status_sets_resolved_at_and_audits(
    consumer_client: AsyncClient, admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    await create_verified_user(consumer_client, unique_email("pccstatus"), "PCC Status User")
    ticket_id = await create_ticket(consumer_client, "Status change ticket")

    admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, admin)
    updated = await admin_unsafe(
        admin_client,
        "PATCH",
        f"/api/v1/platform/support/tickets/{ticket_id}",
        json={"status": "resolved"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "resolved"
    assert updated.json()["resolved_at"] is not None

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == admin.id,
                    AdministrativeAuditEvent.action.in_(
                        ["support.ticket.status_changed", "support.ticket.resolved"]
                    ),
                )
            )
        ).all()
        actions = {event.action for event in events}
        assert "support.ticket.status_changed" in actions
        assert "support.ticket.resolved" in actions


@pytest.mark.asyncio
async def test_reopening_clears_resolved_at(
    consumer_client: AsyncClient, admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    await create_verified_user(consumer_client, unique_email("pccreopen"), "PCC Reopen User")
    ticket_id = await create_ticket(consumer_client, "Reopen ticket")

    admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, admin)
    await admin_unsafe(
        admin_client,
        "PATCH",
        f"/api/v1/platform/support/tickets/{ticket_id}",
        json={"status": "resolved"},
    )
    reopened = await admin_unsafe(
        admin_client,
        "PATCH",
        f"/api/v1/platform/support/tickets/{ticket_id}",
        json={"status": "open"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["resolved_at"] is None


@pytest.mark.asyncio
async def test_assign_ticket_to_admin_and_unassign(
    consumer_client: AsyncClient, admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    await create_verified_user(consumer_client, unique_email("pccassign"), "PCC Assign User")
    ticket_id = await create_ticket(consumer_client, "Assignment ticket")

    owner = await admin_factory(PlatformRole.owner)
    support_admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, owner)

    assigned = await admin_unsafe(
        admin_client,
        "PATCH",
        f"/api/v1/platform/support/tickets/{ticket_id}",
        json={"assigned_admin_id": str(support_admin.id)},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assigned_admin_id"] == str(support_admin.id)

    unassigned = await admin_unsafe(
        admin_client,
        "PATCH",
        f"/api/v1/platform/support/tickets/{ticket_id}",
        json={"assigned_admin_id": None},
    )
    assert unassigned.status_code == 200
    assert unassigned.json()["assigned_admin_id"] is None

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == owner.id,
                    AdministrativeAuditEvent.action == "support.ticket.assigned",
                )
            )
        ).all()
        assert len(events) == 2  # assign + unassign


# --- replies --------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_reply_is_visible_to_requester(
    consumer_client: AsyncClient, admin_client: AsyncClient, admin_factory: AdminFactory
) -> None:
    await create_verified_user(consumer_client, unique_email("pccreply"), "PCC Reply User")
    ticket_id = await create_ticket(consumer_client, "Reply visibility ticket")

    admin = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, admin)
    replied = await admin_unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/support/tickets/{ticket_id}/messages",
        json={"message": "Thanks for the report, we're looking into it."},
    )
    assert replied.status_code == 201, replied.text
    assert replied.json()["author_display_name"] == admin.display_name

    consumer_view = await unsafe(consumer_client, "GET", f"/api/v1/support/tickets/{ticket_id}")
    assert consumer_view.status_code == 200
    messages = consumer_view.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["author"] == "admin"

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == admin.id,
                    AdministrativeAuditEvent.action == "support.ticket.replied",
                )
            )
        ).all()
        assert len(events) == 1
