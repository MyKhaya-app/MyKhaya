import uuid
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit_redaction import redact_audit_metadata
from mykhaya.models import AdministrativeAuditEvent
from mykhaya.platform_security import PlatformContext, safe_session_reference

SECRET_MARKERS = ("password", "secret", "token", "credential", "api_key", "ciphertext")


def _audit_log_method(outcome: str) -> str:
    normalized = outcome.casefold()
    if normalized == "denied":
        return "warning"
    if normalized in {"failure", "failed", "error"}:
        return "error"
    return "info"


def safe_values(values: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in (values or {}).items():
        result[key] = (
            "[REDACTED]" if any(marker in key.casefold() for marker in SECRET_MARKERS) else value
        )
    return result


def platform_audit(
    db: AsyncSession,
    request: Request,
    context: PlatformContext,
    action: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    outcome: str = "succeeded",
    reason: str | None = None,
    previous: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
    failure_category: str | None = None,
    retain: frozenset[str] = frozenset(),
) -> None:
    """``retain`` names fields whose retention in this specific record is
    documented policy (see mykhaya.audit_redaction); everything else personal
    is redacted *before* storage, not only before logging."""
    stored_previous = redact_audit_metadata(safe_values(previous), retain=retain)
    stored_new = redact_audit_metadata(safe_values(new), retain=retain)
    forwarded_previous = redact_audit_metadata(safe_values(previous))
    forwarded_new = redact_audit_metadata(safe_values(new))
    db.add(
        AdministrativeAuditEvent(
            administrator_id=context.administrator.id,
            administrator_role=context.administrator.role.value,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            reason=reason,
            source_ip=context.source_ip,
            request_id=getattr(request.state, "request_id", None),
            session_reference=safe_session_reference(context.session.id),
            previous_values=stored_previous,
            new_values=stored_new,
            failure_category=failure_category,
        )
    )
    log_method = getattr(structlog.get_logger("platform_audit"), _audit_log_method(outcome))
    log_method(
        "administrative_audit_event",
        action=action,
        administrator_id=str(context.administrator.id),
        administrator_role=context.administrator.role.value,
        target_type=target_type,
        target_id=str(target_id) if target_id else None,
        outcome=outcome,
        request_id=getattr(request.state, "request_id", None),
        source_ip=context.source_ip,
        previous_values=forwarded_previous,
        new_values=forwarded_new,
        failure_category=failure_category,
    )
