"""Unit tests for Stripe webhook source-IP policy boundaries."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from mykhaya.billing.webhook_ip_security import (
    enforce_webhook_ip_policy,
    parse_stripe_webhook_ips,
    record_monitored_webhook_request,
    security_stale,
)
from mykhaya.models import SecurityEvent, StripeWebhookIpSecuritySettings
from mykhaya.security import resolve_client_ip


def _request(peer: str, forwarded: str = "") -> Request:
    headers = []
    if forwarded:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/billing/stripe/webhook",
            "headers": headers,
            "client": (peer, 1234),
            "scheme": "https",
            "server": ("example.test", 443),
            "query_string": b"",
        }
    )


def test_stripe_feed_parser_accepts_only_public_ip_addresses() -> None:
    payload = json.dumps({"WEBHOOKS": ["3.18.12.63", "2001:db8::1"]}).encode()
    with pytest.raises(ValueError, match="non-public"):
        parse_stripe_webhook_ips(payload)

    parsed = parse_stripe_webhook_ips(json.dumps({"WEBHOOKS": ["3.18.12.63"]}).encode())
    assert parsed == ["3.18.12.63"]


def test_spoofed_forwarded_header_is_ignored_from_untrusted_peer() -> None:
    settings = SimpleNamespace(trusted_proxy_cidrs=["10.0.0.10/32"])
    assert resolve_client_ip(_request("198.51.100.20", "3.18.12.63"), settings) == "198.51.100.20"


def test_forwarded_client_ip_is_used_only_from_trusted_caddy_peer() -> None:
    settings = SimpleNamespace(trusted_proxy_cidrs=["10.0.0.10/32"])
    assert resolve_client_ip(_request("10.0.0.10", "3.18.12.63"), settings) == "3.18.12.63"


@pytest.mark.asyncio
async def test_enforcement_blocks_unlisted_ip_but_monitoring_allows_it() -> None:
    from unittest.mock import AsyncMock

    settings = SimpleNamespace(trusted_proxy_cidrs=["10.0.0.10/32"])
    row = SimpleNamespace(
        mode="enforcement",
        trusted_ips=["3.18.12.63"],
        last_successful_sync_at=datetime.now(UTC),
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=row))
    decision, ip = await enforce_webhook_ip_policy(
        db, _request("10.0.0.10", "198.51.100.10"), settings
    )
    assert (decision, ip) == ("block", "198.51.100.10")
    row.mode = "monitoring"
    decision, _ = await enforce_webhook_ip_policy(
        db, _request("10.0.0.10", "198.51.100.10"), settings
    )
    assert decision == "monitor"


def test_enforcement_list_is_stale_without_successful_sync() -> None:
    assert security_stale(None, datetime.now(UTC)) is True
    row = StripeWebhookIpSecuritySettings(trusted_ips=["3.18.12.63"])
    assert security_stale(row, datetime.now(UTC)) is True


def test_monitoring_records_only_safe_source_observation() -> None:
    added: list[object] = []
    db = SimpleNamespace(add=added.append)

    record_monitored_webhook_request(
        db, source_ip="3.18.12.63", request_id="req_test"
    )

    assert len(added) == 1
    event = added[0]
    assert isinstance(event, SecurityEvent)
    assert event.event_type == "stripe_webhook_ip_observed"
    assert event.source_ip == "3.18.12.63"
    assert event.safe_detail is not None
