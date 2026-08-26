"""A Child's Home dashboard must reuse the same read endpoints as an adult's —
only write/manage capabilities differ, per mykhaya.household_permissions.
Capability.meals_view is a read-only baseline for PermissionProfile.child_restricted
(see household_permissions.PROFILE_CAPABILITIES); Capability.meals_manage,
Capability.members_view and Capability.members_invite remain out of reach for a
Child regardless of ChildProfile settings. This file exercises those boundaries
end-to-end through a real managed-Child session, not by asserting on a role field.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.household_permissions import PROFILE_CAPABILITIES, Capability
from mykhaya.main import app
from mykhaya.models import FeatureKey, FeatureOverride, PermissionProfile, SubscriptionPlan


def test_child_restricted_profile_grants_meals_view_but_not_meals_manage() -> None:
    """Pure registry check, no DB — the read/write split this whole module
    exists to prove end-to-end, expressed as a single fast assertion."""
    granted = PROFILE_CAPABILITIES[PermissionProfile.child_restricted]
    assert Capability.meals_view in granted
    assert Capability.meals_manage not in granted
    assert Capability.members_view not in granted
    assert Capability.members_invite not in granted
    assert Capability.household_manage_routines not in granted


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def unique(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}"


async def new_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )


async def _make_family_home_with_child(client: AsyncClient, suffix: str) -> tuple[str, str, str]:
    """Registers a Home Admin, creates a Family Home with Meals released, adds
    a Child. Returns (group_id, membership_id, home_code)."""
    await create_verified_user(client, f"admin-{suffix}@example.com", "Home Admin")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": f"Home {suffix}"})
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    home_code = group.json()["child_login_code"]
    assert home_code

    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(group_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.meals, group_id=uuid.UUID(group_id), enabled=True
            )
        )
        await db.commit()

    members = await client.get(f"/api/v1/groups/{group_id}/members")
    assert members.status_code == 200
    admin_membership_id = next(
        row["membership_id"] for row in members.json() if row["relationship"] == "home_admin"
    )

    child = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{group_id}/children",
        json={
            "display_name": "Erin",
            "age_band": "under_13",
            "guardian_membership_ids": [admin_membership_id],
        },
    )
    assert child.status_code == 201, child.text
    return group_id, child.json()["membership_id"], home_code


async def _configure_login(
    client: AsyncClient, group_id: str, membership_id: str, **body: Any
) -> Response:
    return await unsafe(
        client, "PUT", f"/api/v1/groups/{group_id}/children/{membership_id}/login", json=body
    )


async def _child_login(client: AsyncClient, home_code: str, username: str, pin: str) -> Response:
    return await unsafe(
        client,
        "POST",
        "/api/v1/auth/child/login",
        json={"home_code": home_code, "username": username, "pin": pin},
    )


def _high_limits() -> Any:
    return get_settings().model_copy(update={"rate_limit_login": 1000})


async def _logged_in_child(admin_client: AsyncClient, suffix: str) -> tuple[AsyncClient, str]:
    """Full setup: Family Home + Child + login config + an authenticated
    child session. Returns (child_client, group_id) — caller must close
    child_client."""
    group_id, membership_id, home_code = await _make_family_home_with_child(admin_client, suffix)
    assert (
        await _configure_login(
            admin_client, group_id, membership_id, enabled=True, username="erin", pin="4242"
        )
    ).status_code == 200

    child_client = await new_client()
    app.dependency_overrides[get_settings] = _high_limits
    try:
        login = await _child_login(child_client, home_code, "erin", "4242")
        assert login.status_code == 200, login.text
        assert login.json()["principal_type"] == "managed_child"
    finally:
        app.dependency_overrides.pop(get_settings, None)
    return child_client, group_id


@pytest.mark.asyncio
async def test_child_can_view_todays_meal_plan(client: AsyncClient) -> None:
    """The Home dashboard's Meals card must load for a Child — meals_view is
    a read-only baseline capability, not something a parent has to grant via
    ChildProfile settings (there is no such toggle)."""
    child_client, group_id = await _logged_in_child(client, unique("mealview"))
    try:
        today = date.today().isoformat()
        response = await child_client.get(f"/api/v1/homes/{group_id}/meal-plan/day?date={today}")
        assert response.status_code == 200, response.text
    finally:
        await child_client.aclose()


@pytest.mark.asyncio
async def test_child_cannot_create_or_modify_meal_plan_entries(client: AsyncClient) -> None:
    """meals_manage stays out of reach — a Child gaining Meals *visibility*
    must never widen into meal-plan *write* access."""
    child_client, group_id = await _logged_in_child(client, unique("mealwrite"))
    try:
        create_meal = await unsafe(
            child_client,
            "POST",
            f"/api/v1/homes/{group_id}/meals",
            json={"name": "Snacks", "meal_type": "snack", "ingredients": []},
        )
        assert create_meal.status_code == 403

        create_entry = await unsafe(
            child_client,
            "POST",
            f"/api/v1/homes/{group_id}/meal-plan/entries",
            json={
                "quick_meal_name": "Takeaway",
                "date": date.today().isoformat(),
                "meal_slot": "dinner",
            },
        )
        assert create_entry.status_code == 403
    finally:
        await child_client.aclose()


@pytest.mark.asyncio
async def test_child_cannot_view_the_member_roster_or_invite(client: AsyncClient) -> None:
    """members_view/members_invite remain unavailable to a Child — the Home
    dashboard degrades this gracefully client-side instead of granting the
    capability, so this boundary must not have moved."""
    child_client, group_id = await _logged_in_child(client, unique("members"))
    try:
        members = await child_client.get(f"/api/v1/groups/{group_id}/members")
        assert members.status_code == 403

        invite = await unsafe(
            child_client,
            "POST",
            "/api/v1/invitations",
            json={
                "group_id": group_id,
                "email": "someone@example.com",
                "relationship": "partner",
            },
        )
        assert invite.status_code == 403
    finally:
        await child_client.aclose()


@pytest.mark.asyncio
async def test_child_home_page_calls_do_not_error_when_meals_feature_is_on(
    client: AsyncClient,
) -> None:
    """End-to-end proof that the exact endpoint the Home page's Meals card
    calls succeeds for a Child on a Family Home with Meals released — this
    is the concrete request that previously 403'd."""
    child_client, group_id = await _logged_in_child(client, unique("dashboard"))
    try:
        today = date.today().isoformat()
        billing = await child_client.get(f"/api/v1/groups/{group_id}/billing")
        assert billing.status_code == 200
        assert billing.json()["meals_enabled"] is True

        day = await child_client.get(f"/api/v1/homes/{group_id}/meal-plan/day?date={today}")
        assert day.status_code == 200

        feature_matrix = await child_client.get(f"/api/v1/features/{group_id}")
        assert feature_matrix.status_code == 200

        home_response = await child_client.get("/api/v1/groups")
        assert home_response.status_code == 200
        home = next(row for row in home_response.json() if row["id"] == group_id)
        assert "meals.view" in home["capabilities"]
        assert "meals.manage" not in home["capabilities"]
        assert "members.invite" not in home["capabilities"]
        assert "members.view" not in home["capabilities"]
    finally:
        await child_client.aclose()
