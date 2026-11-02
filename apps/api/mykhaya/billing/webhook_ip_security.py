"""Stripe's official webhook source-IP feed and route-only policy enforcement."""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import (
    SecurityEvent,
    StripeWebhookIpSecurityMode,
    StripeWebhookIpSecuritySettings,
)
from mykhaya.security import resolve_client_ip

STRIPE_WEBHOOK_IP_FEED_URL = "https://stripe.com/files/ips/ips_webhooks.json"
SYNC_INTERVAL = timedelta(hours=24)
STALE_AFTER = timedelta(hours=26)
MAX_FEED_BYTES = 128 * 1024
MAX_IPS = 256


def parse_stripe_webhook_ips(payload: bytes) -> list[str]:
    import json

    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("Stripe webhook IP feed is too large.")
    document: Any = json.loads(payload)
    values = document.get("WEBHOOKS") if isinstance(document, dict) else None
    if not isinstance(values, list) or not values or len(values) > MAX_IPS:
        raise ValueError("Stripe webhook IP feed has an invalid WEBHOOKS list.")
    parsed: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Stripe webhook IP feed contains a non-string address.")
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise ValueError("Stripe webhook IP feed contains a non-public address.")
        parsed.add(str(address))
    return sorted(
        parsed,
        key=lambda value: (ipaddress.ip_address(value).version, ipaddress.ip_address(value)),
    )


async def get_security_settings(db: AsyncSession) -> StripeWebhookIpSecuritySettings | None:
    return await db.scalar(select(StripeWebhookIpSecuritySettings).limit(1))


def security_stale(row: StripeWebhookIpSecuritySettings | None, now: datetime) -> bool:
    return (
        row is None
        or not row.trusted_ips
        or row.last_successful_sync_at is None
        or now - row.last_successful_sync_at > STALE_AFTER
    )


async def sync_stripe_webhook_ips(
    db: AsyncSession, *, force: bool = False, now: datetime | None = None
) -> tuple[StripeWebhookIpSecuritySettings, bool]:
    now = now or datetime.now(UTC)
    row = await db.scalar(
        select(StripeWebhookIpSecuritySettings).with_for_update().limit(1)
    )
    if row is None:
        row = StripeWebhookIpSecuritySettings()
        db.add(row)
        await db.flush()
    if not force and row.last_sync_attempt_at and now - row.last_sync_attempt_at < SYNC_INTERVAL:
        return row, False
    row.last_sync_attempt_at = now
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(
                STRIPE_WEBHOOK_IP_FEED_URL, headers={"Accept": "application/json"}
            )
            response.raise_for_status()
        ips = parse_stripe_webhook_ips(response.content)
    except Exception as exc:
        row.last_sync_error = f"{type(exc).__name__}: Stripe webhook IP feed unavailable."[:500]
        return row, False
    row.trusted_ips = ips
    row.last_successful_sync_at = now
    row.last_sync_error = None
    return row, True


async def record_blocked_webhook_request(
    db: AsyncSession, *, source_ip: str, request_id: str | None
) -> None:
    row = await db.scalar(select(StripeWebhookIpSecuritySettings).limit(1))
    if row is None:
        row = StripeWebhookIpSecuritySettings()
        db.add(row)
    row.blocked_request_count += 1
    row.last_blocked_at = datetime.now(UTC)
    db.add(
        SecurityEvent(
            event_type="stripe_webhook_ip_blocked",
            severity="warning",
            outcome="denied",
            source_ip=source_ip,
            request_id=request_id,
            safe_detail="Stripe webhook request rejected by the configured source-IP policy.",
        )
    )


def record_monitored_webhook_request(
    db: AsyncSession, *, source_ip: str, request_id: str | None
) -> None:
    db.add(
        SecurityEvent(
            event_type="stripe_webhook_ip_observed",
            severity="info",
            outcome="observed",
            source_ip=source_ip,
            request_id=request_id,
            safe_detail=(
                "Signature-verified Stripe webhook source observed while IP enforcement "
                "is in monitoring mode."
            ),
        )
    )


async def enforce_webhook_ip_policy(
    db: AsyncSession, request: Request, settings: Settings
) -> tuple[str, str]:
    """Return (decision, resolved_ip): monitor, allow, block, or unavailable."""
    row = await get_security_settings(db)
    resolved_ip = resolve_client_ip(request, settings)
    if row is None or row.mode == StripeWebhookIpSecurityMode.monitoring:
        return "monitor", resolved_ip
    now = datetime.now(UTC)
    if security_stale(row, now):
        return "unavailable", resolved_ip
    return ("allow" if resolved_ip in set(row.trusted_ips) else "block"), resolved_ip
