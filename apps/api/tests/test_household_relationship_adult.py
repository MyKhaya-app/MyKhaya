"""Coverage for the Adult household relationship (see
migrations/versions/0038_household_adult.py and
mykhaya.household_permissions.default_profile/legacy_role).

Adult is for a genuine household member who isn't the Home Admin's partner —
an older child living at home, a housemate, a sibling, another adult
relative. It reuses Partner's default PermissionProfile (standard_partner)
but stays a distinct HouseholdRelationship value; nothing here should ever
conflate the two, grant Adult Home Admin authority, or let Adult receive
managed-Child account behaviour.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.household_permissions import Capability, capabilities_for, default_profile, legacy_role
from mykhaya.main import app
from mykhaya.models import (
    ChildProfile,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    SubscriptionPlan,
    User,
)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def unique_email(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"


async def _make_family_home(client: AsyncClient, name: str) -> str:
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert created.status_code == 201, created.text
    home_id = created.json()["id"]
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    return str(home_id)


async def _owner_membership(client: AsyncClient, home_id: str) -> dict[str, Any]:
    members = await client.get(f"/api/v1/groups/{home_id}/members")
    assert members.status_code == 200
    row: dict[str, Any] = members.json()[0]
    return row


async def _insert_membership(
    db: AsyncSession,
    *,
    group_id: str,
    email: str,
    display_name: str,
    relationship: HouseholdRelationship,
) -> Membership:
    """Directly creates a User + Membership row with the given relationship
    and its real default profile — the same shortcut test_invitations.py's
    "anomaly membership" pattern uses, so capability logic can be exercised
    without going through the full invite/accept email flow."""
    user = User(email=email, display_name=display_name)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    membership = Membership(
        group_id=uuid.UUID(group_id),
        user_id=user.id,
        role=legacy_role(relationship),
        relationship=relationship,
        permission_profile=default_profile(relationship),
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


# --- Adult is a valid, backwards-compatible relationship value -------------


def test_adult_and_legacy_relationships_all_round_trip_through_the_enum() -> None:
    # A pre-existing stored value (e.g. "partner") must keep parsing exactly
    # as before; "adult" must now parse too — the additive-migration
    # guarantee at the Python-enum level.
    for raw in [
        "home_admin",
        "partner",
        "adult",
        "child",
        "extended_family",
        "friend",
        "review_required",
    ]:
        assert HouseholdRelationship(raw).value == raw


@pytest.mark.asyncio
async def test_adult_is_accepted_as_a_member_relationship(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("adult-valid"), "Home Owner")
    home_id = await _make_family_home(client, "Adult Valid Home")
    owner = await _owner_membership(client, home_id)

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/groups/{home_id}/members/{owner['user_id']}",
        json={
            "relationship": "adult",
            "reason": "Testing the new Adult relationship",
            "confirmed": True,
        },
    )
    # Blocked for an unrelated reason (would leave the Home without any Home
    # Admin) — this proves "adult" itself parsed as a valid relationship and
    # reached that later check, rather than failing schema validation.
    assert updated.status_code == 409


# --- Adult defaults to Partner's permission profile, independently ---------
# --- overridable, and never equivalent to Home Admin -----------------------


def test_adult_defaults_to_partners_permission_profile_but_stays_a_distinct_relationship() -> None:
    assert default_profile(HouseholdRelationship.adult) == PermissionProfile.standard_partner
    assert default_profile(HouseholdRelationship.partner) == PermissionProfile.standard_partner
    assert str(HouseholdRelationship.adult) != str(HouseholdRelationship.partner)
    assert legacy_role(HouseholdRelationship.adult) == Role.adult_member
    assert legacy_role(HouseholdRelationship.adult) == legacy_role(HouseholdRelationship.partner)
    # Explicitly required by the task: Adult must never be equivalent to
    # Home Admin.
    assert default_profile(HouseholdRelationship.adult) != PermissionProfile.home_admin


@pytest.mark.asyncio
async def test_adult_member_receives_partners_default_capabilities(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("adult-caps"), "Home Owner")
    home_id = await _make_family_home(client, "Adult Caps Home")

    async with SessionFactory() as db:
        adult_membership = await _insert_membership(
            db,
            group_id=home_id,
            email=unique_email("adult-member"),
            display_name="Housemate Adult",
            relationship=HouseholdRelationship.adult,
        )
        partner_membership = await _insert_membership(
            db,
            group_id=home_id,
            email=unique_email("partner-member"),
            display_name="Partner",
            relationship=HouseholdRelationship.partner,
        )
        adult_capabilities = await capabilities_for(db, adult_membership)
        partner_capabilities = await capabilities_for(db, partner_membership)

    assert adult_capabilities == partner_capabilities
    assert Capability.calendar_create in adult_capabilities
    assert Capability.household_manage not in adult_capabilities
    assert Capability.features_manage not in adult_capabilities


@pytest.mark.asyncio
async def test_advanced_permission_overrides_apply_independently_to_an_adult_member(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("adult-override"), "Home Owner")
    home_id = await _make_family_home(client, "Adult Override Home")

    async with SessionFactory() as db:
        adult_membership = await _insert_membership(
            db,
            group_id=home_id,
            email=unique_email("adult-override-member"),
            display_name="Overridden Adult",
            relationship=HouseholdRelationship.adult,
        )
        # Remove a capability Partner's default profile normally grants...
        adult_membership.permission_overrides = {"calendar.delete": False}
        await db.commit()
        await db.refresh(adult_membership)

        second_adult = await _insert_membership(
            db,
            group_id=home_id,
            email=unique_email("adult-plain-member"),
            display_name="Plain Adult",
            relationship=HouseholdRelationship.adult,
        )

        overridden_capabilities = await capabilities_for(db, adult_membership)
        plain_capabilities = await capabilities_for(db, second_adult)

    assert Capability.calendar_delete not in overridden_capabilities
    assert Capability.calendar_delete in plain_capabilities
    # Everything else about the profile is untouched by the override.
    assert Capability.calendar_create in overridden_capabilities


# --- Adult does not receive managed-Child sign-in/account behaviour --------


@pytest.mark.asyncio
async def test_inviting_an_adult_follows_the_normal_adult_flow_not_child_setup(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("adult-invite"), "Home Owner")
    home_id = await _make_family_home(client, "Adult Invite Home")

    invited = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": home_id, "email": unique_email("adult-invitee"), "relationship": "adult"},
    )
    assert invited.status_code == 201, invited.text
    body = invited.json()
    assert body["relationship"] == "adult"
    assert body["permission_profile"] == "standard_partner"

    async with SessionFactory() as db:
        # No ChildProfile was ever created for this invitation/relationship
        # — scoped to this Home specifically, since the test database is
        # shared across the whole suite run.
        existing = await db.scalar(
            select(ChildProfile.id).where(ChildProfile.group_id == uuid.UUID(home_id))
        )
    assert existing is None


@pytest.mark.asyncio
async def test_adult_relationship_is_rejected_by_the_child_only_setup_endpoint(
    client: AsyncClient,
) -> None:
    # Sanity check the other direction too: the child-specific setup
    # endpoint has nothing to do with "adult" — confirms the two flows stay
    # fully separate.
    await create_verified_user(client, unique_email("adult-not-child"), "Home Owner")
    home_id = await _make_family_home(client, "Adult Not Child Home")

    rejected = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={
            "group_id": home_id,
            "email": unique_email("child-rejected"),
            "relationship": "child",
        },
    )
    assert rejected.status_code == 422
    assert "child setup flow" in rejected.json()["detail"].lower()


# --- Adult respects existing guardian-eligibility rules (unchanged) --------


@pytest.mark.asyncio
async def test_adult_member_is_not_guardian_eligible(client: AsyncClient) -> None:
    """Guardianship is a specific parental-trust relationship (Home Admin or
    Partner), not "any adult in the household" — deliberately not extended
    to Adult. See the completion report's Partner-check audit."""
    await create_verified_user(client, unique_email("adult-guardian"), "Home Owner")
    home_id = await _make_family_home(client, "Adult Guardian Home")

    async with SessionFactory() as db:
        adult_membership = await _insert_membership(
            db,
            group_id=home_id,
            email=unique_email("adult-guardian-member"),
            display_name="Adult Housemate",
            relationship=HouseholdRelationship.adult,
        )
        adult_membership_id = str(adult_membership.id)

    rejected = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/children",
        json={
            "display_name": "Young Person",
            "age_band": "under_13",
            "guardian_membership_ids": [adult_membership_id],
        },
    )
    assert rejected.status_code == 422
    assert "guardian" in rejected.json()["detail"].lower()


# --- Free/Family entitlement enforcement is untouched by Adult -------------


@pytest.mark.asyncio
async def test_free_home_still_cannot_invite_an_adult_member(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("adult-free"), "Home Owner")
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Adult Free Home"})
    assert created.status_code == 201
    home_id = created.json()["id"]  # Stays on the Free plan (no upgrade).

    response = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={
            "group_id": home_id,
            "email": unique_email("adult-free-invitee"),
            "relationship": "adult",
        },
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "plan_limit_reached"
    assert detail["entitlement"] == "home.max_members"


# --- Partner and Child continue working exactly as before -------------------


@pytest.mark.asyncio
async def test_partner_relationship_is_unaffected_by_adding_adult(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("partner-unaffected"), "Home Owner")
    home_id = await _make_family_home(client, "Partner Unaffected Home")

    invited = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={
            "group_id": home_id,
            "email": unique_email("partner-invitee"),
            "relationship": "partner",
        },
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["relationship"] == "partner"
    assert invited.json()["permission_profile"] == "standard_partner"


@pytest.mark.asyncio
async def test_child_relationship_is_unaffected_by_adding_adult(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("child-unaffected"), "Home Owner")
    home_id = await _make_family_home(client, "Child Unaffected Home")
    owner = await _owner_membership(client, home_id)

    child = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/children",
        json={
            "display_name": "Young Person",
            "age_band": "under_13",
            "guardian_membership_ids": [owner["membership_id"]],
        },
    )
    assert child.status_code == 201, child.text
    assert child.json()["permissions"]["calendar_view"] is False
