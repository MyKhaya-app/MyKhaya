import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.avatars.processing import (
    OUTPUT_CONTENT_TYPE,
    UnsupportedImageError,
    process_avatar_upload,
)
from mykhaya.avatars.storage import get_avatar_storage
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.household_permissions import Capability, capabilities_for
from mykhaya.models import Membership, User
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.routers.auth import user_response
from mykhaya.schemas import UserBirthdayUpdate, UserResponse

router = APIRouter(prefix="/users", tags=["users"])
log = structlog.get_logger()

AVATAR_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _avatar_filename() -> str:
    # Server-generated and unpredictable — never the client's filename, never the
    # user id (a fresh name per upload means a changed avatar naturally invalidates
    # any cached/versioned URL rather than needing a separate cache-busting scheme).
    return f"{uuid.uuid4()}.webp"


async def _can_view_avatar(db: AsyncSession, viewer_id: uuid.UUID, target_id: uuid.UUID) -> bool:
    """Mirrors GET /groups/{group_id}/members's own gate (Capability.members_view)
    rather than inventing a separate permission — an avatar is profile data, so it
    follows the same visibility as the rest of that profile: the viewer must share at
    least one active Home membership with the target and hold members_view there.
    The UUID in the URL is unguessable, but that is not treated as the access control
    — this check is."""
    if viewer_id == target_id:
        return True
    viewer_memberships = (
        await db.scalars(
            select(Membership).where(
                Membership.user_id == viewer_id, Membership.removed_at.is_(None)
            )
        )
    ).all()
    for membership in viewer_memberships:
        shares_group = await db.scalar(
            select(Membership.id).where(
                Membership.group_id == membership.group_id,
                Membership.user_id == target_id,
                Membership.removed_at.is_(None),
            )
        )
        if shares_group is None:
            continue
        capabilities = await capabilities_for(db, membership)
        if Capability.members_view in capabilities:
            return True
    return False


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


@router.post("/me/avatar", response_model=UserResponse)
async def upload_my_avatar(
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    await enforce_rate_limit(request, settings, "avatar-upload", 20, 3600)

    raw = await file.read(settings.avatar_max_upload_bytes + 1)
    if len(raw) > settings.avatar_max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That photo is too large. Please choose one under "
            f"{settings.avatar_max_upload_bytes // (1024 * 1024)} MB.",
        )
    if not raw:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No file was uploaded.")

    # Decoding (never trusting the client's Content-Type or filename) is the real
    # validation here — process_avatar_upload also strips metadata, normalises
    # orientation, crops to a square and re-encodes as WebP.
    try:
        processed = process_avatar_upload(raw)
    except UnsupportedImageError as cause:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(cause)) from cause

    storage = get_avatar_storage(settings)
    new_key = _avatar_filename()
    await storage.save(new_key, processed)

    # Only swap the reference — and only clean up the previous file — once the new
    # one is safely written and the DB update has committed. A failure at any point
    # before this leaves the user's existing avatar exactly as it was.
    previous_key = auth.user.avatar_key
    auth.user.avatar_key = new_key
    auth.user.avatar_updated_at = datetime.now(UTC)
    db.add(auth.user)
    await db.commit()

    if previous_key:
        try:
            await storage.delete(previous_key)
        except OSError:  # cleanup best-effort, never fail the request
            await log.awarning("avatar_cleanup_failed", user_id=str(auth.user.id))

    return user_response(auth.user)


@router.delete("/me/avatar", response_model=UserResponse)
async def remove_my_avatar(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    previous_key = auth.user.avatar_key
    if previous_key is None:
        return user_response(auth.user)

    auth.user.avatar_key = None
    auth.user.avatar_updated_at = None
    db.add(auth.user)
    await db.commit()

    storage = get_avatar_storage(settings)
    try:
        await storage.delete(previous_key)
    except OSError:  # cleanup best-effort, never fail the request
        await log.awarning("avatar_cleanup_failed", user_id=str(auth.user.id))

    return user_response(auth.user)


@router.get("/{user_id}/avatar")
async def get_avatar(
    user_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    target = await db.get(User, user_id)
    # Deliberately the same response for "doesn't exist", "has no avatar", and "you
    # aren't authorised to see this person" — distinguishing them would let an
    # authenticated user enumerate valid user ids or household membership by probing
    # this endpoint (see dependencies.py::membership_for for the same pattern).
    if target is None or target.avatar_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No avatar set.")
    if not await _can_view_avatar(db, auth.user.id, target.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No avatar set.")

    storage = get_avatar_storage(settings)
    data = await storage.load(target.avatar_key)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No avatar set.")

    return Response(
        content=data,
        media_type=OUTPUT_CONTENT_TYPE,
        headers={"Cache-Control": AVATAR_CACHE_CONTROL},
    )
