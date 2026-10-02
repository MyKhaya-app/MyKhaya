"""Slice 3 — the Archived lifecycle state for Users and Homes (migration
0053_lifecycle_archived_state). Active/Disabled/Archived semantics:

    Active:   is_active = true,  archived_at IS NULL
    Disabled: is_active = false, archived_at IS NULL
    Archived: is_active = false, archived_at IS NOT NULL

Reuses the same real-endpoint test pattern as test_platform_move_member.py:
the consumer API to create realistic Users/Homes, the PCC admin API to drive
archive/restore.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from test_journey import PASSWORD as CONSUMER_PASSWORD
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
    HouseholdRelationship,
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


async def admin_action(
    admin: AsyncClient, path: str, reason: str = "Slice 3 lifecycle test"
) -> object:
    return await admin_unsafe(admin, "POST", path, json={"reason": reason, "confirmed": True})


# ---------------------------------------------------------------------------
# User archive/restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_user_sets_archived_at_and_disables() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-alice1-{suffix}@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await admin_action(admin, f"/api/v1/platform/users/{user_id}/archive")
        assert response.status_code == 200, response.text

        detail = await admin.get(f"/api/v1/platform/users/{user_id}")
        body = detail.json()
        assert body["active"] is False
        assert body["lifecycle"] == "archived"

        async with SessionFactory() as db:
            row = await db.get(User, uuid.UUID(user_id))
            assert row is not None
            assert row.is_active is False
            assert row.archived_at is not None


@pytest.mark.asyncio
async def test_archive_user_revokes_sessions_and_trusted_devices() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-alice2-{suffix}@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        async with SessionFactory() as db:
            db.add(
                TrustedDevice(
                    user_id=uuid.UUID(user_id),
                    token_hash=f"test-device-hash-{suffix}",
                    device_name="Alice's iPhone",
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                )
            )
            await db.commit()

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        response = await admin_action(admin, f"/api/v1/platform/users/{user_id}/archive")
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            active_sessions = (
                await db.scalars(
                    select(Session).where(
                        Session.user_id == uuid.UUID(user_id), Session.revoked_at.is_(None)
                    )
                )
            ).all()
            assert active_sessions == []
            active_devices = (
                await db.scalars(
                    select(TrustedDevice).where(
                        TrustedDevice.user_id == uuid.UUID(user_id),
                        TrustedDevice.revoked_at.is_(None),
                    )
                )
            ).all()
            assert active_devices == []


@pytest.mark.asyncio
async def test_archived_user_cannot_authenticate() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"arc-alice3-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/users/{user_id}/archive")

    async with consumer_client() as fresh:
        login_response = await consumer_unsafe(
            fresh,
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": CONSUMER_PASSWORD},
        )
        assert login_response.status_code == 401


@pytest.mark.asyncio
async def test_archived_user_memberships_and_history_retained() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-alice4-{suffix}@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/users/{user_id}/archive")

        async with SessionFactory() as db:
            membership = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(home_id),
                    Membership.user_id == uuid.UUID(user_id),
                )
            )
            assert membership is not None
            assert membership.removed_at is None
            user_row = await db.get(User, uuid.UUID(user_id))
            assert user_row is not None
            assert user_row.email == f"arc-alice4-{suffix}@example.com"
            assert user_row.display_name == "Alice"


@pytest.mark.asyncio
async def test_archived_user_appears_in_archived_filter_and_not_active() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-alice5-{suffix}@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/users/{user_id}/archive")

        archived_page = await admin.get("/api/v1/platform/users?lifecycle=archived&page_size=100")
        active_page = await admin.get("/api/v1/platform/users?lifecycle=active&page_size=100")
        disabled_page = await admin.get("/api/v1/platform/users?lifecycle=disabled&page_size=100")

        archived_ids = {item["id"] for item in archived_page.json()["items"]}
        active_ids = {item["id"] for item in active_page.json()["items"]}
        disabled_ids = {item["id"] for item in disabled_page.json()["items"]}
        assert user_id in archived_ids
        assert user_id not in active_ids
        assert user_id not in disabled_ids


@pytest.mark.asyncio
async def test_disabled_user_is_distinct_from_archived_user() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as bob, admin_client_instance() as admin:
        await create_verified_user(bob, f"arc-bob1-{suffix}@example.com", "Bob")
        user_id = (await bob.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/users/{user_id}/suspend")

        detail = (await admin.get(f"/api/v1/platform/users/{user_id}")).json()
        assert detail["lifecycle"] == "disabled"

        disabled_page = await admin.get("/api/v1/platform/users?lifecycle=disabled&page_size=100")
        archived_page = await admin.get("/api/v1/platform/users?lifecycle=archived&page_size=100")
        assert user_id in {item["id"] for item in disabled_page.json()["items"]}
        assert user_id not in {item["id"] for item in archived_page.json()["items"]}


@pytest.mark.asyncio
async def test_existing_reactivate_cannot_reactivate_an_archived_user() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-alice6-{suffix}@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/users/{user_id}/archive")

        response = await admin_action(admin, f"/api/v1/platform/users/{user_id}/reactivate")
        assert response.status_code == 409
        assert "restore" in response.text.lower()

        async with SessionFactory() as db:
            row = await db.get(User, uuid.UUID(user_id))
            assert row is not None
            assert row.is_active is False
            assert row.archived_at is not None


@pytest.mark.asyncio
async def test_restore_returns_an_archived_user_to_active() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-alice7-{suffix}@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/users/{user_id}/archive")

        response = await admin_action(admin, f"/api/v1/platform/users/{user_id}/restore")
        assert response.status_code == 200, response.text

        detail = (await admin.get(f"/api/v1/platform/users/{user_id}")).json()
        assert detail["lifecycle"] == "active"
        assert detail["active"] is True

        async with SessionFactory() as db:
            row = await db.get(User, uuid.UUID(user_id))
            assert row is not None
            assert row.is_active is True
            assert row.archived_at is None
            assert row.suspended_at is None


@pytest.mark.asyncio
async def test_restored_user_remains_logged_out_until_authenticating_again() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"arc-alice8-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/users/{user_id}/archive")
        await admin_action(admin, f"/api/v1/platform/users/{user_id}/restore")

        # Alice's original (pre-archive) session cookie was revoked when
        # archived and restoring does not resurrect it.
        stale_check = await alice.get("/api/v1/users/me")
        assert stale_check.status_code == 401

    async with consumer_client() as fresh:
        login_response = await consumer_unsafe(
            fresh,
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": CONSUMER_PASSWORD},
        )
        assert login_response.status_code == 200


@pytest.mark.asyncio
async def test_restore_rejects_a_user_that_is_not_archived() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-alice9-{suffix}@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await admin_action(admin, f"/api/v1/platform/users/{user_id}/restore")
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_user_archive_and_restore_write_audit_events() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-alice10-{suffix}@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        await admin_action(
            admin, f"/api/v1/platform/users/{user_id}/archive", reason="Duplicate test account"
        )
        await admin_action(
            admin, f"/api/v1/platform/users/{user_id}/restore", reason="Restoring by request"
        )

        async with SessionFactory() as db:
            archive_event = await db.scalar(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.action == "user.archived",
                    AdministrativeAuditEvent.target_id == uuid.UUID(user_id),
                )
            )
            assert archive_event is not None
            assert archive_event.reason == "Duplicate test account"
            assert archive_event.new_values["lifecycle"] == "archived"

            restore_event = await db.scalar(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.action == "user.restored",
                    AdministrativeAuditEvent.target_id == uuid.UUID(user_id),
                )
            )
            assert restore_event is not None
            assert restore_event.reason == "Restoring by request"
            assert restore_event.previous_values["lifecycle"] == "archived"
            assert restore_event.new_values["lifecycle"] == "active"


# ---------------------------------------------------------------------------
# Home archive/restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_home_sets_archived_at_and_disables() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-home-alice1-{suffix}@example.com", "Alice")
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await admin_action(admin, f"/api/v1/platform/homes/{home_id}/archive")
        assert response.status_code == 200, response.text

        detail = (await admin.get(f"/api/v1/platform/homes/{home_id}")).json()
        assert detail["active"] is False
        assert detail["lifecycle"] == "archived"

        async with SessionFactory() as db:
            group = await db.get(Group, uuid.UUID(home_id))
            assert group is not None
            assert group.is_active is False
            assert group.archived_at is not None


@pytest.mark.asyncio
async def test_archive_home_leaves_member_user_accounts_active() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-home-alice2-{suffix}@example.com", "Alice")
        alice_id = (await alice.get("/api/v1/users/me")).json()["id"]
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/homes/{home_id}/archive")

        async with SessionFactory() as db:
            user_row = await db.get(User, uuid.UUID(alice_id))
            assert user_row is not None
            assert user_row.is_active is True
            assert user_row.archived_at is None
            membership = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(home_id),
                    Membership.user_id == uuid.UUID(alice_id),
                )
            )
            assert membership is not None
            assert membership.removed_at is None

        # Alice's own account still works normally.
        me = await alice.get("/api/v1/users/me")
        assert me.status_code == 200


@pytest.mark.asyncio
async def test_archived_home_is_inaccessible_for_normal_use() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-home-alice3-{suffix}@example.com", "Alice")
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/homes/{home_id}/archive")

        members_response = await alice.get(f"/api/v1/groups/{home_id}/members")
        assert members_response.status_code == 404


@pytest.mark.asyncio
async def test_homes_archived_filter_excludes_active_and_disabled() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-home-alice4-{suffix}@example.com", "Alice")
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/homes/{home_id}/archive")

        archived_page = await admin.get("/api/v1/platform/homes?lifecycle=archived&page_size=100")
        active_page = await admin.get("/api/v1/platform/homes?lifecycle=active&page_size=100")
        disabled_page = await admin.get("/api/v1/platform/homes?lifecycle=disabled&page_size=100")
        assert home_id in {item["id"] for item in archived_page.json()["items"]}
        assert home_id not in {item["id"] for item in active_page.json()["items"]}
        assert home_id not in {item["id"] for item in disabled_page.json()["items"]}


@pytest.mark.asyncio
async def test_existing_reactivate_cannot_reactivate_an_archived_home() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-home-alice5-{suffix}@example.com", "Alice")
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/homes/{home_id}/archive")

        response = await admin_action(admin, f"/api/v1/platform/homes/{home_id}/reactivate")
        assert response.status_code == 409
        assert "restore" in response.text.lower()


@pytest.mark.asyncio
async def test_restore_returns_an_archived_home_to_active() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-home-alice6-{suffix}@example.com", "Alice")
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/homes/{home_id}/archive")

        response = await admin_action(admin, f"/api/v1/platform/homes/{home_id}/restore")
        assert response.status_code == 200, response.text

        detail = (await admin.get(f"/api/v1/platform/homes/{home_id}")).json()
        assert detail["lifecycle"] == "active"

        # Normal Home access resumes immediately.
        members_response = await alice.get(f"/api/v1/groups/{home_id}/members")
        assert members_response.status_code == 200


@pytest.mark.asyncio
async def test_restore_home_blocked_without_a_home_admin() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-home-alice7-{suffix}@example.com", "Alice")
        alice_id = (await alice.get("/api/v1/users/me")).json()["id"]
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await admin_action(admin, f"/api/v1/platform/homes/{home_id}/archive")

        # Simulate the sole Home Admin's relationship having been downgraded
        # (e.g. by a subsequent administrative correction) while archived,
        # leaving an active member with no Home Admin at all.
        async with SessionFactory() as db:
            await db.execute(
                update(Membership)
                .where(
                    Membership.group_id == uuid.UUID(home_id),
                    Membership.user_id == uuid.UUID(alice_id),
                )
                .values(relationship=HouseholdRelationship.partner)
            )
            await db.commit()

        response = await admin_action(admin, f"/api/v1/platform/homes/{home_id}/restore")
        assert response.status_code == 409

        async with SessionFactory() as db:
            group = await db.get(Group, uuid.UUID(home_id))
            assert group is not None
            assert group.is_active is False
            assert group.archived_at is not None


@pytest.mark.asyncio
async def test_restore_home_rejects_a_home_that_is_not_archived() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-home-alice8-{suffix}@example.com", "Alice")
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await admin_action(admin, f"/api/v1/platform/homes/{home_id}/restore")
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_home_archive_and_restore_write_audit_events() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-home-alice9-{suffix}@example.com", "Alice")
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        await admin_action(
            admin, f"/api/v1/platform/homes/{home_id}/archive", reason="Duplicate test Home"
        )
        await admin_action(
            admin, f"/api/v1/platform/homes/{home_id}/restore", reason="Restoring by request"
        )

        async with SessionFactory() as db:
            archive_event = await db.scalar(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.action == "home.archived",
                    AdministrativeAuditEvent.target_id == uuid.UUID(home_id),
                )
            )
            assert archive_event is not None
            assert archive_event.reason == "Duplicate test Home"
            assert archive_event.new_values["lifecycle"] == "archived"

            restore_event = await db.scalar(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.action == "home.restored",
                    AdministrativeAuditEvent.target_id == uuid.UUID(home_id),
                )
            )
            assert restore_event is not None
            assert restore_event.reason == "Restoring by request"


# ---------------------------------------------------------------------------
# State invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_state_leaves_is_active_true_with_archived_at_set() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-invariant-{suffix}@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        home_id = await create_home(alice, "Alice's Home")
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        for path in (
            f"/api/v1/platform/users/{user_id}/suspend",
            f"/api/v1/platform/users/{user_id}/archive",
            f"/api/v1/platform/users/{user_id}/restore",
            f"/api/v1/platform/users/{user_id}/archive",
            f"/api/v1/platform/homes/{home_id}/archive",
            f"/api/v1/platform/homes/{home_id}/restore",
            f"/api/v1/platform/homes/{home_id}/archive",
        ):
            await admin_action(admin, path)

        async with SessionFactory() as db:
            user_row = await db.get(User, uuid.UUID(user_id))
            group_row = await db.get(Group, uuid.UUID(home_id))
            assert user_row is not None and group_row is not None
            assert not (user_row.is_active and user_row.archived_at is not None)
            assert not (group_row.is_active and group_row.archived_at is not None)


@pytest.mark.asyncio
async def test_archive_requires_recent_auth() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, f"arc-recentauth-{suffix}@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        async with SessionFactory() as db:
            await db.execute(
                update(PlatformSession)
                .where(PlatformSession.administrator_id == operator.id)
                .values(authenticated_at=datetime.now(UTC) - timedelta(hours=1))
            )
            await db.commit()

        response = await admin_action(admin, f"/api/v1/platform/users/{user_id}/archive")
        assert response.status_code == 403
