import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import AdministrativeAuditEvent
from mykhaya.platform_security import PlatformContext, safe_session_reference

SECRET_MARKERS = ("password", "secret", "token", "credential", "api_key")


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
) -> None:
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
            previous_values=safe_values(previous),
            new_values=safe_values(new),
            failure_category=failure_category,
        )
    )
