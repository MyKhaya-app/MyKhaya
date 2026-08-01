import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit, outbox
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.models import ActionToken, AuthIdentity, Session, TokenPurpose, User
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.schemas import (
    ForgotRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    RegistrationResponse,
    ResetRequest,
    SessionResponse,
    TokenRequest,
    UserResponse,
)
from mykhaya.security import (
    DUMMY_HASH,
    clear_auth_cookies,
    consume_action_token,
    create_action_token,
    hash_secret,
    new_session_token,
    normalise_email,
    password_hash,
    set_auth_cookies,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
GENERIC_EMAIL_MESSAGE = "If that address is registered, an email is on its way."


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
    )


async def issue_session(
    db: AsyncSession, response: Response, request: Request, user: User, settings: Settings
) -> None:
    raw = new_session_token()
    csrf = secrets.token_urlsafe(32)
    session = Session(
        user_id=user.id,
        token_hash=hash_secret(raw, settings.secret_key.get_secret_value()),
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.session_minutes),
        user_agent=request.headers.get("user-agent", "Unknown device")[:300],
    )
    db.add(session)
    await db.flush()
    set_auth_cookies(response, raw, csrf, settings)
    audit(db, request, "session.created", user.id, target_type="session", target_id=session.id)


@router.post("/register", response_model=RegistrationResponse, status_code=status.HTTP_202_ACCEPTED)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RegistrationResponse:
    await enforce_rate_limit(request, settings, "register", settings.rate_limit_register, 300)
    email = normalise_email(str(body.email))
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is None:
        user = User(
            email=email,
            display_name=body.display_name,
            email_verified_at=None if settings.email_verification_enabled else datetime.now(UTC),
        )
        db.add(user)
        await db.flush()
        db.add(AuthIdentity(user_id=user.id, password_hash=password_hash.hash(body.password)))
        if settings.email_verification_enabled:
            token = await create_action_token(
                db, user.id, TokenPurpose.verify_email, settings, 60 * 24
            )
            outbox(db, "email.verify", {"token_id": str(token.id)})
        audit(db, request, "user.registered", user.id, target_type="user", target_id=user.id)
        await db.commit()
    else:
        # Equalise password work and response to reduce account discovery.
        verify_password(body.password, DUMMY_HASH)
    message = (
        GENERIC_EMAIL_MESSAGE
        if settings.email_verification_enabled
        else "Your account is ready. You can sign in now."
    )
    return RegistrationResponse(
        message=message, verification_required=settings.email_verification_enabled
    )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    body: TokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    token = await consume_action_token(db, body.token, TokenPurpose.verify_email, settings)
    user = await db.get(User, token.user_id, with_for_update=True)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)
    audit(db, request, "user.email_verified", user.id, target_type="user", target_id=user.id)
    await db.commit()
    return MessageResponse(message="Your email is verified. You can sign in now.")


@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    await enforce_rate_limit(request, settings, "login", settings.rate_limit_login, 60)
    email = normalise_email(str(body.email))
    result = await db.execute(
        select(User, AuthIdentity)
        .join(AuthIdentity, AuthIdentity.user_id == User.id)
        .where(User.email == email)
    )
    pair = result.one_or_none()
    valid = verify_password(body.password, pair[1].password_hash if pair else DUMMY_HASH)
    if pair is None or not valid or not pair[0].is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The email or password is not correct.")
    user = pair[0]
    if settings.email_verification_enabled and user.email_verified_at is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Please verify your email before signing in."
        )
    await issue_session(db, response, request, user, settings)
    user.last_login_at = datetime.now(UTC)
    user.last_activity_at = datetime.now(UTC)
    await db.commit()
    return user_response(user)


@router.post(
    "/forgot-password", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED
)
async def forgot(
    body: ForgotRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    user = await db.scalar(
        select(User).where(User.email == normalise_email(str(body.email)), User.is_active.is_(True))
    )
    if user is not None:
        await db.execute(
            update(ActionToken)
            .where(
                ActionToken.user_id == user.id,
                ActionToken.purpose == TokenPurpose.reset_password,
                ActionToken.consumed_at.is_(None),
            )
            .values(consumed_at=datetime.now(UTC))
        )
        token = await create_action_token(db, user.id, TokenPurpose.reset_password, settings, 30)
        outbox(db, "email.reset", {"token_id": str(token.id)})
        audit(
            db, request, "password.reset_requested", user.id, target_type="user", target_id=user.id
        )
        await db.commit()
    else:
        verify_password("not-the-users-password", DUMMY_HASH)
    return MessageResponse(message=GENERIC_EMAIL_MESSAGE)


@router.post("/reset-password", response_model=MessageResponse)
async def reset(
    body: ResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    token = await consume_action_token(db, body.token, TokenPurpose.reset_password, settings)
    identity = await db.scalar(
        select(AuthIdentity).where(AuthIdentity.user_id == token.user_id).with_for_update()
    )
    if identity is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")
    identity.password_hash = password_hash.hash(body.password)
    identity.password_changed_at = datetime.now(UTC)
    await db.execute(
        update(Session)
        .where(Session.user_id == token.user_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    audit(db, request, "password.reset", token.user_id, target_type="user", target_id=token.user_id)
    await db.commit()
    return MessageResponse(
        message="Your password has been changed. Sign in with your new password."
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    auth.session.revoked_at = datetime.now(UTC)
    audit(
        db,
        request,
        "session.revoked",
        auth.user.id,
        target_type="session",
        target_id=auth.session.id,
    )
    await db.commit()
    clear_auth_cookies(response, settings)


@router.get("/sessions", response_model=list[SessionResponse])
async def sessions(
    auth: AuthContext = Depends(auth_context), db: AsyncSession = Depends(get_db)
) -> list[SessionResponse]:
    rows = (
        await db.scalars(
            select(Session)
            .where(
                Session.user_id == auth.user.id,
                Session.revoked_at.is_(None),
                Session.expires_at > datetime.now(UTC),
            )
            .order_by(Session.last_seen_at.desc())
            .limit(50)
        )
    ).all()
    return [
        SessionResponse(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            user_agent=row.user_agent,
            current=row.id == auth.session.id,
        )
        for row in rows
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    target = await db.scalar(
        select(Session).where(
            Session.id == session_id, Session.user_id == auth.user.id, Session.revoked_at.is_(None)
        )
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That session could not be found.")
    target.revoked_at = datetime.now(UTC)
    audit(db, request, "session.revoked", auth.user.id, target_type="session", target_id=target.id)
    await db.commit()


@router.post("/sessions/rotate", response_model=UserResponse)
async def rotate_session(
    response: Response,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    auth.session.revoked_at = datetime.now(UTC)
    await issue_session(db, response, request, auth.user, settings)
    audit(
        db,
        request,
        "session.rotated",
        auth.user.id,
        target_type="session",
        target_id=auth.session.id,
    )
    await db.commit()
    return user_response(auth.user)
