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
from mykhaya.models import (
    AuditEvent,
    BudgetCategory,
    BudgetMonthCategory,
    BudgetMonthIncome,
    BudgetMonthItem,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    User,
)


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


@pytest.mark.asyncio
async def test_income_source_creation_reconciles_selected_month_and_handles_duplicates(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"budget-income-{suffix}@example.com", "Income Owner")
    home = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Budget Income Home"})
    assert home.status_code == 201
    home_id = home.json()["id"]
    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Income lifecycle coverage", "confirmed": True},
    )
    assert enabled.status_code == 200

    current = datetime.now(UTC)
    year, month = current.year, current.month
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/income-sources",
        json={"name": "NNUH", "year": year, "month": month},
    )
    assert created.status_code == 201
    source_id = created.json()["id"]

    loaded = await client.get(f"/api/v1/homes/{home_id}/budget/months/{year}/{month}")
    assert loaded.status_code == 200
    assert any(row["source_id"] == source_id for row in loaded.json()["income"])

    duplicate = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/income-sources",
        json={"name": "NNUH", "year": year, "month": month},
    )
    assert duplicate.status_code == 409
    assert "Income source already exists" in duplicate.json()["detail"]
    assert "uq_budget_income_source_name" not in duplicate.text

    previous_month = month - 1 or 12
    previous_year = year if month > 1 else year - 1
    historical = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/months/{previous_year}/{previous_month}",
    )
    assert historical.status_code == 201
    assert next(row for row in historical.json()["income"] if row["source_id"] == source_id)["source_name"] == "NNUH"

    renamed = await unsafe(
        client,
        "PUT",
        f"/api/v1/homes/{home_id}/budget/income-sources/{source_id}",
        json={"name": "NNUH Salary", "sort_order": 0},
    )
    assert renamed.status_code == 200
    current_after_rename = await client.get(f"/api/v1/homes/{home_id}/budget/months/{year}/{month}")
    assert next(row for row in current_after_rename.json()["income"] if row["source_id"] == source_id)["source_name"] == "NNUH Salary"
    historical_after_rename = await client.get(
        f"/api/v1/homes/{home_id}/budget/months/{previous_year}/{previous_month}"
    )
    assert next(row for row in historical_after_rename.json()["income"] if row["source_id"] == source_id)["source_name"] == "NNUH"

    archived = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/budget/income-sources/{source_id}",
    )
    assert archived.status_code == 204
    current_after_archive = await client.get(f"/api/v1/homes/{home_id}/budget/months/{year}/{month}")
    assert all(row["source_id"] != source_id for row in current_after_archive.json()["income"])
    historical_after_archive = await client.get(
        f"/api/v1/homes/{home_id}/budget/months/{previous_year}/{previous_month}"
    )
    assert next(row for row in historical_after_archive.json()["income"] if row["source_id"] == source_id)["source_name"] == "NNUH"

    async with SessionFactory() as db:
        memberships = (
            await db.scalars(
                select(BudgetMonthIncome).where(BudgetMonthIncome.source_id == uuid.UUID(source_id))
            )
        ).all()
    assert len(memberships) == 1


@pytest.mark.asyncio
async def test_budget_items_copy_recurrence_totals_and_entry_notes(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"budget-v2-{suffix}@example.com", "Budget V2 Owner")
    home = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Budget V2 Home"})
    assert home.status_code == 201
    home_id = home.json()["id"]
    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Budget V2 integration coverage", "confirmed": True},
    )
    assert enabled.status_code == 200

    now = datetime.now(UTC)
    year, month = now.year, now.month
    next_period = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1)
    next_year, next_month = next_period.year, next_period.month
    category = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/categories",
        json={"name": "V2 Housing", "year": year, "month": month},
    )
    assert category.status_code == 201
    category_id = category.json()["id"]

    fixed = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/items",
        json={
            "category_id": category_id,
            "name": "Mortgage",
            "item_type": "fixed",
            "default_amount": 1150,
            "recurring": True,
            "starts_on": f"{year}-{month:02d}-01",
            "year": year,
            "month": month,
        },
    )
    variable = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/items",
        json={
            "category_id": category_id,
            "name": "Repairs",
            "item_type": "variable",
            "default_amount": 300,
            "recurring": False,
            "starts_on": f"{year}-{month:02d}-01",
            "year": year,
            "month": month,
        },
    )
    assert fixed.status_code == 201
    assert variable.status_code == 201
    fixed_id = fixed.json()["id"]
    variable_id = variable.json()["id"]

    current = await client.get(f"/api/v1/homes/{home_id}/budget/months/{year}/{month}")
    assert current.status_code == 200
    current_row = next(row for row in current.json()["categories"] if row["category_id"] == category_id)
    assert current_row["planned_amount"] == 1450
    assert {item["item_type"] for item in current_row["items"]} == {"fixed", "variable"}

    edited = await unsafe(
        client,
        "PUT",
        f"/api/v1/homes/{home_id}/budget/items/{fixed_id}",
        json={
            "name": "Mortgage",
            "default_amount": 1200,
            "recurring": True,
            "starts_on": f"{year}-{month:02d}-01",
            "year": year,
            "month": month,
            "planned_amount": 1200,
        },
    )
    assert edited.status_code == 200
    current = await client.get(f"/api/v1/homes/{home_id}/budget/months/{year}/{month}")
    current_row = next(row for row in current.json()["categories"] if row["category_id"] == category_id)
    assert current_row["planned_amount"] == 1500

    copied = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/months/{next_year}/{next_month}/copy",
        json={},
    )
    assert copied.status_code == 200
    copied_row = next(row for row in copied.json()["categories"] if row["category_id"] == category_id)
    assert [item["item_type"] for item in copied_row["items"]] == ["fixed"]
    assert copied_row["planned_amount"] == 1200

    copied_with_variable = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/months/{next_year}/{next_month}/copy",
        json={"copy_fixed_items": True, "copy_variable_items": True, "copy_income_sources": True},
    )
    assert copied_with_variable.status_code == 200
    copied_row = next(row for row in copied_with_variable.json()["categories"] if row["category_id"] == category_id)
    assert {item["item_type"] for item in copied_row["items"]} == {"fixed", "variable"}
    repeated = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/months/{next_year}/{next_month}/copy",
        json={"copy_fixed_items": True, "copy_variable_items": True, "copy_income_sources": True},
    )
    assert repeated.status_code == 200
    repeated_row = next(row for row in repeated.json()["categories"] if row["category_id"] == category_id)
    assert len(repeated_row["items"]) == len(copied_row["items"])

    entry = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/budget/entries",
        json={"category_id": category_id, "description": "Builder supplies", "amount": 42, "spent_on": f"{year}-{month:02d}-15", "note": "Keep receipt"},
    )
    assert entry.status_code == 201
    assert entry.json()["note"] == "Keep receipt"
    updated_entry = await unsafe(
        client,
        "PUT",
        f"/api/v1/homes/{home_id}/budget/entries/{entry.json()['id']}",
        json={"category_id": category_id, "description": "Builder supplies", "amount": 42, "spent_on": f"{year}-{month:02d}-15", "note": "Receipt filed"},
    )
    assert updated_entry.status_code == 200
    assert updated_entry.json()["note"] == "Receipt filed"

    await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/budget/items/{variable_id}")
    async with SessionFactory() as db:
        historical_items = (
            await db.scalars(select(BudgetMonthItem).where(BudgetMonthItem.budget_item_id == uuid.UUID(variable_id)))
        ).all()
    assert historical_items


@pytest.mark.asyncio
async def test_budget_item_partner_sharing_filters_detail_and_revokes_access(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    owner_email = f"budget-share-owner-{suffix}@example.com"
    partner_email = f"budget-share-partner-{suffix}@example.com"
    await create_verified_user(client, owner_email, "Budget Share Owner")
    home = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Budget Privacy Home"})
    assert home.status_code == 201
    home_id = home.json()["id"]
    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Budget privacy coverage", "confirmed": True},
    )
    assert enabled.status_code == 200

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as partner_client:
        await create_verified_user(partner_client, partner_email, "Budget Share Partner")
        async with SessionFactory() as db:
            partner = await db.scalar(select(User).where(User.email == partner_email))
            assert partner is not None
            partner_id = partner.id
            db.add(
                Membership(
                    group_id=uuid.UUID(home_id),
                    user_id=partner_id,
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                )
            )
            await db.commit()

        now = datetime.now(UTC)
        year, month = now.year, now.month
        first_category = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/budget/categories",
            json={"name": "Housing", "year": year, "month": month},
        )
        second_category = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/budget/categories",
            json={"name": "Insurance", "year": year, "month": month},
        )
        assert first_category.status_code == 201
        assert second_category.status_code == 201
        first_id = first_category.json()["id"]
        second_id = second_category.json()["id"]
        mortgage = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/budget/items",
            json={
                "category_id": first_id,
                "name": "Mortgage",
                "item_type": "fixed",
                "default_amount": 1150,
                "recurring": True,
                "starts_on": f"{year}-{month:02d}-01",
                "year": year,
                "month": month,
            },
        )
        insurance = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/budget/items",
            json={
                "category_id": second_id,
                "name": "Insurance",
                "item_type": "variable",
                "default_amount": 240,
                "recurring": False,
                "starts_on": f"{year}-{month:02d}-01",
                "year": year,
                "month": month,
            },
        )
        assert mortgage.status_code == 201
        assert insurance.status_code == 201
        mortgage_id = mortgage.json()["id"]

        share = await unsafe(
            client,
            "PUT",
            f"/api/v1/homes/{home_id}/budget/shares/{partner_id}",
            json={"partner_user_id": str(partner_id), "level": "summary"},
        )
        assert share.status_code == 200, share.text

        discovery = await partner_client.get(f"/api/v1/homes/{home_id}/budget/shared-with-me")
        assert discovery.status_code == 200
        assert discovery.json()[0]["level"] == "summary"
        assert all(key not in discovery.text for key in ("Mortgage", "Insurance", mortgage_id))

        summary = await partner_client.get(
            f"/api/v1/homes/{home_id}/budget/shared/{await _owner_id(owner_email)}/months/{year}/{month}"
        )
        assert summary.status_code == 200
        assert summary.json()["categories"] == []
        assert all(key not in summary.text for key in ("Mortgage", "Insurance", mortgage_id))

        categories_share = await unsafe(
            client,
            "PUT",
            f"/api/v1/homes/{home_id}/budget/shares/{partner_id}",
            json={"partner_user_id": str(partner_id), "level": "categories", "category_ids": [first_id]},
        )
        assert categories_share.status_code == 200
        shared_categories = await partner_client.get(
            f"/api/v1/homes/{home_id}/budget/shared/{await _owner_id(owner_email)}/months/{year}/{month}"
        )
        assert shared_categories.status_code == 200
        assert [row["category_id"] for row in shared_categories.json()["categories"]] == [first_id]
        assert shared_categories.json()["categories"][0]["items"] == []
        assert "Mortgage" not in shared_categories.text

        full_share = await unsafe(
            client,
            "PUT",
            f"/api/v1/homes/{home_id}/budget/shares/{partner_id}",
            json={"partner_user_id": str(partner_id), "level": "full"},
        )
        assert full_share.status_code == 200
        full = await partner_client.get(
            f"/api/v1/homes/{home_id}/budget/shared/{await _owner_id(owner_email)}/months/{year}/{month}"
        )
        assert full.status_code == 200
        assert any(item["name"] == "Mortgage" for item in full.json()["categories"][0]["items"])

        direct_update = await unsafe(
            partner_client,
            "PUT",
            f"/api/v1/homes/{home_id}/budget/items/{mortgage_id}",
            json={
                "name": "Stolen Mortgage",
                "default_amount": 1,
                "recurring": True,
                "starts_on": f"{year}-{month:02d}-01",
                "year": year,
                "month": month,
            },
        )
        assert direct_update.status_code == 404

        revoked = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/budget/shares/{partner_id}")
        assert revoked.status_code == 204
        after_revoke = await partner_client.get(
            f"/api/v1/homes/{home_id}/budget/shared/{await _owner_id(owner_email)}/months/{year}/{month}"
        )
        assert after_revoke.status_code == 404


async def _owner_id(email: str) -> str:
    async with SessionFactory() as db:
        owner = await db.scalar(select(User).where(User.email == email))
        assert owner is not None
        return str(owner.id)
