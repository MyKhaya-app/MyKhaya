from fastapi import APIRouter, Depends

from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.schemas import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def me(auth: AuthContext = Depends(auth_context)) -> UserResponse:
    return UserResponse(
        id=auth.user.id,
        email=auth.user.email,
        display_name=auth.user.display_name,
        email_verified=auth.user.email_verified_at is not None,
    )
