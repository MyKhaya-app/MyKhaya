"""Stripe configuration resolution.

Mirrors the resolve_smtp_config/resolve_push_config shape (source/configured
dataclass) so callers can distinguish "intentionally disabled" from "fully
configured" the same way the rest of the codebase already does — with one
deliberate difference: for Stripe, the Platform-Admin-managed database row (once
enabled) takes precedence *over* the MYKHAYA_STRIPE_* environment variables, not
the other way round. See
docs/architecture/platform-control-centre.md#stripe-configuration-precedence for
why this is reversed from SMTP/push.

Precedence:
    1. platform_stripe_settings row, if `enabled` — authoritative once enabled.
       If the active mode's configuration is incomplete, this returns
       configured=False with an incomplete_reason and does NOT fall through to
       the environment: mixing sources, or silently using Test credentials while
       Live is selected, is exactly what must never happen (see
       docs/architecture/commercial-entitlements.md#stripe-mode-safety).
    2. MYKHAYA_STRIPE_BILLING_CONFIGURED=true (environment) — the original
       bootstrap/fallback path, unchanged in behaviour.
    3. Unconfigured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.secrets_crypto import SecretDecryptionError, decrypt_stripe_secret

if TYPE_CHECKING:
    from mykhaya.models import PlatformStripeSettings

StripeSource = Literal["database", "environment", "unconfigured"]
StripeModeLiteral = Literal["test", "live"]

_SECRET_KEY_PATTERN = {
    "test": re.compile(r"^sk_test_"),
    "live": re.compile(r"^sk_live_"),
}


@dataclass(frozen=True)
class StripeConfig:
    source: StripeSource
    configured: bool
    mode: StripeModeLiteral = "test"
    # Explains why `configured` is False when a Platform Admin has enabled Stripe
    # but the active mode's configuration is incomplete or inconsistent — never
    # populated for the "not configured at all" case, which is self-explanatory.
    incomplete_reason: str | None = None
    # Phase 7's deliberate go-live gate — separate from `configured`. Stripe
    # being fully set up is necessary but not sufficient to accept a *new*
    # paid signup; this is the one flag routers.billing.checkout_session
    # checks before ever creating a Checkout Session. Existing Stripe-backed
    # Homes, webhooks, renewals, cancellations, the Customer Portal, and
    # reconciliation are never gated by this — only new acquisition is. See
    # docs/architecture/commercial-entitlements.md#billing-acquisition-gate.
    # Deliberately still environment-only — this task moves credentials, not
    # the go-live kill switch.
    acquisition_enabled: bool = False
    secret_key: str | None = field(default=None, repr=False)
    webhook_secret: str | None = field(default=None, repr=False)
    publishable_key: str | None = None
    family_monthly_price_id: str | None = None
    family_annual_price_id: str | None = None


class StripeNotConfiguredError(RuntimeError):
    """Raised by any billing operation attempted while Stripe is disabled —
    callers turn this into a 503 "billing is not available" response rather
    than letting an AttributeError on a None secret key leak upward."""


def _from_environment(settings: Settings) -> StripeConfig:
    if not settings.stripe_billing_configured:
        return StripeConfig(source="unconfigured", configured=False)
    secret_key = settings.stripe_secret_key.get_secret_value() if settings.stripe_secret_key else ""
    mode: StripeModeLiteral = "live" if secret_key.startswith("sk_live_") else "test"
    return StripeConfig(
        source="environment",
        configured=True,
        mode=mode,
        acquisition_enabled=settings.stripe_billing_acquisition_enabled,
        secret_key=secret_key or None,
        webhook_secret=settings.stripe_webhook_secret.get_secret_value()
        if settings.stripe_webhook_secret
        else None,
        publishable_key=settings.stripe_publishable_key,
        family_monthly_price_id=settings.stripe_family_monthly_price_id,
        family_annual_price_id=settings.stripe_family_annual_price_id,
    )


def _from_db_row(row: PlatformStripeSettings, settings: Settings) -> StripeConfig:
    from mykhaya.models import StripeMode  # local import avoids a circular import at module load

    mode: StripeModeLiteral = "live" if row.mode == StripeMode.live else "test"
    acquisition_enabled = settings.stripe_billing_acquisition_enabled

    if mode == "test":
        publishable_key = row.test_publishable_key
        encrypted_secret_key = row.encrypted_test_secret_key
        encrypted_webhook_secret = row.encrypted_test_webhook_secret
        monthly_price_id = row.test_family_monthly_price_id
        annual_price_id = row.test_family_annual_price_id
    else:
        publishable_key = row.live_publishable_key
        encrypted_secret_key = row.encrypted_live_secret_key
        encrypted_webhook_secret = row.encrypted_live_webhook_secret
        monthly_price_id = row.live_family_monthly_price_id
        annual_price_id = row.live_family_annual_price_id

    missing = [
        name
        for name, value in (
            ("secret key", encrypted_secret_key),
            ("webhook signing secret", encrypted_webhook_secret),
            ("monthly Price ID", monthly_price_id),
            ("annual Price ID", annual_price_id),
        )
        if not value
    ]
    if missing:
        return StripeConfig(
            source="database",
            configured=False,
            mode=mode,
            acquisition_enabled=acquisition_enabled,
            incomplete_reason=(
                f"{mode.capitalize()} mode is selected but missing: {', '.join(missing)}."
            ),
        )

    assert encrypted_secret_key is not None  # noqa: S101 — guaranteed by the `missing` check above
    assert encrypted_webhook_secret is not None  # noqa: S101
    try:
        secret_key = decrypt_stripe_secret(settings, encrypted_secret_key)
        webhook_secret = decrypt_stripe_secret(settings, encrypted_webhook_secret)
    except SecretDecryptionError:
        # Most likely a MYKHAYA_SECRET_KEY rotation — fail closed rather than crash
        # or use a stale/garbage key. The admin needs to re-enter the secret.
        return StripeConfig(
            source="database",
            configured=False,
            mode=mode,
            acquisition_enabled=acquisition_enabled,
            incomplete_reason=(
                "Stored Stripe credentials could not be decrypted with the current "
                "encryption key and must be re-entered."
            ),
        )

    if not _SECRET_KEY_PATTERN[mode].match(secret_key):
        return StripeConfig(
            source="database",
            configured=False,
            mode=mode,
            acquisition_enabled=acquisition_enabled,
            incomplete_reason=(
                f"The stored secret key does not look like a {mode}-mode Stripe key "
                f"(expected it to start with sk_{mode}_)."
            ),
        )

    return StripeConfig(
        source="database",
        configured=True,
        mode=mode,
        acquisition_enabled=acquisition_enabled,
        secret_key=secret_key,
        webhook_secret=webhook_secret,
        publishable_key=publishable_key,
        family_monthly_price_id=monthly_price_id,
        family_annual_price_id=annual_price_id,
    )


async def resolve_stripe_config(settings: Settings, db: AsyncSession) -> StripeConfig:
    from mykhaya.models import PlatformStripeSettings  # local import avoids a circular import

    row = await db.scalar(select(PlatformStripeSettings).limit(1))
    if row is not None and row.enabled:
        return _from_db_row(row, settings)
    return _from_environment(settings)
