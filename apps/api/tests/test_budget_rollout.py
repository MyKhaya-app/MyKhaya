"""Focused rollout tests for the disabled-by-default Budget Home control."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import AuditEvent, BudgetCategory, BudgetMonthCategory


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.mark.asyncio
async def test_budget_home_rollout_preserves_profile_and_audits_enable_disable(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"budget-rollout-{suffix}@example.com", "Budget Owner")
    home = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Budget Rollout Home"})
    assert home.status_code == 201
    home_id = home.json()["id"]

    management = await client.get(f"/api/v1/features/{home_id}/modules/management")
    assert management.status_code == 200
    budget = next(row for row in management.json() if row["id"] == "budget")
    assert budget["enabled"] is False
    assert budget["toggleable"] is True

    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Enable Budget for rollout", "confirmed": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    profile = await client.get(f"/api/v1/homes/{home_id}/budget")
    assert profile.status_code == 200
    profile_id = profile.json()["id"]
    settings = await unsafe(
        client,
        "PUT",
        f"/api/v1/homes/{home_id}/budget/settings",
        json={"currency": "EUR", "month_start_day": 15},
    )
    assert settings.status_code == 200
    assert settings.json()["month_start_day"] == 15

    disabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": False, "reason": "Disable Budget for rollout", "confirmed": True},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert (await client.get(f"/api/v1/homes/{home_id}/budget")).status_code == 404

    reenabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Restore Budget access", "confirmed": True},
    )
    assert reenabled.status_code == 200
    restored = await client.get(f"/api/v1/homes/{home_id}/budget/settings")
    assert restored.status_code == 200
    assert restored.json()["id"] == profile_id
    assert restored.json()["currency"] == "EUR"
    assert restored.json()["month_start_day"] == 15

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.group_id == uuid.UUID(home_id),
                    AuditEvent.action.in_(("feature.enabled", "feature.disabled")),
                )
                .order_by(AuditEvent.created_at)
            )
        ).all()
    budget_events = [event for event in events if event.metadata_.get("feature") == "budget"]
    assert [event.action for event in budget_events[-3:]] == [
        "feature.enabled",
        "feature.disabled",
        "feature.enabled",
    ]


@pytest.mark.asyncio
async def test_category_creation_seeds_only_selected_snapshot_and_future_months(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"budget-category-{suffix}@example.com", "Category Owner")
    home = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Budget Category Home"})
    assert home.status_code == 201
    home_id = home.json()["id"]

    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Enable category regression coverage", "confirmed": True},
    )
    assert enabled.status_code == 200

    # Establish an earlier snapshot before the category exists.
    historical = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/months/2025/9",
    )
    assert historical.status_code == 201

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/categories",
        json={"name": "Housing", "year": 2026, "month": 9},
    )
    assert created.status_code == 201
    category_id = created.json()["id"]

    current = await client.get(f"/api/v1/homes/{home_id}/budget/months/2026/9")
    assert current.status_code == 200
    current_category = next(
        row for row in current.json()["categories"] if row["category_id"] == category_id
    )
    assert current_category["planned_amount"] == 0
    assert current_category["actual_amount"] == 0

    planned = await unsafe(
        client,
        "PUT",
        f"/api/v1/homes/{home_id}/budget/months/2026/9/categories/{category_id}/plan",
        json={"planned_amount": 1150},
    )
    assert planned.status_code == 200
    reloaded = await client.get(f"/api/v1/homes/{home_id}/budget/months/2026/9")
    assert (
        next(row for row in reloaded.json()["categories"] if row["category_id"] == category_id)["planned_amount"]
        == 1150
    )

    unchanged_historical = await client.get(f"/api/v1/homes/{home_id}/budget/months/2025/9")
    assert unchanged_historical.status_code == 200
    assert all(
        row["category_id"] != category_id for row in unchanged_historical.json()["categories"]
    )

    future = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/budget/months/2026/10")
    assert future.status_code == 201
    assert any(row["category_id"] == category_id for row in future.json()["categories"])


@pytest.mark.asyncio
async def test_current_snapshot_reconciles_pre_fix_missing_category_without_touching_history(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"budget-repair-{suffix}@example.com", "Repair Owner")
    home = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Budget Repair Home"})
    assert home.status_code == 201
    home_id = home.json()["id"]
    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Enable repair regression coverage", "confirmed": True},
    )
    assert enabled.status_code == 200

    now = datetime.now(UTC)
    current_index = now.year * 12 + now.month - 1

    def period(offset: int) -> tuple[int, int]:
        value = current_index + offset
        return value // 12, value % 12 + 1

    previous_year, previous_month = period(-1)
    current_year, current_month = period(0)
    future_year, future_month = period(1)
    later_year, later_month = period(2)

    # This is the pre-fix shape: the master category is created after the
    # previous snapshot, then the current snapshot is missing its membership.
    previous = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/months/{previous_year}/{previous_month}",
    )
    assert previous.status_code == 201
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/categories",
        json={"name": "Housing"},
    )
    assert created.status_code == 201
    category_id = uuid.UUID(created.json()["id"])
    current = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/months/{current_year}/{current_month}",
    )
    assert current.status_code == 201
    current_month_id = uuid.UUID(current.json()["id"])

    async with SessionFactory() as db:
        await db.execute(
            delete(BudgetMonthCategory).where(BudgetMonthCategory.month_id == current_month_id)
        )
        await db.commit()

    categories = await client.get(f"/api/v1/homes/{home_id}/budget/categories")
    assert categories.status_code == 200
    assert any(row["id"] == str(category_id) for row in categories.json())

    # The UI's month load is the compatibility/reconciliation path.
    loaded = await client.get(
        f"/api/v1/homes/{home_id}/budget/months/{current_year}/{current_month}"
    )
    assert loaded.status_code == 200
    repaired = next(
        row for row in loaded.json()["categories"] if row["category_id"] == str(category_id)
    )
    assert repaired["planned_amount"] == 0
    assert repaired["actual_amount"] == 0

    planned = await unsafe(
        client,
        "PUT",
        f"/api/v1/homes/{home_id}/budget/months/{current_year}/{current_month}/categories/{category_id}/plan",
        json={"planned_amount": 500},
    )
    assert planned.status_code == 200
    reloaded = await client.get(
        f"/api/v1/homes/{home_id}/budget/months/{current_year}/{current_month}"
    )
    assert next(
        row for row in reloaded.json()["categories"] if row["category_id"] == str(category_id)
    )["planned_amount"] == 500

    historical = await client.get(
        f"/api/v1/homes/{home_id}/budget/months/{previous_year}/{previous_month}"
    )
    assert historical.status_code == 200
    assert all(row["category_id"] != str(category_id) for row in historical.json()["categories"])

    future = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/months/{future_year}/{future_month}",
    )
    assert future.status_code == 201
    assert any(row["category_id"] == str(category_id) for row in future.json()["categories"])

    async with SessionFactory() as db:
        category = await db.get(BudgetCategory, category_id)
        assert category is not None
        category.archived_at = datetime.now(UTC)
        await db.commit()

    later = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/months/{later_year}/{later_month}",
    )
    assert later.status_code == 201
    assert all(row["category_id"] != str(category_id) for row in later.json()["categories"])
