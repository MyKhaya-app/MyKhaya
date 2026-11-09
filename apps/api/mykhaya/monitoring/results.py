"""The value a health check returns, and the vocabulary used to describe it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Component states. "unknown" means no conclusive, fresh observation exists;
# "not_applicable" means the integration is not configured or enabled in this
# environment, so there is nothing to monitor and nothing to publish.
HEALTHY = "healthy"
DEGRADED = "degraded"
UNAVAILABLE = "unavailable"
UNKNOWN = "unknown"
NOT_APPLICABLE = "not_applicable"
COMPONENT_STATES = (HEALTHY, DEGRADED, UNAVAILABLE, UNKNOWN, NOT_APPLICABLE)

Outcome = Literal["success", "failure", "inconclusive", "monitor_error", "not_applicable"]
FailureSeverity = Literal["degraded", "unavailable"]
Confidence = Literal["verified", "limited"]

# Sanitised, operator-facing failure categories. They deliberately separate
# "the provider is down" from "MyKhaya cannot reach it" from "our credentials
# or configuration are wrong" from "the monitor itself failed".
FAILURE_CATEGORIES: dict[str, str] = {
    "provider_outage": "Provider outage or server error",
    "connectivity": "Connectivity failure",
    "dns": "DNS resolution failure",
    "tls": "TLS or certificate failure",
    "timeout": "Request timed out",
    "auth_config": "Authentication or configuration error",
    "rate_limited": "Rate limited by provider",
    "unexpected_response": "Unexpected response",
    # Behind Cloudflare: where along the path the request failed.
    "edge_origin_unreachable": "Cloudflare could not reach the origin server",
    "edge_origin_tls": "Cloudflare could not establish TLS to the origin",
    "edge_error": "Cloudflare edge error",
    "waf_challenge": "Blocked by a Cloudflare security challenge (cannot verify)",
    "egress": "MyKhaya outbound connectivity failure",
    "error_rate": "Elevated server error rate",
    "latency": "High response latency",
    "backlog": "Processing backlog",
    "heartbeat": "Missing or stale heartbeat",
    "delivery_failures": "Repeated delivery failures",
    "not_configured": "Not configured",
    "monitor_error": "Monitoring check failed to run",
    "stale": "Monitoring observations are stale",
    "simulated": "Simulated failure (DEV fault injection)",
}

# Categories that describe a network path problem rather than a provider
# answering badly; used to spot a MyKhaya-side egress/DNS problem when several
# unrelated providers fail this way at once.
NETWORK_CATEGORIES = frozenset({"connectivity", "dns", "timeout", "tls"})


def category_label(category: str | None) -> str:
    if not category:
        return "Unspecified failure"
    return FAILURE_CATEGORIES.get(category, category.replace("_", " ").capitalize())


def _clip(text: str | None) -> str | None:
    if text is None:
        return None
    text = " ".join(text.split())
    return text[:300] if text else None


@dataclass(frozen=True)
class CheckResult:
    outcome: Outcome
    failure_severity: FailureSeverity = "unavailable"
    category: str | None = None
    # Operator-facing (PCC and alert emails), never the public page. Must
    # already be safe: no credentials, tokens, full URLs with secrets, raw
    # exception text or response bodies.
    detail: str | None = None
    latency_ms: int | None = None
    confidence: Confidence | None = None

    @classmethod
    def success(
        cls,
        detail: str | None = None,
        *,
        latency_ms: int | None = None,
        confidence: Confidence | None = None,
    ) -> CheckResult:
        return cls("success", detail=_clip(detail), latency_ms=latency_ms, confidence=confidence)

    @classmethod
    def failure(
        cls,
        category: str,
        detail: str | None = None,
        *,
        severity: FailureSeverity = "unavailable",
        latency_ms: int | None = None,
    ) -> CheckResult:
        return cls(
            "failure",
            failure_severity=severity,
            category=category,
            detail=_clip(detail),
            latency_ms=latency_ms,
        )

    @classmethod
    def inconclusive(cls, detail: str | None = None) -> CheckResult:
        """Nothing new to judge (e.g. no traffic since the last check). The
        component stays fresh but its counters and state do not move."""
        return cls("inconclusive", detail=_clip(detail))

    @classmethod
    def monitor_error(
        cls, detail: str | None = None, *, category: str = "monitor_error"
    ) -> CheckResult:
        """The check could not produce a verdict about the service (it failed
        to run, or something in front of the service blocked the monitor).
        Never counts against the service; repeated errors leave the component
        to go stale and become Unknown."""
        return cls("monitor_error", category=category, detail=_clip(detail))

    @classmethod
    def not_applicable(cls, detail: str | None = None) -> CheckResult:
        return cls("not_applicable", category="not_configured", detail=_clip(detail))
