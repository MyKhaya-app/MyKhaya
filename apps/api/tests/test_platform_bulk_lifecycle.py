"""Slice 4 — PCC bulk lifecycle cleanup: POST /platform/users/bulk-lifecycle
and /platform/homes/bulk-lifecycle. Both apply exactly the same
_apply_user_disable/_apply_user_archive/_apply_home_disable/_apply_home_
archive transitions the single-entity suspend/archive endpoints use (see
test_platform_lifecycle_archive.py), once per target, with a structured
succeeded/failed response rather than an all-or-nothing transaction.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from test_journey import create_verified_user
from test_journey import unsafe as consumer_unsafe
from test_platform_control_centre import (
    ADMIN_ORIGIN,
    TEST_CLIENT_IP,
    TEST_PROXY_PEER,
    create_admin,
    login,
)
from test_platform_control_centre import unsafe as admin_unsafe

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    Group,
    Membership,
    PlatformRole,
    PlatformSession,
    Session,
    TrustedDevice,
    User,
)

CONSUMER_ORIGIN = "http://localhost:8080"


def consumer_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url=CONSUMER_ORIGIN,
        headers={"Origin": CONSUMER_ORIGIN},
    )


def admin_client_instance() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=(TEST_PROXY_PEER, 44000)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN, "X-Forwarded-For": TEST_CLIENT_IP},
    )


async def create_home(client: AsyncClient, name: str) -> str:
    response = await consumer_unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def bulk_action(
    admin: AsyncClient,
    entity: str,
    ids: list[str],
    action: str,
    reason: str = "Cleaning up test accounts",
) -> object:
    return await admin_unsafe(
        admin,
        "POST",
        f"/api/v1/platform/{entity}/bulk-lifecycle",
        json={"ids": ids, "action": action, "reason": reason, "confirmed": True},
    )


async def register_user(client: AsyncClient, suffix: str, tag: str) -> str:
    await create_verified_user(client, f"bulk-{tag}-{suffix}@example.com", tag.capitalize())
    return (await client.get("/api/v1/users/me")).json()["id"]


async def login_operator(admin: AsyncClient) -> None:
    operator = await create_admin(PlatformRole.owner)
    await login(admin, operator)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_disable_active_users() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as bob,
        admin_client_instance() as admin,
    ):
        alice_id = await register_user(alice, suffix, "alice1")
        bob_id = await register_user(bob, suffix, "bob1")
        await login_operator(admin)

        response = await bulk_action(admin, "users", [alice_id, bob_id], "disable")
        assert response.status_code == 200, response.text
        body = response.json()
        assert sorted(body["succeeded"]) == sorted([alice_id, bob_id])
        assert body["failed"] == []

        async with SessionFactory() as db:
            for uid in (alice_id, bob_id):
                row = await db.get(User, uuid.UUID(uid))
                assert row is not None
                assert row.is_active is False
                assert row.archived_at is None


@pytest.mark.asyncio
async def test_bulk_disable_revokes_sessions_and_trusted_devices() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        alice_id = await register_user(alice, suffix, "alice2")
        async with SessionFactory() as db:
            db.add(
                TrustedDevice(
                    user_id=uuid.UUID(alice_id),
                    token_hash=f"bulk-device-{suffix}",
                    device_name="Alice's iPad",
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                )
            )
            await db.commit()

        await login_operator(admin)
        response = await bulk_action(admin, "users", [alice_id], "disable")
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            active_sessions = (
                await db.scalars(
                    select(Session).where(
                        Session.user_id == uuid.UUID(alice_id), Session.revoked_at.is_(None)
                    )
                )
            ).all()
            assert active_sessions == []
            active_devices = (
                await db.scalars(
                    select(TrustedDevice).where(
                        TrustedDevice.user_id == uuid.UUID(alice_id),
                        TrustedDevice.revoked_at.is_(None),
                    )
                )
            ).all()
            assert active_devices == []


@pytest.mark.asyncio
async def test_bulk_disable_retains_memberships() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        alice_id = await register_user(alice, suffix, "alice3")
        home_id = await create_home(alice, "Alice's Home")
        await login_operator(admin)
        response = await bulk_action(admin, "users", [alice_id], "disable")
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            membership = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(home_id),
                    Membership.user_id == uuid.UUID(alice_id),
                )
            )
            assert membership is not None
            assert membership.removed_at is None


@pytest.mark.asyncio
async def test_bulk_archive_active_users() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        alice_id = await register_user(alice, suffix, "alice4")
        await login_operator(admin)

        response = await bulk_action(admin, "users", [alice_id], "archive")
        assert response.status_code == 200, response.text
        assert response.json()["succeeded"] == [alice_id]

        async with SessionFactory() as db:
            row = await db.get(User, uuid.UUID(alice_id))
            assert row is not None
            assert row.is_active is False
            assert row.archived_at is not None


@pytest.mark.asyncio
async def test_bulk_disable_and_archive_report_distinct_lifecycles() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as bob,
        admin_client_instance() as admin,
    ):
        alice_id = await register_user(alice, suffix, "alice5")
        bob_id = await register_user(bob, suffix, "bob5")
        await login_operator(admin)
        await bulk_action(admin, "users", [alice_id], "disable")
        await bulk_action(admin, "users", [bob_id], "archive")

        disabled_page = await admin.get("/api/v1/platform/users?lifecycle=disabled&page_size=100")
        archived_page = await admin.get("/api/v1/platform/users?lifecycle=archived&page_size=100")
        assert alice_id in {item["id"] for item in disabled_page.json()["items"]}
        assert alice_id not in {item["id"] for item in archived_page.json()["items"]}
        assert bob_id in {item["id"] for item in archived_page.json()["items"]}
        assert bob_id not in {item["id"] for item in disabled_page.json()["items"]}


@pytest.mark.asyncio
async def test_bulk_disable_reports_already_archived_as_failure() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as bob,
        admin_client_instance() as admin,
    ):
        alice_id = await register_user(alice, suffix, "alice6")
        bob_id = await register_user(bob, suffix, "bob6")
        await login_operator(admin)
        await bulk_action(admin, "users", [alice_id], "archive")

        response = await bulk_action(admin, "users", [alice_id, bob_id], "disable")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["succeeded"] == [bob_id]
        assert len(body["failed"]) == 1
        assert body["failed"][0]["id"] == alice_id
        assert body["failed"][0]["code"] == "archived"

        # The already-archived record was not disturbed, and the valid
        # target still succeeded — one bad id doesn't roll back the batch.
        async with SessionFactory() as db:
            alice_row = await db.get(User, uuid.UUID(alice_id))
            bob_row = await db.get(User, uuid.UUID(bob_id))
            assert alice_row is not None and alice_row.archived_at is not None
            assert bob_row is not None
            assert bob_row.is_active is False
            assert bob_row.archived_at is None


@pytest.mark.asyncio
async def test_bulk_archive_is_idempotent_on_an_already_archived_user() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        alice_id = await register_user(alice, suffix, "alice7")
        await login_operator(admin)
        await bulk_action(admin, "users", [alice_id], "archive")

        response = await bulk_action(admin, "users", [alice_id], "archive")
        assert response.status_code == 200, response.text
        assert response.json()["succeeded"] == [alice_id]
        assert response.json()["failed"] == []


@pytest.mark.asyncio
async def test_bulk_user_reports_not_found_target() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        alice_id = await register_user(alice, suffix, "alice8")
        await login_operator(admin)
        missing_id = str(uuid.uuid4())

        response = await bulk_action(admin, "users", [alice_id, missing_id], "disable")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["succeeded"] == [alice_id]
        assert body["failed"] == [
            {"id": missing_id, "code": "not_found", "message": "That user could not be found."}
        ]


@pytest.mark.asyncio
async def test_bulk_user_writes_one_audit_event_per_target() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as bob,
        admin_client_instance() as admin,
    ):
        alice_id = await register_user(alice, suffix, "alice9")
        bob_id = await register_user(bob, suffix, "bob9")
        await login_operator(admin)
        response = await bulk_action(
            admin, "users", [alice_id, bob_id], "archive", reason="Removing stale demo accounts"
        )
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            events = (
                await db.scalars(
                    select(AdministrativeAuditEvent).where(
                        AdministrativeAuditEvent.action == "user.archived",
                        AdministrativeAuditEvent.target_id.in_(
                            [uuid.UUID(alice_id), uuid.UUID(bob_id)]
                        ),
                    )
                )
            ).all()
            assert len(events) == 2
            for event in events:
                assert event.reason == "Removing stale demo accounts"
                assert event.new_values["lifecycle"] == "archived"
                assert "batch_id" in event.new_values


@pytest.mark.asyncio
async def test_bulk_user_rejects_over_limit_batch() -> None:
    async with admin_client_instance() as admin:
        await login_operator(admin)
        ids = [str(uuid.uuid4()) for _ in range(101)]
        response = await bulk_action(admin, "users", ids, "disable")
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_bulk_user_rejects_empty_batch() -> None:
    async with admin_client_instance() as admin:
        await login_operator(admin)
        response = await bulk_action(admin, "users", [], "disable")
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_bulk_user_lifecycle_requires_platform_authentication() -> None:
    async with admin_client_instance() as admin:
        response = await bulk_action(admin, "users", [str(uuid.uuid4())], "disable")
        assert response.status_code in (401, 403, 404)


@pytest.mark.asyncio
async def test_bulk_user_lifecycle_requires_recent_auth() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        alice_id = await register_user(alice, suffix, "alice10")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        async with SessionFactory() as db:
            await db.execute(
                update(PlatformSession)
                .where(PlatformSession.administrator_id == operator.id)
                .values(authenticated_at=datetime.now(UTC) - timedelta(hours=1))
            )
            await db.commit()

        response = await bulk_action(admin, "users", [alice_id], "disable")
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Homes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_disable_active_homes() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        alice_id = await register_user(alice, suffix, "home-alice1")
        home_a = await create_home(alice, "Home A")
        home_b = await create_home(alice, "Home B")
        await login_operator(admin)

        response = await bulk_action(admin, "homes", [home_a, home_b], "disable")
        assert response.status_code == 200, response.text
        assert sorted(response.json()["succeeded"]) == sorted([home_a, home_b])

        async with SessionFactory() as db:
            for gid in (home_a, home_b):
                row = await db.get(Group, uuid.UUID(gid))
                assert row is not None
                assert row.is_active is False
                assert row.archived_at is None
            # The member's own account is never touched by a Home bulk action.
            user_row = await db.get(User, uuid.UUID(alice_id))
            assert user_row is not None
            assert user_row.is_active is True


@pytest.mark.asyncio
async def test_bulk_archive_active_homes_preserves_membership_and_content() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        alice_id = await register_user(alice, suffix, "home-alice2")
        home_id = await create_home(alice, "Duplicate Test Home")
        await login_operator(admin)

        response = await bulk_action(admin, "homes", [home_id], "archive")
        assert response.status_code == 200, response.text
        assert response.json()["succeeded"] == [home_id]

        async with SessionFactory() as db:
            group = await db.get(Group, uuid.UUID(home_id))
            assert group is not None
            assert group.is_active is False
            assert group.archived_at is not None
            membership = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(home_id),
                    Membership.user_id == uuid.UUID(alice_id),
                )
            )
            assert membership is not None
            assert membership.removed_at is None


@pytest.mark.asyncio
async def test_bulk_archive_a_disabled_home_is_allowed() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await register_user(alice, suffix, "home-alice3")
        home_id = await create_home(alice, "Disabled Then Archived")
        await login_operator(admin)
        await bulk_action(admin, "homes", [home_id], "disable")

        response = await bulk_action(admin, "homes", [home_id], "archive")
        assert response.status_code == 200, response.text
        assert response.json()["succeeded"] == [home_id]

        async with SessionFactory() as db:
            group = await db.get(Group, uuid.UUID(home_id))
            assert group is not None
            assert group.archived_at is not None


@pytest.mark.asyncio
async def test_bulk_disable_reports_already_archived_home_as_failure() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await register_user(alice, suffix, "home-alice4")
        home_a = await create_home(alice, "Already Archived Home")
        home_b = await create_home(alice, "Still Active Home")
        await login_operator(admin)
        await bulk_action(admin, "homes", [home_a], "archive")

        response = await bulk_action(admin, "homes", [home_a, home_b], "disable")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["succeeded"] == [home_b]
        assert len(body["failed"]) == 1
        assert body["failed"][0]["id"] == home_a
        assert body["failed"][0]["code"] == "archived"

        async with SessionFactory() as db:
            home_a_row = await db.get(Group, uuid.UUID(home_a))
            assert home_a_row is not None
            assert home_a_row.archived_at is not None  # never demoted back to Disabled


@pytest.mark.asyncio
async def test_bulk_home_reports_not_found_target() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await register_user(alice, suffix, "home-alice5")
        home_id = await create_home(alice, "Real Home")
        await login_operator(admin)
        missing_id = str(uuid.uuid4())

        response = await bulk_action(admin, "homes", [home_id, missing_id], "archive")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["succeeded"] == [home_id]
        assert body["failed"] == [
            {"id": missing_id, "code": "not_found", "message": "That Home could not be found."}
        ]


@pytest.mark.asyncio
async def test_bulk_home_writes_one_audit_event_per_target() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await register_user(alice, suffix, "home-alice6")
        home_a = await create_home(alice, "Home A6")
        home_b = await create_home(alice, "Home B6")
        await login_operator(admin)
        response = await bulk_action(
            admin, "homes", [home_a, home_b], "archive", reason="Removing duplicate test Homes"
        )
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            events = (
                await db.scalars(
                    select(AdministrativeAuditEvent).where(
                        AdministrativeAuditEvent.action == "home.archived",
                        AdministrativeAuditEvent.target_id.in_(
                            [uuid.UUID(home_a), uuid.UUID(home_b)]
                        ),
                    )
                )
            ).all()
            assert len(events) == 2
            for event in events:
                assert event.reason == "Removing duplicate test Homes"
                assert event.new_values["lifecycle"] == "archived"


@pytest.mark.asyncio
async def test_bulk_home_rejects_over_limit_batch() -> None:
    async with admin_client_instance() as admin:
        await login_operator(admin)
        ids = [str(uuid.uuid4()) for _ in range(101)]
        response = await bulk_action(admin, "homes", ids, "archive")
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_bulk_home_lifecycle_requires_platform_authentication() -> None:
    async with admin_client_instance() as admin:
        response = await bulk_action(admin, "homes", [str(uuid.uuid4())], "archive")
        assert response.status_code in (401, 403, 404)


# ---------------------------------------------------------------------------
# State invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_actions_never_leave_is_active_true_with_archived_at_set() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        alice_id = await register_user(alice, suffix, "invariant-alice")
        home_id = await create_home(alice, "Invariant Home")
        await login_operator(admin)

        await bulk_action(admin, "users", [alice_id], "disable")
        await bulk_action(admin, "users", [alice_id], "archive")
        await bulk_action(admin, "homes", [home_id], "disable")
        await bulk_action(admin, "homes", [home_id], "archive")

        async with SessionFactory() as db:
            user_row = await db.get(User, uuid.UUID(alice_id))
            group_row = await db.get(Group, uuid.UUID(home_id))
            assert user_row is not None and group_row is not None
            assert not (user_row.is_active and user_row.archived_at is not None)
            assert not (group_row.is_active and group_row.archived_at is not None)
