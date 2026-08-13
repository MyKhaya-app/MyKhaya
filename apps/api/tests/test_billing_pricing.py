"""mykhaya.billing.pricing — dynamic Family pricing read from Stripe, never
hard-coded. stripe.Price.retrieve is monkeypatched throughout (mirrors the
pywebpush.webpush monkeypatch convention in test_push_notifications.py) —
no real Stripe sandbox call is made.
"""

import pytest
import stripe

from mykhaya.billing import pricing as pricing_module
from mykhaya.billing.config import StripeNotConfiguredError
from mykhaya.billing.pricing import (
    StripePriceConfigurationError,
    fetch_price_amount,
    format_amount,
    get_family_pricing,
)
from mykhaya.config import Settings
from mykhaya.models import BillingInterval

SECRET_KEY = "a" * 40


def _settings(**stripe_overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "secret_key": SECRET_KEY,
        "public_web_url": "http://localhost:8089",
        "admin_url": "http://admin.localhost:8089",
        "status_url": "http://status.localhost:8089",
        "trusted_hosts": ["localhost", "127.0.0.1", "admin.localhost", "status.localhost"],
        "cors_origins": ["http://localhost:8089", "http://admin.localhost:8089"],
        "stripe_billing_configured": True,
        "stripe_secret_key": "sk_test_abc123",
        "stripe_webhook_secret": "whsec_abc123",
        "stripe_family_monthly_price_id": "price_month123",
        "stripe_family_annual_price_id": "price_year123",
    }
    kwargs.update(stripe_overrides)
    return Settings.model_validate(kwargs)


def _fake_price(
    price_id: str,
    *,
    active: bool = True,
    interval: str | None = "month",
    unit_amount: int | None = 399,
) -> dict:
    return {
        "id": price_id,
        "active": active,
        "currency": "gbp",
        "unit_amount": unit_amount,
        "recurring": {"interval": interval} if interval else None,
    }


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    pricing_module.clear_pricing_cache()
    yield
    pricing_module.clear_pricing_cache()


def test_format_amount_two_decimal_currency() -> None:
    assert format_amount(399, "gbp") == "£3.99"
    assert format_amount(3900, "gbp") == "£39.00"


def test_format_amount_zero_decimal_currency() -> None:
    assert format_amount(500, "jpy") == "JPY 500"


def test_format_amount_unknown_currency_symbol() -> None:
    assert format_amount(1000, "nzd") == "NZD 10.00"


@pytest.mark.asyncio
async def test_unconfigured_stripe_raises() -> None:
    settings = _settings(
        stripe_billing_configured=False,
        stripe_secret_key=None,
        stripe_webhook_secret=None,
        stripe_family_monthly_price_id=None,
        stripe_family_annual_price_id=None,
    )
    with pytest.raises(StripeNotConfiguredError):
        await get_family_pricing(settings)


@pytest.mark.asyncio
async def test_resolves_monthly_and_annual_pricing_from_stripe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_retrieve(price_id: str, **kwargs: object) -> dict:
        if price_id == "price_month123":
            return _fake_price(price_id, interval="month", unit_amount=399)
        return _fake_price(price_id, interval="year", unit_amount=3900)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    settings = _settings()
    result = await get_family_pricing(settings)
    monthly, annual = result.options
    assert monthly.interval == BillingInterval.month
    assert monthly.unit_amount == 399
    assert monthly.formatted_amount == "£3.99"
    assert annual.interval == BillingInterval.year
    assert annual.unit_amount == 3900
    assert annual.formatted_amount == "£39.00"
    # Never hard-coded: change what Stripe returns and the result changes too.
    assert result.annual_saving_unit_amount == 399 * 12 - 3900


@pytest.mark.asyncio
async def test_amount_is_never_hard_coded_it_reflects_whatever_stripe_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_retrieve(price_id: str, **kwargs: object) -> dict:
        interval = "month" if price_id == "price_month123" else "year"
        return _fake_price(price_id, interval=interval, unit_amount=999)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    settings = _settings()
    result = await get_family_pricing(settings)
    assert all(option.unit_amount == 999 for option in result.options)
    assert all(option.formatted_amount == "£9.99" for option in result.options)


@pytest.mark.asyncio
async def test_inactive_price_raises_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_retrieve(price_id: str, **kwargs: object) -> dict:
        return _fake_price(price_id, active=False)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    with pytest.raises(StripePriceConfigurationError, match="not active"):
        await get_family_pricing(_settings())


@pytest.mark.asyncio
async def test_non_recurring_price_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_retrieve(price_id: str, **kwargs: object) -> dict:
        return _fake_price(price_id, interval=None)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    with pytest.raises(StripePriceConfigurationError, match="not recurring"):
        await get_family_pricing(_settings())


@pytest.mark.asyncio
async def test_wrong_interval_raises_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_retrieve(price_id: str, **kwargs: object) -> dict:
        # Both configured as monthly, even the one that should be annual.
        return _fake_price(price_id, interval="month")

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    with pytest.raises(StripePriceConfigurationError, match="expected 'year'"):
        await get_family_pricing(_settings())


@pytest.mark.asyncio
async def test_missing_unit_amount_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_retrieve(price_id: str, **kwargs: object) -> dict:
        return _fake_price(price_id, unit_amount=None)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    with pytest.raises(StripePriceConfigurationError, match="no fixed unit amount"):
        await get_family_pricing(_settings())


@pytest.mark.asyncio
async def test_result_is_cached_and_does_not_call_stripe_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def fake_retrieve(price_id: str, **kwargs: object) -> dict:
        calls["count"] += 1
        interval = "month" if price_id == "price_month123" else "year"
        return _fake_price(price_id, interval=interval)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    settings = _settings()
    await get_family_pricing(settings)
    await get_family_pricing(settings)
    assert calls["count"] == 2  # one per price, not four


@pytest.mark.asyncio
async def test_use_cache_false_bypasses_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_retrieve(price_id: str, **kwargs: object) -> dict:
        calls["count"] += 1
        interval = "month" if price_id == "price_month123" else "year"
        return _fake_price(price_id, interval=interval)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    settings = _settings()
    await get_family_pricing(settings)
    await get_family_pricing(settings, use_cache=False)
    assert calls["count"] == 4


@pytest.mark.asyncio
async def test_fetch_price_amount_returns_none_on_missing_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_retrieve(price_id: str, **kwargs: object) -> dict:
        raise stripe.InvalidRequestError("No such price", param="id")

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    result = await fetch_price_amount(SECRET_KEY, "price_does_not_exist")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_price_amount_returns_the_actual_grandfathered_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_retrieve(price_id: str, **kwargs: object) -> dict:
        return _fake_price(price_id, interval="month", unit_amount=299)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    result = await fetch_price_amount(SECRET_KEY, "price_old_grandfathered")
    assert result is not None
    assert result.unit_amount == 299
    assert result.formatted_amount == "£2.99"
