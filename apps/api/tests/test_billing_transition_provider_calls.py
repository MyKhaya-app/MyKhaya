from uuid import uuid4

import pytest

from mykhaya.billing import transitions as transitions_module
from mykhaya.billing.config import StripeConfig
from mykhaya.billing.pricing import PriceOption
from mykhaya.billing.transitions import (
    InvalidSubscriptionTransition,
    SubscriptionValidationError,
    _validate_current_item,
    apply_subscription_change,
    preview_subscription_change,
)
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
        "items": {
            "data": [
                {
                    "id": "si_test",
                    "price": {
                        "id": "price_family_month",
                        "product": "prod_family",
                        "currency": "gbp",
                        "recurring": {"interval": "month"},
                    },
                }
            ]
        },
    }


class _FakeDb:
    async def flush(self) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_price_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    def retrieve(price_id: str, **_: object) -> dict[str, object]:
        interval = "year" if "year" in price_id else "month"
        product = "prod_ultimate" if "ultimate" in price_id else "prod_family"
        return {
            "id": price_id,
            "product": product,
            "currency": "gbp",
            "recurring": {"interval": interval},
        }

    monkeypatch.setattr(transitions_module.stripe.Price, "retrieve", retrieve)


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
    assert result["effective_immediately"] is True
    assert result["effective_at"] is None


@pytest.mark.asyncio
async def test_preview_reads_item_level_periods_under_current_stripe_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call(func):
        return func()

    subscription = _subscription()
    subscription.pop("current_period_start")
    subscription.pop("current_period_end")
    subscription["items"]["data"][0]["current_period_start"] = 1_700_000_000
    subscription["items"]["data"][0]["current_period_end"] = 1_702_592_000
    monkeypatch.setattr(transitions_module, "call_stripe", fake_call)
    monkeypatch.setattr(
        transitions_module.stripe.Subscription,
        "retrieve",
        lambda *a, **k: subscription,
    )
    monkeypatch.setattr(
        transitions_module.stripe.Invoice,
        "create_preview",
        lambda **kwargs: {"amount_due": 2000, "currency": "gbp"},
    )
    async def fake_price(*args):
        return _price_option("price_ultimate_year", BillingInterval.year, 5900)

    monkeypatch.setattr(transitions_module, "fetch_price_amount", fake_price)
    result = await preview_subscription_change(
        _config(), _home(), SubscriptionPlan.ultimate, BillingInterval.year
    )
    assert result["effective_immediately"] is True
    assert result["period_end"].year == 2023


@pytest.mark.asyncio
async def test_multiple_items_select_the_stored_plan_price_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call(func):
        return func()

    subscription = _subscription()
    subscription["items"]["data"].append(
        {"id": "si_addon", "price": {"id": "price_other", "recurring": {"interval": "month"}}}
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(transitions_module, "call_stripe", fake_call)
    monkeypatch.setattr(
        transitions_module.stripe.Subscription,
        "retrieve",
        lambda *a, **k: subscription,
    )

    def fake_preview(**kwargs):
        captured.update(kwargs)
        return {"amount_due": 2000, "currency": "gbp"}

    monkeypatch.setattr(transitions_module.stripe.Invoice, "create_preview", fake_preview)
    async def fake_price(*args):
        return _price_option("price_ultimate_year", BillingInterval.year, 5900)

    monkeypatch.setattr(transitions_module, "fetch_price_amount", fake_price)
    await preview_subscription_change(
        _config(), _home(), SubscriptionPlan.ultimate, BillingInterval.year
    )
    assert captured["subscription_details"]["items"][0]["id"] == "si_test"


def _price_option(price_id: str, interval: BillingInterval, amount: int) -> PriceOption:
    return PriceOption(
        interval=interval,
        provider_price_id=price_id,
        currency="gbp",
        unit_amount=amount,
        formatted_amount=f"£{amount / 100:.2f}",
    )


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


@pytest.mark.asyncio
async def test_historical_family_price_is_valid_when_product_and_terms_match() -> None:
    home = _home()
    home.external_price_id = "price_family_month_historical"
    subscription = _subscription()
    subscription["items"]["data"][0]["price"]["id"] = home.external_price_id
    item = await _validate_current_item(_config(), home, subscription)
    assert item["id"] == "si_test"


@pytest.mark.asyncio
async def test_family_annual_to_ultimate_annual_uses_same_item_and_target_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call(func):
        return func()

    home = _home()
    home.billing_interval = BillingInterval.year
    home.external_price_id = "price_family_year"
    subscription = _subscription()
    subscription["items"]["data"][0]["price"].update(
        {"id": home.external_price_id, "recurring": {"interval": "year"}}
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(transitions_module, "call_stripe", fake_call)
    monkeypatch.setattr(
        transitions_module.stripe.Subscription, "retrieve", lambda *a, **k: subscription
    )
    monkeypatch.setattr(
        transitions_module.stripe.Invoice,
        "create_preview",
        lambda **kwargs: captured.update(kwargs) or {"amount_due": 1000, "currency": "gbp"},
    )
    async def fake_price(*args):
        return _price_option("price_ultimate_year", BillingInterval.year, 5900)

    monkeypatch.setattr(transitions_module, "fetch_price_amount", fake_price)
    result = await preview_subscription_change(
        _config(), home, SubscriptionPlan.ultimate, BillingInterval.year
    )
    assert captured["subscription_details"]["items"] == [
        {"id": "si_test", "price": "price_ultimate_year", "quantity": 1}
    ]
    assert result["target_interval"] is BillingInterval.year


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("product", "prod_other", "stripe_price_product_mismatch"),
        ("currency", "usd", "stripe_price_currency_mismatch"),
        ("recurring", {"interval": "year"}, "stripe_price_interval_mismatch"),
    ],
)
async def test_existing_price_rejects_wrong_product_currency_or_interval(
    field: str, value: object, reason: str
) -> None:
    home = _home()
    subscription = _subscription()
    price = subscription["items"]["data"][0]["price"]
    price[field] = value
    with pytest.raises(SubscriptionValidationError) as caught:
        await _validate_current_item(_config(), home, subscription)
    assert caught.value.validation_reason == reason


@pytest.mark.asyncio
async def test_existing_price_rejects_multiple_eligible_items() -> None:
    home = _home()
    subscription = _subscription()
    subscription["items"]["data"].append(
        {
            "id": "si_duplicate",
            "price": {
                "id": "price_family_month_duplicate",
                "product": "prod_family",
                "currency": "gbp",
                "recurring": {"interval": "month"},
            },
        }
    )
    with pytest.raises(SubscriptionValidationError) as caught:
        await _validate_current_item(_config(), home, subscription)
    assert caught.value.validation_reason == "multiple_or_missing_eligible_items"


@pytest.mark.asyncio
async def test_existing_price_rejects_missing_item_and_database_price_mismatch() -> None:
    home = _home()
    missing = _subscription()
    missing["items"]["data"] = []
    with pytest.raises(InvalidSubscriptionTransition):
        await _validate_current_item(_config(), home, missing)

    mismatched = _subscription()
    home.external_price_id = "price_family_month_historical"
    with pytest.raises(SubscriptionValidationError) as caught:
        await _validate_current_item(_config(), home, mismatched)
    assert caught.value.validation_reason == "local_database_price_does_not_match_stripe"
