"""Dynamic Family pricing, read from Stripe at request time — never
hard-coded. Configured Price IDs are validated (exists, active, recurring,
expected interval) so a broken configuration fails clearly rather than
silently showing a wrong or stale amount. Cached briefly in-process (no
existing Redis-backed generic cache convention to reuse — see
docs/architecture/commercial-entitlements.md#dynamic-pricing) so a page
render never costs a Stripe API round trip, while a changed Price still
becomes visible within a few minutes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import stripe

from mykhaya.billing.client import StripeRequestError, StripeUnavailableError, call_stripe
from mykhaya.billing.config import StripeNotConfiguredError, resolve_stripe_config
from mykhaya.config import Settings
from mykhaya.models import BillingInterval

_CACHE_TTL_SECONDS = 300

# Stripe's documented zero-decimal currencies (abbreviated to the ones
# remotely plausible for MyKhaya) — everything else is treated as a normal
# two-decimal-minor-unit currency. MyKhaya only sells in GBP today; this
# exists so the formatter isn't silently wrong if that ever changes, not as
# a claim of full i18n currency support.
_ZERO_DECIMAL_CURRENCIES = frozenset({"jpy", "krw", "vnd", "clp", "isk", "huf"})
_CURRENCY_SYMBOLS = {"gbp": "£", "usd": "$", "eur": "€"}


class StripePriceConfigurationError(RuntimeError):
    """A configured Stripe Price ID fails validation (missing, inactive, not
    recurring, or the wrong billing interval) — fails the pricing request
    clearly rather than showing a wrong or default amount."""


@dataclass(frozen=True)
class PriceOption:
    interval: BillingInterval
    provider_price_id: str
    currency: str
    unit_amount: int
    formatted_amount: str


@dataclass(frozen=True)
class FamilyPricing:
    plan: str
    options: tuple[PriceOption, PriceOption]
    # Only populated when both options share a currency — the simple case
    # MyKhaya's single-currency launch is in. None rather than a wrong number
    # if that assumption ever stops holding.
    annual_saving_unit_amount: int | None


def format_amount(unit_amount: int, currency: str) -> str:
    currency = currency.lower()
    symbol = _CURRENCY_SYMBOLS.get(currency, f"{currency.upper()} ")
    if currency in _ZERO_DECIMAL_CURRENCIES:
        return f"{symbol}{unit_amount}"
    return f"{symbol}{unit_amount / 100:.2f}"


async def _fetch_and_validate_price(
    secret_key: str, price_id: str, expected_interval: BillingInterval
) -> PriceOption:
    price = await call_stripe(lambda: stripe.Price.retrieve(price_id, api_key=secret_key))
    if not price.get("active", False):
        raise StripePriceConfigurationError(f"Configured Stripe Price {price_id!r} is not active.")
    recurring = price.get("recurring")
    if not recurring:
        raise StripePriceConfigurationError(
            f"Configured Stripe Price {price_id!r} is not recurring."
        )
    if recurring.get("interval") != expected_interval.value:
        raise StripePriceConfigurationError(
            f"Configured Stripe Price {price_id!r} has interval "
            f"{recurring.get('interval')!r}, expected {expected_interval.value!r}."
        )
    unit_amount = price.get("unit_amount")
    if unit_amount is None:
        raise StripePriceConfigurationError(
            f"Configured Stripe Price {price_id!r} has no fixed unit amount."
        )
    currency = price["currency"]
    return PriceOption(
        interval=expected_interval,
        provider_price_id=price_id,
        currency=currency,
        unit_amount=unit_amount,
        formatted_amount=format_amount(unit_amount, currency),
    )


_cache: dict[str, tuple[float, FamilyPricing]] = {}


async def get_family_pricing(settings: Settings, *, use_cache: bool = True) -> FamilyPricing:
    config = resolve_stripe_config(settings)
    if not config.configured or not config.secret_key:
        raise StripeNotConfiguredError("Stripe billing is not configured.")
    assert config.family_monthly_price_id and config.family_annual_price_id  # noqa: S101 — guaranteed by Settings validation

    cache_key = f"{config.family_monthly_price_id}:{config.family_annual_price_id}"
    now = time.monotonic()
    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

    monthly = await _fetch_and_validate_price(
        config.secret_key, config.family_monthly_price_id, BillingInterval.month
    )
    annual = await _fetch_and_validate_price(
        config.secret_key, config.family_annual_price_id, BillingInterval.year
    )
    saving = (
        monthly.unit_amount * 12 - annual.unit_amount
        if monthly.currency == annual.currency
        else None
    )
    pricing = FamilyPricing(
        plan="family", options=(monthly, annual), annual_saving_unit_amount=saving
    )
    _cache[cache_key] = (now, pricing)
    return pricing


async def fetch_price_amount(secret_key: str, price_id: str) -> PriceOption | None:
    """Best-effort live lookup of a *specific* Stripe Price's amount/currency
    for Platform Control Centre display — deliberately unvalidated against
    "is this the currently configured signup price" (unlike
    _fetch_and_validate_price above), since this may be an old, grandfathered
    Price no longer offered to new signups. Returns None rather than raising
    so a Home detail page never breaks because Stripe couldn't be reached."""
    try:
        price = await call_stripe(lambda: stripe.Price.retrieve(price_id, api_key=secret_key))
    except (StripeUnavailableError, StripeRequestError):
        return None
    unit_amount = price.get("unit_amount")
    if unit_amount is None:
        return None
    currency = price["currency"]
    recurring = price.get("recurring") or {}
    interval_raw = recurring.get("interval")
    if interval_raw in ("month", "year"):
        interval = BillingInterval(interval_raw)
    else:
        interval = BillingInterval.month
    return PriceOption(
        interval=interval,
        provider_price_id=price_id,
        currency=currency,
        unit_amount=unit_amount,
        formatted_amount=format_amount(unit_amount, currency),
    )


def clear_pricing_cache() -> None:
    """Test-only escape hatch — production cache invalidation is purely
    time-based (see module docstring)."""
    _cache.clear()
