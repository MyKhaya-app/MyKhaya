import uuid
from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    AuditEvent,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    SubscriptionPlan,
    User,
)


@pytest.fixture
async def api_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.mark.asyncio
async def test_home_admin_features_relationships_and_managed_child(
    api_client: AsyncClient,
) -> None:
    client = api_client
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"controls-{suffix}@example.com", "Control Owner")
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Control Home"})
    assert created.status_code == 201
    home_id = created.json()["id"]
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    assert created.json()["relationship"] == "home_admin"
    assert "features.manage" in created.json()["capabilities"]

    members = await client.get(f"/api/v1/groups/{home_id}/members")
    assert members.status_code == 200
    owner = members.json()[0]
    assert owner["relationship"] == "home_admin"
    assert owner["permission_profile"] == "home_admin"

    final_admin = await unsafe(
        client,
        "PATCH",
        f"/api/v1/groups/{home_id}/members/{owner['user_id']}",
        json={
            "relationship": "partner",
            "reason": "Testing final administrator protection",
            "confirmed": True,
        },
    )
    assert final_admin.status_code == 409

    management = await client.get(f"/api/v1/features/{home_id}/modules/management")
    assert management.status_code == 200
    module_ids = {row["id"] for row in management.json()}
    assert "calendar" in module_ids
    assert "tasks" not in module_ids
    # "shopping" is now the released Lists module (mykhaya.routers.lists) —
    # see docs/architecture/meal-plans.md "Lists integration".
    assert "shopping" in module_ids

    hidden_update = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/tasks/household",
        json={
            "enabled": True,
            "reason": "Hidden modules must remain inaccessible",
            "confirmed": True,
        },
    )
    assert hidden_update.status_code == 404

    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/calendar/household",
        json={
            "enabled": True,
            "reason": "The household needs a shared calendar",
            "confirmed": True,
        },
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

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
    assert child.status_code == 201
    child_row = child.json()
    assert child_row["permissions"]["calendar_view"] is False
    assert child_row["permissions"]["external_sharing"] is False

    changed_permissions = await unsafe(
        client,
        "PUT",
        f"/api/v1/groups/{home_id}/children/{child_row['membership_id']}/permissions",
        json={
            "permissions": {**child_row["permissions"], "calendar_view": True},
            "reason": "Allow read-only access to family events",
            "confirmed": True,
        },
    )
    assert changed_permissions.status_code == 200
    assert changed_permissions.json()["permissions"]["calendar_view"] is True
    assert changed_permissions.json()["permissions"]["calendar_create"] is False

    changed_age = await unsafe(
        client,
        "PUT",
        f"/api/v1/groups/{home_id}/children/{child_row['membership_id']}/age-band",
        json={
            "age_band": "13_to_15",
            "reason": "The guardian completed the age-band review",
            "confirmed": True,
        },
    )
    assert changed_age.status_code == 200
    assert changed_age.json()["age_band"] == "13_to_15"

    review = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/children/{child_row['membership_id']}/adult-transition-review",
        json={
            "reason": "Prepare an explicit adult account conversion review",
            "confirmed": True,
        },
    )
    assert review.status_code == 200
    assert review.json()["transition_status"] == "review_due"

    async with SessionFactory() as db:
        actions = set(
            await db.scalars(select(AuditEvent.action).where(AuditEvent.group_id == home_id))
        )
    assert {
        "feature.enabled",
        "child.created",
        "child.permissions_changed",
        "child.age_band_changed",
        "child.adult_transition_review_requested",
    }.issubset(actions)

    removed = await unsafe(
        client,
        "DELETE",
        f"/api/v1/groups/{home_id}/children/{child_row['membership_id']}",
        json={
            "reason": "Guardian requested privacy-preserving profile removal",
            "confirmed": True,
        },
    )
    assert removed.status_code == 204
    remaining = await client.get(f"/api/v1/groups/{home_id}/children")
    assert remaining.status_code == 200
    assert remaining.json() == []


@pytest.mark.asyncio
async def test_member_colours_are_assigned_and_collision_free(
    api_client: AsyncClient,
) -> None:
    """Colour belongs to the person's membership, assigned server-side, and
    must never collide with another active member of the same home while
    the palette has spare colours — see docs/design/visual-identity.md and
    mykhaya.member_colours. The palette has 18 tokens (mykhaya.colour_palette
    .ColourToken); this creates one more member than that to exercise both
    "everyone distinct while there's room" and "cycles once exhausted"."""
    client = api_client
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"colour-{suffix}@example.com", "Colour Owner")
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Colour Home"})
    assert created.status_code == 201
    home_id = created.json()["id"]
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()

    members = await client.get(f"/api/v1/groups/{home_id}/members")
    admin = members.json()[0]
    assert admin["colour"] is not None
    guardian_id = admin["membership_id"]

    for index in range(18):
        child = await unsafe(
            client,
            "POST",
            f"/api/v1/groups/{home_id}/children",
            json={
                "display_name": f"Child {index:02d}",
                "age_band": "under_13",
                "guardian_membership_ids": [guardian_id],
            },
        )
        assert child.status_code == 201

    all_members = await client.get(f"/api/v1/groups/{home_id}/members")
    assert all_members.status_code == 200
    rows = all_members.json()
    assert len(rows) == 19
    member_colours = [row["colour"] for row in rows]
    assert all(colour is not None for colour in member_colours)
    # Every one of the 18 palette colours gets used at least once — nobody is
    # left without a colour and nothing is skipped while there's still room.
    assert len(set(member_colours)) == 18
    # The 19th member, past the palette's capacity, cycles back to a colour
    # already in use rather than staying blank.
    duplicate_counts = Counter(member_colours)
    assert sum(duplicate_counts.values()) == 19
    assert max(duplicate_counts.values()) == 2


@pytest.mark.asyncio
async def test_member_colour_self_update_admin_update_and_unauthorized(
    api_client: AsyncClient,
) -> None:
    """A member may always recolour themselves; a Home Admin may recolour
    anyone (reusing members.manage_relationships, the same capability that
    already gates every other member-attribute change); anyone else is
    blocked from changing someone else's colour. See
    mykhaya.routers.groups.update_member_colour."""
    client = api_client
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"coloradmin-{suffix}@example.com", "Colour Admin")
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Colour Perms Home"})
    assert created.status_code == 201
    home_id = created.json()["id"]

    members = await client.get(f"/api/v1/groups/{home_id}/members")
    admin = members.json()[0]
    admin_id = admin["user_id"]

    # A second, non-admin household member — a "partner" profile, which has
    # no members.manage_relationships capability (only home_admin does).
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as partner_client:
        partner_email = f"colorpartner-{suffix}@example.com"
        await create_verified_user(partner_client, partner_email, "Colour Partner")
        async with SessionFactory() as db:
            user = await db.scalar(select(User).where(User.email == partner_email))
            assert user is not None
            partner_id = str(user.id)
            db.add(
                Membership(
                    group_id=home_id,
                    user_id=user.id,
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()

        # Admin recolours themselves.
        self_update = await unsafe(
            client,
            "PATCH",
            f"/api/v1/groups/{home_id}/members/{admin_id}/colour",
            json={"colour": "rose"},
        )
        assert self_update.status_code == 200
        assert self_update.json()["colour"] == "rose"

        # Admin recolours the partner — reuses members.manage_relationships.
        admin_recolours_partner = await unsafe(
            client,
            "PATCH",
            f"/api/v1/groups/{home_id}/members/{partner_id}/colour",
            json={"colour": "indigo"},
        )
        assert admin_recolours_partner.status_code == 200
        assert admin_recolours_partner.json()["colour"] == "indigo"

        # Partner recolours themselves — always allowed, no capability needed.
        partner_self_update = await unsafe(
            partner_client,
            "PATCH",
            f"/api/v1/groups/{home_id}/members/{partner_id}/colour",
            json={"colour": "cyan"},
        )
        assert partner_self_update.status_code == 200
        assert partner_self_update.json()["colour"] == "cyan"

        # Partner attempts to recolour the admin — blocked.
        partner_recolours_admin = await unsafe(
            partner_client,
            "PATCH",
            f"/api/v1/groups/{home_id}/members/{admin_id}/colour",
            json={"colour": "lime"},
        )
        assert partner_recolours_admin.status_code == 403

    # An unrecognised colour token is rejected, not silently accepted.
    invalid = await unsafe(
        client,
        "PATCH",
        f"/api/v1/groups/{home_id}/members/{admin_id}/colour",
        json={"colour": "not-a-real-colour"},
    )
    assert invalid.status_code == 422

    # The admin's colour reflects only the successful self-update, never the
    # blocked attempt from the partner.
    final = await client.get(f"/api/v1/groups/{home_id}/members")
    final_admin = next(row for row in final.json() if row["user_id"] == admin_id)
    assert final_admin["colour"] == "rose"
