from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.routers.auth import user_response
from mykhaya.schemas import UserBirthdayUpdate, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def me(auth: AuthContext = Depends(auth_context)) -> UserResponse:
    return user_response(auth.user)


@router.put("/me/birthday", response_model=UserResponse)
async def update_my_birthday(
    body: UserBirthdayUpdate,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    auth.user.birth_month = body.birth_month
    auth.user.birth_day = body.birth_day
    auth.user.birth_year = body.birth_year
    db.add(auth.user)
    await db.commit()
    return user_response(auth.user)
