"""Regression coverage for the "accepted invitation still shows as pending" bug.

Root cause: GET /invitations/group/{group_id} — the Family page's "Pending
invitations" list and its only real caller — excluded revoked invitations but
not accepted ones, so an accepted invitation (with a real, active membership
already created) kept showing up as pending, offering Resend/Revoke. See
mykhaya.routers.invitations.list_invitations.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    SubscriptionPlan,
    User,
)
from mykhaya.security import derived_token


async def _upgrade_to_family(group_id: str) -> None:
    """This file tests invitation list/resend/revoke/accept mechanics, not
    commercial gating — home.max_members restricts Free to a single person,
    so every Home here needs Family to be able to invite anyone at all. See
    test_commercial_plan_cleanup.py for the Free-vs-Family enforcement
    coverage itself."""
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(group_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def unique_email(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"


async def _invite(client: AsyncClient, group_id: str, email: str) -> tuple[str, str]:
    response = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": group_id, "email": email, "relationship": "partner"},
    )
    assert response.status_code == 201, response.text
    invitation_id = response.json()["id"]
    raw = derived_token(
        uuid.UUID(invitation_id), "invitation", get_settings().secret_key.get_secret_value()
    )
    return invitation_id, raw


@pytest.mark.asyncio
async def test_accepted_invitation_no_longer_appears_in_pending_list(
    client: AsyncClient,
) -> None:
    """The exact reported bug: accept → membership active → invite must
    disappear from the pending list, not linger with Resend/Revoke offered."""
    owner_email = unique_email("owner")
    invitee_email = unique_email("invitee")
    await create_verified_user(client, owner_email, "Home Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Hales Home"})
    assert group.status_code == 201
    group_id = group.json()["id"]
    await _upgrade_to_family(group_id)

    invitation_id, raw = await _invite(client, group_id, invitee_email)

    pending_before = await client.get(f"/api/v1/invitations/group/{group_id}")
    assert pending_before.status_code == 200
    assert {row["id"] for row in pending_before.json()} == {invitation_id}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as invitee:
        await create_verified_user(invitee, invitee_email, "Invited Partner")
        accepted = await unsafe(invitee, "POST", "/api/v1/invitations/accept", json={"token": raw})
        assert accepted.status_code == 200

    # The invitation must be gone from the default (pending) listing...
    pending_after = await client.get(f"/api/v1/invitations/group/{group_id}")
    assert pending_after.status_code == 200
    assert pending_after.json() == []

    # ...while the member is genuinely active.
    members = await client.get(f"/api/v1/groups/{group_id}/members")
    assert invitee_email in {row["email"] for row in members.json()}

    # ...and the record itself still exists with accepted_at set — this is a
    # read-side filter, not a delete. History is available on request.
    history = await client.get(
        f"/api/v1/invitations/group/{group_id}", params={"include_accepted": True}
    )
    assert history.status_code == 200
    accepted_row = next(row for row in history.json() if row["id"] == invitation_id)
    assert accepted_row["accepted_at"] is not None


@pytest.mark.asyncio
async def test_resend_and_revoke_are_rejected_for_an_accepted_invitation(
    client: AsyncClient,
) -> None:
    owner_email = unique_email("owner2")
    invitee_email = unique_email("invitee2")
    await create_verified_user(client, owner_email, "Home Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Second Home"})
    assert group.status_code == 201
    group_id = group.json()["id"]
    await _upgrade_to_family(group_id)

    invitation_id, raw = await _invite(client, group_id, invitee_email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as invitee:
        await create_verified_user(invitee, invitee_email, "Invited Partner")
        assert (
            await unsafe(invitee, "POST", "/api/v1/invitations/accept", json={"token": raw})
        ).status_code == 200

    resend = await unsafe(
        client, "POST", "/api/v1/invitations/resend", json={"invitation_id": invitation_id}
    )
    assert resend.status_code == 409

    revoke = await unsafe(
        client, "POST", "/api/v1/invitations/revoke", json={"invitation_id": invitation_id}
    )
    assert revoke.status_code == 409


@pytest.mark.asyncio
async def test_revoked_invitation_still_excluded_from_default_pending_list(
    client: AsyncClient,
) -> None:
    owner_email = unique_email("owner3")
    invitee_email = unique_email("invitee3")
    await create_verified_user(client, owner_email, "Home Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Third Home"})
    assert group.status_code == 201
    group_id = group.json()["id"]
    await _upgrade_to_family(group_id)

    invitation_id, _raw = await _invite(client, group_id, invitee_email)

    revoke = await unsafe(
        client, "POST", "/api/v1/invitations/revoke", json={"invitation_id": invitation_id}
    )
    assert revoke.status_code == 200

    pending = await client.get(f"/api/v1/invitations/group/{group_id}")
    assert pending.status_code == 200
    assert pending.json() == []


@pytest.mark.asyncio
async def test_pending_invite_suppressed_when_active_membership_already_exists(
    client: AsyncClient,
) -> None:
    """Defence in depth: even if accepted_at were somehow never set (a
    membership created through a different path than accept()), an
    invitation must not be listed as pending once an active member already
    holds that email in that home."""
    owner_email = unique_email("owner4")
    invitee_email = unique_email("invitee4")
    await create_verified_user(client, owner_email, "Home Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Fourth Home"})
    assert group.status_code == 201
    group_id = group.json()["id"]
    await _upgrade_to_family(group_id)

    invitation_id, _raw = await _invite(client, group_id, invitee_email)

    # Simulate the anomaly directly: a real, active membership for that email
    # in that home, but the invitation's accepted_at is untouched.
    async with SessionFactory() as db:
        invitee_user = User(email=invitee_email, display_name="Anomaly Partner")
        db.add(invitee_user)
        await db.commit()
        await db.refresh(invitee_user)
        db.add(
            Membership(
                group_id=uuid.UUID(group_id),
                user_id=invitee_user.id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()

    pending = await client.get(f"/api/v1/invitations/group/{group_id}")
    assert pending.status_code == 200
    assert pending.json() == [], (
        "an invitation must never be listed as pending once an active member "
        "already holds that email, even if accepted_at was never set"
    )

    # It is still visible in the explicit history view, unmutated.
    history = await client.get(
        f"/api/v1/invitations/group/{group_id}", params={"include_accepted": True}
    )
    accepted_row = next(row for row in history.json() if row["id"] == invitation_id)
    assert accepted_row["accepted_at"] is None
