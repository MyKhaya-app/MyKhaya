import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.models import ProductUsageEventName, ProductUsageModule, ProductUsagePlatform
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.usage import record_usage_event

router = APIRouter(prefix="/usage", tags=["usage"])


class UsageEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_name: ProductUsageEventName
    platform: ProductUsagePlatform
    module: ProductUsageModule | None = None
    home_id: uuid.UUID | None = None
    app_version: Annotated[str | None, Field(max_length=80)] = None
    usage_session_id: Annotated[
        str | None, Field(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    ] = None
    event_key: Annotated[str | None, Field(max_length=120, pattern=r"^[A-Za-z0-9:_-]+$")] = None


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    request: Request,
    body: UsageEventRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    await enforce_rate_limit(request, settings, "product-usage-events", 300)
    if body.home_id is not None:
        await membership_for(body.home_id, auth, db)
    await record_usage_event(
        db,
        event_name=body.event_name,
        platform=body.platform,
        user_id=auth.user.id,
        group_id=body.home_id,
        module=body.module,
        app_version=body.app_version,
        usage_session_id=body.usage_session_id,
        event_key=body.event_key,
    )
    return {"status": "accepted"}
