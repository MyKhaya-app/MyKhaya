"""Fixed Budget item lifecycle dates and entry-linked payment status.

Covers: BudgetItem.starts_on/ends_on eligibility (inclusive end month, no end
date continuing indefinitely), rejecting an end before the start, and the
BudgetSpendingEntry -> BudgetMonthItem link that derives PAID/NOT PAID status
without a manually-toggled flag or double-counting Actual. See
routers.budget._item_active_in_month, _resolve_linked_item and
_item_payment_status.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from test_budget_rollout import _set_ultimate_plan
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def _shift(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


async def _setup_home(client: AsyncClient, suffix: str, label: str) -> tuple[str, str]:
    email = f"budget-lifecycle-{suffix}@example.com"
    await create_verified_user(client, email, label)
    home = await unsafe(client, "POST", "/api/v1/groups", json={"name": f"{label} Home"})
    assert home.status_code == 201
    home_id = home.json()["id"]
    await _set_ultimate_plan(home_id)
    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Fixed item lifecycle coverage", "confirmed": True},
    )
    assert enabled.status_code == 200
    return home_id, email


async def _month_items(client: AsyncClient, home_id: str, year: int, month: int) -> dict:
    response = await client.get(f"/api/v1/homes/{home_id}/budget/months/{year}/{month}")
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_end_date_is_inclusive_and_no_end_date_continues_indefinitely(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id, _ = await _setup_home(client, suffix, "Lifecycle Dates")
    now = datetime.now(UTC)
    year, month = now.year, now.month
    category = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/categories",
        json={"name": "Loans", "year": year, "month": month},
    )
    assert category.status_code == 201
    category_id = category.json()["id"]

    end_year, end_month = _shift(year, month, 2)
    after_end_year, after_end_month = _shift(year, month, 3)
    far_future_year, far_future_month = _shift(year, month, 24)

    dated = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/items",
        json={
            "category_id": category_id, "name": "Vehicle Loan", "item_type": "fixed",
            "default_amount": 435, "recurring": True,
            "starts_on": f"{year}-{month:02d}-01",
            "ends_on": f"{end_year}-{end_month:02d}-01",
            "notes": "Car loan through XYZ Finance",
            "year": year, "month": month,
        },
    )
    assert dated.status_code == 201
    assert dated.json()["ends_on"] == f"{end_year}-{end_month:02d}-01"
    assert dated.json()["notes"] == "Car loan through XYZ Finance"

    open_ended = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/items",
        json={
            "category_id": category_id, "name": "Subscription", "item_type": "fixed",
            "default_amount": 12, "recurring": True,
            "starts_on": f"{year}-{month:02d}-01",
            "year": year, "month": month,
        },
    )
    assert open_ended.status_code == 201
    assert open_ended.json()["ends_on"] is None

    # Present through the end month inclusive.
    at_end = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/budget/months/{end_year}/{end_month}")
    assert at_end.status_code == 201
    end_items = next(row for row in at_end.json()["categories"] if row["category_id"] == category_id)["items"]
    assert {item["name"] for item in end_items} == {"Vehicle Loan", "Subscription"}

    # Absent the month immediately after the inclusive end month.
    after_end = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/budget/months/{after_end_year}/{after_end_month}")
    assert after_end.status_code == 201
    after_end_items = next(row for row in after_end.json()["categories"] if row["category_id"] == category_id)["items"]
    assert {item["name"] for item in after_end_items} == {"Subscription"}

    # The open-ended item keeps appearing indefinitely.
    far_future = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/months/{far_future_year}/{far_future_month}"
    )
    assert far_future.status_code == 201
    far_future_items = next(
        row for row in far_future.json()["categories"] if row["category_id"] == category_id
    )["items"]
    assert {item["name"] for item in far_future_items} == {"Subscription"}

    # Historical month created before the end-date edit is never rewritten.
    historical = await _month_items(client, home_id, year, month)
    historical_items = next(row for row in historical["categories"] if row["category_id"] == category_id)["items"]
    assert {item["name"] for item in historical_items} == {"Vehicle Loan", "Subscription"}


@pytest.mark.asyncio
async def test_end_before_start_is_rejected(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id, _ = await _setup_home(client, suffix, "Invalid Lifecycle")
    now = datetime.now(UTC)
    year, month = now.year, now.month
    category = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/categories",
        json={"name": "Loans", "year": year, "month": month},
    )
    category_id = category.json()["id"]

    invalid = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/items",
        json={
            "category_id": category_id, "name": "Vehicle Loan", "item_type": "fixed",
            "default_amount": 435, "recurring": True,
            "starts_on": f"{year}-{month:02d}-01",
            "ends_on": f"{year - 1}-{month:02d}-01",
            "year": year, "month": month,
        },
    )
    assert invalid.status_code == 422

    valid = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/items",
        json={
            "category_id": category_id, "name": "Vehicle Loan", "item_type": "fixed",
            "default_amount": 435, "recurring": True,
            "starts_on": f"{year}-{month:02d}-01",
            "year": year, "month": month,
        },
    )
    assert valid.status_code == 201
    item_id = valid.json()["id"]

    invalid_update = await unsafe(
        client, "PUT", f"/api/v1/homes/{home_id}/budget/items/{item_id}",
        json={
            "name": "Vehicle Loan", "default_amount": 435, "recurring": True,
            "starts_on": f"{year}-{month:02d}-01",
            "ends_on": f"{year - 1}-{month:02d}-01",
            "year": year, "month": month,
        },
    )
    assert invalid_update.status_code == 422


@pytest.mark.asyncio
async def test_linked_entry_drives_month_specific_payment_status(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id, _ = await _setup_home(client, suffix, "Payment Status")
    now = datetime.now(UTC)
    year, month = now.year, now.month
    next_year, next_month = _shift(year, month, 1)

    category = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/categories",
        json={"name": "Loans", "year": year, "month": month},
    )
    category_id = category.json()["id"]
    item = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/items",
        json={
            "category_id": category_id, "name": "Vehicle Loan", "item_type": "fixed",
            "default_amount": 435, "recurring": True,
            "starts_on": f"{year}-{month:02d}-01", "year": year, "month": month,
        },
    )
    assert item.status_code == 201

    current = await _month_items(client, home_id, year, month)
    current_category = next(row for row in current["categories"] if row["category_id"] == category_id)
    assert current_category["items"][0]["payment_status"] == "not_paid"
    month_item_id = current_category["items"][0]["id"]

    # Create next month's snapshot so its own copy of the item exists too.
    next_month_resp = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/budget/months/{next_year}/{next_month}")
    assert next_month_resp.status_code == 201
    next_category = next(row for row in next_month_resp.json()["categories"] if row["category_id"] == category_id)
    next_month_item_id = next_category["items"][0]["id"]
    assert next_category["items"][0]["payment_status"] == "not_paid"

    entry = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/entries",
        json={
            "category_id": category_id, "description": "Vehicle Loan", "amount": 435,
            "spent_on": f"{year}-{month:02d}-01", "budget_month_item_id": month_item_id,
        },
    )
    assert entry.status_code == 201
    entry_id = entry.json()["id"]
    assert entry.json()["budget_month_item_id"] == month_item_id

    paid = await _month_items(client, home_id, year, month)
    paid_category = next(row for row in paid["categories"] if row["category_id"] == category_id)
    paid_item = paid_category["items"][0]
    assert paid_item["payment_status"] == "paid"
    assert paid_item["paid_entry"]["amount"] == 435
    assert paid_category["entries_actual"] == 435
    assert paid_category["actual_amount"] == 435  # counted exactly once, no fixed_actual double count
    assert paid_category["planned_amount"] == 435

    # Next month's own snapshot is unaffected by this month's payment.
    still_unpaid_next = await _month_items(client, home_id, next_year, next_month)
    still_unpaid_category = next(row for row in still_unpaid_next["categories"] if row["category_id"] == category_id)
    assert still_unpaid_category["items"][0]["payment_status"] == "not_paid"
    assert still_unpaid_category["items"][0]["id"] == next_month_item_id

    # Editing the linked entry keeps it paid and still counts once.
    edited = await unsafe(
        client, "PUT", f"/api/v1/homes/{home_id}/budget/entries/{entry_id}",
        json={
            "category_id": category_id, "description": "Vehicle Loan", "amount": 435,
            "spent_on": f"{year}-{month:02d}-02", "budget_month_item_id": month_item_id,
        },
    )
    assert edited.status_code == 200
    still_paid = await _month_items(client, home_id, year, month)
    still_paid_category = next(row for row in still_paid["categories"] if row["category_id"] == category_id)
    assert still_paid_category["items"][0]["payment_status"] == "paid"
    assert still_paid_category["actual_amount"] == 435

    # Deleting the linked transaction returns the item to NOT PAID.
    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/budget/entries/{entry_id}")
    assert deleted.status_code == 204
    reverted = await _month_items(client, home_id, year, month)
    reverted_category = next(row for row in reverted["categories"] if row["category_id"] == category_id)
    assert reverted_category["items"][0]["payment_status"] == "not_paid"
    assert reverted_category["items"][0]["paid_entry"] is None
    assert reverted_category["actual_amount"] == 0


@pytest.mark.asyncio
async def test_entry_link_validation_rejects_mismatched_category_and_cross_profile(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id, _ = await _setup_home(client, suffix, "Link Validation")
    now = datetime.now(UTC)
    year, month = now.year, now.month

    loans = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/categories",
        json={"name": "Loans", "year": year, "month": month},
    )
    groceries = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/categories",
        json={"name": "Groceries", "year": year, "month": month},
    )
    loans_id = loans.json()["id"]
    groceries_id = groceries.json()["id"]
    item = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/items",
        json={
            "category_id": loans_id, "name": "Vehicle Loan", "item_type": "fixed",
            "default_amount": 435, "recurring": True,
            "starts_on": f"{year}-{month:02d}-01", "year": year, "month": month,
        },
    )
    month_data = await _month_items(client, home_id, year, month)
    loans_category = next(row for row in month_data["categories"] if row["category_id"] == loans_id)
    month_item_id = loans_category["items"][0]["id"]

    # Wrong category for the linked item.
    mismatched = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/budget/entries",
        json={
            "category_id": groceries_id, "description": "Vehicle Loan", "amount": 435,
            "spent_on": f"{year}-{month:02d}-01", "budget_month_item_id": month_item_id,
        },
    )
    assert mismatched.status_code == 422

    # A different user's own Budget item id is not linkable at all.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_home_id, _ = await _setup_home(other_client, f"{suffix}-other", "Other Owner")
        now2 = datetime.now(UTC)
        other_category = await unsafe(
            other_client, "POST", f"/api/v1/homes/{other_home_id}/budget/categories",
            json={"name": "Loans", "year": now2.year, "month": now2.month},
        )
        other_category_id = other_category.json()["id"]
        cross_profile = await unsafe(
            other_client, "POST", f"/api/v1/homes/{other_home_id}/budget/entries",
            json={
                "category_id": other_category_id, "description": "Vehicle Loan", "amount": 435,
                "spent_on": f"{now2.year}-{now2.month:02d}-01", "budget_month_item_id": month_item_id,
            },
        )
        assert cross_profile.status_code == 404
