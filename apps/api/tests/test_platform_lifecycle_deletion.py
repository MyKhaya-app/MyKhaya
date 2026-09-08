"""Slice 5B — PCC User anonymisation and permanent deletion of genuinely
empty Archived Homes. Both are deliberately narrow: Archive remains the
normal cleanup mechanism (Slices 3/4); these two actions exist only for the
specific cases identified in the Slice 5A policy design (an account that
must stop existing identifiably, and a disposable test/duplicate Home with
no real history).
"""

import uuid
from datetime import UTC, date, datetime, timedelta

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
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    AuthIdentity,
    Group,
    HomeCalendar,
    HomeSubscriptionEvent,
    HouseholdRelationship,
    HouseholdRoutine,
    Invitation,
    ManagedDemoHome,
    ManagedDemoType,
    Membership,
    NativePushDevice,
    PermissionProfile,
    PlatformRole,
    PlatformSession,
    PushSubscription,
    Reminder,
    Role,
    RoutineScope,
    Session,
    SubscriptionPlan,
    TrustedDevice,
    User,
    UserPasskey,
)

CONSUMER_ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"


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


async def create_home(client: AsyncClient, name: str = "Deletion Test Home") -> str:
    response = await consumer_unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def login_operator(admin: AsyncClient) -> None:
    operator = await create_admin(PlatformRole.owner)
    await login(admin, operator)


async def admin_action(
    admin: AsyncClient, path: str, reason: str = "Slice 5B test", **extra: object
) -> object:
    return await admin_unsafe(
        admin, "POST", path, json={"reason": reason, "confirmed": True, **extra}
    )


async def archive_user_via_api(admin: AsyncClient, user_id: str) -> None:
    response = await admin_action(admin, f"/api/v1/platform/users/{user_id}/archive")
    assert response.status_code == 200, response.text


async def archive_home_via_api(admin: AsyncClient, home_id: str) -> None:
    response = await admin_action(admin, f"/api/v1/platform/homes/{home_id}/archive")
    assert response.status_code == 200, response.text


async def anonymise_request(
    admin: AsyncClient, user_id: str, confirmation_text: str, reason: str = "Slice 5B test"
) -> object:
    return await admin_unsafe(
        admin,
        "POST",
        f"/api/v1/platform/users/{user_id}/anonymise",
        json={
            "reason": reason,
            "confirmed": True,
            "confirmation_text": confirmation_text,
        },
    )


async def permanent_delete_home_request(
    admin: AsyncClient, home_id: str, confirmation_text: str, reason: str = "Slice 5B test"
) -> object:
    return await admin_unsafe(
        admin,
        "POST",
        f"/api/v1/platform/homes/{home_id}/permanent-delete",
        json={
            "reason": reason,
            "confirmed": True,
            "confirmation_text": confirmation_text,
        },
    )


# ---------------------------------------------------------------------------
# User anonymisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_user_cannot_anonymise() -> None:
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "anon-active@example.com", "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        await login_operator(admin)

        response = await anonymise_request(admin, user_id, "anon-active@example.com")
        assert response.status_code == 409
        assert "archived" in response.text.lower()


@pytest.mark.asyncio
async def test_disabled_user_cannot_anonymise_directly() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-disabled-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        await login_operator(admin)
        await admin_action(admin, f"/api/v1/platform/users/{user_id}/suspend")

        response = await anonymise_request(admin, user_id, email)
        assert response.status_code == 409
        assert "archived" in response.text.lower()


@pytest.mark.asyncio
async def test_archived_user_can_anonymise_and_becomes_deleted_user() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-ok-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        await login_operator(admin)
        await archive_user_via_api(admin, user_id)

        response = await anonymise_request(admin, user_id, email)
        assert response.status_code == 200, response.text

        detail = (await admin.get(f"/api/v1/platform/users/{user_id}")).json()
        assert detail["lifecycle"] == "anonymised"
        assert detail["active"] is False
        assert detail["display_name"] == "Deleted user"
        assert detail["email"] == f"deleted-{user_id}@removed.mykhaya.invalid"

        async with SessionFactory() as db:
            row = await db.get(User, uuid.UUID(user_id))
            assert row is not None
            assert row.id == uuid.UUID(user_id)
            assert row.anonymised_at is not None
            assert row.is_active is False
            assert row.birth_month is None
            assert row.birth_day is None
            assert row.birth_year is None


@pytest.mark.asyncio
async def test_already_anonymised_user_rejected() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-twice-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        await login_operator(admin)
        await archive_user_via_api(admin, user_id)
        first = await anonymise_request(admin, user_id, email)
        assert first.status_code == 200, first.text

        anonymised_email = f"deleted-{user_id}@removed.mykhaya.invalid"
        second = await anonymise_request(admin, user_id, anonymised_email)
        assert second.status_code == 409
        assert "already" in second.text.lower()


@pytest.mark.asyncio
async def test_confirmation_text_mismatch_blocks_anonymise() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-mismatch-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        await login_operator(admin)
        await archive_user_via_api(admin, user_id)

        response = await anonymise_request(admin, user_id, "wrong@example.com")
        assert response.status_code == 422

        async with SessionFactory() as db:
            row = await db.get(User, uuid.UUID(user_id))
            assert row is not None
            assert row.anonymised_at is None
            assert row.email == email  # untouched — failure rolled back cleanly


@pytest.mark.asyncio
async def test_anonymise_removes_auth_and_device_data() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-auth-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        uid = uuid.UUID(user_id)

        async with SessionFactory() as db:
            auth_identity = await db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == uid))
            assert auth_identity is not None
            db.add(
                UserPasskey(
                    user_id=uid,
                    credential_id=f"cred-{suffix}",
                    public_key="pk",
                    sign_count=0,
                    label="Test key",
                )
            )
            db.add(
                PushSubscription(
                    user_id=uid,
                    endpoint=f"https://push.example/{uuid.uuid4()}",
                    p256dh_key="abc",
                    auth_key="def",
                )
            )
            db.add(
                NativePushDevice(
                    user_id=uid,
                    platform="ios",
                    token=f"token-{suffix}",
                    installation_id=f"install-{suffix}",
                )
            )
            db.add(
                TrustedDevice(
                    user_id=uid,
                    token_hash=f"trusted-{suffix}",
                    device_name="Alice's iPad",
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                )
            )
            await db.commit()

        await login_operator(admin)
        await archive_user_via_api(admin, user_id)
        response = await anonymise_request(admin, user_id, email)
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            assert (
                await db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == uid))
            ) is None
            assert (
                await db.scalar(select(UserPasskey).where(UserPasskey.user_id == uid))
            ) is None
            assert (
                await db.scalar(select(PushSubscription).where(PushSubscription.user_id == uid))
            ) is None
            assert (
                await db.scalar(select(NativePushDevice).where(NativePushDevice.user_id == uid))
            ) is None
            active_sessions = (
                await db.scalars(
                    select(Session).where(Session.user_id == uid, Session.revoked_at.is_(None))
                )
            ).all()
            assert active_sessions == []
            active_devices = (
                await db.scalars(
                    select(TrustedDevice).where(
                        TrustedDevice.user_id == uid, TrustedDevice.revoked_at.is_(None)
                    )
                )
            ).all()
            assert active_devices == []

        # The old identity truly cannot authenticate again.
        async with consumer_client() as fresh:
            login_attempt = await consumer_unsafe(
                fresh, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
            )
            assert login_attempt.status_code == 401


@pytest.mark.asyncio
async def test_anonymise_soft_removes_active_memberships_but_keeps_history() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-member-{suffix}@example.com"
    async with (
        consumer_client() as alice,
        consumer_client() as bob,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, email, "Alice")
        alice_id = (await alice.get("/api/v1/users/me")).json()["id"]
        home_id = await create_home(alice, "Alice's Home")

        # A second member so Alice isn't the sole Home Admin — keeps this
        # test focused on membership-handling, not the last-admin blocker.
        await create_verified_user(bob, f"anon-bob-{suffix}@example.com", "Bob")
        bob_id = (await bob.get("/api/v1/users/me")).json()["id"]
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=uuid.UUID(home_id),
                    user_id=uuid.UUID(bob_id),
                    role=Role.owner,
                    relationship=HouseholdRelationship.home_admin,
                    permission_profile=PermissionProfile.home_admin,
                )
            )
            await db.commit()

        await login_operator(admin)
        await archive_user_via_api(admin, alice_id)
        response = await anonymise_request(admin, alice_id, email)
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            membership = await db.scalar(
                select(Membership).where(
                    Membership.group_id == uuid.UUID(home_id),
                    Membership.user_id == uuid.UUID(alice_id),
                )
            )
            assert membership is not None  # preserved, not deleted
            assert membership.removed_at is not None  # but no longer active
            assert membership.relationship == HouseholdRelationship.home_admin  # history intact


@pytest.mark.asyncio
async def test_last_home_admin_with_remaining_members_blocks_anonymise() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-lastadmin-{suffix}@example.com"
    async with (
        consumer_client() as alice,
        consumer_client() as bob,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, email, "Alice")
        alice_id = (await alice.get("/api/v1/users/me")).json()["id"]
        home_id = await create_home(alice, "Alice's Home")
        await create_verified_user(bob, f"anon-lastbob-{suffix}@example.com", "Bob")
        bob_id = (await bob.get("/api/v1/users/me")).json()["id"]
        async with SessionFactory() as db:
            db.add(
                Membership(
                    group_id=uuid.UUID(home_id),
                    user_id=uuid.UUID(bob_id),
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()

        await login_operator(admin)
        await archive_user_via_api(admin, alice_id)

        eligibility = await admin.get(f"/api/v1/platform/users/{alice_id}/anonymise/eligibility")
        assert eligibility.status_code == 200
        assert "last_home_admin" in eligibility.json()["blockers"]

        response = await anonymise_request(admin, alice_id, email)
        assert response.status_code == 409
        assert "Home Admin" in response.text

        async with SessionFactory() as db:
            row = await db.get(User, uuid.UUID(alice_id))
            assert row is not None
            assert row.anonymised_at is None


@pytest.mark.asyncio
async def test_anonymise_preserves_created_content_attribution() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-content-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        alice_id = (await alice.get("/api/v1/users/me")).json()["id"]
        home_id = await create_home(alice, "Alice's Home")

        today = date.today()
        async with SessionFactory() as db:
            routine = HouseholdRoutine(
                group_id=uuid.UUID(home_id),
                title="Bins out",
                scope=RoutineScope.household,
                week_anchor_date=today,
                start_date=today,
                created_by=uuid.UUID(alice_id),
            )
            db.add(routine)
            await db.commit()
            await db.refresh(routine)
            routine_id = routine.id

        await login_operator(admin)
        await archive_user_via_api(admin, alice_id)
        response = await anonymise_request(admin, alice_id, email)
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            routine_row = await db.get(HouseholdRoutine, routine_id)
            assert routine_row is not None
            assert routine_row.created_by == uuid.UUID(alice_id)  # unchanged, not reassigned
            assert routine_row.title == "Bins out"  # content itself untouched


@pytest.mark.asyncio
async def test_billing_owner_of_non_free_subscription_blocks_anonymise() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-billing-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        alice_id = (await alice.get("/api/v1/users/me")).json()["id"]
        home_id = await create_home(alice, "Alice's Home")
        async with SessionFactory() as db:
            subscription = await get_home_subscription(db, uuid.UUID(home_id))
            assert subscription is not None
            subscription.plan = SubscriptionPlan.family
            subscription.billing_owner_user_id = uuid.UUID(alice_id)
            await db.commit()

        await login_operator(admin)
        await archive_user_via_api(admin, alice_id)

        response = await anonymise_request(admin, alice_id, email)
        assert response.status_code == 409
        assert "billing" in response.text.lower()


@pytest.mark.asyncio
async def test_restore_is_blocked_once_anonymised() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-restore-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        await login_operator(admin)
        await archive_user_via_api(admin, user_id)
        await anonymise_request(admin, user_id, email)

        response = await admin_action(admin, f"/api/v1/platform/users/{user_id}/restore")
        assert response.status_code == 409
        assert "anonymised" in response.text.lower()


@pytest.mark.asyncio
async def test_anonymise_audit_event_contains_no_old_pii() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-audit-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        await login_operator(admin)
        await archive_user_via_api(admin, user_id)
        response = await anonymise_request(admin, user_id, email, reason="GDPR erasure request")
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            event = await db.scalar(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.action == "user.anonymised",
                    AdministrativeAuditEvent.target_id == uuid.UUID(user_id),
                )
            )
            assert event is not None
            assert event.reason == "GDPR erasure request"
            assert event.new_values["lifecycle"] == "anonymised"
            assert "memberships_removed" in event.new_values
            blob = str(event.previous_values) + str(event.new_values)
            assert email not in blob
            assert "Alice" not in blob


@pytest.mark.asyncio
async def test_anonymise_requires_recent_auth() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"anon-recentauth-{suffix}@example.com"
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, email, "Alice")
        user_id = (await alice.get("/api/v1/users/me")).json()["id"]
        operator = await create_admin(PlatformRole.owner)
        await login(admin, operator)
        await archive_user_via_api(admin, user_id)
        async with SessionFactory() as db:
            await db.execute(
                update(PlatformSession)
                .where(PlatformSession.administrator_id == operator.id)
                .values(authenticated_at=datetime.now(UTC) - timedelta(hours=1))
            )
            await db.commit()

        response = await anonymise_request(admin, user_id, email)
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Home permanent delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_home_cannot_permanently_delete() -> None:
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-active@example.com", "Alice")
        home_id = await create_home(alice, "Active Home")
        await login_operator(admin)

        response = await permanent_delete_home_request(admin, home_id, "Active Home")
        assert response.status_code == 409
        assert "archived" in response.text.lower()


@pytest.mark.asyncio
async def test_disabled_home_cannot_permanently_delete() -> None:
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-disabled@example.com", "Alice")
        home_id = await create_home(alice, "Disabled Home")
        await login_operator(admin)
        await admin_action(admin, f"/api/v1/platform/homes/{home_id}/suspend")

        response = await permanent_delete_home_request(admin, home_id, "Disabled Home")
        assert response.status_code == 409
        assert "archived" in response.text.lower()


async def _archive_empty_home(alice: AsyncClient, admin: AsyncClient, name: str) -> str:
    """Creates a Home, moves the sole creator out (so it becomes genuinely
    empty — allowed per Slice 2, moving the sole admin of an otherwise-
    empty Home), then archives it. The minimal path to a Home this
    endpoint should actually accept. The destination Home is created by a
    throwaway second user — Alice would already be an active member of any
    Home she creates herself, so Move Member needs somewhere else."""
    home_id = await create_home(alice, name)
    alice_id = (await alice.get("/api/v1/users/me")).json()["id"]
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with consumer_client() as waystation_owner:
        await create_verified_user(
            waystation_owner, f"waystation-{suffix}@example.com", "Waystation Owner"
        )
        other_home_id = await create_home(waystation_owner, f"{name} — elsewhere")
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(other_home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    move = await admin_unsafe(
        admin,
        "POST",
        f"/api/v1/platform/users/{alice_id}/move-home",
        json={
            "source_group_id": home_id,
            "destination_group_id": other_home_id,
            "destination_relationship": "partner",
            "source_disposition": "leave",
            "reason": "Slice 5B test setup",
            "confirmed": True,
        },
    )
    assert move.status_code == 200, move.text
    await archive_home_via_api(admin, home_id)
    return home_id


@pytest.mark.asyncio
async def test_archived_genuinely_empty_home_can_be_permanently_deleted() -> None:
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-empty@example.com", "Alice")
        await login_operator(admin)
        home_id = await _archive_empty_home(alice, admin, "Empty Home")

        eligibility = await admin.get(
            f"/api/v1/platform/homes/{home_id}/permanent-delete/eligibility"
        )
        assert eligibility.status_code == 200
        assert eligibility.json() == {"eligible": True, "blockers": []}

        response = await permanent_delete_home_request(admin, home_id, "Empty Home")
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            assert (await db.get(Group, uuid.UUID(home_id))) is None


@pytest.mark.asyncio
async def test_home_with_active_membership_blocks_deletion() -> None:
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-activemember@example.com", "Alice")
        home_id = await create_home(alice, "Still Has Alice")
        await login_operator(admin)
        await archive_home_via_api(admin, home_id)

        response = await permanent_delete_home_request(admin, home_id, "Still Has Alice")
        assert response.status_code == 409
        assert "active member" in response.text.lower()


@pytest.mark.asyncio
async def test_home_with_historical_second_member_blocks_deletion() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with (
        consumer_client() as alice,
        consumer_client() as bob,
        admin_client_instance() as admin,
    ):
        await create_verified_user(alice, f"delhome-hist-alice-{suffix}@example.com", "Alice")
        await create_verified_user(bob, f"delhome-hist-bob-{suffix}@example.com", "Bob")
        bob_id = (await bob.get("/api/v1/users/me")).json()["id"]
        await login_operator(admin)
        home_id = await _archive_empty_home(alice, admin, "Had A Second Member")

        # Add, then remove, a second historical member directly — the Home
        # is once again "empty of active members" but has real usage
        # history beyond the creator's own scaffold row.
        async with SessionFactory() as db:
            group = await db.get(Group, uuid.UUID(home_id))
            assert group is not None
            group.is_active = True
            group.archived_at = None
            db.add(
                Membership(
                    group_id=uuid.UUID(home_id),
                    user_id=uuid.UUID(bob_id),
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                    removed_at=datetime.now(UTC),
                )
            )
            await db.commit()
        await archive_home_via_api(admin, home_id)

        eligibility = await admin.get(
            f"/api/v1/platform/homes/{home_id}/permanent-delete/eligibility"
        )
        assert "has_membership_history" in eligibility.json()["blockers"]
        response = await permanent_delete_home_request(admin, home_id, "Had A Second Member")
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_home_with_meaningful_content_blocks_deletion() -> None:
    """One combined test exercising every remaining content-blocker code
    path — each is the same `SELECT ... LIMIT 1` existence check against a
    different table, so this proves the mechanism generically rather than
    repeating near-identical setup once per table."""
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-content@example.com", "Alice")
        await login_operator(admin)
        home_id = await _archive_empty_home(alice, admin, "Content Home")
        alice_id = (await alice.get("/api/v1/users/me")).json()["id"]

        today = date.today()
        async with SessionFactory() as db:
            calendar = await db.scalar(
                select(HomeCalendar).where(
                    HomeCalendar.group_id == uuid.UUID(home_id),
                    HomeCalendar.owner_user_id.is_(None),
                )
            )
            assert calendar is not None
            db.add(
                HouseholdRoutine(
                    group_id=uuid.UUID(home_id),
                    title="Bins out",
                    scope=RoutineScope.household,
                    week_anchor_date=today,
                    start_date=today,
                    created_by=uuid.UUID(alice_id),
                )
            )
            db.add(
                Reminder(
                    group_id=uuid.UUID(home_id),
                    title="Renew passport",
                    scope=RoutineScope.household,
                    due_date=today,
                    due_time=datetime.now(UTC).time(),
                    created_by=uuid.UUID(alice_id),
                )
            )
            db.add(
                Invitation(
                    group_id=uuid.UUID(home_id),
                    email="invitee@example.com",
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                    token_hash="token-hash-content-test",
                    invited_by=uuid.UUID(alice_id),
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
            )
            await db.commit()

        eligibility = await admin.get(
            f"/api/v1/platform/homes/{home_id}/permanent-delete/eligibility"
        )
        assert eligibility.status_code == 200
        blockers = eligibility.json()["blockers"]
        assert "has_routines" in blockers
        assert "has_reminders" in blockers
        assert "has_invitations" in blockers

        response = await permanent_delete_home_request(admin, home_id, "Content Home")
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_home_with_current_non_free_subscription_blocks_deletion() -> None:
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-subplan@example.com", "Alice")
        await login_operator(admin)
        home_id = await _archive_empty_home(alice, admin, "Paid Plan Home")
        async with SessionFactory() as db:
            subscription = await get_home_subscription(db, uuid.UUID(home_id))
            assert subscription is not None
            subscription.plan = SubscriptionPlan.family
            await db.commit()

        eligibility = await admin.get(
            f"/api/v1/platform/homes/{home_id}/permanent-delete/eligibility"
        )
        assert "has_active_subscription" in eligibility.json()["blockers"]
        response = await permanent_delete_home_request(admin, home_id, "Paid Plan Home")
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_home_with_historical_non_free_billing_event_blocks_deletion() -> None:
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-billinghist@example.com", "Alice")
        await login_operator(admin)
        home_id = await _archive_empty_home(alice, admin, "Once Paid Home")
        async with SessionFactory() as db:
            db.add(
                HomeSubscriptionEvent(
                    group_id=uuid.UUID(home_id),
                    event_type="plan_changed",
                    to_plan=SubscriptionPlan.family,
                )
            )
            await db.commit()

        eligibility = await admin.get(
            f"/api/v1/platform/homes/{home_id}/permanent-delete/eligibility"
        )
        assert "has_billing_history" in eligibility.json()["blockers"]
        response = await permanent_delete_home_request(admin, home_id, "Once Paid Home")
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_managed_demo_home_blocks_generic_permanent_delete() -> None:
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-demo@example.com", "Alice")
        alice_id = (await alice.get("/api/v1/users/me")).json()["id"]
        await login_operator(admin)
        home_id = await _archive_empty_home(alice, admin, "Demo Home")
        async with SessionFactory() as db:
            db.add(
                ManagedDemoHome(
                    fixture_key=f"demo-{home_id}",
                    display_name="Demo Home",
                    fixture_type=ManagedDemoType.qa_test,
                    home_id=uuid.UUID(home_id),
                    owner_user_id=uuid.UUID(alice_id),
                )
            )
            await db.commit()

        eligibility = await admin.get(
            f"/api/v1/platform/homes/{home_id}/permanent-delete/eligibility"
        )
        assert "is_managed_demo_home" in eligibility.json()["blockers"]
        response = await permanent_delete_home_request(admin, home_id, "Demo Home")
        assert response.status_code == 409
        assert "demo" in response.text.lower()


@pytest.mark.asyncio
async def test_system_scaffold_alone_does_not_block_deletion() -> None:
    """The Home creation scaffold (creator's own Membership, the 2 default
    HomeCalendars, the 7 system CalendarEventLabel rows, the Free
    HomeSubscription + its "created" event) must not itself count as
    meaningful content — this is the control case for every blocker test
    above."""
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-scaffold@example.com", "Alice")
        await login_operator(admin)
        home_id = await _archive_empty_home(alice, admin, "Scaffold Only Home")

        eligibility = await admin.get(
            f"/api/v1/platform/homes/{home_id}/permanent-delete/eligibility"
        )
        assert eligibility.status_code == 200
        assert eligibility.json() == {"eligible": True, "blockers": []}


@pytest.mark.asyncio
async def test_confirmation_text_mismatch_blocks_home_deletion() -> None:
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-mismatch@example.com", "Alice")
        await login_operator(admin)
        home_id = await _archive_empty_home(alice, admin, "Mismatch Home")

        response = await permanent_delete_home_request(admin, home_id, "Wrong Name")
        assert response.status_code == 422

        async with SessionFactory() as db:
            assert (await db.get(Group, uuid.UUID(home_id))) is not None  # untouched


@pytest.mark.asyncio
async def test_home_deletion_audit_survives_the_deleted_home() -> None:
    async with consumer_client() as alice, admin_client_instance() as admin:
        await create_verified_user(alice, "delhome-audit@example.com", "Alice")
        await login_operator(admin)
        home_id = await _archive_empty_home(alice, admin, "Audited Home")

        response = await permanent_delete_home_request(
            admin, home_id, "Audited Home", reason="Duplicate test Home, no longer needed"
        )
        assert response.status_code == 200, response.text

        async with SessionFactory() as db:
            event = await db.scalar(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.action == "home.permanently_deleted",
                    AdministrativeAuditEvent.target_id == uuid.UUID(home_id),
                )
            )
            assert event is not None
            assert event.reason == "Duplicate test Home, no longer needed"
            assert event.previous_values["name"] == "Audited Home"
            assert (await db.get(Group, uuid.UUID(home_id))) is None  # the Home itself is gone
