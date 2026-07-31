import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit, outbox
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.models import Invitation, Membership, Role
from mykhaya.schemas import InvitationAccept, InvitationCreate, InvitationResponse, MessageResponse
from mykhaya.security import decode_derived_token, derived_token, hash_secret, normalise_email

router = APIRouter(prefix="/invitations", tags=["invitations"])
MANAGERS = {Role.owner, Role.administrator}


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def invite(
    body: InvitationCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InvitationResponse:
    await membership_for(body.group_id, auth, db, MANAGERS)
    if body.role == Role.owner:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Ownership cannot be assigned by invitation."
        )
    row = Invitation(
        group_id=body.group_id,
        email=normalise_email(str(body.email)),
        role=body.role,
        token_hash=hash_secret(secrets.token_urlsafe(32), settings.secret_key.get_secret_value()),
        invited_by=auth.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(row)
    await db.flush()
    raw = derived_token(row.id, "invitation", settings.secret_key.get_secret_value())
    row.token_hash = hash_secret(raw, settings.secret_key.get_secret_value())
    outbox(db, "email.invitation", {"invitation_id": str(row.id)})
    audit(db, request, "invitation.created", auth.user.id, body.group_id, "invitation", row.id)
    await db.commit()
    return InvitationResponse(
        id=row.id, group_id=row.group_id, email=row.email, role=row.role, expires_at=row.expires_at
    )


@router.post("/accept", response_model=MessageResponse)
async def accept(
    body: InvitationAccept,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    identifier = decode_derived_token(
        body.token, "invitation", settings.secret_key.get_secret_value()
    )
    row = (
        await db.scalar(select(Invitation).where(Invitation.id == identifier).with_for_update())
        if identifier
        else None
    )
    expected = hash_secret(body.token, settings.secret_key.get_secret_value())
    if (
        row is None
        or row.accepted_at is not None
        or row.revoked_at is not None
        or row.expires_at <= datetime.now(UTC)
        or not hmac.compare_digest(row.token_hash, expected)
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invitation is invalid or has expired."
        )
    if row.email != auth.user.email:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Sign in with the email address that was invited."
        )
    existing = await db.scalar(
        select(Membership)
        .where(Membership.group_id == row.group_id, Membership.user_id == auth.user.id)
        .with_for_update()
    )
    if existing is None:
        db.add(Membership(group_id=row.group_id, user_id=auth.user.id, role=row.role))
    else:
        existing.removed_at = None
        existing.role = row.role
    row.accepted_at = datetime.now(UTC)
    audit(db, request, "invitation.accepted", auth.user.id, row.group_id, "invitation", row.id)
    await db.commit()
    return MessageResponse(message="Welcome home. The Home is now in your list.")
