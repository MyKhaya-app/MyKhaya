import pytest

from mykhaya.billing.config import StripeConfig
from mykhaya.billing.transitions import (
    InvalidSubscriptionTransition,
    price_id_for,
    validate_transition,
)
from mykhaya.models import BillingInterval, SubscriptionPlan, SubscriptionStatus


def _config() -> StripeConfig:
    return StripeConfig(
        source="environment",
        configured=True,
        secret_key="sk_test_only",
        family_monthly_price_id="price_family_month",
        family_annual_price_id="price_family_year",
        ultimate_monthly_price_id="price_ultimate_month",
        ultimate_annual_price_id="price_ultimate_year",
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (SubscriptionPlan.free, SubscriptionPlan.family),
        (SubscriptionPlan.free, SubscriptionPlan.ultimate),
        (SubscriptionPlan.family, SubscriptionPlan.ultimate),
        (SubscriptionPlan.family, SubscriptionPlan.free),
        (SubscriptionPlan.ultimate, SubscriptionPlan.family),
        (SubscriptionPlan.ultimate, SubscriptionPlan.free),
    ],
)
def test_supported_transition_matrix(current: SubscriptionPlan, target: SubscriptionPlan) -> None:
    validate_transition(current, target)


def test_same_paid_plan_allows_interval_change() -> None:
    validate_transition(
        SubscriptionPlan.family,
        SubscriptionPlan.family,
        BillingInterval.month,
        BillingInterval.year,
    )


def test_same_plan_and_interval_is_rejected() -> None:
    with pytest.raises(InvalidSubscriptionTransition):
        validate_transition(
            SubscriptionPlan.family,
            SubscriptionPlan.family,
            BillingInterval.month,
            BillingInterval.month,
        )


def test_cancel_at_period_end_can_be_reactivated() -> None:
    validate_transition(
        SubscriptionPlan.family,
        SubscriptionPlan.family,
        BillingInterval.month,
        BillingInterval.month,
        SubscriptionStatus.cancel_at_period_end,
    )


def test_free_cannot_change_to_free() -> None:
    with pytest.raises(InvalidSubscriptionTransition):
        validate_transition(SubscriptionPlan.free, SubscriptionPlan.free)


@pytest.mark.parametrize(
    ("plan", "interval", "expected"),
    [
        (SubscriptionPlan.family, BillingInterval.month, "price_family_month"),
        (SubscriptionPlan.family, BillingInterval.year, "price_family_year"),
        (SubscriptionPlan.ultimate, BillingInterval.month, "price_ultimate_month"),
        (SubscriptionPlan.ultimate, BillingInterval.year, "price_ultimate_year"),
        (SubscriptionPlan.free, None, None),
    ],
)
def test_price_ids_are_server_owned(
    plan: SubscriptionPlan, interval: BillingInterval | None, expected: str | None
) -> None:
    assert price_id_for(_config(), plan, interval) == expected


def test_paid_plan_requires_interval() -> None:
    with pytest.raises(InvalidSubscriptionTransition):
        price_id_for(_config(), SubscriptionPlan.family, None)
