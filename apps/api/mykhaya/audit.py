import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import AuditEvent


def audit(
    db: AsyncSession,
    request: Request,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            action=action,
            actor_user_id=actor_user_id,
            group_id=group_id,
            target_type=target_type,
            target_id=target_id,
            request_id=getattr(request.state, "request_id", None),
            metadata_=metadata or {},
        )
    )
