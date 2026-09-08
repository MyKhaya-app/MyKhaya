"""Home join codes (Slice 1) — Home Admin issues a code, another authenticated
user looks it up and requests to join, a Home Admin approves/declines.

Mirrors tests/test_journey.py's AsyncClient-per-user pattern: each user gets
its own AsyncClient (separate cookie jar), so a "Home Admin" client and a
"joiner" client can act independently against the same running app.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import Group, HomeJoinRequest, SubscriptionPlan


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )


async def _create_home(client: AsyncClient, name: str) -> str:
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert created.status_code == 201
    return created.json()["id"]


async def _upgrade_to_family(home_id: str) -> None:
    """A fresh Home is Free (max_members=1) — same upgrade
    test_household_controls.py's own tests use before adding a second
    member, so approving a join request isn't blocked by the Free-plan
    member-limit this test isn't exercising."""
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()


async def _generate_join_code(client: AsyncClient, home_id: str) -> str:
    response = await unsafe(client, "POST", f"/api/v1/groups/{home_id}/join-code/regenerate")
    assert response.status_code == 200
    code = response.json()["code"]
    assert code is not None
    return code


@pytest.mark.asyncio
async def test_home_admin_can_generate_and_view_join_code() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as admin:
        await create_verified_user(admin, f"jc-admin-{suffix}@example.com", "Admin One")
        home_id = await _create_home(admin, "Hales Home")

        empty = await admin.get(f"/api/v1/groups/{home_id}/join-code")
        assert empty.status_code == 200
        assert empty.json() == {"code": None, "generated_at": None}

        code = await _generate_join_code(admin, home_id)
        assert len(code) == 9  # XXXX-XXXX
        assert code[4] == "-"

        view = await admin.get(f"/api/v1/groups/{home_id}/join-code")
        assert view.status_code == 200
        assert view.json()["code"] == code
        assert view.json()["generated_at"] is not None


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_join_code() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as admin, _client() as member:
        await create_verified_user(admin, f"jc-admin2-{suffix}@example.com", "Admin Two")
        home_id = await _create_home(admin, "Second Home")
        await _upgrade_to_family(home_id)
        code = await _generate_join_code(admin, home_id)

        await create_verified_user(member, f"jc-member-{suffix}@example.com", "Member One")
        joined = await unsafe(member, "POST", "/api/v1/home-join/request", json={"code": code})
        assert joined.status_code == 201
        request_id = joined.json()["id"]
        approve = await unsafe(
            admin,
            "POST",
            f"/api/v1/groups/{home_id}/join-requests/{request_id}/approve",
            json={"relationship": "adult", "confirmed": True},
        )
        assert approve.status_code == 200

        # The now-member (an Adult, not a Home Admin) must not be able to
        # manage the join code — members.invite is Home-Admin-only.
        forbidden = await member.get(f"/api/v1/groups/{home_id}/join-code")
        assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_regenerating_invalidates_the_previous_code() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as admin, _client() as joiner:
        await create_verified_user(admin, f"jc-regen-{suffix}@example.com", "Regen Admin")
        home_id = await _create_home(admin, "Regen Home")
        old_code = await _generate_join_code(admin, home_id)
        new_code = await _generate_join_code(admin, home_id)
        assert old_code != new_code

        await create_verified_user(joiner, f"jc-regen-joiner-{suffix}@example.com", "Regen Joiner")
        old_lookup = await unsafe(
            joiner, "POST", "/api/v1/home-join/lookup", json={"code": old_code}
        )
        assert old_lookup.status_code == 404
        new_lookup = await unsafe(
            joiner, "POST", "/api/v1/home-join/lookup", json={"code": new_code}
        )
        assert new_lookup.status_code == 200
        assert new_lookup.json()["group_name"] == "Regen Home"


@pytest.mark.asyncio
async def test_lookup_is_case_and_dash_insensitive() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as admin, _client() as joiner:
        await create_verified_user(admin, f"jc-case-{suffix}@example.com", "Case Admin")
        home_id = await _create_home(admin, "Case Home")
        code = await _generate_join_code(admin, home_id)
        messy = code.lower().replace("-", " ")

        await create_verified_user(joiner, f"jc-case-joiner-{suffix}@example.com", "Case Joiner")
        lookup = await unsafe(joiner, "POST", "/api/v1/home-join/lookup", json={"code": messy})
        assert lookup.status_code == 200
        assert lookup.json()["group_id"] == home_id


@pytest.mark.asyncio
async def test_invalid_code_is_handled_safely() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as joiner:
        await create_verified_user(joiner, f"jc-invalid-{suffix}@example.com", "Invalid Joiner")
        lookup = await unsafe(
            joiner, "POST", "/api/v1/home-join/lookup", json={"code": "ZZZZ-ZZZZ"}
        )
        assert lookup.status_code == 404
        # No stack trace / internal detail leakage.
        assert "Traceback" not in lookup.text


@pytest.mark.asyncio
async def test_possessing_the_code_does_not_create_membership() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as admin, _client() as joiner:
        await create_verified_user(admin, f"jc-possess-{suffix}@example.com", "Possess Admin")
        home_id = await _create_home(admin, "Possess Home")
        code = await _generate_join_code(admin, home_id)

        await create_verified_user(
            joiner, f"jc-possess-joiner-{suffix}@example.com", "Possess Joiner"
        )
        lookup = await unsafe(joiner, "POST", "/api/v1/home-join/lookup", json={"code": code})
        assert lookup.status_code == 200

        # Only the admin's own membership exists — looking the code up alone
        # created nothing for the joiner.
        members = await admin.get(f"/api/v1/groups/{home_id}/members")
        assert len(members.json()) == 1


@pytest.mark.asyncio
async def test_duplicate_pending_request_is_prevented() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as admin, _client() as joiner:
        await create_verified_user(admin, f"jc-dup-{suffix}@example.com", "Dup Admin")
        home_id = await _create_home(admin, "Dup Home")
        code = await _generate_join_code(admin, home_id)

        await create_verified_user(joiner, f"jc-dup-joiner-{suffix}@example.com", "Dup Joiner")
        first = await unsafe(joiner, "POST", "/api/v1/home-join/request", json={"code": code})
        assert first.status_code == 201
        second = await unsafe(joiner, "POST", "/api/v1/home-join/request", json={"code": code})
        assert second.status_code == 409


@pytest.mark.asyncio
async def test_approval_creates_correct_membership_and_role() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as admin, _client() as joiner:
        await create_verified_user(admin, f"jc-approve-{suffix}@example.com", "Approve Admin")
        home_id = await _create_home(admin, "Approve Home")
        await _upgrade_to_family(home_id)
        code = await _generate_join_code(admin, home_id)

        await create_verified_user(
            joiner, f"jc-approve-joiner-{suffix}@example.com", "Approve Joiner"
        )
        request = await unsafe(joiner, "POST", "/api/v1/home-join/request", json={"code": code})
        assert request.status_code == 201
        request_id = request.json()["id"]

        pending = await admin.get(f"/api/v1/groups/{home_id}/join-requests")
        assert pending.status_code == 200
        assert len(pending.json()) == 1
        assert pending.json()[0]["display_name"] == "Approve Joiner"

        approve = await unsafe(
            admin,
            "POST",
            f"/api/v1/groups/{home_id}/join-requests/{request_id}/approve",
            json={"relationship": "partner", "confirmed": True},
        )
        assert approve.status_code == 200
        body = approve.json()
        assert body["relationship"] == "partner"
        assert body["role"] == "adult_member"

        members = await admin.get(f"/api/v1/groups/{home_id}/members")
        assert len(members.json()) == 2

        still_pending = await admin.get(f"/api/v1/groups/{home_id}/join-requests")
        assert still_pending.json() == []


@pytest.mark.asyncio
async def test_decline_creates_no_membership() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as admin, _client() as joiner:
        await create_verified_user(admin, f"jc-decline-{suffix}@example.com", "Decline Admin")
        home_id = await _create_home(admin, "Decline Home")
        code = await _generate_join_code(admin, home_id)

        await create_verified_user(
            joiner, f"jc-decline-joiner-{suffix}@example.com", "Decline Joiner"
        )
        request = await unsafe(joiner, "POST", "/api/v1/home-join/request", json={"code": code})
        request_id = request.json()["id"]

        decline = await unsafe(
            admin,
            "POST",
            f"/api/v1/groups/{home_id}/join-requests/{request_id}/decline",
            json={"confirmed": True},
        )
        assert decline.status_code == 204

        members = await admin.get(f"/api/v1/groups/{home_id}/members")
        assert len(members.json()) == 1

        async with SessionFactory() as db:
            row = await db.get(HomeJoinRequest, uuid.UUID(request_id))
            assert row is not None
            assert row.status.value == "declined"
            assert row.decided_by is not None


@pytest.mark.asyncio
async def test_existing_member_cannot_request_to_join_again() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as admin:
        await create_verified_user(admin, f"jc-self-{suffix}@example.com", "Self Admin")
        home_id = await _create_home(admin, "Self Home")
        code = await _generate_join_code(admin, home_id)

        # The Home Admin is already a member of their own Home.
        again = await unsafe(admin, "POST", "/api/v1/home-join/request", json={"code": code})
        assert again.status_code == 409


@pytest.mark.asyncio
async def test_join_code_secret_is_not_exposed_in_unrelated_responses() -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with _client() as admin:
        await create_verified_user(admin, f"jc-secret-{suffix}@example.com", "Secret Admin")
        home_id = await _create_home(admin, "Secret Home")
        await _generate_join_code(admin, home_id)

        group_response = await admin.get(f"/api/v1/groups/{home_id}")
        assert "join_code" not in group_response.text

        async with SessionFactory() as db:
            group = await db.get(Group, uuid.UUID(home_id))
            assert group is not None
            # The raw code is never stored in plaintext — only a digest and
            # separately-encrypted ciphertext, neither of which is the raw
            # value a client ever typed or saw.
            assert group.join_code_hash is not None
            assert group.join_code_encrypted is not None
