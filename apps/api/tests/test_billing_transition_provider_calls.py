from uuid import uuid4

import pytest

from mykhaya.billing import transitions as transitions_module
from mykhaya.billing.config import StripeConfig
from mykhaya.billing.pricing import PriceOption
from mykhaya.billing.transitions import apply_subscription_change, preview_subscription_change
from mykhaya.models import (
    BillingInterval,
    HomeSubscription,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
)


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


def _home(plan: SubscriptionPlan = SubscriptionPlan.family) -> HomeSubscription:
    home = HomeSubscription(group_id=uuid4())
    home.plan = plan
    home.provider = SubscriptionProvider.stripe
    home.status = SubscriptionStatus.active
    home.billing_interval = BillingInterval.month
    home.external_customer_id = "cus_test"
    home.external_subscription_id = "sub_test"
    home.external_price_id = "price_family_month"
    return home


def _subscription() -> dict[str, object]:
    return {
        "id": "sub_test",
        "customer": "cus_test",
        "status": "active",
        "current_period_start": 1_700_000_000,
        "current_period_end": 1_702_592_000,
        "items": {"data": [{"id": "si_test", "price": {"id": "price_family_month"}}]},
    }


class _FakeDb:
    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_preview_uses_provider_amount_without_frontend_math(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call(func):
        return func()

    monkeypatch.setattr(transitions_module, "call_stripe", fake_call)
    monkeypatch.setattr(
        transitions_module.stripe.Subscription,
        "retrieve",
        lambda *a, **k: _subscription(),
    )
    monkeypatch.setattr(
        transitions_module.stripe.Invoice,
        "create_preview",
        lambda **kwargs: {"amount_due": 1275, "currency": "gbp"},
    )
    async def fake_price(*args):
        return PriceOption(
            interval=BillingInterval.year,
            provider_price_id="price_ultimate_year",
            currency="gbp",
            unit_amount=4999,
            formatted_amount="£49.99",
        )

    monkeypatch.setattr(transitions_module, "fetch_price_amount", fake_price)
    result = await preview_subscription_change(
        _config(), _home(), SubscriptionPlan.ultimate, BillingInterval.year
    )
    assert result["amount_due"] == 1275
    assert result["next_amount"] == 4999


@pytest.mark.asyncio
async def test_pending_payment_does_not_change_entitlement_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call(func):
        return func()

    monkeypatch.setattr(transitions_module, "call_stripe", fake_call)
    monkeypatch.setattr(
        transitions_module.stripe.Subscription,
        "retrieve",
        lambda *a, **k: _subscription(),
    )
    monkeypatch.setattr(
        transitions_module.stripe.Subscription,
        "modify",
        lambda *args, **kwargs: {"pending_update": {"expires_at": 1_702_592_000}},
    )
    home = _home()
    result = await apply_subscription_change(
        _FakeDb(),
        _config(),
        home,
        SubscriptionPlan.ultimate,
        BillingInterval.month,
        idempotency_key="test-key",
    )
    assert result["pending_payment"] is True
    assert home.plan is SubscriptionPlan.family
    assert home.pending_plan is SubscriptionPlan.ultimate
