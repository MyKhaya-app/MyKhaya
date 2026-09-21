import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from mykhaya.budget_schemas import (
    BudgetActualUpdate,
    BudgetIncomingShareResponse,
    BudgetMonthIncomeUpdate,
    BudgetSettingsUpdate,
    BudgetSpendingEntryUpdate,
)
from mykhaya.main import app
from mykhaya.models import BudgetActualSource, BudgetSharingLevel, FeatureKey
from mykhaya.module_registry import ReleaseState, module_definition
from mykhaya.routers.budget import calculate_actual_amount


def test_budget_is_a_released_home_toggleable_module_but_disabled_by_default() -> None:
    definition = module_definition(FeatureKey.budget.value)
    assert definition.release_state == ReleaseState.released
    assert definition.default_enabled is False
    assert definition.household_toggleable is True
    assert definition.home_admin_manageable is True
    assert definition.route == "/budget"


def test_budget_is_a_feature_key_without_an_entitlement_gate() -> None:
    assert FeatureKey.budget.value == "budget"


def test_manual_actual_never_doubles_with_spending_entries() -> None:
    assert calculate_actual_amount(
        BudgetActualSource.manual, Decimal("100.00"), Decimal("40.00")
    ) == Decimal("100.00")
    assert calculate_actual_amount(
        BudgetActualSource.entries, Decimal("100.00"), Decimal("40.00")
    ) == Decimal("40.00")


def test_actual_source_contract_requires_only_the_selected_value() -> None:
    assert BudgetActualUpdate(
        source=BudgetActualSource.manual, manual_actual=100
    ).manual_actual == 100
    assert BudgetActualUpdate(source=BudgetActualSource.entries).manual_actual is None
    with pytest.raises(ValidationError):
        BudgetActualUpdate(source=BudgetActualSource.manual)
    with pytest.raises(ValidationError):
        BudgetActualUpdate(source=BudgetActualSource.entries, manual_actual=100)


def test_partner_sharing_levels_are_explicit() -> None:
    assert {level.value for level in BudgetSharingLevel} == {
        "summary",
        "categories",
        "full",
    }


def test_phase_3b_budget_endpoints_are_registered() -> None:
    routes = {
        (path, method.upper())
        for path, operation in app.openapi()["paths"].items()
        for method in operation
        if method in {"get", "put", "post", "patch", "delete"}
    }
    expected = {
        ("/api/v1/homes/{home_id}/budget/settings", "GET"),
        ("/api/v1/homes/{home_id}/budget/settings", "PUT"),
        ("/api/v1/homes/{home_id}/budget/entries", "GET"),
        ("/api/v1/homes/{home_id}/budget/entries/{entry_id}", "GET"),
        ("/api/v1/homes/{home_id}/budget/entries/{entry_id}", "PUT"),
        ("/api/v1/homes/{home_id}/budget/entries/{entry_id}", "DELETE"),
        ("/api/v1/homes/{home_id}/budget/months/{year}/{month}/income/{source_id}", "PUT"),
        ("/api/v1/homes/{home_id}/budget/shared-with-me", "GET"),
    }
    assert expected <= routes


def test_spending_entry_contract_supports_edit_and_delete_without_source_mixing() -> None:
    entry = BudgetSpendingEntryUpdate(
        category_id=uuid.uuid4(),
        description="Updated groceries",
        amount=42.50,
        spent_on="2026-09-20",
    )
    assert entry.amount == 42.50
    assert calculate_actual_amount(BudgetActualSource.entries, Decimal("100"), Decimal("42.50")) == Decimal("42.50")
    assert calculate_actual_amount(BudgetActualSource.entries, Decimal("100"), Decimal("0")) == Decimal("0")
    assert calculate_actual_amount(BudgetActualSource.manual, Decimal("100"), Decimal("42.50")) == Decimal("100")


def test_monthly_income_mutation_is_explicitly_amount_based() -> None:
    update = BudgetMonthIncomeUpdate(expected_amount=4850, received_amount=4200)
    assert update.expected_amount == 4850
    assert update.received_amount == 4200


def test_budget_settings_are_a_small_user_owned_profile_update() -> None:
    settings = BudgetSettingsUpdate(currency="gbp", month_start_day=15)
    assert settings.currency == "gbp"
    assert settings.month_start_day == 15
    assert not hasattr(settings, "home_id")


def test_budget_month_start_is_bounded_to_safe_calendar_days() -> None:
    with pytest.raises(ValidationError):
        BudgetSettingsUpdate(currency="GBP", month_start_day=0)
    with pytest.raises(ValidationError):
        BudgetSettingsUpdate(currency="GBP", month_start_day=29)


def test_incoming_share_discovery_has_metadata_only() -> None:
    fields = set(BudgetIncomingShareResponse.model_fields)
    assert fields == {"home_id", "owner_user_id", "owner_display_name", "level"}
    assert "categories" not in fields
    assert "income" not in fields
    assert "spending_entries" not in fields


def test_revoked_shares_are_not_representable_as_incoming_discovery() -> None:
    # Discovery is intentionally an active-share response contract; revocation
    # is represented only by absence, while the existing owner list retains the
    # audit-visible inactive row.
    assert "active" not in BudgetIncomingShareResponse.model_fields
