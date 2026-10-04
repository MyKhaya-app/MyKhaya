from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.activity import record_activity_heartbeat
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context

router = APIRouter(prefix="/activity", tags=["activity"])


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await record_activity_heartbeat(db, auth.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
