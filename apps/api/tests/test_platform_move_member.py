"""PCC "Move member" (Slice 2) — moving an existing user's active membership
from one Home to another without recreating the account.

Combines both established test patterns in this suite: the real consumer
API (test_journey.create_verified_user / POST /groups) to set up realistic
Users/Homes/memberships, and the real PCC admin API (test_platform_control_
centre.login / admin_client) to drive the move — rather than hand-crafting
ORM rows that could silently skip a side effect (HomeSubscription creation,
Personal Calendar, member colour) the real endpoints already handle.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    Group,
    HomeJoinRequest,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    PlatformRole,
    Role,
    Session,
    SubscriptionPlan,
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
    # Same trusted-proxy peer/X-Forwarded-For shape as
    # test_platform_control_centre.py's own admin_client fixture — PCC
    # routes are gated by enforce_admin_network/resolve_admin_client_ip,
    # which fail closed (404) for any request that doesn't look like it
    # came through the trusted admin proxy.
    return AsyncClient(
        transport=ASGITransport(app=app, client=(TEST_PROXY_PEER, 44000)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN, "X-Forwarded-For": TEST_CLIENT_IP},
    )


async def create_home(client: AsyncClient, name: str) -> str:
    response = await consumer_unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _upgrade_to_family(home_id: str) -> None:
    # New Homes default to the Free plan (max_members=1) — tests that move a
    # second active member into a destination Home need it upgraded first,
    # same pattern as test_household_controls.py.
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()


async def move_member_request(
    admin: AsyncClient,
    user_id: str,
    source_group_id: str,
    destination_group_id: str,
    relationship: str = "partner",
    source_disposition: str = "leave",
    reason: str = "Reconciling a duplicate-Home support ticket",
) -> object:
    return await admin_unsafe(
        admin,
        "POST",
        f"/api/v1/platform/users/{user_id}/move-home",
        json={
            "source_group_id": source_group_id,
            "destination_group_id": destination_group_id,
            "destination_relationship": relationship,
            "source_disposition": source_disposition,
            "reason": reason,
            "confirmed": True,
        },
    )


@pytest.mark.asyncio
async def test_successful_move_retains_user_id_and_transfers_membership() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await _upgrade_to_family(hales_home_id)

        await create_verified_user(carol, f"mv-carol-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_me = await carol.get("/api/v1/users/me")
        carol_user_id = carol_me.json()["id"]

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(admin, carol_user_id, carol_home_id, hales_home_id)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["user_id"] == carol_user_id
        assert body["relationship"] == "partner"
        assert body["role"] == "adult_member"
        assert body["source_disposition"] in ("archived_empty", "left_unchanged")

        async with SessionFactory() as db:
            source_membership = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(carol_home_id),
                    Membership.user_id == uuid.UUID(carol_user_id),
                )
            )
            assert source_membership is not None
            assert source_membership.removed_at is not None

            destination_membership = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(hales_home_id),
                    Membership.user_id == uuid.UUID(carol_user_id),
                )
            )
            assert destination_membership is not None
            assert destination_membership.removed_at is None
            assert destination_membership.relationship.value == "partner"
            assert destination_membership.role.value == "adult_member"

            # Same User row, same id, same auth material — never recreated.
            user_row = await db.get(User, uuid.UUID(carol_user_id))
            assert user_row is not None
            assert user_row.id == uuid.UUID(carol_user_id)
            assert user_row.is_active is True


@pytest.mark.asyncio
async def test_move_leaves_a_default_source_disposition_home_active_when_not_requested() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice2-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await _upgrade_to_family(hales_home_id)
        await create_verified_user(carol, f"mv-carol2-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(
            admin, carol_user_id, carol_home_id, hales_home_id, source_disposition="leave"
        )
        assert response.status_code == 200, response.text
        assert response.json()["source_disposition"] == "left_unchanged"

        async with SessionFactory() as db:
            source_group = await db.get(Group, uuid.UUID(carol_home_id))
            assert source_group is not None
            assert source_group.is_active is True


@pytest.mark.asyncio
async def test_archive_if_empty_archives_only_when_source_becomes_empty() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice3-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await _upgrade_to_family(hales_home_id)
        await create_verified_user(carol, f"mv-carol3-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(
            admin,
            carol_user_id,
            carol_home_id,
            hales_home_id,
            source_disposition="archive_if_empty",
        )
        assert response.status_code == 200, response.text
        assert response.json()["source_disposition"] == "archived_empty"

        async with SessionFactory() as db:
            source_group = await db.get(Group, uuid.UUID(carol_home_id))
            assert source_group is not None
            assert source_group.is_active is False
            assert source_group.suspended_at is not None
            assert source_group.archived_at is not None


@pytest.mark.asyncio
async def test_archive_if_empty_does_not_archive_a_home_with_remaining_members() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        consumer_client() as dave,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice4-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await create_verified_user(carol, f"mv-carol4-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        # A second member in Carol Home — Carol is Home Admin, Dave is a
        # Partner, so Carol is not the sole admin and the source Home is not
        # empty after Carol moves.
        await create_verified_user(dave, f"mv-dave4-{suffix}@example.com", "Dave")
        dave_user_id = (await dave.get("/api/v1/users/me")).json()["id"]
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=uuid.UUID(carol_home_id),
                    user_id=uuid.UUID(dave_user_id),
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(
            admin,
            carol_user_id,
            carol_home_id,
            hales_home_id,
            relationship="partner",
            source_disposition="archive_if_empty",
        )
        # Carol is the sole Home Admin with another active member remaining
        # — blocked, per the last-admin protection, before disposition even
        # matters.
        assert response.status_code == 409, response.text

        async with SessionFactory() as db:
            source_group = await db.get(Group, uuid.UUID(carol_home_id))
            assert source_group is not None
            assert source_group.is_active is True


@pytest.mark.asyncio
async def test_blocks_moving_the_sole_home_admin_while_other_members_remain() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        consumer_client() as dave,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice5-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await create_verified_user(carol, f"mv-carol5-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]
        await create_verified_user(dave, f"mv-dave5-{suffix}@example.com", "Dave")
        dave_user_id = (await dave.get("/api/v1/users/me")).json()["id"]
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=uuid.UUID(carol_home_id),
                    user_id=uuid.UUID(dave_user_id),
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(admin, carol_user_id, carol_home_id, hales_home_id)
        assert response.status_code == 409
        assert "Home Admin" in response.text

        async with SessionFactory() as db:
            membership = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(carol_home_id),
                    Membership.user_id == uuid.UUID(carol_user_id),
                )
            )
            assert membership is not None
            assert membership.removed_at is None
            no_destination_row = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(hales_home_id),
                    Membership.user_id == uuid.UUID(carol_user_id),
                )
            )
            assert no_destination_row is None


@pytest.mark.asyncio
async def test_blocks_moving_a_user_already_active_in_destination() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice6-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await create_verified_user(carol, f"mv-carol6-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        # Carol already has an active membership at the destination.
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=uuid.UUID(hales_home_id),
                    user_id=uuid.UUID(carol_user_id),
                    role=Role.guest,
                    relationship=HouseholdRelationship.friend,
                    permission_profile=PermissionProfile.explicit_sharing,
                )
            )
            await db.commit()

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(admin, carol_user_id, carol_home_id, hales_home_id)
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_reactivates_historical_destination_membership_instead_of_duplicating() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice7-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await _upgrade_to_family(hales_home_id)
        await create_verified_user(carol, f"mv-carol7-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        # A historical (soft-removed) membership already exists at the
        # destination — the unique (group_id, user_id) constraint means a
        # blind INSERT here would fail; the endpoint must reactivate it.
        historical_membership_id = uuid.uuid4()
        async with SessionFactory() as db:
            db.add(
                Membership(
                    id=historical_membership_id,
                    group_id=uuid.UUID(hales_home_id),
                    user_id=uuid.UUID(carol_user_id),
                    role=Role.guest,
                    relationship=HouseholdRelationship.friend,
                    permission_profile=PermissionProfile.explicit_sharing,
                    removed_at=datetime.now(UTC),
                )
            )
            await db.commit()

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(
            admin, carol_user_id, carol_home_id, hales_home_id, relationship="adult"
        )
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            rows = (
                await db.scalars(
                    select(Membership).where(
                        Membership.group_id == uuid.UUID(hales_home_id),
                        Membership.user_id == uuid.UUID(carol_user_id),
                    )
                )
            ).all()
            # Exactly one row for this (group, user) pair — the historical
            # row was reused, not duplicated.
            assert len(rows) == 1
            assert rows[0].id == historical_membership_id
            assert rows[0].removed_at is None
            assert rows[0].relationship.value == "adult"


@pytest.mark.asyncio
async def test_blocks_move_from_a_source_membership_that_is_not_active() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice8-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await create_verified_user(carol, f"mv-carol8-{suffix}@example.com", "Carol")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]
        other_home_id = await create_home(alice, "Some Other Home")

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        # Carol is not a member of "Some Other Home" at all.
        response = await move_member_request(admin, carol_user_id, other_home_id, hales_home_id)
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_blocks_move_to_an_inactive_destination_home() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice9-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await create_verified_user(carol, f"mv-carol9-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        async with SessionFactory() as db:
            group = await db.get(Group, uuid.UUID(hales_home_id))
            assert group is not None
            group.is_active = False
            await db.commit()

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(admin, carol_user_id, carol_home_id, hales_home_id)
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_enforces_destination_member_limit() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice10-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await create_verified_user(carol, f"mv-carol10-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        # Hales Home is Free (max_members=1) and already has Alice.
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(admin, carol_user_id, carol_home_id, hales_home_id)
        assert response.status_code in (402, 403, 409, 422)

        async with SessionFactory() as db:
            no_destination_row = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(hales_home_id),
                    Membership.user_id == uuid.UUID(carol_user_id),
                )
            )
            assert no_destination_row is None


@pytest.mark.asyncio
async def test_blocks_move_when_user_is_billing_owner_of_a_non_free_source_subscription() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice11-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await _upgrade_to_family(hales_home_id)
        await create_verified_user(carol, f"mv-carol11-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        async with SessionFactory() as db:
            subscription = await get_home_subscription(db, uuid.UUID(carol_home_id))
            assert subscription is not None
            subscription.plan = SubscriptionPlan.family
            subscription.billing_owner_user_id = uuid.UUID(carol_user_id)
            await db.commit()

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(admin, carol_user_id, carol_home_id, hales_home_id)
        assert response.status_code == 409
        assert "billing" in response.text.lower()

        async with SessionFactory() as db:
            source_membership = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(carol_home_id),
                    Membership.user_id == uuid.UUID(carol_user_id),
                )
            )
            assert source_membership is not None
            assert source_membership.removed_at is None


@pytest.mark.asyncio
async def test_pending_destination_join_request_is_resolved_not_left_dangling() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice12-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await _upgrade_to_family(hales_home_id)
        await create_verified_user(carol, f"mv-carol12-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        async with SessionFactory() as db:
            db.add(
                HomeJoinRequest(
                    group_id=uuid.UUID(hales_home_id),
                    user_id=uuid.UUID(carol_user_id),
                    method="join_code",
                )
            )
            await db.commit()

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(admin, carol_user_id, carol_home_id, hales_home_id)
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            request_row = await db.scalar(
                select(HomeJoinRequest).where(
                    HomeJoinRequest.group_id == uuid.UUID(hales_home_id),
                    HomeJoinRequest.user_id == uuid.UUID(carol_user_id),
                )
            )
            assert request_row is not None
            assert request_row.status.value == "cancelled"


@pytest.mark.asyncio
async def test_audit_event_is_written_with_source_and_destination_detail() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice13-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await _upgrade_to_family(hales_home_id)
        await create_verified_user(carol, f"mv-carol13-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)

        response = await move_member_request(
            admin,
            carol_user_id,
            carol_home_id,
            hales_home_id,
            reason="Merging duplicate Home per support ticket #4821",
        )
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            event = await db.scalar(
                select(AdministrativeAuditEvent)
                .where(
                    AdministrativeAuditEvent.administrator_id == operator.id,
                    AdministrativeAuditEvent.action == "member.moved",
                )
                .order_by(AdministrativeAuditEvent.created_at.desc())
            )
            assert event is not None
            assert event.target_id == uuid.UUID(carol_user_id)
            assert event.reason == "Merging duplicate Home per support ticket #4821"
            assert event.previous_values["source_group_id"] == carol_home_id
            assert event.new_values["destination_group_id"] == hales_home_id
            assert event.new_values["relationship"] == "partner"


@pytest.mark.asyncio
async def test_move_does_not_touch_sessions_devices_or_account_credentials() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice14-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await _upgrade_to_family(hales_home_id)
        await create_verified_user(carol, f"mv-carol14-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        async with SessionFactory() as db:
            active_sessions_before = (
                await db.scalars(
                    select(Session).where(
                        Session.user_id == uuid.UUID(carol_user_id), Session.revoked_at.is_(None)
                    )
                )
            ).all()
            assert len(active_sessions_before) >= 1

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        response = await move_member_request(admin, carol_user_id, carol_home_id, hales_home_id)
        assert response.status_code == 200, response.text

        # Carol's own session is untouched — she is still signed in and can
        # keep using the app immediately, now against Hales Home.
        me_after = await carol.get("/api/v1/users/me")
        assert me_after.status_code == 200
        assert me_after.json()["id"] == carol_user_id

        async with SessionFactory() as db:
            active_sessions_after = (
                await db.scalars(
                    select(Session).where(
                        Session.user_id == uuid.UUID(carol_user_id), Session.revoked_at.is_(None)
                    )
                )
            ).all()
            assert len(active_sessions_after) == len(active_sessions_before)
            revoked_devices = (
                await db.scalars(
                    select(TrustedDevice).where(
                        TrustedDevice.user_id == uuid.UUID(carol_user_id),
                        TrustedDevice.revoked_at.is_not(None),
                    )
                )
            ).all()
            assert revoked_devices == []


@pytest.mark.asyncio
async def test_transaction_rollback_leaves_no_partial_membership_state() -> None:
    """Moving into an inactive destination fails validation before any
    membership row is touched — this is the same "fail before modifying
    either membership" behaviour item 11 requires, verified from the data
    side rather than by injecting a mid-transaction fault."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as carol,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"mv-alice15-{suffix}@example.com", "Alice")
        hales_home_id = await create_home(alice, "Hales Home")
        await create_verified_user(carol, f"mv-carol15-{suffix}@example.com", "Carol")
        carol_home_id = await create_home(carol, "Carol Home")
        carol_user_id = (await carol.get("/api/v1/users/me")).json()["id"]

        async with SessionFactory() as db:
            group = await db.get(Group, uuid.UUID(hales_home_id))
            assert group is not None
            group.is_active = False
            await db.commit()

        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        response = await move_member_request(admin, carol_user_id, carol_home_id, hales_home_id)
        assert response.status_code == 422

        async with SessionFactory() as db:
            source_membership = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(carol_home_id),
                    Membership.user_id == uuid.UUID(carol_user_id),
                )
            )
            assert source_membership is not None
            assert source_membership.removed_at is None
            destination_row = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(hales_home_id),
                    Membership.user_id == uuid.UUID(carol_user_id),
                )
            )
            assert destination_row is None
