from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import AuditEvent


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
    assert "shopping" not in module_ids

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
            await db.scalars(
                select(AuditEvent.action).where(AuditEvent.group_id == home_id)
            )
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
