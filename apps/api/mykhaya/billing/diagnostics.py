"""Durable, secret-free Stripe billing diagnostics for Platform Control Centre."""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.entitlements import get_home_subscription, resolve_effective_plan
from mykhaya.models import StripeBillingDiagnostic

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def safe_diagnostic_message(message: str | None) -> str | None:
    if not message:
        return None
    return _CONTROL_CHARS.sub(" ", str(message)).strip()[:500]


async def record_billing_diagnostic(
    db: AsyncSession,
    *,
    source: str,
    stage: str,
    result: str,
    stripe_mode: str | None = None,
    stripe_event_id: str | None = None,
    checkout_session_id: str | None = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    group_id: uuid.UUID | None = None,
    stripe_subscription_status: str | None = None,
    safe_error_code: str | None = None,
    safe_error_message: str | None = None,
    commit: bool = True,
) -> StripeBillingDiagnostic:
    subscription = await get_home_subscription(db, group_id) if group_id else None
    effective = resolve_effective_plan(subscription) if subscription else None
    entitlement_mismatch = (
        stripe_subscription_status in {"active", "trialing"}
        and effective is not None
        and effective.value != "family"
    )
    if entitlement_mismatch and result in {"completed", "processed"}:
        result = "mismatch"
        safe_error_code = safe_error_code or "entitlement_mismatch"
        safe_error_message = (
            safe_error_message
            or "Stripe reports an active subscription but MyKhaya resolves Free."
        )
    row = StripeBillingDiagnostic(
        source=source,
        stripe_mode=stripe_mode,
        stage=stage,
        result=result,
        stripe_event_id=stripe_event_id,
        checkout_session_id=checkout_session_id,
        stripe_customer_id=stripe_customer_id
        or (str(subscription.external_customer_id) if subscription else None),
        stripe_subscription_id=stripe_subscription_id
        or (str(subscription.external_subscription_id) if subscription else None),
        group_id=group_id,
        stripe_subscription_status=stripe_subscription_status,
        stored_subscription_status=subscription.status.value if subscription else None,
        stored_plan=subscription.plan.value if subscription else None,
        effective_plan=effective.value if effective else None,
        safe_error_code=safe_diagnostic_message(safe_error_code),
        safe_error_message=safe_diagnostic_message(safe_error_message),
    )
    db.add(row)
    if commit:
        await db.commit()
    return row
