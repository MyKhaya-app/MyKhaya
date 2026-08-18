import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from mykhaya.audit import audit
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, require_adult_session
from mykhaya.models import (
    ActionToken,
    AuthIdentity,
    ChildProfile,
    Group,
    HouseholdRelationship,
    Invitation,
    Membership,
    Session,
    SessionKind,
    TokenPurpose,
    TrustedDevice,
    User,
    UserPasskey,
)
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification_email
from mykhaya.platform_mfa import (
    build_family_authentication_options,
    build_family_registration_options,
    pop_webauthn_challenge,
    pop_webauthn_token_challenge,
    store_webauthn_challenge,
    store_webauthn_token_challenge,
    verify_family_authentication,
    verify_family_registration,
)
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.schemas import (
    ChildLoginRequest,
    ForgotRequest,
    LoginRequest,
    MessageResponse,
    MobileSessionResponse,
    PasskeyAuthenticationVerifyRequest,
    PasskeyOptionsResponse,
    PasskeyRegistrationVerifyRequest,
    PasskeyRenameRequest,
    PasskeyResponse,
    RegisterRequest,
    RegistrationResponse,
    ResetRequest,
    SessionResponse,
    TokenRequest,
    TrustedDeviceResponse,
    UserResponse,
)
from mykhaya.security import (
    DUMMY_HASH,
    clear_auth_cookies,
    consume_action_token,
    create_action_token,
    decode_derived_token,
    derived_token,
    hash_secret,
    new_session_token,
    normalise_child_username,
    normalise_email,
    normalise_home_code,
    password_hash,
    require_device_csrf,
    require_secure_transport,
    resolve_client_ip,
    set_auth_cookies,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
GENERIC_EMAIL_MESSAGE = "If that address is registered, an email is on its way."
auth_diag_log = structlog.get_logger("auth_diag")
PASSKEY_LOGIN_COOKIE = "mk_passkey_challenge"
PASSKEY_CHALLENGE_TTL_SECONDS = 300
FRESH_AUTH_WINDOW = timedelta(minutes=10)


def _auth_diag(request: Request, event: str, **fields: object) -> None:
    auth_diag_log.info(
        "auth_diag",
        auth_event=event,
        request_id=getattr(request.state, "request_id", None),
        route=request.url.path,
        session_cookie=bool(request.cookies.get("mk_session")),
        device_cookie=bool(request.cookies.get("mk_device")),
        device_csrf_cookie=bool(request.cookies.get("mk_device_csrf")),
        csrf_header=bool(request.headers.get("x-csrf-token")),
        **fields,
    )


def require_fresh_adult_auth(auth: AuthContext) -> None:
    if auth.session.kind != SessionKind.adult:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This action is not available to a Child.")
    if (
        auth.session.fresh_auth_at is None
        or datetime.now(UTC) - auth.session.fresh_auth_at > FRESH_AUTH_WINDOW
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Please sign in again before changing your passkey settings.",
        )


def passkey_response(row: UserPasskey) -> PasskeyResponse:
    return PasskeyResponse(
        id=row.id,
        label=row.label,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        authenticator_attachment=row.authenticator_attachment,
    )


def parse_authenticator_attachment(credential_json: str) -> str | None:
    """The browser reports this directly on the registration response
    (RegistrationResponseJSON.authenticatorAttachment) — "platform" or
    "cross-platform". Older browsers, or a client that didn't send it, omit
    the field entirely; treated the same as an unrecognised value: unknown,
    not a security signal either way (see UserPasskey.authenticator_attachment)."""
    try:
        parsed = json.loads(credential_json)
        value = parsed.get("authenticatorAttachment")
        return value if value in ("platform", "cross-platform") else None
    except (json.JSONDecodeError, AttributeError):
        return None


def parse_passkey_credential_id(credential_json: str) -> str | None:
    try:
        parsed = json.loads(credential_json)
        raw_id = parsed.get("rawId") or parsed.get("id")
        if not isinstance(raw_id, str):
            return None
        return bytes_to_base64url(base64url_to_bytes(raw_id))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def user_response(user: User, session: Session | None = None) -> UserResponse:
    principal = session.kind if session is not None else SessionKind.adult
    return UserResponse(
        id=user.id,
        # A managed Child's synthetic .invalid placeholder address is an internal
        # implementation detail, never returned to any client — see the field
        # comment on schemas.UserResponse.email.
        email=user.email if principal == SessionKind.adult else None,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
        birth_month=user.birth_month,
        birth_day=user.birth_day,
        birth_year=user.birth_year,
        avatar_version=user.avatar_key,
        principal_type=principal.value,
    )


async def issue_session(
    db: AsyncSession,
    response: Response,
    request: Request,
    user: User,
    settings: Settings,
    kind: SessionKind = SessionKind.adult,
    trusted_device_id: uuid.UUID | None = None,
    device_token: str | None = None,
    device_csrf: str | None = None,
    fresh_auth_at: datetime | None = None,
) -> Session:
    raw = new_session_token()
    csrf = secrets.token_urlsafe(32)
    session = Session(
        user_id=user.id,
        trusted_device_id=trusted_device_id,
        token_hash=hash_secret(raw, settings.secret_key.get_secret_value()),
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.session_minutes),
        fresh_auth_at=fresh_auth_at,
        user_agent=request.headers.get("user-agent", "Unknown device")[:300],
        kind=kind,
    )
    db.add(session)
    await db.flush()
    set_auth_cookies(response, raw, csrf, settings, device_token, device_csrf)
    audit(db, request, "session.created", user.id, target_type="session", target_id=session.id)
    return session


def mobile_client_descriptor(request: Request) -> str:
    """Display-only device label. X-MyKhaya-* headers are never trusted for
    anything beyond this - they are diagnostic text, not authentication or
    authorisation input."""
    client = request.headers.get("x-mykhaya-client")
    platform = request.headers.get("x-mykhaya-platform")
    version = request.headers.get("x-mykhaya-app-version")
    parts = [part for part in (client, platform, version) if part]
    if parts:
        return " ".join(parts)[:300]
    return request.headers.get("user-agent", "Unknown device")[:300]


def device_platform(request: Request) -> str:
    return request.headers.get("x-mykhaya-platform", "Web/PWA")[:80]


async def issue_trusted_device(
    db: AsyncSession,
    request: Request,
    user: User,
    settings: Settings,
    kind: SessionKind,
) -> tuple[TrustedDevice, str, str]:
    raw = new_session_token()
    csrf = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    device = TrustedDevice(
        user_id=user.id,
        token_hash=hash_secret(raw, settings.secret_key.get_secret_value()),
        last_used_at=now,
        expires_at=now + timedelta(days=settings.trusted_device_days),
        device_name=request.headers.get("x-mykhaya-device-name", "MyKhaya device")[:120],
        platform=device_platform(request),
        user_agent=request.headers.get("user-agent", "Unknown device")[:300],
        ip_created=resolve_client_ip(request, settings),
        ip_last_seen=resolve_client_ip(request, settings),
        kind=kind,
    )
    db.add(device)
    await db.flush()
    audit(
        db,
        request,
        "trusted_device.created",
        user.id,
        target_type="trusted_device",
        target_id=device.id,
    )
    return device, raw, csrf


async def issue_family_session(
    db: AsyncSession,
    response: Response,
    request: Request,
    user: User,
    settings: Settings,
    kind: SessionKind,
    fresh_auth_at: datetime | None = None,
) -> Session:
    device, device_token, device_csrf = await issue_trusted_device(
        db, request, user, settings, kind
    )
    return await issue_session(
        db,
        response,
        request,
        user,
        settings,
        kind=kind,
        trusted_device_id=device.id,
        device_token=device_token,
        device_csrf=device_csrf,
        fresh_auth_at=fresh_auth_at,
    )


async def issue_mobile_session(
    db: AsyncSession,
    request: Request,
    user: User,
    settings: Settings,
    kind: SessionKind = SessionKind.adult,
    fresh_auth_at: datetime | None = None,
) -> tuple[str, Session]:
    """Bearer-transport equivalent of issue_session: same Session model, same
    token scheme, no cookies. Returns the raw token - callers must put it in
    the response body only, never a cookie, never a log line."""
    raw = new_session_token()
    session = Session(
        user_id=user.id,
        token_hash=hash_secret(raw, settings.secret_key.get_secret_value()),
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.session_minutes),
        fresh_auth_at=fresh_auth_at,
        user_agent=mobile_client_descriptor(request),
        kind=kind,
    )
    db.add(session)
    await db.flush()
    audit(db, request, "session.created", user.id, target_type="session", target_id=session.id)
    return raw, session


async def authenticate_credentials(
    db: AsyncSession, request: Request, settings: Settings, body: LoginRequest, bucket: str
) -> User:
    """Shared by /auth/login and /auth/mobile/login so the security-sensitive
    part (rate limiting, password check, active/verified checks) is never
    duplicated between transports."""
    await enforce_rate_limit(request, settings, bucket, settings.rate_limit_login, 60)
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
    user = cast(User, pair[0])
    if settings.email_verification_enabled and user.email_verified_at is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Please verify your email before signing in."
        )
    return user


@router.post("/register", response_model=RegistrationResponse, status_code=status.HTTP_202_ACCEPTED)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RegistrationResponse:
    await enforce_rate_limit(request, settings, "register", settings.rate_limit_register, 300)
    email = normalise_email(str(body.email))

    invitation_row: Invitation | None = None
    if settings.registration_mode == "closed":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is currently closed.")
    if settings.registration_mode == "invitation_only":
        if not body.invitation_token:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Registration is invitation-only during this pilot.",
            )
        invitation_id = decode_derived_token(
            body.invitation_token, "invitation", settings.secret_key.get_secret_value()
        )
        invitation_row = (
            await db.scalar(
                select(Invitation).where(Invitation.id == invitation_id).with_for_update()
            )
            if invitation_id
            else None
        )
        if (
            invitation_row is None
            or invitation_row.revoked_at is not None
            or invitation_row.accepted_at is not None
            or invitation_row.expires_at <= datetime.now(UTC)
            or invitation_row.email != email
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This invitation is invalid for the supplied email address.",
            )

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
            raw = derived_token(
                token.id, token.purpose.value, settings.secret_key.get_secret_value()
            )
            subject, message, html = await render_notification_email(
                db,
                settings,
                "email_verification",
                {"link": f"{settings.public_web_url}/verify-email?token={raw}"},
            )
            await notify(
                db,
                settings=settings,
                recipient_user_id=user.id,
                notification_type="email_verification",
                title=subject,
                body=message,
                idempotency_key=f"email_verification:{token.id}",
                html_body=html,
            )
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
    user = await authenticate_credentials(db, request, settings, body, "login")
    fresh_auth_at = datetime.now(UTC)
    session = await issue_family_session(
        db, response, request, user, settings, SessionKind.adult, fresh_auth_at=fresh_auth_at
    )
    user.last_login_at = datetime.now(UTC)
    user.last_activity_at = datetime.now(UTC)
    await db.commit()
    return user_response(user, session)


@router.post("/passkeys/register/options", response_model=PasskeyOptionsResponse)
async def passkey_register_options(
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PasskeyOptionsResponse:
    require_fresh_adult_auth(auth)
    await enforce_rate_limit(request, settings, "family-passkey-register", 10, 300)
    existing = list(
        await db.scalars(
            select(UserPasskey.credential_id).where(
                UserPasskey.user_id == auth.user.id,
                UserPasskey.revoked_at.is_(None),
            )
        )
    )
    options_json, challenge = build_family_registration_options(
        settings,
        auth.user.id,
        auth.user.email,
        auth.user.display_name,
        existing,
    )
    await store_webauthn_challenge(settings, "family-register", auth.session.id, challenge)
    return PasskeyOptionsResponse(options_json=options_json)


@router.post("/passkeys/register/verify", response_model=PasskeyResponse)
async def passkey_register_verify(
    body: PasskeyRegistrationVerifyRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PasskeyResponse:
    require_fresh_adult_auth(auth)
    await enforce_rate_limit(request, settings, "family-passkey-register", 10, 300)
    challenge = await pop_webauthn_challenge(settings, "family-register", auth.session.id)
    if challenge is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This passkey setup attempt has expired.")
    result = verify_family_registration(settings, body.credential_json, challenge)
    if result is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This passkey could not be registered.")
    duplicate = await db.scalar(
        select(UserPasskey).where(UserPasskey.credential_id == result.credential_id)
    )
    if duplicate is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That passkey is already registered.")
    count = await db.scalar(
        select(func.count()).select_from(UserPasskey).where(UserPasskey.user_id == auth.user.id)
    )
    label = " ".join((body.label or f"Passkey {(count or 0) + 1}").split())[:100]
    row = UserPasskey(
        user_id=auth.user.id,
        credential_id=result.credential_id,
        public_key=result.public_key,
        sign_count=result.sign_count,
        label=label,
        authenticator_attachment=parse_authenticator_attachment(body.credential_json),
    )
    db.add(row)
    audit(
        db,
        request,
        "user.passkey_registered",
        auth.user.id,
        target_type="user_passkey",
        target_id=row.id,
    )
    await db.commit()
    return passkey_response(row)


@router.post("/passkeys/login/options", response_model=PasskeyOptionsResponse)
async def passkey_login_options(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> PasskeyOptionsResponse:
    require_secure_transport(request, settings)
    await enforce_rate_limit(request, settings, "family-passkey-login", 8, 300)
    token = secrets.token_urlsafe(32)
    options_json, challenge = build_family_authentication_options(settings)
    await store_webauthn_token_challenge(settings, "family-login", token, challenge)
    response.set_cookie(
        PASSKEY_LOGIN_COOKIE,
        token,
        max_age=PASSKEY_CHALLENGE_TTL_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        domain=settings.cookie_domain,
    )
    return PasskeyOptionsResponse(options_json=options_json)


@router.post("/passkeys/login/verify", response_model=UserResponse)
async def passkey_login_verify(
    body: PasskeyAuthenticationVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    require_secure_transport(request, settings)
    await enforce_rate_limit(request, settings, "family-passkey-login", 8, 300)
    token = request.cookies.get(PASSKEY_LOGIN_COOKIE)
    challenge = (
        await pop_webauthn_token_challenge(settings, "family-login", token)
        if token
        else None
    )
    if challenge is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This passkey sign-in attempt has expired."
        )
    credential_id = parse_passkey_credential_id(body.credential_json)
    row = (
        await db.scalar(
            select(UserPasskey).where(
                UserPasskey.credential_id == credential_id,
                UserPasskey.revoked_at.is_(None),
            )
        )
        if credential_id
        else None
    )
    user = (
        await db.scalar(
            select(User)
            .join(AuthIdentity, AuthIdentity.user_id == User.id)
            .where(User.id == row.user_id, User.is_active.is_(True))
        )
        if row is not None
        else None
    )
    if row is None or user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "We couldn't verify this passkey.")
    new_sign_count = verify_family_authentication(
        settings, body.credential_json, challenge, row.public_key, row.sign_count
    )
    if new_sign_count is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "We couldn't verify this passkey.")
    now = datetime.now(UTC)
    row.sign_count = new_sign_count
    row.last_used_at = now
    session = await issue_family_session(
        db,
        response,
        request,
        user,
        settings,
        SessionKind.adult,
        fresh_auth_at=now,
    )
    user.last_login_at = now
    user.last_activity_at = now
    audit(
        db,
        request,
        "user.passkey_authenticated",
        user.id,
        target_type="user_passkey",
        target_id=row.id,
    )
    await db.commit()
    response.delete_cookie(
        PASSKEY_LOGIN_COOKIE,
        path="/",
        domain=settings.cookie_domain,
    )
    return user_response(user, session)


@router.get("/passkeys", response_model=list[PasskeyResponse])
async def list_passkeys(
    auth: AuthContext = Depends(auth_context), db: AsyncSession = Depends(get_db)
) -> list[PasskeyResponse]:
    require_adult_session(auth)
    rows = await db.scalars(
        select(UserPasskey)
        .where(UserPasskey.user_id == auth.user.id, UserPasskey.revoked_at.is_(None))
        .order_by(UserPasskey.created_at)
    )
    return [passkey_response(row) for row in rows]


@router.patch("/passkeys/{passkey_id}", response_model=PasskeyResponse)
async def rename_passkey(
    passkey_id: uuid.UUID,
    body: PasskeyRenameRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> PasskeyResponse:
    require_fresh_adult_auth(auth)
    row = await db.scalar(
        select(UserPasskey).where(
            UserPasskey.id == passkey_id,
            UserPasskey.user_id == auth.user.id,
            UserPasskey.revoked_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That passkey could not be found.")
    row.label = " ".join(body.label.split())[:100]
    audit(
        db,
        request,
        "user.passkey_renamed",
        auth.user.id,
        target_type="user_passkey",
        target_id=row.id,
    )
    await db.commit()
    return passkey_response(row)


@router.delete("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_passkey(
    passkey_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    require_fresh_adult_auth(auth)
    row = await db.scalar(
        select(UserPasskey).where(
            UserPasskey.id == passkey_id,
            UserPasskey.user_id == auth.user.id,
            UserPasskey.revoked_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That passkey could not be found.")
    row.revoked_at = datetime.now(UTC)
    audit(
        db,
        request,
        "user.passkey_revoked",
        auth.user.id,
        target_type="user_passkey",
        target_id=row.id,
    )
    await db.commit()


CHILD_LOGIN_GENERIC_MESSAGE = "Incorrect sign-in details."


@router.post("/child/login", response_model=UserResponse)
async def child_login(
    body: ChildLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    """Managed Child sign-in — deliberately separate from /login: no email, no
    password, no verification/reset flow. A Home code + Child username + PIN,
    all rate limited, all failures returning the identical generic message so
    neither the Home, the username nor the PIN can be distinguished as the
    wrong element (no enumeration of Homes or Child usernames).
    """
    # Per-IP (matches adult login's own bucket) *and* per sign-in-identity — a
    # slow, distributed attempt against one specific Child is limited even if it
    # never trips the per-IP bucket, and vice versa.
    await enforce_rate_limit(request, settings, "child-login", settings.rate_limit_login, 60)
    identity_bucket = "child-login-identity:" + hash_secret(
        f"{normalise_home_code(body.home_code)}:{normalise_child_username(body.username)}",
        settings.secret_key.get_secret_value(),
    )
    await enforce_rate_limit(request, settings, identity_bucket, 8, 900)

    group = await db.scalar(
        select(Group).where(
            Group.child_login_code == normalise_home_code(body.home_code),
            Group.is_active.is_(True),
        )
    )
    profile = None
    if group is not None:
        # ChildProfile.group_id (not just the Membership join) is what
        # uq_child_login_username_per_home is defined over, so this query can never
        # return more than one row for a given (group, username) — the database
        # itself guarantees that, not just the application's read pattern.
        profile = await db.scalar(
            select(ChildProfile)
            .join(Membership, Membership.id == ChildProfile.membership_id)
            .where(
                ChildProfile.group_id == group.id,
                Membership.relationship == HouseholdRelationship.child,
                Membership.removed_at.is_(None),
                ChildProfile.login_enabled.is_(True),
                ChildProfile.username_normalised == normalise_child_username(body.username),
            )
        )
    stored_hash = profile.pin_hash if profile and profile.pin_hash else DUMMY_HASH
    valid = verify_password(body.pin, stored_hash)
    if profile is None or not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, CHILD_LOGIN_GENERIC_MESSAGE)

    membership = await db.get(Membership, profile.membership_id)
    assert membership is not None
    user = await db.get(User, membership.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, CHILD_LOGIN_GENERIC_MESSAGE)

    session = await issue_family_session(
        db, response, request, user, settings, SessionKind.managed_child
    )
    user.last_login_at = datetime.now(UTC)
    user.last_activity_at = datetime.now(UTC)
    await db.commit()
    return user_response(user, session)


@router.post("/renew", response_model=UserResponse)
async def renew(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    """Silently replace an expired application session using the rotating
    family-device credential. The device credential is never returned in JSON.
    """
    try:
        require_device_csrf(request, settings)
    except HTTPException as exc:
        _auth_diag(
            request,
            "RENEW_CSRF_FAILED",
            status_code=exc.status_code,
            csrf_reason=(
                "CSRF_COOKIE_MISSING"
                if not request.cookies.get("mk_device_csrf")
                else "CSRF_HEADER_MISSING"
                if not request.headers.get("x-csrf-token")
                else "CSRF_INVALID"
            ),
        )
        raise
    raw = request.cookies.get("mk_device")
    if not raw:
        _auth_diag(request, "RENEW_FAILED", result="NO_TRUSTED_COOKIE", status_code=401)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to continue.")
    now = datetime.now(UTC)
    device_result = await db.execute(
        select(User, TrustedDevice)
        .join(TrustedDevice, TrustedDevice.user_id == User.id)
        .where(
            TrustedDevice.token_hash == hash_secret(raw, settings.secret_key.get_secret_value()),
            TrustedDevice.revoked_at.is_(None),
            TrustedDevice.expires_at > now,
            User.is_active.is_(True),
        )
        .with_for_update()
    )
    pair = device_result.one_or_none()
    if pair is None:
        known_device_result = await db.execute(
            select(User, TrustedDevice)
            .join(TrustedDevice, TrustedDevice.user_id == User.id)
            .where(
                TrustedDevice.token_hash
                == hash_secret(raw, settings.secret_key.get_secret_value())
            )
        )
        known_pair = known_device_result.one_or_none()
        if known_pair is None:
            result = "TOKEN_MISMATCH"
            device_id = None
            user_id = None
        else:
            known_user, known_device = known_pair
            device_id = str(known_device.id)
            user_id = str(known_user.id)
            result = (
                "USER_INVALID"
                if not known_user.is_active
                else "DEVICE_REVOKED"
                if known_device.revoked_at is not None
                else "DEVICE_EXPIRED"
                if known_device.expires_at <= now
                else "TRUSTED_DEVICE_NOT_FOUND"
            )
        _auth_diag(
            request,
            "RENEW_FAILED",
            result=result,
            user_id=user_id,
            device_id=device_id,
            status_code=401,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to continue.")
    user, device = pair

    if device.kind == SessionKind.managed_child:
        child_active = await db.scalar(
            select(ChildProfile.id)
            .join(Membership, Membership.id == ChildProfile.membership_id)
            .where(
                Membership.user_id == user.id,
                Membership.relationship == HouseholdRelationship.child,
                Membership.removed_at.is_(None),
                ChildProfile.login_enabled.is_(True),
            )
        )
        if child_active is None:
            device.revoked_at = now
            await db.commit()
            _auth_diag(
                request,
                "RENEW_FAILED",
                result="CHILD_ACCOUNT_INVALID",
                user_id=str(user.id),
                device_id=str(device.id),
                status_code=401,
            )
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to continue.")

    rotated_token = new_session_token()
    device_csrf = secrets.token_urlsafe(32)
    device.token_hash = hash_secret(rotated_token, settings.secret_key.get_secret_value())
    device.last_used_at = now
    device.expires_at = now + timedelta(days=settings.trusted_device_days)
    device.ip_last_seen = resolve_client_ip(request, settings)
    session = await issue_session(
        db,
        response,
        request,
        user,
        settings,
        kind=device.kind,
        trusted_device_id=device.id,
        device_token=rotated_token,
        device_csrf=device_csrf,
    )
    await db.commit()
    _auth_diag(
        request,
        "RENEW_SUCCESS",
        result="SUCCESS",
        user_id=str(user.id),
        device_id=str(device.id),
        session_id=str(session.id),
        rotation_performed=True,
        new_cookies_emitted=True,
        status_code=200,
    )
    return user_response(user, session)


@router.post("/mobile/login", response_model=MobileSessionResponse)
async def mobile_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MobileSessionResponse:
    """Native-client equivalent of /login: same credential check, opaque
    Session token, but returned in the body (not a cookie) since a native
    app has no cookie jar to rely on. Sets no cookies. Never logs the raw
    token - only the caller who receives this response ever sees it."""
    require_secure_transport(request, settings)
    user = await authenticate_credentials(db, request, settings, body, "mobile_login")
    raw, session = await issue_mobile_session(
        db, request, user, settings, fresh_auth_at=datetime.now(UTC)
    )
    user.last_login_at = datetime.now(UTC)
    user.last_activity_at = datetime.now(UTC)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return MobileSessionResponse(**user_response(user, session).model_dump(), session_token=raw)


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
        raw = derived_token(token.id, token.purpose.value, settings.secret_key.get_secret_value())
        subject, message, html = await render_notification_email(
            db,
            settings,
            "password_reset",
            {"link": f"{settings.public_web_url}/reset-password?token={raw}"},
        )
        await notify(
            db,
            settings=settings,
            recipient_user_id=user.id,
            notification_type="password_reset",
            title=subject,
            body=message,
            idempotency_key=f"password_reset:{token.id}",
            html_body=html,
        )
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
    await db.execute(
        update(TrustedDevice)
        .where(TrustedDevice.user_id == token.user_id, TrustedDevice.revoked_at.is_(None))
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
    if auth.session.trusted_device_id is not None:
        await db.execute(
            update(TrustedDevice)
            .where(TrustedDevice.id == auth.session.trusted_device_id)
            .values(revoked_at=datetime.now(UTC))
        )
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


def require_bearer_transport(auth: AuthContext) -> None:
    if auth.transport != "bearer":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This endpoint requires bearer authentication."
        )


@router.post("/mobile/logout", status_code=status.HTTP_204_NO_CONTENT)
async def mobile_logout(
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revokes the session; does not touch cookies (there are none for a
    bearer session) and is not subject to CSRF (bearer transport). The
    mobile client must still clear its SecureStore token locally even if
    this call fails - see ADR 0010."""
    require_bearer_transport(auth)
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


@router.get("/devices", response_model=list[TrustedDeviceResponse])
async def devices(
    auth: AuthContext = Depends(auth_context), db: AsyncSession = Depends(get_db)
) -> list[TrustedDeviceResponse]:
    rows = (
        await db.scalars(
            select(TrustedDevice)
            .where(
                TrustedDevice.user_id == auth.user.id,
                TrustedDevice.revoked_at.is_(None),
                TrustedDevice.expires_at > datetime.now(UTC),
            )
            .order_by(TrustedDevice.last_used_at.desc())
            .limit(50)
        )
    ).all()
    return [
        TrustedDeviceResponse(
            id=row.id,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            expires_at=row.expires_at,
            device_name=row.device_name,
            platform=row.platform,
            user_agent=row.user_agent,
            current=row.id == auth.session.trusted_device_id,
        )
        for row in rows
    ]


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: uuid.UUID,
    response: Response,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    target = await db.scalar(
        select(TrustedDevice).where(
            TrustedDevice.id == device_id,
            TrustedDevice.user_id == auth.user.id,
            TrustedDevice.revoked_at.is_(None),
        )
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That device could not be found.")
    target.revoked_at = datetime.now(UTC)
    await db.execute(
        update(Session)
        .where(Session.trusted_device_id == target.id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    audit(
        db,
        request,
        "trusted_device.revoked",
        auth.user.id,
        target_type="trusted_device",
        target_id=target.id,
    )
    await db.commit()
    if target.id == auth.session.trusted_device_id:
        clear_auth_cookies(response, settings)


@router.post("/devices/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_other_devices(
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    current_device_id = auth.session.trusted_device_id
    if current_device_id is not None:
        await db.execute(
            update(TrustedDevice)
            .where(
                TrustedDevice.user_id == auth.user.id,
                TrustedDevice.id != current_device_id,
                TrustedDevice.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await db.execute(
            update(Session)
            .where(
                Session.user_id == auth.user.id,
                Session.trusted_device_id != current_device_id,
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
    audit(db, request, "trusted_device.others_revoked", auth.user.id)
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
    # kind must be carried over from the session being rotated, never left to
    # issue_session's adult default — otherwise a managed Child session rotating
    # its own session would silently come back as an *adult* session for the same
    # underlying User row, defeating require_adult_session and every other
    # kind-based check from that point on.
    new_session = await issue_session(
        db,
        response,
        request,
        auth.user,
        settings,
        kind=auth.session.kind,
        fresh_auth_at=auth.session.fresh_auth_at,
    )
    audit(
        db,
        request,
        "session.rotated",
        auth.user.id,
        target_type="session",
        target_id=auth.session.id,
    )
    await db.commit()
    return user_response(auth.user, new_session)


@router.post("/mobile/sessions/rotate", response_model=MobileSessionResponse)
async def rotate_mobile_session(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MobileSessionResponse:
    """Old token is revoked and the new one created in the same transaction
    (one commit below) - there is no window where both are simultaneously
    valid. If the app is killed before it persists the new token to
    SecureStore, the user is signed out and must sign in again; that is the
    intended safe failure mode, not a bug."""
    require_secure_transport(request, settings)
    require_bearer_transport(auth)
    auth.session.revoked_at = datetime.now(UTC)
    # See the identical comment in rotate_session: kind must carry over from the
    # session being rotated, not silently reset to issue_mobile_session's adult
    # default.
    raw, new_session = await issue_mobile_session(
        db,
        request,
        auth.user,
        settings,
        kind=auth.session.kind,
        fresh_auth_at=auth.session.fresh_auth_at,
    )
    audit(
        db,
        request,
        "session.rotated",
        auth.user.id,
        target_type="session",
        target_id=auth.session.id,
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return MobileSessionResponse(
        **user_response(auth.user, new_session).model_dump(), session_token=raw
    )
