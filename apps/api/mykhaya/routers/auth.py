import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, quote

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from mykhaya.apple_auth import (
    AppleAuthenticationError,
    AppleFlowState,
    ApplePendingIdentity,
    authorization_url,
    consume_flow_state,
    consume_pending_identity,
    exchange_code,
    load_pending_identity,
    require_apple_configuration,
    store_flow_state,
    store_pending_identity,
    verify_identity_token,
)
from mykhaya.audit import audit
from mykhaya.auth_providers import external_auth_provider_statuses
from mykhaya.browser_preauth import (
    BrowserPreAuth,
    consume_browser_pre_auth,
    create_browser_pre_auth,
    load_browser_pre_auth,
)
from mykhaya.config import Settings, get_settings
from mykhaya.consumer_mfa import (
    EMAIL_CHALLENGE_TTL_SECONDS,
    EMAIL_MAX_ATTEMPTS,
    claim_totp_step,
    generate_totp_secret,
    hash_email_code,
    hash_transaction,
    matched_totp_step,
    new_email_code,
    totp_provisioning_uri,
)
from mykhaya.consumer_mfa_policy import (
    ConsumerMfaPolicyError,
    EffectiveConsumerMfaPolicy,
    resolve_consumer_mfa_policy,
)
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, require_adult_session
from mykhaya.external_identities import (
    ExternalIdentityNotFound,
    ExternalIdentityOwnershipConflict,
    LastAuthenticationMethodError,
    find_external_identity,
    link_external_identity,
    touch_external_identity,
    unlink_external_identity,
)
from mykhaya.founding_beta import (
    beta_invitation_valid,
    current_programme,
    invitation_token_hash,
)
from mykhaya.google_auth import (
    GoogleAuthenticationError,
    GoogleFlowState,
    GooglePendingIdentity,
    require_google_configuration,
)
from mykhaya.google_auth import authorization_url as google_authorization_url
from mykhaya.google_auth import consume_flow_state as consume_google_flow_state
from mykhaya.google_auth import consume_pending_identity as consume_google_pending_identity
from mykhaya.google_auth import exchange_code as exchange_google_code
from mykhaya.google_auth import load_pending_identity as load_google_pending_identity
from mykhaya.google_auth import new_code_verifier as new_google_code_verifier
from mykhaya.google_auth import store_flow_state as store_google_flow_state
from mykhaya.google_auth import store_pending_identity as store_google_pending_identity
from mykhaya.google_auth import verify_identity_token as verify_google_identity_token
from mykhaya.legal import validate_signup_acceptances
from mykhaya.legal_evidence import queue_acceptance_evidence
from mykhaya.models import (
    ActionToken,
    AuthIdentity,
    BetaPendingRegistration,
    ChildProfile,
    ExternalIdentity,
    ExternalIdentityProvider,
    Group,
    HouseholdRelationship,
    Invitation,
    LegalAcceptance,
    LegalAcceptanceContext,
    LegalActionVerb,
    LegalRecordType,
    Membership,
    MfaEmailChallenge,
    Session,
    SessionKind,
    TokenPurpose,
    TrustedDevice,
    User,
    UserMfaMethod,
    UserMfaMethodRecord,
    UserPasskey,
)
from mykhaya.native_external_auth import (
    NativeExternalPendingIdentity,
    NativeMfaTransaction,
    consume_native_external_pending,
    consume_native_external_transaction,
    consume_native_mfa_transaction,
    hash_redemption_verifier,
    load_native_external_pending,
    load_native_mfa_transaction,
    new_native_external_transaction,
    store_native_external_pending,
    store_native_external_transaction,
    store_native_mfa_transaction,
    verify_redemption_verifier,
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
from mykhaya.platform_runtime import email_verification_required, evaluate_signup_policy
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.schemas import (
    AppleRecoveryOptionsResponse,
    AppleRecoveryRequest,
    AuthContinuationResponse,
    ChildLoginRequest,
    ConsumerMfaStatusResponse,
    ExternalIdentityResponse,
    ForgotRequest,
    GoogleRecoveryOptionsResponse,
    GoogleRecoveryRequest,
    LoginRequest,
    MessageResponse,
    MfaOptionsResponse,
    MfaPreferenceRequest,
    MfaStartRequest,
    MfaStartResponse,
    MfaTotpVerifyRequest,
    MfaVerifyRequest,
    MobileDeviceRenewRequest,
    MobileLoginRequest,
    MobileSessionResponse,
    NativeExternalBrowserStartRequest,
    NativeExternalBrowserStartResponse,
    NativeExternalExchangeRequest,
    NativeExternalLinkRequest,
    NativeExternalRecoveryResponse,
    NativeExternalRegisterRequest,
    NativeExternalStartRequest,
    NativeExternalStartResponse,
    NativeMfaContinuationResponse,
    NativeMfaStartRequest,
    NativeMfaVerifyRequest,
    PasskeyAuthenticationVerifyRequest,
    PasskeyOptionsResponse,
    PasskeyRegistrationVerifyRequest,
    PasskeyRenameRequest,
    PasskeyResponse,
    ReauthenticateRequest,
    RegisterRequest,
    RegistrationResponse,
    ResetRequest,
    SessionResponse,
    SignInMethodsResponse,
    TokenRequest,
    TrustedDeviceResponse,
    UserResponse,
)
from mykhaya.secrets_crypto import decrypt_user_mfa_totp, encrypt_user_mfa_totp
from mykhaya.security import (
    DUMMY_HASH,
    clear_auth_cookies,
    consume_action_token,
    create_action_token,
    current_user,
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


def _native_external_failure(
    request: Request, stage: str, category: str, *, provider: str | None, **fields: str | None
) -> None:
    """Safe native provider diagnostics: fixed categories and the request id
    (the client's per-attempt correlation id) only. Never tokens, nonces,
    transaction ids, provider subjects or email addresses."""
    auth_diag_log.warning(
        "native_external_auth_failed",
        stage=stage,
        category=category,
        provider=provider,
        request_id=getattr(request.state, "request_id", None),
        **fields,
    )


PASSKEY_LOGIN_COOKIE = "mk_passkey_challenge"
PASSKEY_CHALLENGE_TTL_SECONDS = 300
FRESH_AUTH_WINDOW = timedelta(minutes=10)
APPLE_LOGIN_ERROR = "apple=error"
GOOGLE_LOGIN_ERROR = "google=error"


async def complete_browser_authentication(
    db: AsyncSession,
    response: Response,
    request: Request,
    user: User,
    settings: Settings,
    *,
    method: str,
    kind: SessionKind = SessionKind.adult,
    destination: str | None = None,
    onboarding: bool = False,
) -> UserResponse | AuthContinuationResponse:
    """Shared final browser-auth seam; native callers do not use this path."""
    policy = (
        await _resolve_browser_mfa_policy(db, user.id, settings)
        if kind == SessionKind.adult
        else None
    )
    if policy is not None and policy.enforcement_enabled and policy.required:
        transaction_id = await create_browser_pre_auth(
            settings,
            user_id=str(user.id),
            method=method,
            destination=destination,
            onboarding=onboarding,
        )
        audit(db, request, "browser.pre_auth.created", user.id, target_type="browser_pre_auth")
        return AuthContinuationResponse(
            authentication_state="additional_auth_required",
            transaction_id=transaction_id,
            destination=destination,
            onboarding=onboarding,
        )
    session = await issue_family_session(
        db, response, request, user, settings, kind, fresh_auth_at=datetime.now(UTC)
    )
    user.last_login_at = datetime.now(UTC)
    user.last_activity_at = datetime.now(UTC)
    return user_response(user, session)


async def _resolve_browser_mfa_policy(
    db: AsyncSession, user_id: uuid.UUID, settings: Settings
) -> EffectiveConsumerMfaPolicy:
    try:
        return await resolve_consumer_mfa_policy(db, user_id, settings)
    except ConsumerMfaPolicyError:
        auth_diag_log.error("consumer_mfa_policy_invalid", user_id=str(user_id))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "We couldn't complete secure sign-in. Please contact support.",
        ) from None


async def _mfa_preauth_user(
    transaction_id: str, db: AsyncSession, settings: Settings
) -> tuple[BrowserPreAuth, User]:
    state = await load_browser_pre_auth(settings, transaction_id)
    if state is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    try:
        user_id = uuid.UUID(state.user_id)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid."
        ) from exc
    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.email_verified_at is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid.")
    return state, user


async def _active_mfa_methods(db: AsyncSession, user_id: uuid.UUID) -> set[UserMfaMethod]:
    rows = (
        await db.scalars(
            select(UserMfaMethodRecord).where(
                UserMfaMethodRecord.user_id == user_id,
                UserMfaMethodRecord.enabled.is_(True),
                UserMfaMethodRecord.revoked_at.is_(None),
            )
        )
    ).all()
    return {row.method for row in rows}


def _masked_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = "*" * len(local)
    else:
        masked = local[0] + "*" * min(6, len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


def _usable_browser_mfa_methods(
    allowed: set[UserMfaMethod],
    active: set[UserMfaMethod],
    email_verified: bool,
    *,
    allow_totp_enrolment: bool = False,
) -> list[str]:
    """Return methods the consumer can use now, in stable UI order.

    A required TOTP-only policy keeps the enrollment method visible even when
    no factor is active yet; the existing start/verify flow completes setup.
    """
    usable = active & allowed
    if email_verified and UserMfaMethod.email in allowed:
        usable.add(UserMfaMethod.email)
    methods = [
        method.value for method in (UserMfaMethod.totp, UserMfaMethod.email) if method in usable
    ]
    if allow_totp_enrolment and not methods and allowed == {UserMfaMethod.totp}:
        return [UserMfaMethod.totp.value]
    return methods


def _preferred_browser_mfa_method(user: User, methods: list[str]) -> str | None:
    preferred = user.preferred_mfa_method
    return preferred if preferred in methods else (methods[0] if methods else None)


@router.get("/mfa/options", response_model=MfaOptionsResponse)
async def browser_mfa_options(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MfaOptionsResponse:
    _state, user = await _mfa_preauth_user(transaction_id, db, settings)
    policy = await _resolve_browser_mfa_policy(db, user.id, settings)
    active = await _active_mfa_methods(db, user.id)
    allowed = {UserMfaMethod(method) for method in policy.allowed_methods}
    methods = _usable_browser_mfa_methods(
        allowed, active, user.email_verified_at is not None, allow_totp_enrolment=True
    )
    return MfaOptionsResponse(
        methods=methods,
        destination=_masked_email(user.email),
        primary_auth_method=_state.method,
        onboarding=_state.onboarding,
        policy="required" if policy.required else "optional",
        policy_source=policy.source,
        enrolment_required=not bool(active & allowed),
        preferred_method=_preferred_browser_mfa_method(user, methods),
    )


@router.post("/mfa/start", response_model=MfaStartResponse)
async def browser_mfa_start(
    body: MfaStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MfaStartResponse:
    state, user = await _mfa_preauth_user(body.transaction_id, db, settings)
    policy = await _resolve_browser_mfa_policy(db, user.id, settings)
    active = await _active_mfa_methods(db, user.id)
    allowed = {UserMfaMethod(method) for method in policy.allowed_methods}
    usable = _usable_browser_mfa_methods(
        allowed, active, user.email_verified_at is not None, allow_totp_enrolment=True
    )
    if body.method not in usable:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That MFA method is not allowed by policy.")
    if body.method == UserMfaMethod.email.value:
        await enforce_rate_limit(request, settings, f"mfa-email-send:{user.id}", 3, 900)
        now = datetime.now(UTC)
        reference_hash = hash_transaction(settings, body.transaction_id)
        await db.execute(
            update(MfaEmailChallenge)
            .where(
                MfaEmailChallenge.user_id == user.id,
                MfaEmailChallenge.transaction_reference_hash == reference_hash,
                MfaEmailChallenge.consumed_at.is_(None),
                MfaEmailChallenge.superseded_at.is_(None),
            )
            .values(superseded_at=now)
        )
        code = new_email_code()
        challenge = MfaEmailChallenge(
            user_id=user.id,
            transaction_reference_hash=reference_hash,
            code_hash=hash_email_code(settings, code),
            expires_at=now + timedelta(seconds=EMAIL_CHALLENGE_TTL_SECONDS),
        )
        db.add(challenge)
        await db.flush()
        subject, message, html = await render_notification_email(
            db, settings, "mfa_email_code", {"code": code}
        )
        await notify(
            db,
            settings=settings,
            recipient_user_id=user.id,
            notification_type="mfa_email_code",
            title=subject,
            body=message,
            html_body=html,
            idempotency_key=f"mfa-email:{challenge.id}",
            is_critical=True,
            sensitive_email_expires_at=challenge.expires_at,
        )
        audit(
            db,
            request,
            "MFA_EMAIL_CHALLENGE_CREATED",
            user.id,
            target_type="mfa_email_challenge",
        )
        await db.commit()
        enrolling = UserMfaMethod.email not in await _active_mfa_methods(db, user.id)
        return MfaStartResponse(
            method="email", destination=_masked_email(user.email), enrolling=enrolling
        )

    await enforce_rate_limit(request, settings, f"mfa-totp-start:{user.id}", 5, 300)
    factor = await db.scalar(
        select(UserMfaMethodRecord).where(
            UserMfaMethodRecord.user_id == user.id,
            UserMfaMethodRecord.method == UserMfaMethod.totp,
        )
    )
    enrolling = factor is None or not factor.enabled or factor.revoked_at is not None
    if enrolling:
        secret = generate_totp_secret()
        if factor is None:
            factor = UserMfaMethodRecord(user_id=user.id, method=UserMfaMethod.totp)
            db.add(factor)
        factor.encrypted_secret = encrypt_user_mfa_totp(settings, secret)
        factor.enabled = False
        factor.revoked_at = None
        await db.flush()
        audit(db, request, "MFA_TOTP_ENROLMENT_STARTED", user.id, target_type="mfa_method")
        await db.commit()
        return MfaStartResponse(
            method="totp",
            provisioning_uri=totp_provisioning_uri(secret, user.email),
            manual_key=secret,
            enrolling=True,
        )
    audit(db, request, "MFA_TOTP_VERIFICATION_STARTED", user.id, target_type="mfa_method")
    await db.commit()
    return MfaStartResponse(method="totp", enrolling=False)


@router.post("/mfa/verify", response_model=UserResponse)
async def browser_mfa_verify(
    body: MfaVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    state, user = await _mfa_preauth_user(body.transaction_id, db, settings)
    policy = await _resolve_browser_mfa_policy(db, user.id, settings)
    if body.method not in policy.allowed_methods:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That MFA method is not allowed by policy.")
    now = datetime.now(UTC)
    if body.method == UserMfaMethod.email.value:
        await enforce_rate_limit(request, settings, f"mfa-email-verify:{user.id}", 10, 900)
        challenge = await db.scalar(
            select(MfaEmailChallenge)
            .where(
                MfaEmailChallenge.user_id == user.id,
                MfaEmailChallenge.transaction_reference_hash
                == hash_transaction(settings, body.transaction_id),
                MfaEmailChallenge.consumed_at.is_(None),
                MfaEmailChallenge.superseded_at.is_(None),
            )
            .order_by(MfaEmailChallenge.created_at.desc())
            .with_for_update()
        )
        if (
            challenge is None
            or challenge.expires_at <= now
            or challenge.attempts >= EMAIL_MAX_ATTEMPTS
        ):
            audit(
                db,
                request,
                "MFA_EMAIL_CHALLENGE_FAILED",
                user.id,
                target_type="mfa_email_challenge",
            )
            audit(db, request, "MFA_LOGIN_FAILED", user.id, target_type="browser_mfa")
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That verification code is invalid.")
        challenge.attempts += 1
        if not secrets.compare_digest(challenge.code_hash, hash_email_code(settings, body.code)):
            audit(
                db,
                request,
                "MFA_EMAIL_CHALLENGE_FAILED",
                user.id,
                target_type="mfa_email_challenge",
            )
            audit(db, request, "MFA_LOGIN_FAILED", user.id, target_type="browser_mfa")
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That verification code is invalid.")
        challenge.consumed_at = now
        factor = await db.scalar(
            select(UserMfaMethodRecord).where(
                UserMfaMethodRecord.user_id == user.id,
                UserMfaMethodRecord.method == UserMfaMethod.email,
            )
        )
        if factor is None:
            factor = UserMfaMethodRecord(user_id=user.id, method=UserMfaMethod.email)
            db.add(factor)
        factor.enabled = True
        factor.enrolled_at = factor.enrolled_at or now
        factor.last_used_at = now
        audit(
            db,
            request,
            "MFA_EMAIL_CHALLENGE_SUCCEEDED",
            user.id,
            target_type="mfa_email_challenge",
        )
    else:
        await enforce_rate_limit(request, settings, f"mfa-totp-verify:{user.id}", 10, 300)
        factor = await db.scalar(
            select(UserMfaMethodRecord).where(
                UserMfaMethodRecord.user_id == user.id,
                UserMfaMethodRecord.method == UserMfaMethod.totp,
                UserMfaMethodRecord.revoked_at.is_(None),
            )
        )
        if factor is None or not factor.encrypted_secret:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Authenticator setup is required.")
        was_enabled = factor.enabled
        step = matched_totp_step(
            decrypt_user_mfa_totp(settings, factor.encrypted_secret), body.code
        )
        if step is None or not await claim_totp_step(settings, user.id, step):
            audit(db, request, "MFA_TOTP_VERIFICATION_FAILED", user.id, target_type="mfa_method")
            audit(db, request, "MFA_LOGIN_FAILED", user.id, target_type="browser_mfa")
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That verification code is invalid.")
        factor.enabled = True
        factor.enrolled_at = factor.enrolled_at or now
        factor.last_used_at = now
        audit(db, request, "MFA_TOTP_VERIFICATION_SUCCEEDED", user.id, target_type="mfa_method")
        if not was_enabled:
            audit(db, request, "MFA_TOTP_ENROLLED", user.id, target_type="mfa_method")

    consumed = await consume_browser_pre_auth(settings, body.transaction_id)
    if consumed is None or consumed.user_id != str(user.id):
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    session = await issue_family_session(
        db, response, request, user, settings, SessionKind.adult, fresh_auth_at=now
    )
    user.last_login_at = now
    user.last_activity_at = now
    audit(db, request, "MFA_LOGIN_SUCCEEDED", user.id, target_type="session")
    await db.commit()
    return user_response(user, session)


@router.post("/mfa/totp/setup", response_model=MfaStartResponse)
async def authenticated_totp_setup(
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MfaStartResponse:
    require_fresh_adult_auth(auth)
    secret = generate_totp_secret()
    factor = await db.scalar(
        select(UserMfaMethodRecord).where(
            UserMfaMethodRecord.user_id == auth.user.id,
            UserMfaMethodRecord.method == UserMfaMethod.totp,
        )
    )
    if factor is None:
        factor = UserMfaMethodRecord(user_id=auth.user.id, method=UserMfaMethod.totp)
        db.add(factor)
    elif factor.enabled:
        audit(db, request, "MFA_TOTP_RESET", auth.user.id, target_type="mfa_method")
    factor.encrypted_secret = encrypt_user_mfa_totp(settings, secret)
    factor.enabled = False
    factor.revoked_at = None
    await db.commit()
    audit(db, request, "MFA_TOTP_ENROLMENT_STARTED", auth.user.id, target_type="mfa_method")
    await db.commit()
    return MfaStartResponse(
        method="totp",
        provisioning_uri=totp_provisioning_uri(secret, auth.user.email),
        manual_key=secret,
        enrolling=True,
    )


@router.get("/mfa/status", response_model=ConsumerMfaStatusResponse)
async def authenticated_mfa_status(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConsumerMfaStatusResponse:
    if auth.session.kind != SessionKind.adult:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This action is not available to a Child.")
    policy = await _resolve_browser_mfa_policy(db, auth.user.id, settings)
    active = await _active_mfa_methods(db, auth.user.id)
    email_available = auth.user.email_verified_at is not None and "email" in policy.allowed_methods
    totp_enabled = UserMfaMethod.totp in active
    usable_methods = _usable_browser_mfa_methods(
        {UserMfaMethod(method) for method in policy.allowed_methods},
        active,
        auth.user.email_verified_at is not None,
    )
    return ConsumerMfaStatusResponse(
        required=policy.required,
        allowed_methods=sorted(policy.allowed_methods),
        email_available=email_available,
        email_destination=_masked_email(auth.user.email) if email_available else None,
        totp_enabled=totp_enabled,
        can_disable_totp=totp_enabled and (not policy.required or email_available),
        usable_methods=usable_methods,
        preferred_method=_preferred_browser_mfa_method(auth.user, usable_methods),
    )


@router.patch("/mfa/preference", response_model=ConsumerMfaStatusResponse)
async def update_mfa_preference(
    body: MfaPreferenceRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConsumerMfaStatusResponse:
    require_fresh_adult_auth(auth)
    policy = await _resolve_browser_mfa_policy(db, auth.user.id, settings)
    active = await _active_mfa_methods(db, auth.user.id)
    usable = _usable_browser_mfa_methods(
        {UserMfaMethod(method) for method in policy.allowed_methods},
        active,
        auth.user.email_verified_at is not None,
    )
    if body.method is not None and body.method not in usable:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose an available MFA method.")
    auth.user.preferred_mfa_method = body.method
    await db.commit()
    return await authenticated_mfa_status(auth, db, settings)


@router.post("/reauthenticate", response_model=MessageResponse)
async def reauthenticate_consumer(
    body: ReauthenticateRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    require_adult_session(auth)
    await enforce_rate_limit(request, settings, f"consumer-reauth:{auth.user.id}", 8, 300)
    identity = await db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == auth.user.id))
    if not verify_password(body.password, identity.password_hash if identity else DUMMY_HASH):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The password is not correct.")
    auth.session.fresh_auth_at = datetime.now(UTC)
    await db.commit()
    return MessageResponse(message="Identity verified.")


@router.delete("/mfa/totp")
async def remove_authenticated_totp(
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    require_fresh_adult_auth(auth)
    factor = await db.scalar(
        select(UserMfaMethodRecord).where(
            UserMfaMethodRecord.user_id == auth.user.id,
            UserMfaMethodRecord.method == UserMfaMethod.totp,
        )
    )
    if factor is None or not factor.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Authenticator app is not enabled.")
    factor.enabled = False
    factor.revoked_at = datetime.now(UTC)
    factor.encrypted_secret = None
    audit(db, request, "MFA_TOTP_REMOVED", auth.user.id, target_type="mfa_method")
    await db.commit()
    return {"message": "Authenticator app removed."}


@router.post("/mfa/totp/verify", response_model=ConsumerMfaStatusResponse)
async def verify_authenticated_totp(
    body: MfaTotpVerifyRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConsumerMfaStatusResponse:
    require_fresh_adult_auth(auth)
    factor = await db.scalar(
        select(UserMfaMethodRecord).where(
            UserMfaMethodRecord.user_id == auth.user.id,
            UserMfaMethodRecord.method == UserMfaMethod.totp,
        )
    )
    if factor is None or not factor.encrypted_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Authenticator setup is required.")
    step = matched_totp_step(decrypt_user_mfa_totp(settings, factor.encrypted_secret), body.code)
    if step is None or not await claim_totp_step(settings, auth.user.id, step):
        audit(db, request, "MFA_TOTP_ENROLMENT_FAILED", auth.user.id, target_type="mfa_method")
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That authenticator code isn't correct.")
    now = datetime.now(UTC)
    factor.enabled = True
    factor.enrolled_at = factor.enrolled_at or now
    factor.last_used_at = now
    audit(db, request, "MFA_TOTP_ENROLLED", auth.user.id, target_type="mfa_method")
    await db.commit()
    return await authenticated_mfa_status(auth=auth, db=db, settings=settings)


def _safe_return_path(value: str | None) -> str | None:
    if value and value.startswith("/") and not value.startswith("//"):
        return value[:500]
    return None


def _native_browser_return_uri(
    settings: Settings, provider: ExternalIdentityProvider, platform: str
) -> str:
    """Return the only supported browser-mediated native callback.

    iOS Apple and Android Google use their native SDK boundaries. Android
    Apple and iOS Google use the system browser, so those are the only
    provider/platform pairs accepted by this endpoint.
    """
    if provider == ExternalIdentityProvider.apple and platform == "android":
        value = settings.native_apple_return_uri
    elif provider == ExternalIdentityProvider.google and platform == "ios":
        value = settings.native_google_return_uri
    else:
        value = None
    if not value:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "This native browser sign-in callback is not configured.",
        )
    return value


def _apple_redirect(settings: Settings, suffix: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.public_web_url.rstrip('/')}/login?{suffix}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _apple_settings_redirect(settings: Settings, suffix: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.public_web_url.rstrip('/')}/settings/security?{suffix}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _google_redirect(settings: Settings, suffix: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.public_web_url.rstrip('/')}/login?{suffix}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _social_registration_context(return_path: str | None) -> str:
    """Carry only the signed-in registration intent through provider choice."""
    if not return_path or not return_path.startswith("/register?"):
        return ""
    query = parse_qs(return_path.split("?", 1)[1], keep_blank_values=False)
    if query.get("beta") != ["1"]:
        return ""
    invitation = query.get("beta_invitation", [None])[0]
    suffix = "&beta=1"
    if invitation:
        suffix += f"&beta_invitation={quote(invitation, safe='')}"
    return suffix


def _google_settings_redirect(settings: Settings, suffix: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.public_web_url.rstrip('/')}/settings/security?{suffix}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _apple_audit_failure(
    db: AsyncSession, request: Request, user_id: uuid.UUID | None = None
) -> None:
    audit(db, request, "APPLE_LOGIN_FAILED", user_id, target_type="external_identity")


def _apple_name(raw: str | None) -> str:
    if not raw or len(raw) > 8192:
        return "Apple user"
    try:
        parsed = json.loads(raw)
        name = parsed.get("name") if isinstance(parsed, dict) else None
        if isinstance(name, dict):
            parts = []
            for part in ("firstName", "lastName"):
                value = name.get(part)
                if isinstance(value, str) and value.strip():
                    parts.append(" ".join(value.split())[:100])
            value = " ".join(parts)
            if value:
                return value[:100]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return "Apple user"


def _google_name(claims: dict[str, object]) -> str:
    value = claims.get("name")
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())[:100]
    return "Google user"


@router.get("/apple/start")
async def apple_login_start(
    request: Request,
    next_path: str | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    try:
        require_apple_configuration(settings)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        await store_flow_state(
            settings,
            state,
            AppleFlowState(
                nonce=nonce,
                intent="login",
                user_id=None,
                return_path=_safe_return_path(next_path),
            ),
        )
        audit(db, request, "APPLE_LOGIN_STARTED", target_type="external_identity")
        await db.commit()
        return RedirectResponse(
            authorization_url(settings, state, nonce), status_code=status.HTTP_303_SEE_OTHER
        )
    except AppleAuthenticationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.post("/apple/link/start")
async def apple_link_start(
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    require_fresh_adult_auth(auth)
    try:
        require_apple_configuration(settings)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        await store_flow_state(
            settings,
            state,
            AppleFlowState(nonce=nonce, intent="link", user_id=str(auth.user.id), return_path=None),
        )
        audit(db, request, "APPLE_LOGIN_STARTED", auth.user.id, target_type="external_identity")
        await db.commit()
        return {"authorization_url": authorization_url(settings, state, nonce, "email name")}
    except AppleAuthenticationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/identities", response_model=SignInMethodsResponse)
async def authenticated_external_identities(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[ExternalIdentityResponse]:
    require_adult_session(auth)
    password_available = await db.scalar(
        select(AuthIdentity.id).where(AuthIdentity.user_id == auth.user.id)
    )
    identities = await db.scalars(
        select(ExternalIdentity)
        .where(ExternalIdentity.user_id == auth.user.id)
        .order_by(ExternalIdentity.linked_at.asc())
    )
    return SignInMethodsResponse(
        password_available=password_available is not None,
        identities=[
            ExternalIdentityResponse(
                provider=identity.provider.value,
                provider_email=identity.provider_email,
                provider_email_verified=identity.provider_email_verified,
                linked_at=identity.linked_at,
                last_used_at=identity.last_used_at,
            )
            for identity in identities
        ],
    )


@router.get("/apple/recovery/options", response_model=AppleRecoveryOptionsResponse)
async def apple_recovery_options(
    transaction_id: str,
    settings: Settings = Depends(get_settings),
) -> AppleRecoveryOptionsResponse:
    pending = await load_pending_identity(settings, transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Apple sign-in attempt has expired.")
    return AppleRecoveryOptionsResponse(
        can_register=pending.can_register,
        provider_email=pending.provider_email,
        display_name=pending.display_name,
    )


@router.post(
    "/apple/recovery/link",
    response_model=MessageResponse,
)
async def apple_recovery_link(
    body: AppleRecoveryRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    require_fresh_adult_auth(auth)
    pending = await load_pending_identity(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Apple sign-in attempt has expired.")
    if pending.intended_user_id and pending.intended_user_id != str(auth.user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This Apple linking attempt is invalid.")
    pending = await consume_pending_identity(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Apple sign-in attempt has expired.")
    current = await db.get(User, auth.user.id, with_for_update=True)
    if current is None or not current.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your sign-in session is no longer valid."
        )
    try:
        await link_external_identity(
            db,
            request,
            user_id=current.id,
            provider=ExternalIdentityProvider.apple,
            provider_subject=pending.subject,
            provider_email=pending.provider_email,
            provider_email_verified=pending.email_verified,
        )
    except ExternalIdentityOwnershipConflict:
        audit(
            db, request, "APPLE_IDENTITY_LINK_FAILED", current.id, target_type="external_identity"
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Apple identity is already linked."
        ) from None
    audit(db, request, "APPLE_IDENTITY_LINKED", current.id, target_type="external_identity")
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This Apple identity was linked by another request. Please retry sign-in.",
        ) from None
    return MessageResponse(message="Apple sign-in has been linked to your account.")


@router.post(
    "/apple/recovery/register",
    response_model=UserResponse | AuthContinuationResponse,
)
async def apple_recovery_register(
    body: AppleRecoveryRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse | AuthContinuationResponse:
    pending = await load_pending_identity(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Apple sign-in attempt has expired.")
    if not pending.can_register or not pending.provider_email:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This Apple identity must be linked to an existing account.",
        )
    policy = await evaluate_signup_policy(db, settings)
    if body.beta:
        beta_allowed = policy.beta_path and (
            not policy.invitation_required
            or bool(body.beta_invitation_token)
            and await beta_invitation_valid(db, body.beta_invitation_token, pending.provider_email)
        )
    else:
        beta_allowed = policy.normal_path and not policy.invitation_required
    if not beta_allowed or not policy.domain_allowed(pending.provider_email):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "New accounts cannot be created with Apple right now.",
        )
    resolved_legal_acceptances = await validate_signup_acceptances(
        db,
        [(item.document_key, item.document_version_id) for item in body.legal_acceptances],
    )
    pending = await consume_pending_identity(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Apple sign-in attempt has expired.")
    existing = await db.scalar(
        select(User).where(User.email == normalise_email(pending.provider_email)).with_for_update()
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account already uses this email. Sign in and link Apple instead.",
        )
    identity = await find_external_identity(
        db, ExternalIdentityProvider.apple, pending.subject, for_update=True
    )
    if identity is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Apple identity is already linked.")
    user = User(
        email=normalise_email(pending.provider_email),
        display_name=pending.display_name,
        email_verified_at=datetime.now(UTC) if pending.email_verified else None,
    )
    db.add(user)
    await db.flush()
    for resolved in resolved_legal_acceptances:
        record_type = (
            LegalRecordType.user_acceptance
            if resolved.document.action_verb == LegalActionVerb.accept
            else LegalRecordType.user_acknowledgement
        )
        acceptance = LegalAcceptance(
            created_at=datetime.now(UTC),
            record_type=record_type,
            document_version_id=resolved.version.id,
            user_id=user.id,
            context=(
                LegalAcceptanceContext.beta_registration
                if body.beta
                else LegalAcceptanceContext.signup
            ),
            platform=body.platform,
            ip_address=resolve_client_ip(request, settings),
            user_agent=request.headers.get("user-agent", "")[:300] or None,
        )
        db.add(acceptance)
        await queue_acceptance_evidence(
            db,
            acceptance=acceptance,
            document=resolved.document,
            version=resolved.version,
            user=user,
        )
    await link_external_identity(
        db,
        request,
        user_id=user.id,
        provider=ExternalIdentityProvider.apple,
        provider_subject=pending.subject,
        provider_email=pending.provider_email,
        provider_email_verified=pending.email_verified,
    )
    if body.beta:
        programme = await current_programme(db)
        db.add(
            BetaPendingRegistration(
                user_id=user.id,
                programme_id=programme.id,
                token_hash=hash_secret(
                    secrets.token_urlsafe(32), settings.secret_key.get_secret_value()
                ),
                invitation_token_hash=invitation_token_hash(body.beta_invitation_token)
                if body.beta_invitation_token
                else None,
                expires_at=datetime.now(UTC) + timedelta(days=BETA_INTENT_TTL_DAYS),
            )
        )
    result = await complete_browser_authentication(
        db,
        response,
        request,
        user,
        settings,
        method="apple",
        destination=pending.return_path or "/onboarding",
        onboarding=True,
    )
    audit(db, request, "APPLE_IDENTITY_REGISTERED", user.id, target_type="external_identity")
    await db.commit()
    return result


@router.delete("/apple/link")
async def unlink_apple_identity(
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    require_fresh_adult_auth(auth)
    try:
        await unlink_external_identity(
            db,
            request,
            user_id=auth.user.id,
            provider=ExternalIdentityProvider.apple,
        )
    except ExternalIdentityNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Apple identity is linked.") from None
    except LastAuthenticationMethodError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Add another sign-in method before unlinking Apple.",
        ) from None
    audit(db, request, "APPLE_IDENTITY_UNLINKED", auth.user.id, target_type="external_identity")
    await db.commit()
    return {"message": "Apple sign-in has been unlinked."}


def _apple_form_value(fields: dict[str, list[str]], name: str) -> str | None:
    values = fields.get(name)
    if not values:
        return None
    if len(values) != 1:
        raise AppleAuthenticationError("Invalid Apple sign-in response.")
    return values[0]


async def _apple_callback(
    request: Request,
    state: str | None,
    code: str | None,
    error: str | None,
    user: str | None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    flow: AppleFlowState | None = None
    try:
        if not state or len(state) > 512:
            raise AppleAuthenticationError("Invalid Apple sign-in state.")
        flow = await consume_flow_state(settings, state)
        if error:
            raise AppleAuthenticationError("Apple sign-in was cancelled.")
        if not code:
            raise AppleAuthenticationError("Apple sign-in did not return an authorization code.")
        identity_token = await exchange_code(settings, code)
        claims = await verify_identity_token(settings, identity_token, flow.nonce)
        subject = str(claims["sub"])
        provider_email = claims.get("email")
        provider_email = (
            provider_email.strip().casefold() if isinstance(provider_email, str) else None
        )
        email_verified = claims.get("email_verified") in (True, "true", "1")

        identity = await find_external_identity(
            db, ExternalIdentityProvider.apple, subject, for_update=True
        )

        if flow.native_return_uri:
            if (
                flow.native_platform is None
                or flow.native_environment != settings.environment
                or flow.native_transaction_id is None
                or flow.native_redemption_verifier_hash is None
                or _native_browser_return_uri(
                    settings, ExternalIdentityProvider.apple, flow.native_platform
                )
                != flow.native_return_uri
            ):
                raise AppleAuthenticationError("This native callback is invalid.")
            if identity is None and not provider_email:
                raise AppleAuthenticationError("Apple did not provide an email for this account.")
            policy = await evaluate_signup_policy(db, settings)
            await store_native_external_pending(
                settings,
                NativeExternalPendingIdentity(
                    transaction_id=flow.native_transaction_id,
                    provider=ExternalIdentityProvider.apple,
                    subject=subject,
                    provider_email=provider_email,
                    email_verified=email_verified,
                    display_name=_apple_name(user),
                    can_register=identity is None
                    and bool(provider_email)
                    and policy.normal_path
                    and not policy.invitation_required
                    and policy.domain_allowed(provider_email),
                    platform=flow.native_platform,
                    redemption_verifier_hash=flow.native_redemption_verifier_hash,
                    intended_user_id=flow.user_id if flow.intent == "link" else None,
                    intent=flow.intent,
                ),
            )
            await db.commit()
            return RedirectResponse(
                f"{flow.native_return_uri}?transaction={flow.native_transaction_id}&provider=apple",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        if flow.intent == "link":
            if not flow.user_id:
                raise AppleAuthenticationError("This Apple linking attempt is invalid.")
            pending_transaction = secrets.token_urlsafe(32)
            await store_pending_identity(
                settings,
                pending_transaction,
                ApplePendingIdentity(
                    transaction_id=pending_transaction,
                    subject=subject,
                    provider_email=provider_email,
                    email_verified=email_verified,
                    display_name=_apple_name(user),
                    can_register=False,
                    return_path=None,
                    intended_user_id=flow.user_id,
                ),
            )
            await db.commit()
            return _apple_settings_redirect(
                settings, f"apple=link_required&transaction={pending_transaction}"
            )

        if identity is not None:
            candidate = await db.get(User, identity.user_id, with_for_update=True)
            if candidate is None or not candidate.is_active:
                raise AppleAuthenticationError("Apple sign-in could not be completed.")
            linked_user = candidate
            await touch_external_identity(
                db,
                identity=identity,
                provider_email=provider_email,
                provider_email_verified=email_verified,
            )
        else:
            # An email match is never an implicit identity link. Keep the
            # verified provider identity in a short-lived, single-use recovery
            # transaction and require an explicit account decision. This is
            # essential for Apple private-relay addresses, which may not match
            # the user's existing MyKhaya email at all.
            existing = (
                await db.scalar(select(User).where(User.email == provider_email))
                if provider_email
                else None
            )
            if not provider_email:
                raise AppleAuthenticationError("Apple did not provide an email for this account.")
            policy = await evaluate_signup_policy(db, settings)
            beta_registration = bool(_social_registration_context(flow.return_path))
            pending_transaction = secrets.token_urlsafe(32)
            await store_pending_identity(
                settings,
                pending_transaction,
                ApplePendingIdentity(
                    transaction_id=pending_transaction,
                    subject=subject,
                    provider_email=provider_email,
                    email_verified=email_verified,
                    display_name=_apple_name(user),
                    can_register=(
                        existing is None
                        and (
                            (policy.beta_path if beta_registration else policy.normal_path)
                            and (beta_registration or not policy.invitation_required)
                        )
                        and policy.domain_allowed(provider_email)
                    ),
                    return_path=flow.return_path,
                ),
            )
            audit(db, request, "APPLE_RECOVERY_CREATED", target_type="external_identity")
            await db.commit()
            return _apple_redirect(
                settings,
                f"apple=choose&transaction={pending_transaction}{_social_registration_context(flow.return_path)}",
            )

        has_home = await db.scalar(
            select(Membership.id).where(Membership.user_id == linked_user.id)
        )
        destination = flow.return_path or ("/home" if has_home else "/onboarding")
        session_response = RedirectResponse(
            f"{settings.public_web_url.rstrip('/')}{destination}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        result = await complete_browser_authentication(
            db,
            session_response,
            request,
            linked_user,
            settings,
            method="apple",
            destination=destination,
            onboarding=has_home is None,
        )
        if isinstance(result, AuthContinuationResponse):
            session_response = _apple_redirect(
                settings,
                f"auth=additional&transaction={result.transaction_id}",
            )
        audit(db, request, "APPLE_LOGIN_SUCCESS", linked_user.id, target_type="external_identity")
        await db.commit()
        return session_response
    except HTTPException:
        await db.rollback()
        if flow is not None and flow.intent == "link":
            return _apple_settings_redirect(settings, "apple=error")
        raise
    except Exception as exc:
        await db.rollback()
        try:
            user_id = uuid.UUID(flow.user_id) if flow and flow.user_id else None
        except ValueError:
            user_id = None
        action = (
            "APPLE_IDENTITY_LINK_FAILED"
            if flow is not None and flow.intent == "link"
            else "APPLE_LOGIN_FAILED"
        )
        audit(db, request, action, user_id, target_type="external_identity")
        await db.commit()
        if isinstance(exc, AppleAuthenticationError):
            if flow is not None and flow.intent == "link":
                return _apple_settings_redirect(settings, "apple=error")
            return _apple_redirect(settings, APPLE_LOGIN_ERROR)
        if flow is not None and flow.intent == "link":
            return _apple_settings_redirect(settings, "apple=error")
        return _apple_redirect(settings, APPLE_LOGIN_ERROR)


@router.get("/apple/callback")
async def apple_callback_get(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    user: str | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    # Retain GET only for compatibility with previously-issued authorization
    # attempts. New authorization requests always use Apple's form_post mode.
    return await _apple_callback(request, state, code, error, user, db, settings)


@router.post("/apple/callback")
async def apple_callback_post(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Invalid Apple response format."
        )
    try:
        body = await request.body()
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=8)
        state = _apple_form_value(fields, "state")
        code = _apple_form_value(fields, "code")
        error = _apple_form_value(fields, "error")
        user = _apple_form_value(fields, "user")
    except (UnicodeDecodeError, ValueError, AppleAuthenticationError) as exc:
        if isinstance(exc, AppleAuthenticationError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Apple response format.") from exc
    return await _apple_callback(request, state, code, error, user, db, settings)


@router.get("/google/start")
async def google_login_start(
    request: Request,
    next_path: str | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    try:
        require_google_configuration(settings)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = new_google_code_verifier()
        await store_google_flow_state(
            settings,
            state,
            GoogleFlowState(
                nonce=nonce,
                code_verifier=verifier,
                intent="login",
                user_id=None,
                return_path=_safe_return_path(next_path),
            ),
        )
        audit(db, request, "GOOGLE_LOGIN_STARTED", target_type="external_identity")
        await db.commit()
        return RedirectResponse(
            google_authorization_url(settings, state, nonce, verifier),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except GoogleAuthenticationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.post("/google/link/start")
async def google_link_start(
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    require_fresh_adult_auth(auth)
    try:
        require_google_configuration(settings)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = new_google_code_verifier()
        await store_google_flow_state(
            settings,
            state,
            GoogleFlowState(
                nonce=nonce,
                code_verifier=verifier,
                intent="link",
                user_id=str(auth.user.id),
                return_path=None,
            ),
        )
        audit(db, request, "GOOGLE_LOGIN_STARTED", auth.user.id, target_type="external_identity")
        await db.commit()
        return {"authorization_url": google_authorization_url(settings, state, nonce, verifier)}
    except GoogleAuthenticationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/google/recovery/options", response_model=GoogleRecoveryOptionsResponse)
async def google_recovery_options(
    transaction_id: str, settings: Settings = Depends(get_settings)
) -> GoogleRecoveryOptionsResponse:
    pending = await load_google_pending_identity(settings, transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Google sign-in attempt has expired.")
    return GoogleRecoveryOptionsResponse(
        can_register=pending.can_register,
        provider_email=pending.provider_email,
        display_name=pending.display_name,
    )


@router.post("/google/recovery/link", response_model=MessageResponse)
async def google_recovery_link(
    body: GoogleRecoveryRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    require_fresh_adult_auth(auth)
    pending = await load_google_pending_identity(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Google sign-in attempt has expired.")
    current = await db.get(User, auth.user.id, with_for_update=True)
    if current is None or not current.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your sign-in session is no longer valid."
        )
    if current.email != pending.provider_email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This Google linking attempt is invalid.")
    pending = await consume_google_pending_identity(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Google sign-in attempt has expired.")
    try:
        await link_external_identity(
            db,
            request,
            user_id=current.id,
            provider=ExternalIdentityProvider.google,
            provider_subject=pending.subject,
            provider_email=pending.provider_email,
            provider_email_verified=pending.email_verified,
        )
    except ExternalIdentityOwnershipConflict:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Google identity is already linked."
        ) from None
    audit(db, request, "GOOGLE_IDENTITY_LINKED", current.id, target_type="external_identity")
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Google identity was linked by another request."
        ) from None
    return MessageResponse(message="Google sign-in has been linked to your account.")


@router.post("/google/recovery/register", response_model=UserResponse | AuthContinuationResponse)
async def google_recovery_register(
    body: GoogleRecoveryRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse | AuthContinuationResponse:
    pending = await load_google_pending_identity(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Google sign-in attempt has expired.")
    if not pending.can_register or not pending.email_verified:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Google identity must be linked to an existing account."
        )
    policy = await evaluate_signup_policy(db, settings)
    if body.beta:
        beta_allowed = policy.beta_path and (
            not policy.invitation_required
            or bool(body.beta_invitation_token)
            and await beta_invitation_valid(db, body.beta_invitation_token, pending.provider_email)
        )
    else:
        beta_allowed = policy.normal_path and not policy.invitation_required
    if not beta_allowed or not policy.domain_allowed(pending.provider_email):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "New accounts cannot be created with Google right now."
        )
    resolved_legal_acceptances = await validate_signup_acceptances(
        db, [(item.document_key, item.document_version_id) for item in body.legal_acceptances]
    )
    pending = await consume_google_pending_identity(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Google sign-in attempt has expired.")
    existing = await db.scalar(
        select(User).where(User.email == normalise_email(pending.provider_email)).with_for_update()
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account already uses this email. Sign in and link Google instead.",
        )
    identity = await find_external_identity(
        db, ExternalIdentityProvider.google, pending.subject, for_update=True
    )
    if identity is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Google identity is already linked.")
    user = User(
        email=normalise_email(pending.provider_email),
        display_name=pending.display_name,
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    await db.flush()
    for resolved in resolved_legal_acceptances:
        record_type = (
            LegalRecordType.user_acceptance
            if resolved.document.action_verb == LegalActionVerb.accept
            else LegalRecordType.user_acknowledgement
        )
        acceptance = LegalAcceptance(
            created_at=datetime.now(UTC),
            record_type=record_type,
            document_version_id=resolved.version.id,
            user_id=user.id,
            context=(
                LegalAcceptanceContext.beta_registration
                if body.beta
                else LegalAcceptanceContext.signup
            ),
            platform=body.platform,
            ip_address=resolve_client_ip(request, settings),
            user_agent=request.headers.get("user-agent", "")[:300] or None,
        )
        db.add(acceptance)
        await queue_acceptance_evidence(
            db,
            acceptance=acceptance,
            document=resolved.document,
            version=resolved.version,
            user=user,
        )
    await link_external_identity(
        db,
        request,
        user_id=user.id,
        provider=ExternalIdentityProvider.google,
        provider_subject=pending.subject,
        provider_email=pending.provider_email,
        provider_email_verified=pending.email_verified,
    )
    if body.beta:
        programme = await current_programme(db)
        db.add(
            BetaPendingRegistration(
                user_id=user.id,
                programme_id=programme.id,
                token_hash=hash_secret(
                    secrets.token_urlsafe(32), settings.secret_key.get_secret_value()
                ),
                invitation_token_hash=invitation_token_hash(body.beta_invitation_token)
                if body.beta_invitation_token
                else None,
                expires_at=datetime.now(UTC) + timedelta(days=BETA_INTENT_TTL_DAYS),
            )
        )
    result = await complete_browser_authentication(
        db,
        response,
        request,
        user,
        settings,
        method="google",
        destination=pending.return_path or "/onboarding",
        onboarding=True,
    )
    audit(db, request, "GOOGLE_IDENTITY_REGISTERED", user.id, target_type="external_identity")
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Google identity is already linked."
        ) from None
    return result


@router.delete("/google/link")
async def unlink_google_identity(
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    require_fresh_adult_auth(auth)
    try:
        await unlink_external_identity(
            db, request, user_id=auth.user.id, provider=ExternalIdentityProvider.google
        )
    except ExternalIdentityNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Google identity is linked.") from None
    except LastAuthenticationMethodError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Add another sign-in method before unlinking Google."
        ) from None
    audit(db, request, "GOOGLE_IDENTITY_UNLINKED", auth.user.id, target_type="external_identity")
    await db.commit()
    return {"message": "Google sign-in has been unlinked."}


@router.get("/google/callback")
async def google_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    flow: GoogleFlowState | None = None
    try:
        if not state or len(state) > 512:
            raise GoogleAuthenticationError("Invalid Google sign-in state.")
        flow = await consume_google_flow_state(settings, state)
        if error:
            raise GoogleAuthenticationError("Google sign-in was cancelled.")
        if not code:
            raise GoogleAuthenticationError("Google sign-in did not return an authorization code.")
        token = await exchange_google_code(settings, code, flow.code_verifier)
        claims = await verify_google_identity_token(settings, token, flow.nonce)
        subject = str(claims["sub"])
        provider_email = str(claims["email"]).strip().casefold()
        identity = await find_external_identity(
            db, ExternalIdentityProvider.google, subject, for_update=True
        )
        if flow.native_return_uri:
            if (
                flow.native_platform is None
                or flow.native_environment != settings.environment
                or flow.native_transaction_id is None
                or flow.native_redemption_verifier_hash is None
                or _native_browser_return_uri(
                    settings, ExternalIdentityProvider.google, flow.native_platform
                )
                != flow.native_return_uri
            ):
                raise GoogleAuthenticationError("This native callback is invalid.")
            policy = await evaluate_signup_policy(db, settings)
            await store_native_external_pending(
                settings,
                NativeExternalPendingIdentity(
                    transaction_id=flow.native_transaction_id,
                    provider=ExternalIdentityProvider.google,
                    subject=subject,
                    provider_email=provider_email,
                    email_verified=True,
                    display_name=_google_name(claims),
                    can_register=identity is None
                    and policy.normal_path
                    and not policy.invitation_required
                    and policy.domain_allowed(provider_email),
                    platform=flow.native_platform,
                    redemption_verifier_hash=flow.native_redemption_verifier_hash,
                    intended_user_id=flow.user_id if flow.intent == "link" else None,
                    intent=flow.intent,
                ),
            )
            await db.commit()
            return RedirectResponse(
                f"{flow.native_return_uri}?transaction={flow.native_transaction_id}&provider=google",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        if flow.intent == "link":
            linked_user, _session = await current_user(request, db, settings)
            if flow.user_id != str(linked_user.id):
                raise GoogleAuthenticationError("This Google linking attempt is invalid.")
            await link_external_identity(
                db,
                request,
                user_id=linked_user.id,
                provider=ExternalIdentityProvider.google,
                provider_subject=subject,
                provider_email=provider_email,
                provider_email_verified=True,
            )
            await db.commit()
            return _google_settings_redirect(settings, "google=linked")
        if identity is not None:
            linked_user = await db.get(User, identity.user_id, with_for_update=True)
            if linked_user is None or not linked_user.is_active:
                raise GoogleAuthenticationError("Google sign-in could not be completed.")
            await touch_external_identity(
                db, identity=identity, provider_email=provider_email, provider_email_verified=True
            )
        else:
            existing = await db.scalar(select(User).where(User.email == provider_email))
            policy = await evaluate_signup_policy(db, settings)
            beta_registration = bool(_social_registration_context(flow.return_path))
            transaction_id = secrets.token_urlsafe(32)
            await store_google_pending_identity(
                settings,
                transaction_id,
                GooglePendingIdentity(
                    transaction_id=transaction_id,
                    subject=subject,
                    provider_email=provider_email,
                    email_verified=True,
                    display_name=_google_name(claims),
                    can_register=existing is None
                    and (
                        (policy.beta_path if beta_registration else policy.normal_path)
                        and (beta_registration or not policy.invitation_required)
                    )
                    and policy.domain_allowed(provider_email),
                    return_path=flow.return_path,
                ),
            )
            audit(db, request, "GOOGLE_RECOVERY_CREATED", target_type="external_identity")
            await db.commit()
            return _google_redirect(
                settings,
                f"google=choose&transaction={transaction_id}{_social_registration_context(flow.return_path)}",
            )
        has_home = await db.scalar(
            select(Membership.id).where(Membership.user_id == linked_user.id)
        )
        destination = flow.return_path or ("/home" if has_home else "/onboarding")
        response = RedirectResponse(
            f"{settings.public_web_url.rstrip('/')}{destination}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        result = await complete_browser_authentication(
            db,
            response,
            request,
            linked_user,
            settings,
            method="google",
            destination=destination,
            onboarding=has_home is None,
        )
        if isinstance(result, AuthContinuationResponse):
            response = _google_redirect(
                settings, f"auth=additional&transaction={result.transaction_id}"
            )
        audit(db, request, "GOOGLE_LOGIN_SUCCESS", linked_user.id, target_type="external_identity")
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        if flow is not None and flow.intent == "link":
            return _google_settings_redirect(settings, GOOGLE_LOGIN_ERROR)
        raise
    except Exception as exc:
        await db.rollback()
        if flow is not None and flow.intent == "link":
            return _google_settings_redirect(settings, GOOGLE_LOGIN_ERROR)
        if isinstance(exc, GoogleAuthenticationError):
            return _google_redirect(settings, GOOGLE_LOGIN_ERROR)
        return _google_redirect(settings, GOOGLE_LOGIN_ERROR)


@router.get("/providers")
async def authentication_provider_status(
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Return safe provider configuration state for future auth surfaces.

    This endpoint reports status only; it never authenticates a provider,
    creates a session, or returns credentials.
    """
    return {"providers": [item.public_dict() for item in external_auth_provider_statuses(settings)]}


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
    expires_at: datetime | None = None,
) -> Session:
    raw = new_session_token()
    csrf = secrets.token_urlsafe(32)
    session = Session(
        user_id=user.id,
        trusted_device_id=trusted_device_id,
        token_hash=hash_secret(raw, settings.secret_key.get_secret_value()),
        expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=settings.session_minutes),
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
    existing_device_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    mint_device: bool = True,
) -> tuple[str, Session, str | None]:
    """Bearer-transport equivalent of issue_session: same Session model, same
    token scheme, no cookies. Returns the raw session token - callers must
    put it in the response body only, never a cookie, never a log line.

    At login time (existing_device_id=None) also issues a TrustedDevice (the
    same row/table the browser's "remember this device" cookie uses — see
    issue_family_session) linked via Session.trusted_device_id, and returns
    its own raw renewal token alongside the session token. This is what
    gives a native app a genuinely long-lived (settings.trusted_device_days,
    e.g. 90 days) path back in after its short-lived bearer session
    (settings.session_minutes) has expired, via
    POST /auth/mobile/sessions/renew, without ever asking for a password
    again — the exact bearer-transport equivalent of the browser's silent
    /auth/renew. Before this, a native session that outlived
    session_minutes without ever calling the (session-still-valid-only)
    /mobile/sessions/rotate endpoint had no way back in at all.

    When rotating an *already*-valid session (existing_device_id set — see
    rotate_mobile_session), the existing device is reused unchanged rather
    than minting a new TrustedDevice on every rotation; the returned device
    token is None in that case since nothing about the device credential
    changed and there is nothing new to persist.

    Rotation passes expires_at when it must not extend the session's lifetime
    (see _rotated_session_expiry) and then also mint_device=False, so a
    device-less session cannot gain a renewal credential while consumer MFA
    is required."""
    raw = new_session_token()
    device_raw: str | None = None
    device_id = existing_device_id
    if device_id is None and mint_device:
        device, device_raw, _device_csrf = await issue_trusted_device(
            db, request, user, settings, kind
        )
        device_id = device.id
    session = Session(
        user_id=user.id,
        token_hash=hash_secret(raw, settings.secret_key.get_secret_value()),
        expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=settings.session_minutes),
        fresh_auth_at=fresh_auth_at,
        user_agent=mobile_client_descriptor(request),
        trusted_device_id=device_id,
        kind=kind,
    )
    db.add(session)
    await db.flush()
    audit(db, request, "session.created", user.id, target_type="session", target_id=session.id)
    return raw, session, device_raw


async def authenticate_credentials(
    db: AsyncSession, request: Request, settings: Settings, body: LoginRequest, bucket: str
) -> User:
    """Shared by /auth/login and /auth/mobile/login so the security-sensitive
    part (rate limiting, password check, active/verified checks) is never
    duplicated between transports."""
    await enforce_rate_limit(request, settings, bucket, settings.rate_limit_login, 60)
    email = normalise_email(str(body.email))
    await db.execute(
        delete(BetaPendingRegistration).where(
            BetaPendingRegistration.expires_at <= datetime.now(UTC),
        )
    )
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
    if await email_verification_required(db, settings) and user.email_verified_at is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Please verify your email before signing in."
        )
    return user


# How long a Founding Beta registration intent waits for its owner to verify
# and enrol. Longer than the 24h verification link on purpose: a user who
# requests a fresh link later must still land in the Beta continuation.
BETA_INTENT_TTL_DAYS = 30


@router.post("/register", response_model=RegistrationResponse, status_code=status.HTTP_202_ACCEPTED)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RegistrationResponse:
    await enforce_rate_limit(request, settings, "register", settings.rate_limit_register, 300)
    email = normalise_email(str(body.email))
    # Every gate below is decided by the one resolver in mykhaya.platform_runtime
    # (see SignupPolicy for the documented precedence) and runs before the
    # existing-email lookup, so an existing and a new address are rejected
    # identically — none of these checks can become an account-discovery signal.
    policy = await evaluate_signup_policy(db, settings)
    if not policy.open:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is currently closed.")
    beta = body.beta_requested
    if beta:
        if not policy.beta_path:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Founding Beta joining is not currently open."
            )
    elif not policy.normal_path:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "New accounts can currently only be created by joining the Founding Beta.",
        )
    if not policy.domain_allowed(email):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Registration is not available for that email address.",
        )
    verification_required = await email_verification_required(db, settings)

    invitation_row: Invitation | None = None
    if policy.invitation_required and beta:
        if not body.beta_invitation_token or not await beta_invitation_valid(
            db, body.beta_invitation_token, email
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Registration is invitation-only. A valid Beta invitation is required.",
            )
    elif policy.invitation_required:
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

    # Validated before the existing-email lookup, unconditionally, so a
    # re-used email and a genuinely new one are rejected identically by
    # this check — it must never become a second account-discovery signal
    # alongside the dummy-hash password-timing equalisation below.
    # Account creation requires the global documents only. The Founding Beta
    # Terms are a separate legal stage, accepted after verification in the
    # authenticated Beta continuation — never at registration.
    resolved_legal_acceptances = await validate_signup_acceptances(
        db,
        [(item.document_key, item.document_version_id) for item in body.legal_acceptances],
    )

    existing = await db.scalar(select(User).where(User.email == email))
    if existing is None:
        user = User(
            email=email,
            display_name=body.display_name,
            email_verified_at=None if verification_required else datetime.now(UTC),
        )
        db.add(user)
        await db.flush()
        db.add(AuthIdentity(user_id=user.id, password_hash=password_hash.hash(body.password)))
        if beta:
            # The durable Beta intent: survives verification and first sign-in
            # without relying on any query string, and is consumed when the
            # verified user enrols (POST /beta/join).
            programme = await current_programme(db)
            db.add(
                BetaPendingRegistration(
                    user_id=user.id,
                    programme_id=programme.id,
                    token_hash=hash_secret(
                        secrets.token_urlsafe(32), settings.secret_key.get_secret_value()
                    ),
                    invitation_token_hash=invitation_token_hash(body.beta_invitation_token)
                    if body.beta_invitation_token
                    else None,
                    expires_at=datetime.now(UTC) + timedelta(days=BETA_INTENT_TTL_DAYS),
                )
            )
        for resolved in resolved_legal_acceptances:
            record_type = (
                LegalRecordType.user_acceptance
                if resolved.document.action_verb == LegalActionVerb.accept
                else LegalRecordType.user_acknowledgement
            )
            acceptance = LegalAcceptance(
                created_at=datetime.now(UTC),
                record_type=record_type,
                document_version_id=resolved.version.id,
                user_id=user.id,
                context=(
                    LegalAcceptanceContext.beta_registration
                    if beta
                    else LegalAcceptanceContext.signup
                ),
                platform=body.platform,
                ip_address=resolve_client_ip(request, settings),
                user_agent=request.headers.get("user-agent", "")[:300] or None,
            )
            db.add(acceptance)
            await queue_acceptance_evidence(
                db,
                acceptance=acceptance,
                document=resolved.document,
                version=resolved.version,
                user=user,
            )
        if verification_required:
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
        if verification_required
        else "Your account is ready. You can sign in now."
    )
    return RegistrationResponse(message=message, verification_required=verification_required)


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
    # Beta registration remains staged here (BetaPendingRegistration). Beta
    # Terms, Home creation, capacity allocation and the entitlement grant
    # happen only in the authenticated Beta continuation after sign-in.
    audit(db, request, "user.email_verified", user.id, target_type="user", target_id=user.id)
    await db.commit()
    return MessageResponse(message="Your email is verified. You can sign in now.")


@router.post("/login", response_model=UserResponse | AuthContinuationResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse | AuthContinuationResponse:
    user = await authenticate_credentials(db, request, settings, body, "login")
    result = await complete_browser_authentication(
        db, response, request, user, settings, method="password", destination="/home"
    )
    await db.commit()
    return result


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


@router.post("/passkeys/login/verify", response_model=UserResponse | AuthContinuationResponse)
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
        await pop_webauthn_token_challenge(settings, "family-login", token) if token else None
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
    result = await complete_browser_authentication(
        db,
        response,
        request,
        user,
        settings,
        method="passkey",
        destination="/home",
    )
    if isinstance(result, UserResponse):
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
    return result


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


async def authenticate_child_credentials(
    db: AsyncSession, request: Request, settings: Settings, body: ChildLoginRequest, bucket: str
) -> User:
    """Shared by /child/login and /auth/mobile/child/login — same rationale as
    authenticate_credentials for the adult path: the security-sensitive check
    (rate limiting, PIN verification, active/login-enabled checks) is never
    duplicated between transports. `bucket` lets the two callers use separate
    per-IP rate-limit buckets without changing the shared identity-bucket
    logic below, which must stay keyed on the child identity regardless of
    which endpoint is used."""
    # Per-IP *and* per-sign-in-identity — a slow, distributed attempt against
    # one specific Child is limited even if it never trips the per-IP bucket,
    # and vice versa.
    await enforce_rate_limit(request, settings, bucket, settings.rate_limit_login, 60)
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
    return user


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
    user = await authenticate_child_credentials(db, request, settings, body, "child-login")
    session = await issue_family_session(
        db, response, request, user, settings, SessionKind.managed_child
    )
    user.last_login_at = datetime.now(UTC)
    user.last_activity_at = datetime.now(UTC)
    await db.commit()
    return user_response(user, session)


@router.post("/mobile/child/login", response_model=MobileSessionResponse)
async def mobile_child_login(
    body: ChildLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MobileSessionResponse:
    """Native-client equivalent of /child/login — same relationship as
    /mobile/login has to /login (see ADR 0010): identical credential check,
    opaque Session token, but returned in the body instead of a cookie. A
    managed Child is a normal Session row with kind=managed_child regardless
    of transport — this does not introduce a second child-auth mechanism,
    just a second way to carry the same session."""
    require_secure_transport(request, settings)
    user = await authenticate_child_credentials(db, request, settings, body, "child-login-mobile")
    raw, session, device_raw = await issue_mobile_session(
        db, request, user, settings, kind=SessionKind.managed_child
    )
    user.last_login_at = datetime.now(UTC)
    user.last_activity_at = datetime.now(UTC)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return MobileSessionResponse(
        **user_response(user, session).model_dump(), session_token=raw, device_token=device_raw
    )


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
                TrustedDevice.token_hash == hash_secret(raw, settings.secret_key.get_secret_value())
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

    if device.kind == SessionKind.adult:
        policy = await _resolve_browser_mfa_policy(db, user.id, settings)
        if policy.enforcement_enabled and policy.required:
            device.revoked_at = now
            audit(
                db,
                request,
                "session.renewal_blocked_mfa_required",
                user.id,
                target_type="trusted_device",
                target_id=device.id,
            )
            await db.commit()
            _auth_diag(
                request,
                "RENEW_FAILED",
                result="MFA_REQUIRED",
                user_id=str(user.id),
                device_id=str(device.id),
                status_code=401,
            )
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to continue.")

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


async def _native_mfa_continuation(
    db: AsyncSession,
    request: Request,
    settings: Settings,
    user: User,
    *,
    primary: str,
    platform: str,
    redemption_verifier_hash: str,
) -> NativeMfaContinuationResponse:
    """Hold a native sign-in at pre-authentication until the consumer MFA
    policy is satisfied through /auth/mobile/mfa/*. No session or device
    credential exists until /auth/mobile/mfa/verify succeeds."""
    mfa_transaction = NativeMfaTransaction(
        transaction_id=secrets.token_urlsafe(32),
        user_id=str(user.id),
        provider=primary,
        platform=platform,
        redemption_verifier_hash=redemption_verifier_hash,
    )
    await store_native_mfa_transaction(settings, mfa_transaction)
    audit(db, request, "native.pre_auth.created", user.id, target_type="native_pre_auth")
    return NativeMfaContinuationResponse(
        authentication_state="additional_auth_required",
        transaction_id=mfa_transaction.transaction_id,
        provider=primary,
    )


@router.post("/mobile/login", response_model=MobileSessionResponse | NativeMfaContinuationResponse)
async def mobile_login(
    body: MobileLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MobileSessionResponse | NativeMfaContinuationResponse:
    """Native-client equivalent of /login: same credential check, opaque
    Session token, but returned in the body (not a cookie) since a native
    app has no cookie jar to rely on. Sets no cookies. Never logs the raw
    token - only the caller who receives this response ever sees it.

    The consumer MFA policy applies exactly as it does to browser /login:
    nothing about a request proves it came from the MyKhaya app (no app
    attestation exists; X-MyKhaya-* headers are display-only), so exempting
    this endpoint would let any password holder bypass required MFA."""
    require_secure_transport(request, settings)
    user = await authenticate_credentials(db, request, settings, body, "mobile_login")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    policy = await _resolve_browser_mfa_policy(db, user.id, settings)
    if policy.enforcement_enabled and policy.required:
        if body.redemption_verifier is None:
            # An older client that cannot continue an MFA challenge. Fail
            # closed: the password was correct, but no session is issued.
            await db.commit()
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Additional verification is required. Update MyKhaya and sign in again.",
            )
        continuation = await _native_mfa_continuation(
            db,
            request,
            settings,
            user,
            primary="password",
            platform=device_platform(request),
            redemption_verifier_hash=hash_redemption_verifier(body.redemption_verifier),
        )
        await db.commit()
        return continuation
    raw, session, device_raw = await issue_mobile_session(
        db, request, user, settings, fresh_auth_at=datetime.now(UTC)
    )
    user.last_login_at = datetime.now(UTC)
    user.last_activity_at = datetime.now(UTC)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return MobileSessionResponse(
        **user_response(user, session).model_dump(), session_token=raw, device_token=device_raw
    )


@router.post("/mobile/external/start", response_model=NativeExternalStartResponse)
async def mobile_external_start(
    body: NativeExternalStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NativeExternalStartResponse:
    require_secure_transport(request, settings)
    provider = ExternalIdentityProvider(body.provider)
    if (provider, body.platform) not in {
        (ExternalIdentityProvider.apple, "ios"),
        (ExternalIdentityProvider.google, "android"),
    }:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This provider must use the system-browser native flow on this platform.",
        )
    if (provider == ExternalIdentityProvider.apple and not settings.apple_sign_in_enabled) or (
        provider == ExternalIdentityProvider.google and not settings.google_sign_in_enabled
    ):
        _native_external_failure(request, "start", "provider_disabled", provider=provider.value)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This sign-in method is unavailable.")
    native_client_id = (
        settings.apple_native_client_id
        if provider == ExternalIdentityProvider.apple
        else settings.google_native_client_id
    )
    if not native_client_id:
        _native_external_failure(
            request, "start", "native_client_id_not_configured", provider=provider.value
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "This native sign-in method is not configured."
        )
    user_id: str | None = None
    if body.intent == "link":
        auth = await auth_context(request, db, settings)
        require_adult_session(auth)
        if (
            auth.session.fresh_auth_at is None
            or auth.session.fresh_auth_at < datetime.now(UTC) - FRESH_AUTH_WINDOW
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Fresh authentication is required.")
        user_id = str(auth.user.id)
    tx = new_native_external_transaction(
        provider,
        client_id=native_client_id,
        environment=settings.environment,
        intent=body.intent,
        user_id=user_id,
        platform=body.platform,
        redemption_verifier=body.redemption_verifier,
        apple_nonce_hash=provider == ExternalIdentityProvider.apple,
    )
    await store_native_external_transaction(settings, tx)
    return NativeExternalStartResponse(
        transaction_id=tx.transaction_id,
        nonce=tx.client_nonce,
        provider=body.provider,
        client_id=native_client_id,
    )


@router.post("/mobile/external/browser/start", response_model=NativeExternalBrowserStartResponse)
async def mobile_external_browser_start(
    body: NativeExternalBrowserStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NativeExternalBrowserStartResponse:
    require_secure_transport(request, settings)
    provider = ExternalIdentityProvider(body.provider)
    expected_return_uri = _native_browser_return_uri(settings, provider, body.platform)
    if not expected_return_uri or body.return_uri != expected_return_uri:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This native callback is not registered for the environment.",
        )
    user_id: str | None = None
    if body.intent == "link":
        auth = await auth_context(request, db, settings)
        require_adult_session(auth)
        if (
            auth.session.fresh_auth_at is None
            or auth.session.fresh_auth_at < datetime.now(UTC) - FRESH_AUTH_WINDOW
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Fresh authentication is required.")
        user_id = str(auth.user.id)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    transaction_id = secrets.token_urlsafe(32)
    redemption_verifier_hash = hash_redemption_verifier(body.redemption_verifier)
    if body.provider == "apple":
        require_apple_configuration(settings)
        await store_flow_state(
            settings,
            state,
            AppleFlowState(
                nonce=nonce,
                intent=body.intent,
                user_id=user_id,
                return_path=None,
                native_return_uri=body.return_uri,
                native_platform=body.platform,
                native_environment=settings.environment,
                native_transaction_id=transaction_id,
                native_redemption_verifier_hash=redemption_verifier_hash,
            ),
        )
        url = authorization_url(settings, state, nonce)
    else:
        require_google_configuration(settings)
        verifier = new_google_code_verifier()
        await store_google_flow_state(
            settings,
            state,
            GoogleFlowState(
                nonce=nonce,
                code_verifier=verifier,
                intent=body.intent,
                user_id=user_id,
                return_path=None,
                native_return_uri=body.return_uri,
                native_platform=body.platform,
                native_environment=settings.environment,
                native_transaction_id=transaction_id,
                native_redemption_verifier_hash=redemption_verifier_hash,
            ),
        )
        url = google_authorization_url(settings, state, nonce, verifier)
    audit(db, request, "native.external_login_started", target_type="external_identity")
    await db.commit()
    return NativeExternalBrowserStartResponse(
        authorization_url=url,
        transaction_id=transaction_id,
    )


@router.post(
    "/mobile/external/exchange",
    response_model=MobileSessionResponse
    | NativeExternalRecoveryResponse
    | NativeMfaContinuationResponse
    | MessageResponse,
)
async def mobile_external_exchange(
    body: NativeExternalExchangeRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> (
    MobileSessionResponse
    | NativeExternalRecoveryResponse
    | NativeMfaContinuationResponse
    | MessageResponse
):
    require_secure_transport(request, settings)
    tx = await consume_native_external_transaction(settings, body.transaction_id)
    if tx is None:
        # Unknown, expired or already redeemed (replay) — indistinguishable by design.
        _native_external_failure(
            request, "exchange", "transaction_missing_expired_or_replayed", provider=None
        )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid or has expired."
        )
    if tx.environment != settings.environment:
        _native_external_failure(
            request, "exchange", "environment_mismatch", provider=tx.provider.value
        )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid or has expired."
        )
    if not verify_redemption_verifier(body.redemption_verifier, tx.redemption_verifier_hash):
        _native_external_failure(
            request, "exchange", "redemption_verifier_mismatch", provider=tx.provider.value
        )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid or has expired."
        )
    try:
        if tx.provider == ExternalIdentityProvider.apple:
            claims = await verify_identity_token(
                settings,
                body.identity_token,
                tx.nonce,
                tx.client_id,
            )
            subject = str(claims["sub"])
            provider_email = claims.get("email") if isinstance(claims.get("email"), str) else None
            email_verified = (
                claims.get("email_verified") is True or claims.get("email_verified") == "true"
            )
            display_name = str(claims.get("name") or claims.get("given_name") or "Apple user")
        else:
            claims = await verify_google_identity_token(
                settings,
                body.identity_token,
                tx.nonce,
                tx.client_id,
            )
            subject = str(claims["sub"])
            provider_email = str(claims["email"])
            email_verified = True
            display_name = str(claims.get("name") or "Google user")
    except (
        AppleAuthenticationError,
        GoogleAuthenticationError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        _native_external_failure(
            request,
            "exchange",
            "provider_token_rejected",
            provider=tx.provider.value,
            reason=getattr(exc, "reason", None) or type(exc).__name__,
        )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The provider sign-in could not be verified."
        ) from None

    identity = await find_external_identity(db, tx.provider, subject, for_update=True)
    if tx.intent == "link":
        if tx.user_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This linking attempt is invalid.")
        auth = await auth_context(request, db, settings)
        if str(auth.user.id) != tx.user_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "This linking attempt belongs to another session."
            )
        if identity is not None and identity.user_id != auth.user.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This provider identity is already linked."
            )
        try:
            await link_external_identity(
                db,
                request,
                user_id=auth.user.id,
                provider=tx.provider,
                provider_subject=subject,
                provider_email=provider_email,
                provider_email_verified=email_verified,
            )
            await db.commit()
        except (ExternalIdentityOwnershipConflict, IntegrityError):
            await db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This provider identity is already linked."
            ) from None
        return MessageResponse(
            message=f"{tx.provider.value.title()} sign-in has been linked to your account."
        )

    if identity is not None:
        user = await db.get(User, identity.user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This provider identity is unavailable."
            )
        mfa_policy = await _resolve_browser_mfa_policy(db, user.id, settings)
        if mfa_policy.enforcement_enabled and mfa_policy.required:
            continuation = await _native_mfa_continuation(
                db,
                request,
                settings,
                user,
                primary=tx.provider.value,
                platform=tx.platform,
                redemption_verifier_hash=tx.redemption_verifier_hash,
            )
            await db.commit()
            return continuation
        await touch_external_identity(
            db,
            identity=identity,
            provider_email=provider_email,
            provider_email_verified=email_verified,
        )
        raw, session, device_raw = await issue_mobile_session(
            db, request, user, settings, fresh_auth_at=datetime.now(UTC)
        )
        user.last_login_at = datetime.now(UTC)
        user.last_activity_at = datetime.now(UTC)
        await db.commit()
        response.headers["Cache-Control"] = "no-store"
        return MobileSessionResponse(
            **user_response(user, session).model_dump(), session_token=raw, device_token=device_raw
        )

    signup_policy = await evaluate_signup_policy(db, settings)
    can_register = bool(
        provider_email
        and email_verified
        and signup_policy.normal_path
        and not signup_policy.invitation_required
        and signup_policy.domain_allowed(provider_email)
    )
    await store_native_external_pending(
        settings,
        NativeExternalPendingIdentity(
            transaction_id=tx.transaction_id,
            provider=tx.provider,
            subject=subject,
            provider_email=provider_email,
            email_verified=email_verified,
            display_name=display_name,
            can_register=can_register,
            platform=tx.platform,
            redemption_verifier_hash=tx.redemption_verifier_hash,
        ),
    )
    return NativeExternalRecoveryResponse(
        authentication_state="account_choice",
        transaction_id=tx.transaction_id,
        provider=tx.provider.value,
        provider_email=provider_email,
        display_name=display_name,
        can_register=can_register,
    )


@router.post(
    "/mobile/external/redeem",
    response_model=MobileSessionResponse
    | NativeExternalRecoveryResponse
    | NativeMfaContinuationResponse
    | MessageResponse,
)
async def mobile_external_redeem(
    body: NativeExternalLinkRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> (
    MobileSessionResponse
    | NativeExternalRecoveryResponse
    | NativeMfaContinuationResponse
    | MessageResponse
):
    require_secure_transport(request, settings)
    pending = await load_native_external_pending(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    if not verify_redemption_verifier(body.redemption_verifier, pending.redemption_verifier_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid or has expired."
        )
    identity = await find_external_identity(db, pending.provider, pending.subject, for_update=True)
    if pending.intended_user_id is not None:
        auth = await auth_context(request, db, settings)
        require_adult_session(auth)
        if str(auth.user.id) != pending.intended_user_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "This linking attempt belongs to another session."
            )
        if identity is not None and identity.user_id != auth.user.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This provider identity is already linked."
            )
        consumed = await consume_native_external_pending(settings, body.transaction_id)
        if consumed is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
        try:
            await link_external_identity(
                db,
                request,
                user_id=auth.user.id,
                provider=pending.provider,
                provider_subject=pending.subject,
                provider_email=pending.provider_email,
                provider_email_verified=pending.email_verified,
            )
            await db.commit()
        except (ExternalIdentityOwnershipConflict, IntegrityError):
            await db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This provider identity is already linked."
            ) from None
        return MessageResponse(
            message=f"{pending.provider.value.title()} sign-in has been linked to your account."
        )
    if identity is None:
        return NativeExternalRecoveryResponse(
            authentication_state="account_choice",
            transaction_id=pending.transaction_id,
            provider=pending.provider.value,
            provider_email=pending.provider_email,
            display_name=pending.display_name,
            can_register=pending.can_register,
        )
    consumed = await consume_native_external_pending(settings, body.transaction_id)
    if consumed is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    user = await db.get(User, identity.user_id, with_for_update=True)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This provider identity is unavailable.")
    await touch_external_identity(
        db,
        identity=identity,
        provider_email=pending.provider_email,
        provider_email_verified=pending.email_verified,
    )
    policy = await _resolve_browser_mfa_policy(db, user.id, settings)
    if policy.enforcement_enabled and policy.required:
        continuation = await _native_mfa_continuation(
            db,
            request,
            settings,
            user,
            primary=pending.provider.value,
            platform=pending.platform,
            redemption_verifier_hash=pending.redemption_verifier_hash,
        )
        await db.commit()
        return continuation
    raw, session, device_raw = await issue_mobile_session(
        db, request, user, settings, fresh_auth_at=datetime.now(UTC)
    )
    user.last_login_at = datetime.now(UTC)
    user.last_activity_at = datetime.now(UTC)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return MobileSessionResponse(
        **user_response(user, session).model_dump(), session_token=raw, device_token=device_raw
    )


@router.post("/mobile/external/recovery/link", response_model=MessageResponse)
async def mobile_external_recovery_link(
    body: NativeExternalLinkRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    require_secure_transport(request, settings)
    auth = await auth_context(request, db, settings)
    require_adult_session(auth)
    if (
        auth.session.fresh_auth_at is None
        or auth.session.fresh_auth_at < datetime.now(UTC) - FRESH_AUTH_WINDOW
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Fresh authentication is required.")
    pending = await load_native_external_pending(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    if pending.intent == "link":
        if not pending.intended_user_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This linking attempt is invalid.")
        if pending.intended_user_id != str(auth.user.id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "This linking attempt belongs to another session."
            )
    if not verify_redemption_verifier(body.redemption_verifier, pending.redemption_verifier_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid or has expired."
        )
    pending = await consume_native_external_pending(settings, body.transaction_id)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    try:
        await link_external_identity(
            db,
            request,
            user_id=auth.user.id,
            provider=pending.provider,
            provider_subject=pending.subject,
            provider_email=pending.provider_email,
            provider_email_verified=pending.email_verified,
        )
        await db.commit()
    except (ExternalIdentityOwnershipConflict, IntegrityError):
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This provider identity is already linked."
        ) from None
    return MessageResponse(
        message=f"{pending.provider.value.title()} sign-in has been linked to your account."
    )


@router.post(
    "/mobile/external/recovery/register",
    response_model=MobileSessionResponse | NativeMfaContinuationResponse,
)
async def mobile_external_recovery_register(
    body: NativeExternalRegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MobileSessionResponse | NativeMfaContinuationResponse:
    require_secure_transport(request, settings)
    pending = await load_native_external_pending(settings, body.transaction_id)
    if pending is None or not pending.can_register or not pending.provider_email:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This provider identity must be linked to an existing account.",
        )
    if not verify_redemption_verifier(body.redemption_verifier, pending.redemption_verifier_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid or has expired."
        )
    resolved = await validate_signup_acceptances(
        db, [(item.document_key, item.document_version_id) for item in body.legal_acceptances]
    )
    existing = await db.scalar(
        select(User).where(User.email == normalise_email(pending.provider_email)).with_for_update()
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account already uses this email. Sign in and link the provider instead.",
        )
    if (
        await find_external_identity(db, pending.provider, pending.subject, for_update=True)
        is not None
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "This provider identity is already linked.")
    consumed = await consume_native_external_pending(settings, body.transaction_id)
    if consumed is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    assert consumed is not None
    pending = consumed
    assert pending.provider_email is not None
    user = User(
        email=normalise_email(pending.provider_email),
        display_name=body.display_name or pending.display_name,
        email_verified_at=datetime.now(UTC) if pending.email_verified else None,
    )
    db.add(user)
    await db.flush()
    for item in resolved:
        acceptance = LegalAcceptance(
            created_at=datetime.now(UTC),
            record_type=(
                LegalRecordType.user_acceptance
                if item.document.action_verb == LegalActionVerb.accept
                else LegalRecordType.user_acknowledgement
            ),
            document_version_id=item.version.id,
            user_id=user.id,
            context=LegalAcceptanceContext.signup,
            platform=body.platform,
            ip_address=resolve_client_ip(request, settings),
            user_agent=request.headers.get("user-agent", "")[:300] or None,
        )
        db.add(acceptance)
        await queue_acceptance_evidence(
            db, acceptance=acceptance, document=item.document, version=item.version, user=user
        )
    await link_external_identity(
        db,
        request,
        user_id=user.id,
        provider=pending.provider,
        provider_subject=pending.subject,
        provider_email=pending.provider_email,
        provider_email_verified=pending.email_verified,
    )
    policy = await _resolve_browser_mfa_policy(db, user.id, settings)
    if policy.enforcement_enabled and policy.required:
        continuation = await _native_mfa_continuation(
            db,
            request,
            settings,
            user,
            primary=pending.provider.value,
            platform=pending.platform,
            redemption_verifier_hash=pending.redemption_verifier_hash,
        )
        await db.commit()
        return continuation
    raw, session, device_raw = await issue_mobile_session(
        db, request, user, settings, fresh_auth_at=datetime.now(UTC)
    )
    user.last_login_at = datetime.now(UTC)
    user.last_activity_at = datetime.now(UTC)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return MobileSessionResponse(
        **user_response(user, session).model_dump(), session_token=raw, device_token=device_raw
    )


@router.get("/mobile/mfa/options", response_model=MfaOptionsResponse)
async def mobile_mfa_options(
    transaction_id: str,
    redemption_verifier: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MfaOptionsResponse:
    require_secure_transport(request, settings)
    state = await load_native_mfa_transaction(settings, transaction_id)
    if state is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    if not verify_redemption_verifier(redemption_verifier, state.redemption_verifier_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid or has expired."
        )
    user = await db.get(User, uuid.UUID(state.user_id))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid.")
    policy = await _resolve_browser_mfa_policy(db, user.id, settings)
    active = await _active_mfa_methods(db, user.id)
    allowed = {UserMfaMethod(method) for method in policy.allowed_methods}
    methods = _usable_browser_mfa_methods(
        allowed, active, user.email_verified_at is not None, allow_totp_enrolment=True
    )
    return MfaOptionsResponse(
        methods=methods,
        destination=_masked_email(user.email),
        primary_auth_method=state.provider,
        policy="required" if policy.required else "optional",
        policy_source=policy.source,
        enrolment_required=not bool(active & allowed),
        preferred_method=_preferred_browser_mfa_method(user, methods),
    )


@router.post("/mobile/mfa/start", response_model=MfaStartResponse)
async def mobile_mfa_start(
    body: NativeMfaStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MfaStartResponse:
    require_secure_transport(request, settings)
    state = await load_native_mfa_transaction(settings, body.transaction_id)
    if state is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    if not verify_redemption_verifier(body.redemption_verifier, state.redemption_verifier_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid or has expired."
        )
    user = await db.get(User, uuid.UUID(state.user_id))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid.")
    policy = await _resolve_browser_mfa_policy(db, user.id, settings)
    active = await _active_mfa_methods(db, user.id)
    allowed = {UserMfaMethod(method) for method in policy.allowed_methods}
    usable = _usable_browser_mfa_methods(
        allowed, active, user.email_verified_at is not None, allow_totp_enrolment=True
    )
    if body.method not in usable:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That MFA method is not allowed by policy.")
    if body.method == UserMfaMethod.email.value:
        await enforce_rate_limit(request, settings, f"mfa-email-send:{user.id}", 3, 900)
        now = datetime.now(UTC)
        reference_hash = hash_transaction(settings, body.transaction_id)
        await db.execute(
            update(MfaEmailChallenge)
            .where(
                MfaEmailChallenge.user_id == user.id,
                MfaEmailChallenge.transaction_reference_hash == reference_hash,
                MfaEmailChallenge.consumed_at.is_(None),
                MfaEmailChallenge.superseded_at.is_(None),
            )
            .values(superseded_at=now)
        )
        code = new_email_code()
        challenge = MfaEmailChallenge(
            user_id=user.id,
            transaction_reference_hash=reference_hash,
            code_hash=hash_email_code(settings, code),
            expires_at=now + timedelta(seconds=EMAIL_CHALLENGE_TTL_SECONDS),
        )
        db.add(challenge)
        await db.flush()
        subject, message, html = await render_notification_email(
            db, settings, "mfa_email_code", {"code": code}
        )
        await notify(
            db,
            settings=settings,
            recipient_user_id=user.id,
            notification_type="mfa_email_code",
            title=subject,
            body=message,
            html_body=html,
            idempotency_key=f"mfa-email:{challenge.id}",
            is_critical=True,
            sensitive_email_expires_at=challenge.expires_at,
        )
        audit(
            db,
            request,
            "MFA_EMAIL_CHALLENGE_CREATED",
            user.id,
            target_type="mfa_email_challenge",
        )
        await db.commit()
        return MfaStartResponse(
            method="email", destination=_masked_email(user.email), enrolling=False
        )
    await enforce_rate_limit(request, settings, f"mfa-totp-start:{user.id}", 5, 300)
    factor = await db.scalar(
        select(UserMfaMethodRecord).where(
            UserMfaMethodRecord.user_id == user.id,
            UserMfaMethodRecord.method == UserMfaMethod.totp,
        )
    )
    enrolling = factor is None or not factor.enabled or factor.revoked_at is not None
    if enrolling:
        secret = generate_totp_secret()
        if factor is None:
            factor = UserMfaMethodRecord(user_id=user.id, method=UserMfaMethod.totp)
            db.add(factor)
        factor.encrypted_secret = encrypt_user_mfa_totp(settings, secret)
        factor.enabled = False
        factor.revoked_at = None
        await db.commit()
        return MfaStartResponse(
            method="totp",
            provisioning_uri=totp_provisioning_uri(secret, user.email),
            manual_key=secret,
            enrolling=True,
        )
    await db.commit()
    return MfaStartResponse(method="totp", enrolling=False)


@router.post("/mobile/mfa/verify", response_model=MobileSessionResponse)
async def mobile_mfa_verify(
    body: NativeMfaVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MobileSessionResponse:
    """Mirror of /auth/mfa/verify for native pre-authentication.

    The transaction is read (not consumed) while the code is checked, so a
    mistyped code does not discard the primary factor; failed attempts are
    rate limited and audited exactly like the browser flow. The transaction
    is consumed atomically only after a correct code, immediately before the
    session is issued, so a transaction can never yield two sessions."""
    require_secure_transport(request, settings)
    state = await load_native_mfa_transaction(settings, body.transaction_id)
    if state is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    if not verify_redemption_verifier(body.redemption_verifier, state.redemption_verifier_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid or has expired."
        )
    user = await db.get(User, uuid.UUID(state.user_id), with_for_update=True)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt is invalid.")
    policy = await _resolve_browser_mfa_policy(db, user.id, settings)
    if body.method not in policy.allowed_methods:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That MFA method is not allowed by policy.")
    now = datetime.now(UTC)
    if body.method == UserMfaMethod.email.value:
        await enforce_rate_limit(request, settings, f"mfa-email-verify:{user.id}", 10, 900)
        challenge = await db.scalar(
            select(MfaEmailChallenge)
            .where(
                MfaEmailChallenge.user_id == user.id,
                MfaEmailChallenge.transaction_reference_hash
                == hash_transaction(settings, body.transaction_id),
                MfaEmailChallenge.consumed_at.is_(None),
                MfaEmailChallenge.superseded_at.is_(None),
            )
            .order_by(MfaEmailChallenge.created_at.desc())
            .with_for_update()
        )
        if (
            challenge is None
            or challenge.expires_at <= now
            or challenge.attempts >= EMAIL_MAX_ATTEMPTS
        ):
            audit(
                db,
                request,
                "MFA_EMAIL_CHALLENGE_FAILED",
                user.id,
                target_type="mfa_email_challenge",
            )
            audit(db, request, "MFA_LOGIN_FAILED", user.id, target_type="native_mfa")
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That verification code is invalid.")
        challenge.attempts += 1
        if not secrets.compare_digest(challenge.code_hash, hash_email_code(settings, body.code)):
            audit(
                db,
                request,
                "MFA_EMAIL_CHALLENGE_FAILED",
                user.id,
                target_type="mfa_email_challenge",
            )
            audit(db, request, "MFA_LOGIN_FAILED", user.id, target_type="native_mfa")
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That verification code is invalid.")
        challenge.consumed_at = now
        factor = await db.scalar(
            select(UserMfaMethodRecord).where(
                UserMfaMethodRecord.user_id == user.id,
                UserMfaMethodRecord.method == UserMfaMethod.email,
            )
        )
        if factor is None:
            factor = UserMfaMethodRecord(user_id=user.id, method=UserMfaMethod.email)
            db.add(factor)
        factor.enabled = True
        factor.enrolled_at = factor.enrolled_at or now
        factor.last_used_at = now
        audit(
            db,
            request,
            "MFA_EMAIL_CHALLENGE_SUCCEEDED",
            user.id,
            target_type="mfa_email_challenge",
        )
    else:
        await enforce_rate_limit(request, settings, f"mfa-totp-verify:{user.id}", 10, 300)
        factor = await db.scalar(
            select(UserMfaMethodRecord).where(
                UserMfaMethodRecord.user_id == user.id,
                UserMfaMethodRecord.method == UserMfaMethod.totp,
                UserMfaMethodRecord.revoked_at.is_(None),
            )
        )
        if factor is None or not factor.encrypted_secret:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Authenticator setup is required.")
        was_enabled = factor.enabled
        step = matched_totp_step(
            decrypt_user_mfa_totp(settings, factor.encrypted_secret), body.code
        )
        if step is None or not await claim_totp_step(settings, user.id, step):
            audit(db, request, "MFA_TOTP_VERIFICATION_FAILED", user.id, target_type="mfa_method")
            audit(db, request, "MFA_LOGIN_FAILED", user.id, target_type="native_mfa")
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That verification code is invalid.")
        factor.enabled = True
        factor.enrolled_at = factor.enrolled_at or now
        factor.last_used_at = now
        audit(db, request, "MFA_TOTP_VERIFICATION_SUCCEEDED", user.id, target_type="mfa_method")
        if not was_enabled:
            audit(db, request, "MFA_TOTP_ENROLLED", user.id, target_type="mfa_method")

    # Single issuance: only the request that atomically consumes the
    # pre-authentication may mint the session (replay/race protection).
    consumed = await consume_native_mfa_transaction(settings, body.transaction_id)
    if consumed is None or consumed.user_id != str(user.id):
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    raw, session, device_raw = await issue_mobile_session(
        db, request, user, settings, fresh_auth_at=now
    )
    user.last_login_at = now
    user.last_activity_at = now
    audit(db, request, "MFA_LOGIN_SUCCEEDED", user.id, target_type="session")
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return MobileSessionResponse(
        **user_response(user, session).model_dump(), session_token=raw, device_token=device_raw
    )


@router.post(
    "/forgot-password", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED
)
async def forgot(
    body: ForgotRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    # Password-recovery requests are deliberately generic, but still need an
    # abuse limit so an attacker cannot repeatedly trigger reset-email delivery
    # for a known address (or consume mail/worker capacity with arbitrary ones).
    await enforce_rate_limit(request, settings, "forgot-password", 5, 300)
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


def require_cookie_transport(auth: AuthContext) -> None:
    """Counterpart of require_bearer_transport for endpoints that issue browser
    cookies, so a bearer request cannot be converted into a cookie session."""
    if auth.transport != "cookie":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This endpoint requires browser session authentication."
        )


async def _rotated_session_expiry(
    db: AsyncSession, auth: AuthContext, settings: Settings
) -> datetime | None:
    """Expiry for the session that replaces ``auth.session`` on rotation.

    Session expiry never slides, so rotation is the only way a still-valid
    session's lifetime could be extended. While the effective consumer MFA
    policy is enforced and Required, rotation still replaces the credential but
    keeps the original expiry: an adult session (including one issued before
    the policy changed) then ends on schedule, and only a new sign-in that
    satisfies the policy starts a new lifetime. ``None`` means the normal
    fresh lifetime (MFA not required, or a managed-child session).
    """
    if auth.session.kind != SessionKind.adult:
        return None
    policy = await _resolve_browser_mfa_policy(db, auth.user.id, settings)
    if policy.enforcement_enabled and policy.required:
        return auth.session.expires_at
    return None


@router.post("/mobile/logout", status_code=status.HTTP_204_NO_CONTENT)
async def mobile_logout(
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revokes the session and its linked TrustedDevice (the renewable
    credential — see issue_mobile_session); does not touch cookies (there
    are none for a bearer session) and is not subject to CSRF (bearer
    transport). Mirrors the browser /auth/logout's identical
    session-plus-device revocation. The mobile client must still clear its
    SecureStore token locally even if this call fails - see ADR 0010."""
    require_bearer_transport(auth)
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
    # Browser rotation issues cookies; a bearer (native) token must use
    # /auth/mobile/sessions/rotate and is never converted into a cookie session.
    require_cookie_transport(auth)
    expires_at = await _rotated_session_expiry(db, auth, settings)
    auth.session.revoked_at = datetime.now(UTC)
    # kind must be carried over from the session being rotated, never left to
    # issue_session's adult default — otherwise a managed Child session rotating
    # its own session would silently come back as an *adult* session for the same
    # underlying User row, defeating require_adult_session and every other
    # kind-based check from that point on. The trusted device link is carried
    # over too, so device revocation (DELETE /auth/devices/{id}, revoke-others)
    # still reaches the rotated session.
    new_session = await issue_session(
        db,
        response,
        request,
        auth.user,
        settings,
        kind=auth.session.kind,
        trusted_device_id=auth.session.trusted_device_id,
        fresh_auth_at=auth.session.fresh_auth_at,
        expires_at=expires_at,
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
    # While consumer MFA is required, rotation keeps the original expiry (see
    # _rotated_session_expiry) rather than refusing: the credential can still
    # be rotated, but a session can never be extended past its lifetime.
    expires_at = await _rotated_session_expiry(db, auth, settings)
    auth.session.revoked_at = datetime.now(UTC)
    # See the identical comment in rotate_session: kind must carry over from the
    # session being rotated, not silently reset to issue_mobile_session's adult
    # default. existing_device_id reuses the session's current TrustedDevice
    # rather than minting a new one on every rotation — see
    # issue_mobile_session's docstring.
    # existing_device_id set => issue_mobile_session never mints a new device
    # and always returns None for the device token here — see its docstring.
    raw, new_session, device_raw = await issue_mobile_session(
        db,
        request,
        auth.user,
        settings,
        kind=auth.session.kind,
        fresh_auth_at=auth.session.fresh_auth_at,
        existing_device_id=auth.session.trusted_device_id,
        expires_at=expires_at,
        # A legacy device-less session still gains a renewal device here (the
        # established compatibility path), but only when rotation grants a
        # fresh lifetime anyway; never while MFA is required.
        mint_device=expires_at is None,
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
        **user_response(auth.user, new_session).model_dump(),
        session_token=raw,
        device_token=device_raw,
    )


@router.post("/mobile/sessions/renew", response_model=MobileSessionResponse)
async def renew_mobile_session(
    body: MobileDeviceRenewRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MobileSessionResponse:
    """Bearer-transport equivalent of /auth/renew: silently mints a fresh
    session from the long-lived TrustedDevice credential once the previous
    bearer session_token has already expired — deliberately takes no
    AuthContext dependency, the same way /auth/renew reads mk_device instead
    of requiring a currently-valid mk_session. No CSRF check: bearer
    transport is CSRF-exempt throughout (ADR 0010), matching every other
    /mobile/* endpoint.

    The device credential is rotated here too (old token revoked, this
    response's device_token is the only copy of the new one) — the native
    client must persist it before this call is considered complete, exactly
    as it already must for session_token; if the app is killed first, the
    next renewal attempt correctly fails as an unrecognised/already-rotated
    device token, and the user simply signs in again. This is the identical
    single-use-credential trade-off /auth/renew already accepts for the
    browser's mk_device cookie."""
    require_secure_transport(request, settings)
    now = datetime.now(UTC)
    pair = (
        await db.execute(
            select(User, TrustedDevice)
            .join(TrustedDevice, TrustedDevice.user_id == User.id)
            .where(
                TrustedDevice.token_hash
                == hash_secret(body.device_token, settings.secret_key.get_secret_value()),
                TrustedDevice.revoked_at.is_(None),
                TrustedDevice.expires_at > now,
                User.is_active.is_(True),
            )
            .with_for_update()
        )
    ).one_or_none()
    if pair is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to continue.")
    user, device = pair

    # Same rule as browser /auth/renew: a long-lived device credential must
    # not keep minting sessions once the consumer MFA policy is required, or
    # a credential issued before the policy (or from a pre-MFA sign-in)
    # would bypass it indefinitely. The person signs in again and completes
    # MFA through /auth/mobile/login or the native provider exchange.
    if device.kind == SessionKind.adult:
        policy = await _resolve_browser_mfa_policy(db, user.id, settings)
        if policy.enforcement_enabled and policy.required:
            device.revoked_at = now
            audit(
                db,
                request,
                "session.renewal_blocked_mfa_required",
                user.id,
                target_type="trusted_device",
                target_id=device.id,
            )
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to continue.")

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
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to continue.")

    rotated_device_token = new_session_token()
    device.token_hash = hash_secret(rotated_device_token, settings.secret_key.get_secret_value())
    device.last_used_at = now
    device.expires_at = now + timedelta(days=settings.trusted_device_days)
    device.ip_last_seen = resolve_client_ip(request, settings)
    raw, session, _device_raw = await issue_mobile_session(
        db, request, user, settings, kind=device.kind, existing_device_id=device.id
    )
    audit(db, request, "session.renewed", user.id, target_type="session", target_id=session.id)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return MobileSessionResponse(
        **user_response(user, session).model_dump(),
        session_token=raw,
        device_token=rotated_device_token,
    )
