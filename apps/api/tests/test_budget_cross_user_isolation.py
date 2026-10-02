"""Regression coverage for the two authorization boundaries budget.py relies
on, neither of which had an explicit test before this file: (1) a user who is
not a member of the Home gets no access to that Home's budget route at all,
and (2) two users who *are* members of the same Home never see each other's
budget data, because BudgetProfile/BudgetItem are keyed to the caller's own
user id (`_profile(db, auth.user.id)` in routers/budget.py), never to an id
supplied in the request. See docs/security/MYKHAYA_SECURITY_AUDIT_2026-10.md
(BOLA/IDOR audit) for why this file exists.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_budget_rollout import _set_ultimate_plan
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import HouseholdRelationship, Membership, PermissionProfile, Role, User


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


async def _setup_home(client: AsyncClient, suffix: str, label: str) -> str:
    await create_verified_user(client, f"budget-iso-{suffix}@example.com", label)
    home = await unsafe(client, "POST", "/api/v1/groups", json={"name": f"{label} Home"})
    assert home.status_code == 201
    home_id = home.json()["id"]
    await _set_ultimate_plan(home_id)
    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Cross-user isolation coverage", "confirmed": True},
    )
    assert enabled.status_code == 200
    return home_id


async def _join_home_as_adult_member(home_id: str, email: str, name: str) -> None:
    """Add an existing registered+verified user to a Home directly, bypassing
    the invitation flow (irrelevant to what this test proves)."""
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        db.add(
            Membership(
                group_id=uuid.UUID(home_id),
                user_id=user.id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_budget_route_denies_a_user_who_is_not_a_home_member(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _setup_home(client, suffix, "Owner")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as outsider:
        await create_verified_user(outsider, f"budget-outsider-{suffix}@example.com", "Outsider")
        denied = await outsider.get(f"/api/v1/homes/{home_id}/budget")
        assert denied.status_code in (403, 404)


@pytest.mark.asyncio
async def test_two_members_of_the_same_home_never_see_each_others_budget_items(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _setup_home(client, suffix, "Shared")

    second_email = f"budget-iso-second-{suffix}@example.com"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        await create_verified_user(second_client, second_email, "Second Member")
        await _join_home_as_adult_member(home_id, second_email, "Second Member")

        now = datetime.now(UTC)
        category = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/budget/categories",
            json={"name": "Owner's Category", "year": now.year, "month": now.month},
        )
        assert category.status_code == 201

        owner_item = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/budget/items",
            json={
                "category_id": category.json()["id"],
                "name": "Owner's Private Line Item",
                "item_type": "fixed",
                "default_amount": 123,
                "recurring": True,
                "starts_on": datetime.now(UTC).strftime("%Y-%m-01"),
                "year": datetime.now(UTC).year,
                "month": datetime.now(UTC).month,
            },
        )
        assert owner_item.status_code == 201

        second_member_items = await second_client.get(f"/api/v1/homes/{home_id}/budget/items")
        assert second_member_items.status_code == 200
        assert second_member_items.json() == [], (
            "A second Home member must never see another member's budget items — "
            "budget data is keyed to the caller's own user id, not shared per-Home."
        )

        second_member_profile = await second_client.get(f"/api/v1/homes/{home_id}/budget")
        assert second_member_profile.status_code == 200
        owner_profile = await client.get(f"/api/v1/homes/{home_id}/budget")
        assert owner_profile.status_code == 200
        assert second_member_profile.json()["id"] != owner_profile.json()["id"], (
            "Each Home member must get their own BudgetProfile row, never the "
            "first member's row returned for a different caller."
        )
