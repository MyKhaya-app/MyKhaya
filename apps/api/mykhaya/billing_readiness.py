"""Operator-facing "is this deployment correctly configured to enable Stripe
billing" readiness check (Phase 7). See
docs/operations/billing-production-readiness.md#readiness-command.

Prints PASS/WARN/BLOCKER lines, never a secret value. Makes no live Stripe
API call unless `--check-stripe` is passed, and refuses to do so against a
live-mode secret key — this command must never itself be the thing that
verifies against real, chargeable Stripe. Run it inside the API container:

    docker compose run --rm api python -m mykhaya.billing_readiness
    docker compose run --rm api python -m mykhaya.billing_readiness --check-stripe

This command answers "is configuration internally consistent and complete,"
not "has the real Stripe sandbox lifecycle actually been verified" — the
latter is a manual/documented procedure (see
docs/operations/billing-production-readiness.md#real-sandbox-verification)
that this script cannot substitute for.

Reads the Platform Control Centre database (via its own short-lived session) since
Stripe configuration may now be Platform-Admin-managed rather than environment-only —
see mykhaya.billing.config.resolve_stripe_config.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.billing.client import StripeRequestError, StripeUnavailableError
from mykhaya.billing.config import StripeConfig, StripeNotConfiguredError, resolve_stripe_config
from mykhaya.billing.pricing import StripePriceConfigurationError, get_family_pricing
from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory


class ReadinessLevel(StrEnum):
    passed = "PASS"
    warn = "WARN"
    blocker = "BLOCKER"


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    level: ReadinessLevel
    detail: str


def _config_checks(settings: Settings, config: StripeConfig) -> list[ReadinessCheck]:
    if not config.configured:
        return [
            ReadinessCheck(
                "Stripe configuration",
                ReadinessLevel.blocker,
                config.incomplete_reason
                or "Not configured — MYKHAYA_STRIPE_BILLING_CONFIGURED is false and no "
                "Platform Control Centre Stripe configuration is enabled. "
                "Free/Complimentary Homes only.",
            )
        ]
    checks = [
        ReadinessCheck(
            "Stripe configuration",
            ReadinessLevel.passed,
            f"Configured (source={config.source}).",
        )
    ]

    is_live = config.mode == "live"
    checks.append(
        ReadinessCheck(
            "Stripe mode",
            ReadinessLevel.passed,
            f"{'Live' if is_live else 'Test'} mode secret key "
            f"(MYKHAYA_ENVIRONMENT={settings.environment}).",
        )
    )
    # Settings.validate_stripe_configuration already refuses to start with a
    # mismatched mode/environment when Stripe is environment-managed; for a
    # Platform Control Centre-managed row, resolve_stripe_config's own
    # mode/key-prefix check plays the same role — this line is defensive
    # restating, not the actual enforcement point either way.
    if is_live and settings.environment != "production":
        checks.append(
            ReadinessCheck(
                "Mode/environment match",
                ReadinessLevel.blocker,
                "Live key outside production — this should be unreachable at startup; "
                "if seen, treat as a configuration emergency.",
            )
        )

    checks.append(
        ReadinessCheck(
            "Monthly Price ID",
            ReadinessLevel.passed if config.family_monthly_price_id else ReadinessLevel.blocker,
            config.family_monthly_price_id or "Not configured.",
        )
    )
    checks.append(
        ReadinessCheck(
            "Annual Price ID",
            ReadinessLevel.passed if config.family_annual_price_id else ReadinessLevel.blocker,
            config.family_annual_price_id or "Not configured.",
        )
    )
    checks.append(
        ReadinessCheck(
            "Webhook secret",
            ReadinessLevel.passed if config.webhook_secret else ReadinessLevel.blocker,
            "Configured." if config.webhook_secret else "Not configured.",
        )
    )
    checks.append(
        ReadinessCheck(
            "Billing acquisition (kill switch)",
            ReadinessLevel.passed if config.acquisition_enabled else ReadinessLevel.warn,
            "Enabled — new Checkout Sessions are permitted."
            if config.acquisition_enabled
            else "Disabled — new Checkout is currently refused server-side. This is the "
            "expected state until a deliberate go-live decision (see the go-live checklist).",
        )
    )
    checks.append(
        ReadinessCheck(
            "Public web URL",
            ReadinessLevel.passed if settings.public_web_url else ReadinessLevel.blocker,
            settings.public_web_url
            or "Not configured — Checkout/Portal return URLs would be invalid.",
        )
    )
    if is_live and settings.public_web_url and not settings.public_web_url.startswith("https://"):
        checks.append(
            ReadinessCheck(
                "Public web URL scheme",
                ReadinessLevel.blocker,
                "Live mode requires an HTTPS MYKHAYA_PUBLIC_WEB_URL.",
            )
        )
    return checks


async def _stripe_connectivity_check(
    settings: Settings, config: StripeConfig, db: AsyncSession, *, check_stripe: bool
) -> ReadinessCheck:
    if not check_stripe:
        return ReadinessCheck(
            "Live Stripe connectivity",
            ReadinessLevel.warn,
            "Not checked — pass --check-stripe to verify the configured Price IDs "
            "against the real Stripe API.",
        )
    if not config.configured or not config.secret_key:
        return ReadinessCheck(
            "Live Stripe connectivity", ReadinessLevel.blocker, "Cannot check — not configured."
        )
    if config.secret_key.startswith("sk_live_"):
        return ReadinessCheck(
            "Live Stripe connectivity",
            ReadinessLevel.blocker,
            "Refusing to run --check-stripe against a live-mode key from this diagnostic "
            "command — verify live Prices manually in the Stripe Dashboard instead.",
        )
    try:
        pricing = await get_family_pricing(settings, db, use_cache=False)
    except StripeNotConfiguredError:
        return ReadinessCheck(
            "Live Stripe connectivity", ReadinessLevel.blocker, "Stripe not configured."
        )
    except StripePriceConfigurationError as exc:
        return ReadinessCheck(
            "Live Stripe connectivity",
            ReadinessLevel.blocker,
            f"Configured Price ID(s) invalid: {exc}",
        )
    except (StripeUnavailableError, StripeRequestError) as exc:
        return ReadinessCheck(
            "Live Stripe connectivity", ReadinessLevel.blocker, f"Could not reach Stripe: {exc}"
        )
    return ReadinessCheck(
        "Live Stripe connectivity",
        ReadinessLevel.passed,
        f"Monthly and annual test Prices resolved successfully "
        f"(currency={pricing.options[0].currency.upper()}).",
    )


async def run_readiness_checks(*, check_stripe: bool = False) -> list[ReadinessCheck]:
    settings = get_settings()
    async with SessionFactory() as db:
        config = await resolve_stripe_config(settings, db)
        checks = _config_checks(settings, config)
        checks.append(
            await _stripe_connectivity_check(settings, config, db, check_stripe=check_stripe)
        )
    return checks


def _main() -> int:
    parser = argparse.ArgumentParser(description="MyKhaya Stripe billing readiness check.")
    parser.add_argument(
        "--check-stripe",
        action="store_true",
        help="Also verify configured Price IDs against the live Stripe API (test mode only).",
    )
    args = parser.parse_args()
    checks = asyncio.run(run_readiness_checks(check_stripe=args.check_stripe))
    blockers = [check for check in checks if check.level == ReadinessLevel.blocker]
    for check in checks:
        print(f"{check.level.value:8} {check.name}: {check.detail}")
    print()
    if blockers:
        print("READY FOR LIVE BILLING: NO")
        print(f"{len(blockers)} blocker(s) — see BLOCKER lines above.")
    else:
        print(
            "READY FOR LIVE BILLING: configuration checks pass — this does NOT by itself "
            "mean go-live is approved. See the full checklist in "
            "docs/operations/billing-production-readiness.md#go-live-checklist, including "
            "real Stripe sandbox verification and the business/tax/legal decisions."
        )
    return 1 if blockers else 0


if __name__ == "__main__":
    sys.exit(_main())
