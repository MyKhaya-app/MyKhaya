import asyncio
import json
import secrets
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import structlog
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.mailer import resolve_smtp_config, send_email
from mykhaya.models import (
    ActionToken,
    AdministrativeAuditEvent,
    AdministrativeNote,
    AdminRecoveryCode,
    AdminWebAuthnCredential,
    AuditEvent,
    AuthIdentity,
    BackupRun,
    FeatureFlag,
    FeatureKey,
    FeatureOverride,
    Group,
    Invitation,
    Membership,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationTemplate,
    NotificationTemplateRevision,
    OperationalHeartbeat,
    OutboxEvent,
    PlatformAdministrator,
    PlatformAdministratorInvitation,
    PlatformPushSettings,
    PlatformRole,
    PlatformSession,
    PlatformSessionStatus,
    PlatformSetting,
    PlatformSmtpSettings,
    PublicIncident,
    PushSubscription,
    SecurityEvent,
    Session,
    SmtpConnectionSecurity,
    TokenPurpose,
    User,
    WorkerJobRecord,
)
from mykhaya.module_registry import ReleaseState, feature_modules, module_definition
from mykhaya.notifications.default_templates import (
    DEFAULT_TEMPLATE_VERSION,
    SAMPLE_VARIABLES,
    TEMPLATES,
)
from mykhaya.notifications.engine import notify
from mykhaya.notifications.push import generate_vapid_keypair, resolve_push_config, send_push
from mykhaya.notifications.templates import (
    UnknownTemplateVariable,
    get_override,
    render_notification,
    substitute,
    validate_override_text,
)
from mykhaya.platform_audit import platform_audit
from mykhaya.platform_health import current_platform_health
from mykhaya.platform_mfa import (
    build_authentication_options,
    build_registration_options,
    claim_totp_step,
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    pop_webauthn_challenge,
    store_webauthn_challenge,
    totp_matched_step,
    totp_provisioning_uri,
    verify_authentication,
    verify_registration,
)
from mykhaya.platform_schemas import (
    AdministratorInvitationAccept,
    AdministratorInvitationCreate,
    AdministratorInvitationPreview,
    AdministratorInvitationResponse,
    AdministratorMfaResetRequest,
    AdministratorSecurityResponse,
    AdministratorSecuritySummaryResponse,
    AdministratorUpdate,
    FeatureFlagUpdate,
    IncidentCreate,
    IncidentUpdate,
    InvitationState,
    MfaPolicyResponse,
    MfaPolicyUpdate,
    ModuleUpdate,
    NoteRequest,
    NotificationTemplatePreviewRequest,
    NotificationTemplatePreviewResponse,
    NotificationTemplateResponse,
    NotificationTemplateTestRequest,
    NotificationTemplateUpdate,
    PageResponse,
    PlatformActorResponse,
    PlatformLoginRequest,
    PlatformReauthenticateRequest,
    PushGenerateKeysRequest,
    PushTestRequest,
    PushVapidSettingsUpdate,
    RecoveryCodesResponse,
    RecoveryCodeStatusResponse,
    RecoveryCodeVerifyRequest,
    SensitiveActionRequest,
    SettingUpdate,
    SmtpSettingsUpdate,
    TestEmailRequest,
    TotpCodeRequest,
    TotpDisableRequest,
    TotpSetupResponse,
    WebAuthnAssertionRequest,
    WebAuthnAuthenticationOptionsResponse,
    WebAuthnCredentialRename,
    WebAuthnCredentialResponse,
    WebAuthnRegistrationOptionsResponse,
    WebAuthnRegistrationVerifyRequest,
)
from mykhaya.platform_security import (
    MFA_POLICY_SETTING_KEY,
    PlatformContext,
    administrator_has_mfa_enrolled,
    clear_admin_cookies,
    enforce_admin_host,
    enforce_admin_network,
    new_admin_session,
    platform_context,
    platform_mfa_flow_context,
    require_recent_auth,
    require_roles,
    resolve_admin_mfa_required,
    set_admin_cookies,
)
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.secrets_crypto import SecretDecryptionError, decrypt_secret, encrypt_secret
from mykhaya.security import (
    DUMMY_HASH,
    create_action_token,
    derived_token,
    hash_secret,
    normalise_email,
    password_hash,
    verify_password,
)

router = APIRouter(prefix="/platform", tags=["platform-control-centre"])
log = structlog.get_logger()
ALL_ROLES = tuple(PlatformRole)
OPERATORS = (PlatformRole.owner, PlatformRole.administrator)
SUPPORT = (*OPERATORS, PlatformRole.support)
SECURITY = (PlatformRole.owner, PlatformRole.security)
SETTINGS = (PlatformRole.owner,)
# Arbitrary fixed key for the transaction-scoped advisory lock guarding the
# "at least one active Owner" invariant (PCC-SEC-003) — any constant works,
# it just has to be the same constant everywhere it's taken.
OWNER_MEMBERSHIP_LOCK_KEY = 0x4D794B68_4F776E72  # "MyKh" "Ownr" as hex, arbitrary


def actor_response(admin: PlatformAdministrator, session_status: str) -> PlatformActorResponse:
    return PlatformActorResponse(
        id=admin.id,
        email=admin.email,
        display_name=admin.display_name,
        role=admin.role,
        mfa_enrolled=admin.mfa_enrolled,
        session_status=session_status,
    )


@router.post("/auth/login", response_model=PlatformActorResponse)
async def login(
    body: PlatformLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformActorResponse:
    enforce_admin_host(request, settings)
    source_ip = enforce_admin_network(request, settings)
    await enforce_rate_limit(request, settings, "platform-login", settings.rate_limit_login, 300)
    admin = await db.scalar(
        select(PlatformAdministrator).where(
            PlatformAdministrator.email == normalise_email(str(body.email))
        )
    )
    valid = verify_password(body.password, admin.password_hash if admin else DUMMY_HASH)
    if admin is None or not valid or not admin.is_active:
        db.add(
            SecurityEvent(
                event_type="administrator_login_failed",
                severity="medium",
                outcome="denied",
                administrator_id=admin.id if admin else None,
                source_ip=source_ip,
                request_id=getattr(request.state, "request_id", None),
                safe_detail="Administrator credentials were rejected.",
            )
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The email or password is not correct.")
    mfa_required = await resolve_admin_mfa_required(db, settings)
    has_mfa = await administrator_has_mfa_enrolled(db, admin.id)
    if has_mfa:
        session_status = PlatformSessionStatus.pending_mfa
    elif mfa_required:
        session_status = PlatformSessionStatus.mfa_setup_required
    else:
        session_status = PlatformSessionStatus.full
    session, raw, csrf = new_admin_session(admin, request, settings, source_ip, session_status)
    db.add(session)
    admin.last_login_at = datetime.now(UTC)
    await db.flush()
    context = PlatformContext(admin, session, source_ip)
    platform_audit(
        db,
        request,
        context,
        "administrator.signed_in",
        "administrator",
        admin.id,
        new={"session_status": session_status.value},
    )
    await db.commit()
    set_admin_cookies(response, raw, csrf, settings)
    return actor_response(admin, session_status.value)


@router.get("/auth/me", response_model=PlatformActorResponse)
async def me(
    context: PlatformContext = Depends(platform_mfa_flow_context),
) -> PlatformActorResponse:
    return actor_response(context.administrator, context.session.status.value)


@router.post("/auth/reauthenticate", response_model=PlatformActorResponse)
async def reauthenticate(
    body: PlatformReauthenticateRequest,
    request: Request,
    context: PlatformContext = Depends(platform_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformActorResponse:
    # PCC-SEC-002: this is a password-guessing surface against an already-valid
    # session cookie (it's what proves "recent auth" for every sensitive
    # action), so it needs the same throttling as every other password/code
    # check — plus a bucket scoped to the specific administrator, since an
    # attacker rotating source IPs would otherwise dodge the IP-only bucket
    # while still hammering one identity. Mirrors the two-bucket pattern
    # already used for Managed Child sign-in (mykhaya.routers.auth).
    await enforce_rate_limit(request, settings, "platform-reauth", 8, 300)
    identity_bucket = "platform-reauth-identity:" + hash_secret(
        str(context.administrator.id), settings.secret_key.get_secret_value()
    )
    await enforce_rate_limit(request, settings, identity_bucket, 8, 300)
    if not verify_password(body.password, context.administrator.password_hash):
        db.add(
            SecurityEvent(
                event_type="administrator_reauthentication_failed",
                severity="medium",
                outcome="denied",
                administrator_id=context.administrator.id,
                source_ip=context.source_ip,
                request_id=getattr(request.state, "request_id", None),
                safe_detail="Re-authentication password was rejected.",
            )
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The password is not correct.")
    context.session.authenticated_at = datetime.now(UTC)
    platform_audit(
        db,
        request,
        context,
        "administrator.reauthenticated",
        "administrator",
        context.administrator.id,
    )
    await db.commit()
    return actor_response(context.administrator, context.session.status.value)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    context: PlatformContext = Depends(platform_mfa_flow_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    context.session.revoked_at = datetime.now(UTC)
    platform_audit(db, request, context, "administrator.signed_out", "session", context.session.id)
    await db.commit()
    clear_admin_cookies(response)


@router.get("/auth/sessions")
async def list_sessions(
    context: PlatformContext = Depends(platform_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(PlatformSession)
            .where(
                PlatformSession.administrator_id == context.administrator.id,
                PlatformSession.revoked_at.is_(None),
                PlatformSession.absolute_expires_at > datetime.now(UTC),
            )
            .order_by(PlatformSession.last_seen_at.desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "id": row.id,
            "created_at": row.created_at,
            "last_seen_at": row.last_seen_at,
            "absolute_expires_at": row.absolute_expires_at,
            "user_agent": row.user_agent,
            "source_ip": row.source_ip,
            "current": row.id == context.session.id,
        }
        for row in rows
    ]


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_own_session(
    session_id: uuid.UUID,
    request: Request,
    context: PlatformContext = Depends(platform_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """Revoke a single one of your own sessions (e.g. an old device you no
    longer use) without signing out everywhere — the complement to
    /auth/revoke-all. Scoped to the caller's own administrator_id, same as
    list_sessions, so this can never be used to revoke someone else's
    session."""
    require_recent_auth(context, settings)
    row = await db.scalar(
        select(PlatformSession).where(
            PlatformSession.id == session_id,
            PlatformSession.administrator_id == context.administrator.id,
            PlatformSession.revoked_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That session could not be found.")
    row.revoked_at = datetime.now(UTC)
    platform_audit(db, request, context, "administrator.session_revoked", "session", row.id)
    await db.commit()


@router.post("/auth/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_admin_sessions(
    body: SensitiveActionRequest,
    request: Request,
    response: Response,
    context: PlatformContext = Depends(platform_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    require_recent_auth(context, settings)
    await db.execute(
        update(PlatformSession)
        .where(
            PlatformSession.administrator_id == context.administrator.id,
            PlatformSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    platform_audit(
        db,
        request,
        context,
        "administrator.sessions_revoked",
        "administrator",
        context.administrator.id,
        reason=body.reason,
    )
    await db.commit()
    clear_admin_cookies(response)


def _ensure_session_status(context: PlatformContext, *allowed: PlatformSessionStatus) -> None:
    if context.session.status not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This action is not available right now.")


async def _complete_login_step(
    db: AsyncSession,
    request: Request,
    response: Response,
    context: PlatformContext,
    settings: Settings,
    action: str,
) -> PlatformContext:
    """Shared tail for every 'this proves the second factor' endpoint.

    If the session was still mid-flow (pending_mfa or mfa_setup_required),
    proving the second factor is a genuine privilege boundary — a
    password-verified principal is not the same as a fully authenticated one —
    so this issues a *new* session with a new token and revokes the old one,
    rather than flipping a status flag on the same token in place. That closes
    the session-fixation gap a boolean-only transition would leave open: the
    pre-MFA token never itself becomes a fully privileged token, whether it was
    proving an existing factor or completing first-time mandatory enrollment.

    If the session was already full (an already-authenticated administrator
    voluntarily enrolling an *additional* method from their Security page),
    there is no privilege transition to protect, so the existing session is
    left untouched.
    """
    if context.session.status == PlatformSessionStatus.full:
        platform_audit(db, request, context, action, "administrator", context.administrator.id)
        await db.commit()
        return context

    context.session.revoked_at = datetime.now(UTC)
    new_session, raw, csrf = new_admin_session(
        context.administrator, request, settings, context.source_ip, PlatformSessionStatus.full
    )
    db.add(new_session)
    await db.flush()
    new_context = PlatformContext(context.administrator, new_session, context.source_ip)
    platform_audit(
        db,
        request,
        new_context,
        action,
        "administrator",
        context.administrator.id,
        new={"session_rotated": True},
    )
    await db.commit()
    set_admin_cookies(response, raw, csrf, settings)
    return new_context


@router.post("/auth/mfa/totp/setup", response_model=TotpSetupResponse)
async def setup_totp(
    request: Request,
    context: PlatformContext = Depends(platform_mfa_flow_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TotpSetupResponse:
    """Generates and stores a new (not-yet-active) secret — mykhaya.platform_mfa
    encrypts it the same way the SMTP/VAPID secrets are encrypted at rest.
    totp_enabled stays False until /totp/verify proves the administrator can
    actually generate a valid code with it."""
    _ensure_session_status(
        context, PlatformSessionStatus.full, PlatformSessionStatus.mfa_setup_required
    )
    await enforce_rate_limit(request, settings, "platform-mfa-setup", 10, 300)
    secret = generate_totp_secret()
    context.administrator.totp_secret_encrypted = encrypt_secret(settings, secret)
    context.administrator.totp_enabled = False
    context.administrator.totp_verified_at = None
    await db.commit()
    return TotpSetupResponse(
        secret=secret,
        provisioning_uri=totp_provisioning_uri(secret, context.administrator.email),
    )


@router.post("/auth/mfa/totp/verify", response_model=PlatformActorResponse)
async def verify_totp_setup(
    body: TotpCodeRequest,
    request: Request,
    response: Response,
    context: PlatformContext = Depends(platform_mfa_flow_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformActorResponse:
    _ensure_session_status(
        context, PlatformSessionStatus.full, PlatformSessionStatus.mfa_setup_required
    )
    await enforce_rate_limit(request, settings, "platform-mfa-setup", 10, 300)
    admin = context.administrator
    if not admin.totp_secret_encrypted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Start TOTP setup before verifying a code.")
    try:
        secret = decrypt_secret(settings, admin.totp_secret_encrypted)
    except SecretDecryptionError as cause:
        raise HTTPException(status.HTTP_409_CONFLICT, "Start TOTP setup again.") from cause
    step = totp_matched_step(secret, body.code)
    if step is None or not await claim_totp_step(settings, "totp-setup", admin.id, step):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That code is not correct.")
    was_enrolled = await administrator_has_mfa_enrolled(db, admin.id)
    admin.totp_enabled = True
    admin.totp_verified_at = datetime.now(UTC)
    admin.mfa_enrolled = True
    new_context = await _complete_login_step(
        db,
        request,
        response,
        context,
        settings,
        "administrator.mfa_enrolled" if not was_enrolled else "administrator.totp_enabled",
    )
    return actor_response(admin, new_context.session.status.value)


@router.post("/auth/mfa/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_totp(
    body: TotpDisableRequest,
    request: Request,
    context: PlatformContext = Depends(platform_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    require_recent_auth(context, settings)
    admin = context.administrator
    if not admin.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "TOTP is not enabled.")
    has_webauthn = (
        await db.scalar(
            select(AdminWebAuthnCredential.id).where(
                AdminWebAuthnCredential.administrator_id == admin.id
            )
        )
    ) is not None
    if not has_webauthn and await resolve_admin_mfa_required(db, settings):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is your only second factor and MFA is required. Add another method "
            "before removing this one.",
        )
    admin.totp_enabled = False
    admin.totp_secret_encrypted = None
    admin.totp_verified_at = None
    admin.mfa_enrolled = has_webauthn
    platform_audit(
        db, request, context, "administrator.totp_disabled", "administrator", admin.id,
        reason=body.reason,
    )
    await db.commit()


@router.post("/auth/mfa/totp/login-verify", response_model=PlatformActorResponse)
async def verify_totp_login(
    body: TotpCodeRequest,
    request: Request,
    response: Response,
    context: PlatformContext = Depends(platform_mfa_flow_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformActorResponse:
    _ensure_session_status(context, PlatformSessionStatus.pending_mfa)
    await enforce_rate_limit(request, settings, "platform-mfa-verify", 8, 300)
    admin = context.administrator
    if not admin.totp_enabled or not admin.totp_secret_encrypted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That code is not correct.")
    try:
        secret = decrypt_secret(settings, admin.totp_secret_encrypted)
    except SecretDecryptionError as cause:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That code is not correct.") from cause
    step = totp_matched_step(secret, body.code)
    if step is None or not await claim_totp_step(settings, "totp-login", admin.id, step):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That code is not correct.")
    await _complete_login_step(
        db, request, response, context, settings, "administrator.mfa_verified"
    )
    return actor_response(admin, "full")


@router.post(
    "/auth/mfa/webauthn/register/options", response_model=WebAuthnRegistrationOptionsResponse
)
async def webauthn_register_options(
    request: Request,
    context: PlatformContext = Depends(platform_mfa_flow_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WebAuthnRegistrationOptionsResponse:
    _ensure_session_status(
        context, PlatformSessionStatus.full, PlatformSessionStatus.mfa_setup_required
    )
    await enforce_rate_limit(request, settings, "platform-mfa-setup", 10, 300)
    existing = list(
        await db.scalars(
            select(AdminWebAuthnCredential.credential_id).where(
                AdminWebAuthnCredential.administrator_id == context.administrator.id
            )
        )
    )
    options_json, challenge = build_registration_options(
        settings,
        context.administrator.id,
        context.administrator.email,
        context.administrator.display_name,
        existing,
    )
    await store_webauthn_challenge(settings, "register", context.session.id, challenge)
    return WebAuthnRegistrationOptionsResponse(options_json=options_json)


@router.post("/auth/mfa/webauthn/register/verify", response_model=PlatformActorResponse)
async def webauthn_register_verify(
    body: WebAuthnRegistrationVerifyRequest,
    request: Request,
    response: Response,
    context: PlatformContext = Depends(platform_mfa_flow_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformActorResponse:
    _ensure_session_status(
        context, PlatformSessionStatus.full, PlatformSessionStatus.mfa_setup_required
    )
    await enforce_rate_limit(request, settings, "platform-mfa-setup", 10, 300)
    challenge = await pop_webauthn_challenge(settings, "register", context.session.id)
    if challenge is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This registration attempt has expired.")
    result = verify_registration(settings, body.credential_json, challenge)
    if result is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This passkey could not be registered.")
    admin = context.administrator
    was_enrolled = await administrator_has_mfa_enrolled(db, admin.id)
    db.add(
        AdminWebAuthnCredential(
            administrator_id=admin.id,
            credential_id=result.credential_id,
            public_key=result.public_key,
            sign_count=result.sign_count,
            label=body.label,
        )
    )
    admin.mfa_enrolled = True
    new_context = await _complete_login_step(
        db,
        request,
        response,
        context,
        settings,
        "administrator.mfa_enrolled" if not was_enrolled else "administrator.passkey_registered",
    )
    return actor_response(admin, new_context.session.status.value)


@router.get("/auth/mfa/webauthn/credentials", response_model=list[WebAuthnCredentialResponse])
async def list_webauthn_credentials(
    context: PlatformContext = Depends(platform_context), db: AsyncSession = Depends(get_db)
) -> list[WebAuthnCredentialResponse]:
    rows = list(
        await db.scalars(
            select(AdminWebAuthnCredential)
            .where(AdminWebAuthnCredential.administrator_id == context.administrator.id)
            .order_by(AdminWebAuthnCredential.created_at)
        )
    )
    return [
        WebAuthnCredentialResponse(
            id=row.id, label=row.label, created_at=row.created_at, last_used_at=row.last_used_at
        )
        for row in rows
    ]


@router.patch(
    "/auth/mfa/webauthn/credentials/{credential_id}", response_model=WebAuthnCredentialResponse
)
async def rename_webauthn_credential(
    credential_id: uuid.UUID,
    body: WebAuthnCredentialRename,
    context: PlatformContext = Depends(platform_context),
    db: AsyncSession = Depends(get_db),
) -> WebAuthnCredentialResponse:
    row = await db.scalar(
        select(AdminWebAuthnCredential).where(
            AdminWebAuthnCredential.id == credential_id,
            AdminWebAuthnCredential.administrator_id == context.administrator.id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That passkey could not be found.")
    row.label = body.label
    await db.commit()
    return WebAuthnCredentialResponse(
        id=row.id, label=row.label, created_at=row.created_at, last_used_at=row.last_used_at
    )


@router.delete(
    "/auth/mfa/webauthn/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_webauthn_credential(
    credential_id: uuid.UUID,
    request: Request,
    context: PlatformContext = Depends(platform_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    require_recent_auth(context, settings)
    admin = context.administrator
    row = await db.scalar(
        select(AdminWebAuthnCredential).where(
            AdminWebAuthnCredential.id == credential_id,
            AdminWebAuthnCredential.administrator_id == admin.id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That passkey could not be found.")
    remaining = await db.scalar(
        select(func.count())
        .select_from(AdminWebAuthnCredential)
        .where(
            AdminWebAuthnCredential.administrator_id == admin.id,
            AdminWebAuthnCredential.id != credential_id,
        )
    )
    if (
        not remaining
        and not admin.totp_enabled
        and await resolve_admin_mfa_required(db, settings)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is your only second factor and MFA is required. Add another method "
            "before removing this one.",
        )
    await db.delete(row)
    admin.mfa_enrolled = bool(remaining) or admin.totp_enabled
    platform_audit(
        db, request, context, "administrator.passkey_removed", "administrator", admin.id
    )
    await db.commit()


@router.post(
    "/auth/mfa/webauthn/login/options", response_model=WebAuthnAuthenticationOptionsResponse
)
async def webauthn_login_options(
    request: Request,
    context: PlatformContext = Depends(platform_mfa_flow_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WebAuthnAuthenticationOptionsResponse:
    _ensure_session_status(context, PlatformSessionStatus.pending_mfa)
    await enforce_rate_limit(request, settings, "platform-mfa-verify", 8, 300)
    credential_ids = list(
        await db.scalars(
            select(AdminWebAuthnCredential.credential_id).where(
                AdminWebAuthnCredential.administrator_id == context.administrator.id
            )
        )
    )
    if not credential_ids:
        raise HTTPException(status.HTTP_409_CONFLICT, "No passkey is registered.")
    options_json, challenge = build_authentication_options(settings, credential_ids)
    await store_webauthn_challenge(settings, "login", context.session.id, challenge)
    return WebAuthnAuthenticationOptionsResponse(options_json=options_json)


@router.post("/auth/mfa/webauthn/login/verify", response_model=PlatformActorResponse)
async def webauthn_login_verify(
    body: WebAuthnAssertionRequest,
    request: Request,
    response: Response,
    context: PlatformContext = Depends(platform_mfa_flow_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformActorResponse:
    _ensure_session_status(context, PlatformSessionStatus.pending_mfa)
    await enforce_rate_limit(request, settings, "platform-mfa-verify", 8, 300)
    challenge = await pop_webauthn_challenge(settings, "login", context.session.id)
    if challenge is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in attempt has expired.")
    try:
        parsed = json.loads(body.credential_json)
        raw_id = parsed["rawId"] if "rawId" in parsed else parsed["id"]
    except (json.JSONDecodeError, KeyError, TypeError) as cause:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That passkey is not recognised."
        ) from cause
    credential_id = bytes_to_base64url(base64url_to_bytes(raw_id))
    row = await db.scalar(
        select(AdminWebAuthnCredential).where(
            AdminWebAuthnCredential.administrator_id == context.administrator.id,
            AdminWebAuthnCredential.credential_id == credential_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That passkey is not recognised.")
    new_sign_count = verify_authentication(
        settings, body.credential_json, challenge, row.public_key, row.sign_count
    )
    if new_sign_count is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That passkey could not be verified.")
    row.sign_count = new_sign_count
    row.last_used_at = datetime.now(UTC)
    await _complete_login_step(
        db, request, response, context, settings, "administrator.mfa_verified"
    )
    return actor_response(context.administrator, "full")


@router.post("/auth/mfa/recovery-codes", response_model=RecoveryCodesResponse)
async def generate_recovery_codes_endpoint(
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext = Depends(platform_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RecoveryCodesResponse:
    """Regenerating invalidates every previous code — there is only ever one
    active batch per administrator, matching 'regeneration invalidates all
    previous recovery codes.'"""
    require_recent_auth(context, settings)
    admin = context.administrator
    # The authoritative check, not the cached admin.mfa_enrolled flag — recovery
    # codes are only meaningful as a backup for a real, currently-enrolled
    # factor.
    if not await administrator_has_mfa_enrolled(db, admin.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Set up a passkey or authenticator app before generating recovery codes.",
        )
    await db.execute(
        delete(AdminRecoveryCode).where(AdminRecoveryCode.administrator_id == admin.id)
    )
    codes = generate_recovery_codes()
    for code in codes:
        db.add(
            AdminRecoveryCode(
                administrator_id=admin.id, code_hash=hash_recovery_code(settings, code)
            )
        )
    platform_audit(
        db, request, context, "administrator.recovery_codes_generated", "administrator", admin.id,
        reason=body.reason,
    )
    await db.commit()
    return RecoveryCodesResponse(codes=codes)


@router.get("/auth/mfa/recovery-codes/status", response_model=RecoveryCodeStatusResponse)
async def recovery_code_status(
    context: PlatformContext = Depends(platform_context), db: AsyncSession = Depends(get_db)
) -> RecoveryCodeStatusResponse:
    remaining = await db.scalar(
        select(func.count())
        .select_from(AdminRecoveryCode)
        .where(
            AdminRecoveryCode.administrator_id == context.administrator.id,
            AdminRecoveryCode.used_at.is_(None),
        )
    )
    return RecoveryCodeStatusResponse(remaining=remaining or 0)


@router.post("/auth/mfa/recovery-codes/login-verify", response_model=PlatformActorResponse)
async def verify_recovery_code_login(
    body: RecoveryCodeVerifyRequest,
    request: Request,
    response: Response,
    context: PlatformContext = Depends(platform_mfa_flow_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformActorResponse:
    _ensure_session_status(context, PlatformSessionStatus.pending_mfa)
    await enforce_rate_limit(request, settings, "platform-mfa-verify", 8, 300)
    code_hash = hash_recovery_code(settings, body.code)
    # PCC-SEC-004: a plain SELECT-then-mutate here would let two concurrent
    # requests both read the code as unused before either commits, consuming
    # it twice. A single conditional UPDATE...WHERE used_at IS NULL is
    # atomic — PostgreSQL row-locks the matched row for the duration of the
    # UPDATE, so a second concurrent UPDATE against the same row blocks until
    # the first commits, then re-evaluates the WHERE clause and finds
    # used_at is no longer NULL. Only one request can ever get a matched row
    # back, regardless of worker/process/replica concurrency.
    consumed = await db.execute(
        update(AdminRecoveryCode)
        .where(
            AdminRecoveryCode.administrator_id == context.administrator.id,
            AdminRecoveryCode.code_hash == code_hash,
            AdminRecoveryCode.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
        .returning(AdminRecoveryCode.id)
    )
    if consumed.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That recovery code is not valid.")
    platform_audit(
        db, request, context, "administrator.recovery_code_used", "administrator",
        context.administrator.id,
    )
    await _complete_login_step(
        db, request, response, context, settings, "administrator.mfa_verified"
    )
    return actor_response(context.administrator, "full")


@router.get("/auth/mfa/policy", response_model=MfaPolicyResponse)
async def mfa_policy(
    _: PlatformContext = Depends(require_roles(*OPERATORS, PlatformRole.security)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MfaPolicyResponse:
    return MfaPolicyResponse(
        required=await resolve_admin_mfa_required(db, settings),
        environment_enforced=settings.admin_mfa_required,
    )


@router.put("/auth/mfa/policy", response_model=MfaPolicyResponse)
async def update_mfa_policy(
    body: MfaPolicyUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(PlatformRole.owner)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MfaPolicyResponse:
    require_recent_auth(context, settings)
    if settings.admin_mfa_required:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "MFA is required by this deployment's environment configuration and cannot be "
            "turned off here.",
        )
    row = await db.scalar(
        select(PlatformSetting).where(PlatformSetting.key == MFA_POLICY_SETTING_KEY)
    )
    previous = bool(row.value.get("required")) if row else False
    if row is None:
        row = PlatformSetting(key=MFA_POLICY_SETTING_KEY, value={"required": body.required})
        db.add(row)
    else:
        row.value = {"required": body.required}
    row.updated_by = context.administrator.id
    platform_audit(
        db,
        request,
        context,
        "platform.mfa_policy_changed",
        "platform_setting",
        None,
        reason=body.reason,
        previous={"required": previous},
        new={"required": body.required},
    )
    await db.commit()
    return MfaPolicyResponse(required=body.required, environment_enforced=False)


@router.get("/administrators/{administrator_id}/security")
async def administrator_security(
    administrator_id: uuid.UUID,
    context: PlatformContext = Depends(require_roles(*OPERATORS, PlatformRole.security)),
    db: AsyncSession = Depends(get_db),
) -> AdministratorSecurityResponse | AdministratorSecuritySummaryResponse:
    """PCC-SEC-006: visibility is split from authority-to-modify. Owner sees
    the full detail (including raw session IPs/user-agents) for anyone,
    including other Owners — Owner already has that authority everywhere
    else. Administrator/Security get a reduced summary (no raw session IPs,
    user agents, session IDs, or per-credential labels) and, mirroring the
    MFA-reset fix, no visibility into an Owner target at all — being able to
    *inspect* an Owner's security posture is itself privileged information
    those roles don't need, independent of the fact they can't *act* on it.

    This is deliberately narrower than what Security can see via
    security_events/audit_events (NEW-001, accepted by design — see those
    functions' docstrings): a security-monitoring role legitimately needs
    "which IP touched this event" platform-wide, but not "here is this
    Owner's full session/credential inventory," which is what this endpoint
    guards.

    Viewing your own security page always gets the full shape regardless of
    role — this is the same endpoint the Security tab uses to list your own
    passkey/session IDs so you can rename/remove/revoke them, which needs the
    real data, not a summary, and there is no visibility concern in showing
    your own account its own detail."""
    admin = await db.get(PlatformAdministrator, administrator_id)
    if admin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That administrator could not be found.")
    is_self = administrator_id == context.administrator.id
    is_owner_caller = context.administrator.role == PlatformRole.owner or is_self
    if admin.role == PlatformRole.owner and not is_owner_caller:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a Platform Owner can view another Owner's security detail.",
        )
    remaining = await db.scalar(
        select(func.count())
        .select_from(AdminRecoveryCode)
        .where(AdminRecoveryCode.administrator_id == admin.id, AdminRecoveryCode.used_at.is_(None))
    )
    active_sessions = (
        await db.scalars(
            select(PlatformSession)
            .where(
                PlatformSession.administrator_id == admin.id,
                PlatformSession.revoked_at.is_(None),
                PlatformSession.absolute_expires_at > datetime.now(UTC),
            )
            .order_by(PlatformSession.last_seen_at.desc())
            .limit(50)
        )
    ).all()
    if not is_owner_caller:
        return AdministratorSecuritySummaryResponse(
            id=admin.id,
            email=admin.email,
            display_name=admin.display_name,
            role=admin.role,
            is_active=admin.is_active,
            mfa_enrolled=admin.mfa_enrolled,
            totp_enabled=admin.totp_enabled,
            totp_verified_at=admin.totp_verified_at,
            webauthn_credential_count=await db.scalar(
                select(func.count())
                .select_from(AdminWebAuthnCredential)
                .where(AdminWebAuthnCredential.administrator_id == admin.id)
            )
            or 0,
            recovery_codes_remaining=remaining or 0,
            active_session_count=len(active_sessions),
            last_seen_at=active_sessions[0].last_seen_at if active_sessions else None,
        )
    credentials = list(
        await db.scalars(
            select(AdminWebAuthnCredential)
            .where(AdminWebAuthnCredential.administrator_id == admin.id)
            .order_by(AdminWebAuthnCredential.created_at)
        )
    )
    return AdministratorSecurityResponse(
        id=admin.id,
        email=admin.email,
        display_name=admin.display_name,
        role=admin.role,
        is_active=admin.is_active,
        mfa_enrolled=admin.mfa_enrolled,
        totp_enabled=admin.totp_enabled,
        totp_verified_at=admin.totp_verified_at,
        webauthn_credentials=[
            WebAuthnCredentialResponse(
                id=row.id, label=row.label, created_at=row.created_at, last_used_at=row.last_used_at
            )
            for row in credentials
        ],
        recovery_codes_remaining=remaining or 0,
        sessions=[
            {
                "id": row.id,
                "created_at": row.created_at,
                "last_seen_at": row.last_seen_at,
                "absolute_expires_at": row.absolute_expires_at,
                "user_agent": row.user_agent,
                "source_ip": row.source_ip,
            }
            for row in active_sessions
        ],
    )


@router.patch("/administrators/{administrator_id}", response_model=PlatformActorResponse)
async def update_administrator(
    administrator_id: uuid.UUID,
    body: AdministratorUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(PlatformRole.owner)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformActorResponse:
    require_recent_auth(context, settings)
    # PCC-SEC-003: the final-Owner check below reads a COUNT over rows other
    # than the one this transaction locks with with_for_update() — under plain
    # READ COMMITTED that count is not protected by that row lock, so two
    # concurrent requests each demoting a *different* one of the last two
    # Owners could each see "at least one other Owner" and both commit,
    # leaving zero. A transaction-scoped advisory lock serializes every call
    # to this endpoint globally (released automatically at commit/rollback),
    # which is enough here since Owner-affecting mutations are a rare,
    # low-throughput administrative action, not a hot path.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": OWNER_MEMBERSHIP_LOCK_KEY})
    admin = await db.scalar(
        select(PlatformAdministrator)
        .where(PlatformAdministrator.id == administrator_id)
        .with_for_update()
    )
    if admin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That administrator could not be found.")
    next_active = admin.is_active if body.is_active is None else body.is_active
    next_role = admin.role if body.role is None else body.role
    if (not next_active or next_role != PlatformRole.owner) and admin.role == PlatformRole.owner:
        other_owners = await db.scalar(
            select(func.count())
            .select_from(PlatformAdministrator)
            .where(
                PlatformAdministrator.role == PlatformRole.owner,
                PlatformAdministrator.is_active.is_(True),
                PlatformAdministrator.id != admin.id,
            )
        )
        if not other_owners:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This is the final active Platform Owner. Promote another administrator to "
                "Owner before changing this one.",
            )
    previous = {"is_active": admin.is_active, "role": admin.role.value}
    admin.is_active = next_active
    admin.role = next_role
    if not next_active:
        await db.execute(
            update(PlatformSession)
            .where(
                PlatformSession.administrator_id == admin.id,
                PlatformSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
    platform_audit(
        db,
        request,
        context,
        "administrator.updated",
        "administrator",
        admin.id,
        reason=body.reason,
        previous=previous,
        new={"is_active": next_active, "role": next_role.value},
    )
    await db.commit()
    return actor_response(admin, "full")


@router.post("/administrators/{administrator_id}/mfa/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_administrator_mfa(
    administrator_id: uuid.UUID,
    body: AdministratorMfaResetRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(PlatformRole.owner, PlatformRole.security)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """Clears every second factor for another administrator — e.g. they lost
    their device. They will be sent through MFA enrollment again on their next
    login if the policy still requires it; this never leaves them permanently
    locked out, but it does force re-enrollment rather than silently trusting
    the old (possibly compromised) device again."""
    require_recent_auth(context, settings)
    if administrator_id == context.administrator.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Use your own Security page to manage your own MFA methods.",
        )
    admin = await db.get(PlatformAdministrator, administrator_id)
    if admin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That administrator could not be found.")
    # PCC-SEC-001: require_roles above lets both Owner and Security reach this
    # endpoint (Security legitimately needs to be able to respond to a lost
    # device without waiting on an Owner), but Security must never be able to
    # touch an Owner's MFA — that would let a lower-privileged role strip the
    # highest-privilege account's second factor and force it out of every
    # session. Only an Owner may target an Owner.
    if admin.role == PlatformRole.owner and context.administrator.role != PlatformRole.owner:
        db.add(
            SecurityEvent(
                event_type="administrator_mfa_reset_denied_role_escalation",
                severity="high",
                outcome="denied",
                administrator_id=context.administrator.id,
                source_ip=context.source_ip,
                request_id=getattr(request.state, "request_id", None),
                safe_detail=(
                    f"A {context.administrator.role.value} attempted to reset a Platform "
                    "Owner's MFA and was denied."
                ),
            )
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a Platform Owner can reset another Owner's MFA.",
        )
    admin.totp_enabled = False
    admin.totp_secret_encrypted = None
    admin.totp_verified_at = None
    admin.mfa_enrolled = False
    await db.execute(
        delete(AdminWebAuthnCredential).where(AdminWebAuthnCredential.administrator_id == admin.id)
    )
    await db.execute(
        delete(AdminRecoveryCode).where(AdminRecoveryCode.administrator_id == admin.id)
    )
    await db.execute(
        update(PlatformSession)
        .where(PlatformSession.administrator_id == admin.id, PlatformSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    platform_audit(
        db,
        request,
        context,
        "administrator.mfa_reset",
        "administrator",
        admin.id,
        reason=body.reason,
    )
    await db.commit()


def _invitation_state(row: PlatformAdministratorInvitation) -> InvitationState:
    if row.revoked_at is not None:
        return "revoked"
    if row.accepted_at is not None:
        return "accepted"
    if row.expires_at <= datetime.now(UTC):
        return "expired"
    return "pending"


async def _invitation_response(
    db: AsyncSession, row: PlatformAdministratorInvitation
) -> AdministratorInvitationResponse:
    inviter = await db.get(PlatformAdministrator, row.invited_by) if row.invited_by else None
    return AdministratorInvitationResponse(
        id=row.id,
        email=row.email,
        display_name=row.display_name,
        role=row.role,
        state=_invitation_state(row),
        invited_by_display_name=inviter.display_name if inviter else None,
        created_at=row.created_at,
        expires_at=row.expires_at,
        accepted_at=row.accepted_at,
        revoked_at=row.revoked_at,
    )


INVITATION_EXPIRY = timedelta(hours=24)


async def _send_invitation_email(
    db: AsyncSession,
    settings: Settings,
    row: PlatformAdministratorInvitation,
    inviter_display_name: str,
    raw_token: str,
) -> None:
    subject, message = await render_notification(
        db,
        "platform_administrator_invitation",
        {
            "inviter_display_name": inviter_display_name,
            "role": row.role.value.replace("_", " ").title(),
            "link": f"{settings.admin_url}/accept-invitation?token={raw_token}",
            "expires_at": row.expires_at.isoformat(),
        },
    )
    await notify(
        db,
        settings=settings,
        recipient_email=row.email,
        notification_type="platform_administrator_invitation",
        title=subject,
        body=message,
        idempotency_key=f"platform_administrator_invitation:{row.id}:{row.token_hash}",
    )


@router.post(
    "/administrators/invitations",
    response_model=AdministratorInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_administrator_invitation(
    body: AdministratorInvitationCreate,
    request: Request,
    context: PlatformContext = Depends(require_roles(PlatformRole.owner)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AdministratorInvitationResponse:
    """The only normal path to a new PlatformAdministrator besides the
    one-time bootstrap script — see docs/architecture/administrative-authentication.md.
    Owner-only, fresh-auth-gated, since this can grant platform-wide access
    (including, if role=owner, another Owner)."""
    require_recent_auth(context, settings)
    email = normalise_email(body.email)
    existing_admin = await db.scalar(
        select(PlatformAdministrator.id).where(PlatformAdministrator.email == email)
    )
    if existing_admin is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An administrator with that email already exists."
        )
    active_invitation = await db.scalar(
        select(PlatformAdministratorInvitation.id).where(
            PlatformAdministratorInvitation.email == email,
            PlatformAdministratorInvitation.accepted_at.is_(None),
            PlatformAdministratorInvitation.revoked_at.is_(None),
            PlatformAdministratorInvitation.expires_at > datetime.now(UTC),
        )
    )
    if active_invitation is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An active invitation already exists for that address."
        )
    raw_token = secrets.token_urlsafe(32)
    row = PlatformAdministratorInvitation(
        email=email,
        display_name=body.display_name.strip(),
        role=body.role,
        token_hash=hash_secret(raw_token, settings.secret_key.get_secret_value()),
        invited_by=context.administrator.id,
        expires_at=datetime.now(UTC) + INVITATION_EXPIRY,
    )
    db.add(row)
    await db.flush()
    await _send_invitation_email(db, settings, row, context.administrator.display_name, raw_token)
    platform_audit(
        db,
        request,
        context,
        "platform_administrator_invitation.created",
        "platform_administrator_invitation",
        row.id,
        reason=body.reason,
        new={"email": row.email, "role": row.role.value},
    )
    await db.commit()
    return await _invitation_response(db, row)


@router.get("/administrators/invitations", response_model=list[AdministratorInvitationResponse])
async def list_administrator_invitations(
    _: PlatformContext = Depends(require_roles(PlatformRole.owner)),
    db: AsyncSession = Depends(get_db),
) -> list[AdministratorInvitationResponse]:
    rows = (
        await db.scalars(
            select(PlatformAdministratorInvitation)
            .order_by(PlatformAdministratorInvitation.created_at.desc())
            .limit(200)
        )
    ).all()
    return [await _invitation_response(db, row) for row in rows]


@router.post(
    "/administrators/invitations/{invitation_id}/resend",
    response_model=AdministratorInvitationResponse,
)
async def resend_administrator_invitation(
    invitation_id: uuid.UUID,
    request: Request,
    context: PlatformContext = Depends(require_roles(PlatformRole.owner)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AdministratorInvitationResponse:
    """Reissuing generates a genuinely new random token and overwrites
    token_hash on the same row — the previous raw link, wherever it ended up,
    no longer matches anything and is rejected the same way an unknown token
    would be."""
    require_recent_auth(context, settings)
    row = await db.scalar(
        select(PlatformAdministratorInvitation)
        .where(PlatformAdministratorInvitation.id == invitation_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That invitation could not be found.")
    if row.accepted_at is not None or row.revoked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invitation is no longer active.")
    raw_token = secrets.token_urlsafe(32)
    row.token_hash = hash_secret(raw_token, settings.secret_key.get_secret_value())
    row.expires_at = datetime.now(UTC) + INVITATION_EXPIRY
    await _send_invitation_email(db, settings, row, context.administrator.display_name, raw_token)
    platform_audit(
        db,
        request,
        context,
        "platform_administrator_invitation.reissued",
        "platform_administrator_invitation",
        row.id,
    )
    await db.commit()
    return await _invitation_response(db, row)


@router.post(
    "/administrators/invitations/{invitation_id}/revoke",
    response_model=AdministratorInvitationResponse,
)
async def revoke_administrator_invitation(
    invitation_id: uuid.UUID,
    request: Request,
    context: PlatformContext = Depends(require_roles(PlatformRole.owner)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AdministratorInvitationResponse:
    require_recent_auth(context, settings)
    row = await db.scalar(
        select(PlatformAdministratorInvitation)
        .where(PlatformAdministratorInvitation.id == invitation_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That invitation could not be found.")
    if row.accepted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Accepted invitations cannot be revoked.")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        platform_audit(
            db,
            request,
            context,
            "platform_administrator_invitation.revoked",
            "platform_administrator_invitation",
            row.id,
        )
        await db.commit()
    return await _invitation_response(db, row)


@router.get("/administrators/invitations/preview", response_model=AdministratorInvitationPreview)
async def preview_administrator_invitation(
    request: Request,
    token: str = Query(min_length=30, max_length=500),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AdministratorInvitationPreview:
    """No session exists yet at this point — gated by host/network like every
    admin-subdomain route, plus a rate limit, but not by platform_context."""
    enforce_admin_host(request, settings)
    enforce_admin_network(request, settings)
    await enforce_rate_limit(request, settings, "platform-admin-invitation", 20, 300)
    digest = hash_secret(token, settings.secret_key.get_secret_value())
    row = await db.scalar(
        select(PlatformAdministratorInvitation).where(
            PlatformAdministratorInvitation.token_hash == digest
        )
    )
    if row is None or _invitation_state(row) != "pending":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invitation is invalid or has expired."
        )
    inviter = await db.get(PlatformAdministrator, row.invited_by) if row.invited_by else None
    return AdministratorInvitationPreview(
        email=row.email,
        display_name=row.display_name,
        role=row.role,
        invited_by_display_name=inviter.display_name if inviter else None,
        expires_at=row.expires_at,
    )


@router.post("/administrators/invitations/accept", response_model=PlatformActorResponse)
async def accept_administrator_invitation(
    body: AdministratorInvitationAccept,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlatformActorResponse:
    """Establishes the invited person's own password and creates their
    PlatformAdministrator row — the only place besides the bootstrap script
    that does so. From here the brand-new account goes through exactly the
    same session-issuance and MFA-policy logic as an ordinary /auth/login:
    mfa_setup_required if policy demands it (this administrator has no MFA
    yet, by construction), otherwise full."""
    enforce_admin_host(request, settings)
    source_ip = enforce_admin_network(request, settings)
    await enforce_rate_limit(request, settings, "platform-admin-invitation", 20, 300)
    digest = hash_secret(body.token, settings.secret_key.get_secret_value())
    row = await db.scalar(
        select(PlatformAdministratorInvitation)
        .where(PlatformAdministratorInvitation.token_hash == digest)
        .with_for_update()
    )
    if row is None or _invitation_state(row) != "pending":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This invitation is invalid or has expired."
        )
    existing_admin = await db.scalar(
        select(PlatformAdministrator.id).where(PlatformAdministrator.email == row.email)
    )
    if existing_admin is not None:
        # Someone else already claimed this email between preview and accept.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An administrator with that email already exists."
        )
    admin = PlatformAdministrator(
        email=row.email,
        display_name=row.display_name,
        password_hash=password_hash.hash(body.password),
        role=row.role,
        mfa_enrolled=False,
    )
    db.add(admin)
    try:
        await db.flush()
    except IntegrityError as cause:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An administrator with that email already exists."
        ) from cause
    row.accepted_at = datetime.now(UTC)

    mfa_required = await resolve_admin_mfa_required(db, settings)
    session_status = (
        PlatformSessionStatus.mfa_setup_required if mfa_required else PlatformSessionStatus.full
    )
    session, raw, csrf = new_admin_session(admin, request, settings, source_ip, session_status)
    db.add(session)
    await db.flush()
    context = PlatformContext(admin, session, source_ip)
    platform_audit(
        db,
        request,
        context,
        "platform_administrator_invitation.accepted",
        "platform_administrator_invitation",
        row.id,
    )
    platform_audit(
        db,
        request,
        context,
        "administrator.created",
        "administrator",
        admin.id,
        new={"role": admin.role.value, "invited_via": "invitation"},
    )
    await db.commit()
    set_admin_cookies(response, raw, csrf, settings)
    return actor_response(admin, session_status.value)


@router.get("/overview")
async def overview(
    _: PlatformContext = Depends(require_roles(*ALL_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    last_day = now - timedelta(hours=24)
    user_counts = (
        await db.execute(
            select(
                func.count(User.id),
                func.count(User.id).filter(User.email_verified_at.is_not(None)),
                func.count(User.id).filter(User.email_verified_at.is_(None)),
                func.count(User.id).filter(User.is_active.is_(True)),
                func.count(User.id).filter(User.is_active.is_(False)),
            )
        )
    ).one()
    group_counts = (
        await db.execute(
            select(
                func.count(Group.id),
                func.count(Group.id).filter(Group.is_active.is_(True)),
                func.count(Group.id).filter(Group.is_active.is_(False)),
            )
        )
    ).one()
    failed_logins = (
        await db.scalar(
            select(func.count(SecurityEvent.id)).where(
                SecurityEvent.event_type.in_(["login_failed", "administrator_login_failed"]),
                SecurityEvent.created_at >= last_day,
            )
        )
        or 0
    )
    locked_accounts = (
        await db.scalar(
            select(func.count(AuthIdentity.user_id)).where(AuthIdentity.locked_until > now)
        )
        or 0
    )
    active_sessions = (
        await db.scalar(
            select(func.count(Session.id)).where(
                Session.revoked_at.is_(None), Session.expires_at > now
            )
        )
        or 0
    )
    active_admin_sessions = (
        await db.scalar(
            select(func.count(PlatformSession.id)).where(
                PlatformSession.revoked_at.is_(None),
                PlatformSession.idle_expires_at > now,
                PlatformSession.absolute_expires_at > now,
            )
        )
        or 0
    )
    admin_counts = (
        await db.execute(
            select(
                func.count(PlatformAdministrator.id).filter(
                    PlatformAdministrator.is_active.is_(True)
                ),
                func.count(PlatformAdministrator.id).filter(
                    PlatformAdministrator.is_active.is_(True),
                    PlatformAdministrator.mfa_enrolled.is_(True),
                ),
            )
        )
    ).one()
    current_health = await current_platform_health(db, settings, now=now)
    failed_jobs = current_health.actionable_failed_jobs
    queue_depth: int | None = current_health.queue_depth

    heartbeats = {
        row.service: row for row in (await db.scalars(select(OperationalHeartbeat))).all()
    }
    service_states: list[dict[str, str]] = [{"service": "Database", "state": "Healthy"}]
    actions: list[dict[str, str]] = []
    for service in ("worker", "scheduler"):
        heartbeat = heartbeats.get(service)
        stale = heartbeat is None or (now - heartbeat.observed_at).total_seconds() > 30
        state = "Unavailable" if heartbeat is None else ("Degraded" if stale else "Healthy")
        service_states.append({"service": service.title(), "state": state})
        if stale:
            actions.append(
                {
                    "severity": "critical" if heartbeat is None else "warning",
                    "title": f"{service.title()} heartbeat is missing or stale",
                    "detail": f"Check the {service} service process.",
                    "href": "/health",
                }
            )
    service_states.append(
        {
            "service": "Queue",
            "state": current_health.queue_state.title(),
        }
    )
    if current_health.queue_reason:
        actions.append(
            {
                "severity": "warning",
                "title": "Queue has unprocessed work",
                "detail": current_health.queue_reason,
                "href": "/jobs",
            }
        )
    email_configured = current_health.smtp.configured
    service_states.append(
        {"service": "Email", "state": "Healthy" if email_configured else "Not configured"}
    )
    if failed_jobs:
        actions.append(
            {
                "severity": "warning",
                "title": f"{failed_jobs} background job{'s' if failed_jobs != 1 else ''} failed",
                "detail": "Inspect the safe failure details and retry eligible jobs.",
                "href": "/jobs",
            }
        )
    if not email_configured:
        actions.append(
            {
                "severity": "warning",
                "title": "Email is not configured",
                "detail": "Configure a transport before enabling email-dependent journeys.",
                "href": "/mail",
            }
        )

    metadata_candidates = {
        "version": settings.version,
        "channel": settings.build_channel,
    }
    if settings.environment != "production":
        metadata_candidates.update(
            {
                "commit": settings.commit_sha,
                "build_time": settings.build_time,
                "environment": settings.environment,
            }
        )
    valid_metadata = {
        key: value
        for key, value in metadata_candidates.items()
        if isinstance(value, str) and value.strip() and value.casefold() != "unknown"
    }
    if settings.environment == "production" and "version" not in valid_metadata:
        actions.append(
            {
                "severity": "warning",
                "title": "Deployment version metadata is missing",
                "detail": "Populate the release build arguments in the deployment workflow.",
                "href": "/health",
            }
        )

    admin_activity = (
        await db.scalars(
            select(AdministrativeAuditEvent)
            .where(AdministrativeAuditEvent.outcome == "succeeded")
            .order_by(AdministrativeAuditEvent.created_at.desc())
            .limit(8)
        )
    ).all()
    household_activity = (
        await db.scalars(
            select(AuditEvent)
            .where(AuditEvent.action.in_(["user.registered", "group.created"]))
            .order_by(AuditEvent.created_at.desc())
            .limit(8)
        )
    ).all()
    failed_job_activity = (
        await db.scalars(
            select(WorkerJobRecord)
            .where(WorkerJobRecord.status == "failed")
            .order_by(WorkerJobRecord.finished_at.desc())
            .limit(5)
        )
    ).all()
    recent_activity_rows: list[dict[str, Any]] = [
        {
            "id": str(row.id),
            "action": row.action,
            "target_type": row.target_type,
            "created_at": row.created_at,
        }
        for row in admin_activity
    ]
    recent_activity_rows.extend(
        [
            {
                "id": str(row.id),
                "action": row.action,
                "target_type": row.target_type,
                "created_at": row.created_at,
            }
            for row in household_activity
        ]
    )
    recent_activity_rows.extend(
        [
            {
                "id": str(row.id),
                "action": "email.delivery_failed"
                if row.topic == "notification.email"
                else "job.failed",
                "target_type": "job",
                "created_at": row.finished_at or row.created_at,
            }
            for row in failed_job_activity
        ]
    )
    recent_activity = sorted(
        recent_activity_rows,
        key=lambda item: item["created_at"],
        reverse=True,
    )[:8]

    overall = "Healthy"
    if any(item["state"] in {"Unavailable", "Degraded"} for item in service_states):
        overall = "Degraded"
    elif actions:
        overall = "Warning"
    return {
        "users": dict(
            zip(
                ("total", "verified", "unverified", "active", "suspended"), user_counts, strict=True
            )
        ),
        "homes": dict(zip(("total", "active", "suspended"), group_counts, strict=True)),
        "metrics": {
            "users": user_counts[0],
            "homes": group_counts[0],
            "active_sessions": active_sessions,
            "failed_jobs": failed_jobs,
        },
        "security": {
            "failed_logins_24h": failed_logins,
            "locked_accounts": locked_accounts,
            "active_administrator_sessions": active_admin_sessions,
            "administrators_with_mfa": admin_counts[1],
            "active_administrators": admin_counts[0],
        },
        "operations": {"queue_depth": queue_depth},
        "status": {"state": overall, "checked_at": now},
        "health": service_states,
        "actions": actions,
        "recent_activity": recent_activity,
        "deployment": valid_metadata,
    }


@router.get("/users", response_model=PageResponse)
async def users(
    q: str | None = Query(default=None, max_length=100),
    verified: bool | None = None,
    active: bool | None = None,
    sort: Literal["created_at", "email", "display_name", "last_login_at"] = "created_at",
    direction: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=25, ge=1, le=100),
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> PageResponse:
    filters: list[Any] = []
    if q:
        term = f"%{q.strip()}%"
        filters.append(or_(User.email.ilike(term), User.display_name.ilike(term)))
    if verified is not None:
        filters.append(
            User.email_verified_at.is_not(None) if verified else User.email_verified_at.is_(None)
        )
    if active is not None:
        filters.append(User.is_active.is_(active))
    where = and_(*filters)
    total = await db.scalar(select(func.count(User.id)).where(where)) or 0
    column = getattr(User, sort)
    order = column.asc() if direction == "asc" else column.desc()
    rows = (
        await db.scalars(
            select(User)
            .where(where)
            .order_by(order, User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    ids = [row.id for row in rows]
    home_counts: dict[uuid.UUID, int] = (
        {
            user_id: count
            for user_id, count in (
                await db.execute(
                    select(Membership.user_id, func.count(Membership.id))
                    .where(Membership.user_id.in_(ids), Membership.removed_at.is_(None))
                    .group_by(Membership.user_id)
                )
            ).all()
        }
        if ids
        else {}
    )
    session_counts: dict[uuid.UUID, int] = (
        {
            user_id: count
            for user_id, count in (
                await db.execute(
                    select(Session.user_id, func.count(Session.id))
                    .where(
                        Session.user_id.in_(ids),
                        Session.revoked_at.is_(None),
                        Session.expires_at > datetime.now(UTC),
                    )
                    .group_by(Session.user_id)
                )
            ).all()
        }
        if ids
        else {}
    )
    return PageResponse(
        items=[
            {
                "id": row.id,
                "email": row.email,
                "display_name": row.display_name,
                "verified": row.email_verified_at is not None,
                "active": row.is_active,
                "created_at": row.created_at,
                "last_login_at": row.last_login_at,
                "last_activity_at": row.last_activity_at,
                "home_count": home_counts.get(row.id, 0),
                "session_count": session_counts.get(row.id, 0),
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/users/{user_id}")
async def user_detail(
    user_id: uuid.UUID,
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user could not be found.")
    memberships = (
        await db.execute(
            select(Membership, Group)
            .join(Group, Group.id == Membership.group_id)
            .where(Membership.user_id == user_id, Membership.removed_at.is_(None))
            .limit(100)
        )
    ).all()
    sessions = (
        await db.scalars(
            select(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .order_by(Session.last_seen_at.desc())
            .limit(50)
        )
    ).all()
    notes = (
        await db.scalars(
            select(AdministrativeNote)
            .where(
                AdministrativeNote.target_type == "user", AdministrativeNote.target_id == user_id
            )
            .order_by(AdministrativeNote.created_at.desc())
            .limit(50)
        )
    ).all()
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "verified": user.email_verified_at is not None,
        "active": user.is_active,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "last_activity_at": user.last_activity_at,
        "homes": [
            {"id": group.id, "name": group.name, "role": membership.role}
            for membership, group in memberships
        ],
        "sessions": [
            {
                "id": row.id,
                "created_at": row.created_at,
                "last_seen_at": row.last_seen_at,
                "expires_at": row.expires_at,
                "user_agent": row.user_agent,
            }
            for row in sessions
        ],
        "notes": [
            {
                "id": row.id,
                "body": row.body,
                "created_at": row.created_at,
                "administrator_id": row.administrator_id,
            }
            for row in notes
        ],
    }


async def _user_state_action(
    user_id: uuid.UUID,
    active: bool,
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext,
    db: AsyncSession,
    settings: Settings,
) -> dict[str, str]:
    require_recent_auth(context, settings)
    user = await db.get(User, user_id, with_for_update=True)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user could not be found.")
    previous = user.is_active
    user.is_active = active
    user.suspended_at = None if active else datetime.now(UTC)
    if not active:
        await db.execute(
            update(Session)
            .where(Session.user_id == user.id, Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    platform_audit(
        db,
        request,
        context,
        "user.reactivated" if active else "user.suspended",
        "user",
        user.id,
        reason=body.reason,
        previous={"active": previous},
        new={"active": active},
    )
    await db.commit()
    return {"message": "User reactivated." if active else "User suspended and sessions revoked."}


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: uuid.UUID,
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    return await _user_state_action(user_id, False, body, request, context, db, settings)


@router.post("/users/{user_id}/reactivate")
async def reactivate_user(
    user_id: uuid.UUID,
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    return await _user_state_action(user_id, True, body, request, context, db, settings)


@router.post("/users/{user_id}/revoke-sessions")
async def revoke_user_sessions(
    user_id: uuid.UUID,
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    require_recent_auth(context, settings)
    if await db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user could not be found.")
    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    platform_audit(
        db, request, context, "user.sessions_revoked", "user", user_id, reason=body.reason
    )
    await db.commit()
    return {"message": "All user sessions were revoked."}


async def _enqueue_user_mail(
    user_id: uuid.UUID,
    purpose: TokenPurpose,
    action: str,
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext,
    db: AsyncSession,
    settings: Settings,
) -> dict[str, str]:
    require_recent_auth(context, settings)
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user could not be found.")
    if purpose == TokenPurpose.verify_email and user.email_verified_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That email address is already verified.")
    await db.execute(
        update(ActionToken)
        .where(
            ActionToken.user_id == user.id,
            ActionToken.purpose == purpose,
            ActionToken.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.now(UTC))
    )
    token = await create_action_token(db, user.id, purpose, settings, 30)
    raw = derived_token(token.id, purpose.value, settings.secret_key.get_secret_value())
    if purpose == TokenPurpose.verify_email:
        notification_type = "email_verification"
        link = f"{settings.public_web_url}/verify-email?token={raw}"
    else:
        notification_type = "password_reset"
        link = f"{settings.public_web_url}/reset-password?token={raw}"
    subject, message = await render_notification(db, notification_type, {"link": link})
    await notify(
        db,
        settings=settings,
        recipient_user_id=user.id,
        notification_type=notification_type,
        title=subject,
        body=message,
        idempotency_key=f"{notification_type}:{token.id}",
    )
    platform_audit(db, request, context, action, "user", user.id, reason=body.reason)
    await db.commit()
    return {"message": "The email was queued safely."}


@router.post("/users/{user_id}/resend-verification")
async def resend_verification(
    user_id: uuid.UUID,
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    return await _enqueue_user_mail(
        user_id,
        TokenPurpose.verify_email,
        "user.verification_resent",
        body,
        request,
        context,
        db,
        settings,
    )


@router.post("/users/{user_id}/send-password-reset")
async def send_password_reset(
    user_id: uuid.UUID,
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    return await _enqueue_user_mail(
        user_id,
        TokenPurpose.reset_password,
        "user.password_reset_sent",
        body,
        request,
        context,
        db,
        settings,
    )


@router.post("/users/{user_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_user_note(
    user_id: uuid.UUID,
    body: NoteRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if await db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user could not be found.")
    note = AdministrativeNote(
        administrator_id=context.administrator.id,
        target_type="user",
        target_id=user_id,
        body=body.body.strip(),
    )
    db.add(note)
    await db.flush()
    platform_audit(db, request, context, "user.note_added", "user", user_id)
    await db.commit()
    return {"id": note.id, "created_at": note.created_at}


@router.get("/homes", response_model=PageResponse)
async def homes(
    q: str | None = Query(default=None, max_length=100),
    active: bool | None = None,
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=25, ge=1, le=100),
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> PageResponse:
    filters: list[Any] = []
    if q:
        filters.append(Group.name.ilike(f"%{q.strip()}%"))
    if active is not None:
        filters.append(Group.is_active.is_(active))
    where = and_(*filters)
    total = await db.scalar(select(func.count(Group.id)).where(where)) or 0
    rows = (
        await db.scalars(
            select(Group)
            .where(where)
            .order_by(Group.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items: list[dict[str, Any]] = []
    for group in rows:
        owner = (
            await db.execute(
                select(User)
                .join(Membership, Membership.user_id == User.id)
                .where(
                    Membership.group_id == group.id,
                    Membership.role == "owner",
                    Membership.removed_at.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        member_count = (
            await db.scalar(
                select(func.count(Membership.id)).where(
                    Membership.group_id == group.id, Membership.removed_at.is_(None)
                )
            )
            or 0
        )
        invitation_count = (
            await db.scalar(
                select(func.count(Invitation.id)).where(
                    Invitation.group_id == group.id,
                    Invitation.accepted_at.is_(None),
                    Invitation.revoked_at.is_(None),
                )
            )
            or 0
        )
        items.append(
            {
                "id": group.id,
                "name": group.name,
                "owner": {"id": owner.id, "email": owner.email, "display_name": owner.display_name}
                if owner
                else None,
                "created_at": group.created_at,
                "last_activity_at": group.last_activity_at,
                "member_count": member_count,
                "invitation_count": invitation_count,
                "active": group.is_active,
            }
        )
    return PageResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/homes/{group_id}")
async def home_detail(
    group_id: uuid.UUID,
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Home could not be found.")
    members = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.group_id == group_id, Membership.removed_at.is_(None))
            .limit(200)
        )
    ).all()
    invitations = (
        await db.scalars(
            select(Invitation)
            .where(
                Invitation.group_id == group_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
            .limit(200)
        )
    ).all()
    overrides = (
        await db.scalars(select(FeatureOverride).where(FeatureOverride.group_id == group_id))
    ).all()
    notes = (
        await db.scalars(
            select(AdministrativeNote)
            .where(
                AdministrativeNote.target_type == "home",
                AdministrativeNote.target_id == group_id,
            )
            .order_by(AdministrativeNote.created_at.desc())
            .limit(50)
        )
    ).all()
    return {
        "id": group.id,
        "name": group.name,
        "created_at": group.created_at,
        "last_activity_at": group.last_activity_at,
        "active": group.is_active,
        "members": [
            {
                "user_id": user.id,
                "display_name": user.display_name,
                "email": user.email,
                "role": membership.role,
            }
            for membership, user in members
        ],
        "pending_invitations": [
            {"id": row.id, "email": row.email, "role": row.role, "expires_at": row.expires_at}
            for row in invitations
        ],
        "feature_overrides": [
            {"feature": row.feature_key, "enabled": row.enabled} for row in overrides
        ],
        "notes": [{"id": row.id, "body": row.body, "created_at": row.created_at} for row in notes],
    }


@router.post("/homes/{group_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_home_note(
    group_id: uuid.UUID,
    body: NoteRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if await db.get(Group, group_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Home could not be found.")
    note = AdministrativeNote(
        administrator_id=context.administrator.id,
        target_type="home",
        target_id=group_id,
        body=body.body.strip(),
    )
    db.add(note)
    await db.flush()
    platform_audit(db, request, context, "home.note_added", "home", group_id)
    await db.commit()
    return {"id": note.id, "created_at": note.created_at}


@router.put("/homes/{group_id}/feature-flags/{key}")
async def update_home_feature_flag(
    group_id: uuid.UUID,
    key: FeatureKey,
    body: FeatureFlagUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    if module_definition(key.value).release_state == ReleaseState.hidden:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if await db.get(Group, group_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Home could not be found.")
    row = await db.scalar(
        select(FeatureOverride)
        .where(FeatureOverride.group_id == group_id, FeatureOverride.feature_key == key)
        .with_for_update()
    )
    previous = row.enabled if row else None
    if row is None:
        row = FeatureOverride(
            feature_key=key,
            group_id=group_id,
            enabled=body.enabled,
            updated_by=context.administrator.id,
        )
        db.add(row)
    else:
        row.enabled = body.enabled
        row.updated_by = context.administrator.id
    platform_audit(
        db,
        request,
        context,
        "feature_flag.home_override_updated",
        "home",
        group_id,
        reason=body.reason,
        previous={"key": key.value, "enabled": previous},
        new={"key": key.value, "enabled": body.enabled},
    )
    await db.commit()
    return {"key": key, "home_id": group_id, "enabled": body.enabled}


@router.post("/homes/{group_id}/{action}")
async def home_state(
    group_id: uuid.UUID,
    action: Literal["suspend", "reactivate"],
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    require_recent_auth(context, settings)
    group = await db.get(Group, group_id, with_for_update=True)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Home could not be found.")
    previous = group.is_active
    group.is_active = action == "reactivate"
    group.suspended_at = None if group.is_active else datetime.now(UTC)
    platform_audit(
        db,
        request,
        context,
        f"home.{action}d" if action == "suspend" else "home.reactivated",
        "home",
        group.id,
        reason=body.reason,
        previous={"active": previous},
        new={"active": group.is_active},
    )
    await db.commit()
    return {"message": f"Home {action}d." if action == "suspend" else "Home reactivated."}


def _probe_file_storage(storage_dir: Path) -> shutil._ntuple_diskusage:
    """Blocking on purpose — run via asyncio.to_thread. A real write/read/delete
    probe (not just checking the path exists) confirms the volume is actually
    usable, not just present. Isolated to a single small dedicated file, never a
    destructive operation on anything an avatar upload might have written."""
    storage_dir.mkdir(parents=True, exist_ok=True)
    probe_path = storage_dir / f".health-check-{uuid.uuid4().hex}"
    probe_path.write_bytes(b"ok")
    probe_path.read_bytes()
    probe_path.unlink()
    return shutil.disk_usage(storage_dir)


@router.get("/health")
async def internal_health(
    _: PlatformContext = Depends(require_roles(*ALL_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    checked = datetime.now(UTC)
    services: list[dict[str, Any]] = []

    def observation(
        service: str,
        state: str,
        explanation: str,
        *,
        last_success: datetime | None = None,
        last_failure: datetime | None = None,
        action: str | None = None,
    ) -> None:
        services.append(
            {
                "service": service,
                "state": state,
                "explanation": explanation,
                "last_checked": checked,
                "last_success": last_success,
                "last_failure": last_failure,
                "recommended_action": action,
            }
        )

    observation(
        "Application process",
        "Healthy",
        "The authenticated diagnostics request completed.",
        last_success=checked,
    )
    try:
        await db.execute(text("SELECT 1"))
        observation(
            "Database",
            "Healthy",
            "Database connectivity check succeeded.",
            last_success=checked,
        )
    except Exception as exc:
        await log.awarning(
            "platform_health_check_failed", service="database", error=type(exc).__name__
        )
        observation(
            "Database",
            "Unavailable",
            "Database connectivity check failed.",
            last_failure=checked,
            action="Check the database service and deployment credentials.",
        )

    try:
        revision = await db.scalar(text("SELECT version_num FROM alembic_version"))
        config_path = next(
            (
                candidate
                for candidate in (Path.cwd() / "alembic.ini", Path.cwd() / "apps/api/alembic.ini")
                if candidate.exists()
            ),
            None,
        )
        expected_heads: set[str] | None = None
        if config_path:
            alembic_config = AlembicConfig(str(config_path))
            alembic_config.set_main_option(
                "script_location", str(config_path.parent / "migrations")
            )
            expected_heads = set(ScriptDirectory.from_config(alembic_config).get_heads())
        migration_current = bool(revision and expected_heads and revision in expected_heads)
        observation(
            "Migration state",
            "Healthy"
            if migration_current
            else ("Not configured" if expected_heads is None else "Warning"),
            "The database schema is at the current migration head."
            if migration_current
            else (
                "Migration scripts are not available in this diagnostics runtime."
                if expected_heads is None
                else "The database schema is not at the current migration head."
            ),
            last_success=checked if migration_current else None,
            action=None
            if migration_current
            else (
                "Include migration scripts in the runtime diagnostics image."
                if expected_heads is None
                else "Run the deployment migration step before serving traffic."
            ),
        )
    except Exception as exc:
        await log.awarning(
            "platform_health_check_failed", service="migrations", error=type(exc).__name__
        )
        observation(
            "Migration state",
            "Unavailable",
            "The applied database migration revision could not be read.",
            last_failure=checked,
            action="Verify the Alembic migration table and deployment migration step.",
        )

    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.ping()
        queued = int(await redis.llen("mykhaya:jobs"))
        observation(
            "Cache",
            "Healthy",
            "Redis responded to the live connectivity check.",
            last_success=checked,
        )
        observation(
            "Queue",
            "Healthy",
            f"The live queue contains {queued} job{'s' if queued != 1 else ''}.",
            last_success=checked,
        )
    except Exception as exc:
        await log.awarning(
            "platform_health_check_failed", service="redis", error=type(exc).__name__
        )
        observation(
            "Cache",
            "Unavailable",
            "Redis did not respond to the live connectivity check.",
            last_failure=checked,
            action="Check the Redis service and network path.",
        )
        observation(
            "Queue",
            "Unavailable",
            "Live queue depth could not be retrieved.",
            last_failure=checked,
            action="Restore Redis connectivity before retrying jobs.",
        )
    finally:
        await redis.aclose()

    heartbeats = (await db.scalars(select(OperationalHeartbeat))).all()
    by_service = {row.service: row for row in heartbeats}
    for name in ("worker", "scheduler"):
        row = by_service.get(name)
        stale = row is None or (checked - row.observed_at).total_seconds() > 30
        observation(
            name.title(),
            "Unavailable" if row is None else ("Degraded" if stale else "Healthy"),
            "No heartbeat has been recorded."
            if row is None
            else ("The last heartbeat is stale." if stale else "The heartbeat is current."),
            last_success=row.last_success_at if row else None,
            action=f"Check the {name} service process." if stale else None,
        )

    # NotificationDelivery (not WorkerJobRecord) is authoritative for channel
    # health — it's the per-recipient outcome record already used by the
    # Communications Timeline/Diagnostics pages, so this card can never disagree
    # with those. WorkerJobRecord remains the source for the Jobs page, which is
    # about job execution, not delivery outcome.
    last_email_success = await db.scalar(
        select(func.max(NotificationDelivery.attempted_at)).where(
            NotificationDelivery.channel == NotificationChannel.email,
            NotificationDelivery.status == NotificationDeliveryStatus.sent,
        )
    )
    last_email_failure = await db.scalar(
        select(func.max(NotificationDelivery.attempted_at)).where(
            NotificationDelivery.channel == NotificationChannel.email,
            NotificationDelivery.status == NotificationDeliveryStatus.failed,
        )
    )
    recent_email_failures = (
        await db.scalar(
            select(func.count())
            .select_from(NotificationDelivery)
            .where(
                NotificationDelivery.channel == NotificationChannel.email,
                NotificationDelivery.status == NotificationDeliveryStatus.failed,
                NotificationDelivery.attempted_at > checked - timedelta(hours=24),
            )
        )
        or 0
    )
    email_config = await resolve_smtp_config(settings, db)
    email_configured = email_config.configured
    observation(
        "Email",
        "Not configured"
        if not email_configured
        else ("Degraded" if recent_email_failures > 0 else "Healthy"),
        "No email transport is configured."
        if not email_configured
        else (
            f"{recent_email_failures} delivery failure"
            f"{'s' if recent_email_failures != 1 else ''} in the last 24 hours. See the Email page."
            if recent_email_failures
            else "The email transport is configured and recent deliveries have succeeded."
        ),
        last_success=last_email_success,
        last_failure=last_email_failure,
        action=None if email_configured else "Configure the deployment email transport.",
    )

    push_config = await resolve_push_config(settings, db)
    active_subscriptions = (
        await db.scalar(
            select(func.count())
            .select_from(PushSubscription)
            .where(PushSubscription.disabled_at.is_(None))
        )
        or 0
    )
    last_push_success = await db.scalar(
        select(func.max(NotificationDelivery.attempted_at)).where(
            NotificationDelivery.channel == NotificationChannel.push,
            NotificationDelivery.status == NotificationDeliveryStatus.sent,
        )
    )
    last_push_failure = await db.scalar(
        select(func.max(NotificationDelivery.attempted_at)).where(
            NotificationDelivery.channel == NotificationChannel.push,
            NotificationDelivery.status == NotificationDeliveryStatus.failed,
        )
    )
    recent_push_failures = (
        await db.scalar(
            select(func.count())
            .select_from(NotificationDelivery)
            .where(
                NotificationDelivery.channel == NotificationChannel.push,
                NotificationDelivery.status == NotificationDeliveryStatus.failed,
                NotificationDelivery.attempted_at > checked - timedelta(hours=24),
            )
        )
        or 0
    )
    observation(
        "Push notifications",
        "Not configured"
        if not push_config.configured
        else ("Degraded" if recent_push_failures > 0 else "Healthy"),
        "No push provider is configured."
        if not push_config.configured
        else (
            f"{active_subscriptions} active subscription"
            f"{'s' if active_subscriptions != 1 else ''}, "
            f"{recent_push_failures} failure{'s' if recent_push_failures != 1 else ''} "
            "in the last 24 hours."
        ),
        last_success=last_push_success,
        last_failure=last_push_failure,
        action=None if push_config.configured else "Configure a push provider on the Push page.",
    )

    storage_dir = Path(settings.avatar_storage_dir)
    try:
        usage = await asyncio.to_thread(_probe_file_storage, storage_dir)
        free_ratio = usage.free / usage.total if usage.total else 0
        low_space = free_ratio < 0.1
        observation(
            "File storage",
            "Degraded" if low_space else "Healthy",
            f"{usage.free // (1024 * 1024)} MB free of {usage.total // (1024 * 1024)} MB "
            f"({free_ratio:.0%}) at {storage_dir}. A write/read/delete probe succeeded.",
            last_success=checked,
            action="The storage volume is running low on free space." if low_space else None,
        )
    except OSError as exc:
        await log.awarning(
            "platform_health_check_failed", service="file_storage", error=type(exc).__name__
        )
        observation(
            "File storage",
            "Unavailable",
            "The storage path could not be written to, read from, or deleted.",
            last_failure=checked,
            action="Check the storage volume mount and permissions.",
        )

    latest_backup = await db.scalar(
        select(BackupRun).order_by(BackupRun.started_at.desc()).limit(1)
    )
    if latest_backup is None:
        observation(
            "Backup service",
            "Not configured",
            "No backup run has ever been recorded.",
            action="Schedule infrastructure/scripts/backup.sh and confirm it reports completion.",
        )
    else:
        age_hours = (checked - latest_backup.started_at).total_seconds() / 3600
        overdue = age_hours > settings.backup_expected_interval_hours
        if not latest_backup.succeeded:
            observation(
                "Backup service",
                "Unavailable",
                f"The most recent backup attempt failed. {latest_backup.detail or ''}".strip(),
                last_failure=latest_backup.started_at,
                action="Check the backup job logs.",
            )
        else:
            size_note = (
                f", {latest_backup.size_bytes // (1024 * 1024)} MB"
                if latest_backup.size_bytes
                else ""
            )
            observation(
                "Backup service",
                "Degraded" if overdue else "Healthy",
                f"Last successful backup {age_hours:.1f}h ago{size_note}."
                + (" This is overdue." if overdue else ""),
                last_success=latest_backup.completed_at or latest_backup.started_at,
                action=(
                    "The latest backup is overdue — check the backup schedule."
                    if overdue
                    else None
                ),
            )

    # Deliberately not a live check. Email (SMTP) and Push (VAPID) already own
    # their own health cards, computed from real delivery data above — probing
    # SMTP reachability again here would just be Email's health reported a
    # second time under a different name, and could disagree with it (port
    # reachable but deliveries failing, or vice versa). MyKhaya has no other
    # externally-integrated service today (no object storage, no OIDC
    # provider). This card exists for when one is added, not to manufacture
    # activity out of the two that already have dedicated cards.
    observation(
        "External dependencies",
        "Not applicable",
        "MyKhaya has no separate external service integrations beyond Email and Push, "
        "which have their own health cards above.",
    )
    observation(
        "Public status service",
        "Healthy" if settings.status_public_enabled else "Not configured",
        "The public status route is enabled in this application process."
        if settings.status_public_enabled
        else "The public status route is disabled.",
        last_success=checked if settings.status_public_enabled else None,
        action=None
        if settings.status_public_enabled
        else "Enable the public status service if required.",
    )
    overall = "Healthy"
    if any(row["state"] == "Unavailable" for row in services):
        overall = "Degraded"
    elif any(row["state"] == "Degraded" for row in services):
        overall = "Warning"
    return {"overall": overall, "services": services, "checked_at": checked}


@router.get("/jobs")
async def jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    _: PlatformContext = Depends(require_roles(*ALL_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    total = await db.scalar(select(func.count(WorkerJobRecord.id))) or 0
    state_counts = (
        await db.execute(
            select(WorkerJobRecord.status, func.count(WorkerJobRecord.id)).group_by(
                WorkerJobRecord.status
            )
        )
    ).all()
    pending = (
        await db.scalar(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.processed_at.is_(None), OutboxEvent.available_at <= now
            )
        )
        or 0
    )
    scheduled = (
        await db.scalar(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.processed_at.is_(None), OutboxEvent.available_at > now
            )
        )
        or 0
    )
    redis_depth: int | None = None
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        redis_depth = int(await redis.llen("mykhaya:jobs"))
    except Exception as exc:
        await log.awarning(
            "platform_metric_unavailable", metric="jobs_queue", error=type(exc).__name__
        )
    finally:
        await redis.aclose()
    worker_heartbeat = await db.get(OperationalHeartbeat, "worker")
    scheduler_heartbeat = await db.get(OperationalHeartbeat, "scheduler")
    next_scheduled_execution = await db.scalar(
        select(func.min(OutboxEvent.available_at)).where(OutboxEvent.processed_at.is_(None))
    )
    last_success = await db.scalar(
        select(func.max(WorkerJobRecord.finished_at)).where(WorkerJobRecord.status == "completed")
    )
    rows = (
        await db.scalars(
            select(WorkerJobRecord)
            .order_by(WorkerJobRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    outbox_ids = [row.outbox_event_id for row in rows if row.outbox_event_id]
    outbox_rows = {
        event.id: event
        for event in (
            await db.scalars(select(OutboxEvent).where(OutboxEvent.id.in_(outbox_ids)))
        ).all()
    }
    return {
        "summary": {
            **{str(state): count for state, count in state_counts},
            "queued": None if redis_depth is None else redis_depth + pending,
            "scheduled": scheduled,
            "worker_heartbeat": worker_heartbeat.observed_at if worker_heartbeat else None,
            "scheduler_heartbeat": scheduler_heartbeat.observed_at if scheduler_heartbeat else None,
            "next_scheduled_execution": next_scheduled_execution,
            "last_successful_execution": last_success,
        },
        "items": [
            {
                "id": row.id,
                "job_type": row.topic,
                "state": row.status,
                "created_at": row.created_at,
                "started_at": row.started_at,
                "completed_at": row.finished_at,
                "duration_ms": (
                    int((row.finished_at - row.started_at).total_seconds() * 1000)
                    if row.finished_at and row.started_at
                    else None
                ),
                "retry_count": row.attempts,
                "safe_failure_message": row.error,
                "occurrence_id": outbox.dedupe_key if outbox else None,
                "scheduled_for": outbox.payload.get("date") if outbox else None,
            }
            for row in rows
            for outbox in [outbox_rows.get(row.outbox_event_id) if row.outbox_event_id else None]
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: uuid.UUID,
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    job = await db.get(WorkerJobRecord, job_id, with_for_update=True)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That job could not be found.")
    if job.status != "failed" or job.outbox_event_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed queued jobs can be retried.")
    event = await db.get(OutboxEvent, job.outbox_event_id)
    if event is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The source event is no longer available.")
    job.status = "queued"
    job.finished_at = None
    job.error = None
    platform_audit(
        db,
        request,
        context,
        "job.retry_requested",
        "job",
        job.id,
        reason=body.reason,
        previous={"status": "failed"},
        new={"status": "queued"},
    )
    await db.commit()
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.rpush("mykhaya:jobs", json.dumps({"event_id": str(event.id)}))
    except Exception as exc:
        job.status = "failed"
        job.error = "QueueUnavailable"
        await db.commit()
        await log.awarning("job_retry_enqueue_failed", job_id=str(job.id), error=type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The queue is unavailable."
        ) from exc
    finally:
        await redis.aclose()
    return {"id": job.id, "state": "queued"}


SETTING_RULES: dict[str, tuple[type[Any], str]] = {
    "platform_display_name": (str, "safe_live"),
    "support_contact_address": (str, "safe_live"),
    "registration_enabled": (bool, "sensitive_live"),
    "invite_only_mode": (bool, "sensitive_live"),
    "email_verification_required": (bool, "sensitive_live"),
    "allowed_registration_domains": (list, "sensitive_live"),
    "maximum_homes_per_user": (int, "safe_live"),
    "maximum_members_per_home": (int, "safe_live"),
    "invitation_expiry_days": (int, "safe_live"),
    "maintenance_mode": (bool, "sensitive_live"),
    "default_locale": (str, "safe_live"),
    "default_timezone": (str, "safe_live"),
    "privacy_notice_version": (str, "safe_live"),
    "terms_version": (str, "safe_live"),
}


@router.get("/settings")
async def settings_list(
    _: PlatformContext = Depends(require_roles(*ALL_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    rows = {row.key: row for row in (await db.scalars(select(PlatformSetting))).all()}
    return {
        "settings": [
            {
                "key": key,
                "value": rows[key].value.get("value") if key in rows else None,
                "category": category,
                "editable": True,
            }
            for key, (_, category) in SETTING_RULES.items()
        ],
        "environment": [
            {
                "key": "public_url",
                "value": settings.public_web_url,
                "category": "environment_controlled",
                "editable": False,
            },
            {
                "key": "admin_url",
                "value": settings.admin_url,
                "category": "environment_controlled",
                "editable": False,
            },
            {
                "key": "status_url",
                "value": settings.status_url,
                "category": "environment_controlled",
                "editable": False,
            },
        ],
    }


@router.put("/settings/{key}")
async def update_setting(
    key: str,
    body: SettingUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*SETTINGS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    rule = SETTING_RULES.get(key)
    if (
        rule is None
        or not isinstance(body.value, rule[0])
        or (rule[0] is int and isinstance(body.value, bool))
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That setting or value is not valid."
        )
    if isinstance(body.value, int) and not 1 <= body.value <= 10_000:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That numeric value is outside the allowed range."
        )
    row = await db.scalar(
        select(PlatformSetting).where(PlatformSetting.key == key).with_for_update()
    )
    previous = row.value.get("value") if row else None
    if row is None:
        row = PlatformSetting(
            key=key, value={"value": body.value}, updated_by=context.administrator.id
        )
        db.add(row)
    else:
        row.value = {"value": body.value}
        row.updated_by = context.administrator.id
    platform_audit(
        db,
        request,
        context,
        "setting.updated",
        "setting",
        reason=body.reason,
        previous={key: previous},
        new={key: body.value},
    )
    await db.commit()
    return {"key": key, "value": body.value, "category": rule[1]}


@router.get("/modules")
async def modules(
    _: PlatformContext = Depends(require_roles(*ALL_ROLES)), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = {row.key: row for row in (await db.scalars(select(FeatureFlag))).all()}
    return [
        {
            "key": FeatureKey(module.id),
            "name": module.name,
            "description": module.description,
            "category": module.category,
            "dependencies": module.dependencies,
            "enabled": rows[FeatureKey(module.id)].enabled
            if FeatureKey(module.id) in rows
            else False,
            "release_state": (
                rows[FeatureKey(module.id)].release_state or module.release_state.value
                if FeatureKey(module.id) in rows
                else module.release_state.value
            ),
        }
        for module in feature_modules()
    ]


@router.put("/modules/{key}")
async def update_module(
    key: FeatureKey,
    body: ModuleUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == key).with_for_update())
    previous = row.enabled if row else False
    previous_state = (
        row.release_state
        if row and row.release_state
        else module_definition(key.value).release_state.value
    )
    if row is None:
        row = FeatureFlag(
            key=key,
            enabled=body.enabled,
            release_state=body.release_state.value,
            updated_by=context.administrator.id,
        )
        db.add(row)
    else:
        row.enabled = body.enabled
        row.release_state = body.release_state.value
        row.updated_by = context.administrator.id
    platform_audit(
        db,
        request,
        context,
        "module.updated",
        "module",
        reason=body.reason,
        previous={"key": key.value, "enabled": previous, "release_state": previous_state},
        new={
            "key": key.value,
            "enabled": body.enabled,
            "release_state": body.release_state.value,
        },
    )
    await db.commit()
    return {"key": key, "enabled": body.enabled, "release_state": body.release_state}


@router.get("/security", response_model=PageResponse)
async def security_events(
    event_type: str | None = Query(default=None, max_length=80),
    severity: str | None = Query(default=None, max_length=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    _: PlatformContext = Depends(require_roles(*SECURITY)),
    db: AsyncSession = Depends(get_db),
) -> PageResponse:
    """Includes `source_ip` for every event, Owners included — accepted by
    design (NEW-001 from the Platform Control Centre security re-review):
    the Security role's job is monitoring security activity platform-wide,
    which requires seeing where that activity came from regardless of whose
    account it belongs to. This is deliberately a narrower grant than
    `GET /administrators/{id}/security` (PCC-SEC-006), which withholds an
    Owner's session/credential detail from Security entirely — visibility
    into "this IP touched this event" here is not the same as visibility
    into "here is this Owner's live session inventory" there, and it does
    not carry any authority to act on an Owner's account (MFA reset stays
    Owner-only for Owner targets — PCC-SEC-001; individual session revoke
    stays self-only regardless of role — see revoke_own_session). See
    test_platform_security_remediation.py's
    test_security_role_can_see_owner_related_audit_events_but_not_full_detail_or_control
    for the regression test proving this exact boundary."""
    filters = []
    if event_type:
        filters.append(SecurityEvent.event_type == event_type)
    if severity:
        filters.append(SecurityEvent.severity == severity)
    where = and_(*filters)
    total = await db.scalar(select(func.count(SecurityEvent.id)).where(where)) or 0
    rows = (
        await db.scalars(
            select(SecurityEvent)
            .where(where)
            .order_by(SecurityEvent.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return PageResponse(
        items=[
            {
                "id": row.id,
                "created_at": row.created_at,
                "event_type": row.event_type,
                "severity": row.severity,
                "outcome": row.outcome,
                "user_id": row.user_id,
                "administrator_id": row.administrator_id,
                "source_ip": row.source_ip,
                "request_id": row.request_id,
                "detail": row.safe_detail,
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/audit", response_model=PageResponse)
async def audit_events(
    action: str | None = Query(default=None, max_length=100),
    outcome: str | None = Query(default=None, max_length=30),
    request_id: str | None = Query(default=None, max_length=80),
    # Matches an administrator who was either the actor or the target of the
    # event — the same "belongs to this administrator's history" definition
    # the Administrator detail page's Activity tab needs, now computed by the
    # query instead of fetched-then-filtered client-side.
    administrator_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    _: PlatformContext = Depends(require_roles(*SECURITY)),
    db: AsyncSession = Depends(get_db),
) -> PageResponse:
    """Same NEW-001 policy as security_events above: Security sees
    `source_ip` on every audit row, including rows about an Owner — accepted
    by design, not a PCC-SEC-006 gap. See that function's docstring."""
    filters = []
    if action:
        filters.append(AdministrativeAuditEvent.action == action)
    if outcome:
        filters.append(AdministrativeAuditEvent.outcome == outcome)
    if request_id:
        filters.append(AdministrativeAuditEvent.request_id == request_id)
    if administrator_id:
        filters.append(
            or_(
                AdministrativeAuditEvent.administrator_id == administrator_id,
                AdministrativeAuditEvent.target_id == administrator_id,
            )
        )
    where = and_(*filters)
    total = await db.scalar(select(func.count(AdministrativeAuditEvent.id)).where(where)) or 0
    rows = (
        await db.scalars(
            select(AdministrativeAuditEvent)
            .where(where)
            .order_by(AdministrativeAuditEvent.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return PageResponse(
        items=[
            {
                "id": row.id,
                "created_at": row.created_at,
                "administrator_id": row.administrator_id,
                "administrator_role": row.administrator_role,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "outcome": row.outcome,
                "reason": row.reason,
                "source_ip": row.source_ip,
                "request_id": row.request_id,
                "session_reference": row.session_reference,
                "previous_values": row.previous_values,
                "new_values": row.new_values,
                "failure_category": row.failure_category,
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/administrators")
async def administrators(
    _: PlatformContext = Depends(require_roles(PlatformRole.owner)),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(select(PlatformAdministrator).order_by(PlatformAdministrator.created_at))
    ).all()
    return [
        {
            "id": row.id,
            "email": row.email,
            "display_name": row.display_name,
            "role": row.role,
            "active": row.is_active,
            "mfa_enrolled": row.mfa_enrolled,
            "last_login_at": row.last_login_at,
        }
        for row in rows
    ]


async def _get_smtp_settings_row(db: AsyncSession) -> PlatformSmtpSettings | None:
    row: PlatformSmtpSettings | None = await db.scalar(select(PlatformSmtpSettings).limit(1))
    return row


@router.get("/mail")
async def mail_configuration(
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    pending = (
        await db.scalar(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.topic == "notification.email", OutboxEvent.processed_at.is_(None)
            )
        )
        or 0
    )
    last_success = await db.scalar(
        select(func.max(WorkerJobRecord.finished_at)).where(
            WorkerJobRecord.topic == "notification.email", WorkerJobRecord.status == "completed"
        )
    )
    failures = (
        await db.scalars(
            select(WorkerJobRecord)
            .where(
                WorkerJobRecord.topic == "notification.email",
                WorkerJobRecord.status == "failed",
            )
            .order_by(WorkerJobRecord.finished_at.desc())
            .limit(10)
        )
    ).all()
    config = await resolve_smtp_config(settings, db)
    row = await _get_smtp_settings_row(db)
    failure_labels: dict[uuid.UUID, str] = {}
    for failure in failures:
        if failure.outbox_event_id is None:
            continue
        source_event = await db.get(OutboxEvent, failure.outbox_event_id)
        notification_type = source_event.payload.get("notification_type") if source_event else None
        if notification_type:
            failure_labels[failure.id] = notification_type
    return {
        "configured": config.configured,
        "transport": "SMTP" if config.configured else None,
        "sender_identity": config.sender if config.configured else None,
        "queue_depth": pending,
        "last_successful_delivery": last_success,
        "recent_failures": [
            {
                "id": row.id,
                "job_type": failure_labels.get(row.id, row.topic),
                "failed_at": row.finished_at,
                "safe_failure_message": row.error,
            }
            for row in failures
        ],
        "managed_by": config.source,
        "smtp_settings": {
            "enabled": row.enabled if row else False,
            "host": row.host if row else "",
            "port": row.port if row else 587,
            "connection_security": row.connection_security.value if row else "starttls",
            "auth_enabled": row.auth_enabled if row else False,
            "username": row.username if row else None,
            "password_configured": bool(row.encrypted_password) if row else False,
            "sender_name": row.sender_name if row else "MyKhaya",
            "sender_email": row.sender_email if row else "",
            "reply_to": row.reply_to if row else None,
            "timeout_seconds": row.timeout_seconds if row else 10,
            "updated_at": row.updated_at if row else None,
            "editable": config.source != "environment",
        },
    }


@router.put("/mail/smtp-settings")
async def update_smtp_settings(
    body: SmtpSettingsUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    if settings.email_delivery_configured:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "SMTP is managed by the deployment environment and cannot be changed here.",
        )
    row = await _get_smtp_settings_row(db)
    was_enabled = row.enabled if row else False
    had_password = bool(row.encrypted_password) if row else False

    if row is None:
        row = PlatformSmtpSettings()
        db.add(row)

    if body.enabled and body.auth_enabled and not body.password and not had_password:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A password is required when authentication is enabled.",
        )

    row.enabled = body.enabled
    row.host = body.host.strip()
    row.port = body.port
    row.connection_security = SmtpConnectionSecurity(body.connection_security)
    row.auth_enabled = body.auth_enabled
    row.username = body.username.strip() if body.username else None
    row.sender_name = body.sender_name.strip()
    row.sender_email = body.sender_email.strip()
    row.reply_to = body.reply_to.strip() if body.reply_to else None
    row.timeout_seconds = body.timeout_seconds
    row.updated_by_administrator_id = context.administrator.id

    credentials_replaced = False
    if body.password:
        row.encrypted_password = encrypt_secret(settings, body.password)
        credentials_replaced = True
    elif not body.auth_enabled:
        row.encrypted_password = None
        row.username = None

    platform_audit(
        db,
        request,
        context,
        "smtp.settings_changed",
        "smtp_settings",
        reason=body.reason,
        new={
            "enabled": row.enabled,
            "host": row.host,
            "port": row.port,
            "connection_security": row.connection_security.value,
            "auth_enabled": row.auth_enabled,
        },
    )
    if credentials_replaced:
        platform_audit(
            db, request, context, "smtp.credentials_replaced", "smtp_settings", reason=body.reason
        )
    if was_enabled and not row.enabled:
        platform_audit(
            db, request, context, "smtp.disabled", "smtp_settings", reason=body.reason
        )
    await db.commit()
    return {"message": "SMTP settings saved."}


@router.post("/mail/smtp-settings/clear-password")
async def clear_smtp_password(
    body: SensitiveActionRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    require_recent_auth(context, settings)
    row = await _get_smtp_settings_row(db)
    if row is None or not row.encrypted_password:
        raise HTTPException(status.HTTP_409_CONFLICT, "No stored SMTP password to clear.")
    row.encrypted_password = None
    row.username = None
    row.updated_by_administrator_id = context.administrator.id
    platform_audit(
        db, request, context, "smtp.credentials_replaced", "smtp_settings", reason=body.reason
    )
    await db.commit()
    return {"message": "Stored SMTP credentials cleared."}


@router.post("/mail/test")
async def send_test_email(
    body: TestEmailRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    require_recent_auth(context, settings)
    await enforce_rate_limit(request, settings, "platform-test-email", 3, 300)
    config = await resolve_smtp_config(settings, db)
    if not config.configured:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is not configured.")
    try:
        await asyncio.to_thread(
            send_email,
            config,
            str(body.recipient),
            "MyKhaya test email",
            "This test confirms that the MyKhaya deployment can deliver email.",
        )
    except Exception as exc:
        platform_audit(
            db,
            request,
            context,
            "email.test_failed",
            "email_transport",
            reason=body.reason,
            new={"recipient_domain": str(body.recipient).rsplit("@", 1)[-1]},
            outcome="failure",
            failure_category=type(exc).__name__,
        )
        await db.commit()
        await log.awarning("platform_test_email_failed", error=type(exc).__name__)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The test email could not be delivered. Check the email transport.",
        ) from exc
    platform_audit(
        db,
        request,
        context,
        "email.test_sent",
        "email_transport",
        reason=body.reason,
        new={"recipient_domain": str(body.recipient).rsplit("@", 1)[-1]},
    )
    await db.commit()
    return {"message": "Test email delivered successfully."}


async def _get_push_settings_row(db: AsyncSession) -> PlatformPushSettings | None:
    row: PlatformPushSettings | None = await db.scalar(select(PlatformPushSettings).limit(1))
    return row


@router.get("/push")
async def push_configuration(
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    config = await resolve_push_config(settings, db)
    row = await _get_push_settings_row(db)
    active_subscriptions = (
        await db.scalar(
            select(func.count(PushSubscription.id)).where(PushSubscription.disabled_at.is_(None))
        )
        or 0
    )
    failures = (
        await db.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.channel == NotificationChannel.push,
                NotificationDelivery.status == NotificationDeliveryStatus.failed,
            )
            .order_by(NotificationDelivery.attempted_at.desc())
            .limit(10)
        )
    ).all()
    return {
        "configured": config.configured,
        "managed_by": config.source,
        "public_key": config.public_key,
        "active_subscriptions": active_subscriptions,
        "recent_failures": [
            {
                "id": row.id,
                "notification_type": row.notification_type,
                "failed_at": row.attempted_at,
                "safe_failure_message": row.sanitised_failure_reason,
            }
            for row in failures
        ],
        "push_settings": {
            "enabled": row.enabled if row else False,
            "subject": row.subject if row else None,
            "vapid_public_key": row.vapid_public_key if row else None,
            "private_key_configured": bool(row.encrypted_vapid_private_key) if row else False,
            "updated_at": row.updated_at if row else None,
            "editable": config.source != "environment",
        },
    }


@router.put("/push/vapid-settings")
async def update_push_settings(
    body: PushVapidSettingsUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    if settings.push_delivery_configured:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Push is managed by the deployment environment and cannot be changed here.",
        )
    row = await _get_push_settings_row(db)
    if row is None or not row.vapid_public_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Generate a VAPID key pair before enabling push notifications.",
        )
    was_enabled = row.enabled
    row.enabled = body.enabled
    row.subject = body.subject
    row.updated_by_administrator_id = context.administrator.id
    platform_audit(
        db,
        request,
        context,
        "push.settings_changed",
        "push_settings",
        reason=body.reason,
        new={"enabled": row.enabled, "subject": row.subject},
    )
    if was_enabled and not row.enabled:
        platform_audit(db, request, context, "push.disabled", "push_settings", reason=body.reason)
    await db.commit()
    return {"message": "Push settings saved."}


@router.post("/push/vapid-settings/generate-keys")
async def generate_push_keys(
    body: PushGenerateKeysRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    if settings.push_delivery_configured:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Push is managed by the deployment environment and cannot be changed here.",
        )
    row = await _get_push_settings_row(db)
    if row is not None and row.vapid_public_key and not body.rotate:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A key pair already exists. Confirm rotation to replace it.",
        )
    public_key, private_key = generate_vapid_keypair()
    if row is None:
        row = PlatformPushSettings()
        db.add(row)
    rotating = bool(row.vapid_public_key)
    row.vapid_public_key = public_key
    row.encrypted_vapid_private_key = encrypt_secret(settings, private_key)
    row.updated_by_administrator_id = context.administrator.id
    platform_audit(
        db,
        request,
        context,
        "push.vapid_keys_rotated" if rotating else "push.vapid_keys_generated",
        "push_settings",
        reason=body.reason,
    )
    await db.commit()
    return {
        "message": (
            "New VAPID keys generated. Every previously registered device is now "
            "invalid and will stop receiving push until it re-subscribes."
            if rotating
            else "VAPID keys generated."
        ),
        "public_key": public_key,
    }


@router.post("/push/test")
async def send_test_push(
    body: PushTestRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    await enforce_rate_limit(request, settings, "platform-test-push", 3, 300)
    config = await resolve_push_config(settings, db)
    if not config.configured:
        raise HTTPException(status.HTTP_409_CONFLICT, "Push is not configured.")
    recipient = await db.scalar(select(User).where(User.email == normalise_email(body.recipient)))
    if recipient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No household member has that email.")
    subscriptions = (
        await db.scalars(
            select(PushSubscription).where(
                PushSubscription.user_id == recipient.id, PushSubscription.disabled_at.is_(None)
            )
        )
    ).all()
    if not subscriptions:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That member has no registered devices to test."
        )
    results = []
    for subscription in subscriptions:
        try:
            await asyncio.to_thread(
                send_push,
                config,
                subscription,
                {
                    "title": "MyKhaya test notification",
                    "body": "This confirms push notifications are working.",
                    "deep_link": {"type": "settings"},
                    "notification_type": "test_push",
                },
            )
            results.append({"device_label": subscription.device_label, "result": "accepted"})
        except Exception as exc:
            # Covers both WebPushException (the push service rejected/failed the
            # request) and lower-level encoding errors from a malformed subscription
            # (e.g. corrupted or truncated keys) — either way this is a per-device
            # delivery failure, not a reason to fail the whole admin request.
            results.append(
                {"device_label": subscription.device_label, "result": type(exc).__name__}
            )
            await log.awarning(
                "platform_test_push_device_failed",
                error=type(exc).__name__,
                subscription_id=str(subscription.id),
            )
    any_accepted = any(r["result"] == "accepted" for r in results)
    platform_audit(
        db,
        request,
        context,
        "push.test_sent" if any_accepted else "push.test_failed",
        "push_transport",
        reason=body.reason,
        new={
            "recipient_domain": str(body.recipient).rsplit("@", 1)[-1],
            "device_count": len(results),
        },
        outcome="succeeded" if any_accepted else "failure",
    )
    await db.commit()
    return {"results": results}


def _template_response(
    template_type: str, override: NotificationTemplate | None
) -> NotificationTemplateResponse:
    default = TEMPLATES[template_type]
    is_override = override is not None
    return NotificationTemplateResponse(
        template_type=template_type,
        channel=NotificationChannel.email.value,
        description=default.description,
        allowed_variables=sorted(default.allowed_variables),
        default_subject=default.subject,
        default_body=default.body,
        subject=(override.subject if override and override.subject else default.subject),
        body=(override.body_text if override and override.body_text else default.body),
        is_override=is_override,
        enabled=override.enabled if override else True,
        is_stale=bool(override and override.based_on_default_version < DEFAULT_TEMPLATE_VERSION),
        updated_at=override.updated_at if override else None,
    )


@router.get("/notification-templates")
async def list_notification_templates(
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationTemplateResponse]:
    overrides = {
        row.template_type: row
        for row in (
            await db.scalars(
                select(NotificationTemplate).where(
                    NotificationTemplate.channel == NotificationChannel.email
                )
            )
        ).all()
    }
    return [
        _template_response(template_type, overrides.get(template_type))
        for template_type in sorted(TEMPLATES)
    ]


@router.get("/notification-templates/{template_type}")
async def get_notification_template(
    template_type: str,
    _: PlatformContext = Depends(require_roles(*SUPPORT)),
    db: AsyncSession = Depends(get_db),
) -> NotificationTemplateResponse:
    if template_type not in TEMPLATES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That template does not exist.")
    override = await get_override(db, template_type)
    return _template_response(template_type, override)


@router.put("/notification-templates/{template_type}")
async def update_notification_template(
    template_type: str,
    body: NotificationTemplateUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NotificationTemplateResponse:
    require_recent_auth(context, settings)
    default = TEMPLATES.get(template_type)
    if default is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That template does not exist.")
    try:
        validate_override_text(body.subject, default.allowed_variables)
        validate_override_text(body.body, default.allowed_variables)
    except UnknownTemplateVariable as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown template variable: {{{{{exc}}}}}. Allowed: "
            f"{', '.join(sorted(default.allowed_variables))}.",
        ) from exc

    override = await get_override(db, template_type)
    if override is None:
        override = NotificationTemplate(
            template_type=template_type, channel=NotificationChannel.email
        )
        db.add(override)
    else:
        db.add(
            NotificationTemplateRevision(
                template_id=override.id,
                subject=override.subject,
                body_text=override.body_text,
                body_html=override.body_html,
                replaced_by_administrator_id=context.administrator.id,
            )
        )
    override.subject = body.subject
    override.body_text = body.body
    override.enabled = body.enabled
    override.based_on_default_version = DEFAULT_TEMPLATE_VERSION
    override.updated_by_administrator_id = context.administrator.id
    platform_audit(
        db,
        request,
        context,
        "notification_template.updated",
        "notification_template",
        reason=body.reason,
        new={"template_type": template_type, "enabled": body.enabled},
    )
    await db.commit()
    await db.refresh(override)
    return _template_response(template_type, override)


@router.delete("/notification-templates/{template_type}")
async def reset_notification_template(
    template_type: str,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NotificationTemplateResponse:
    require_recent_auth(context, settings)
    if template_type not in TEMPLATES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That template does not exist.")
    override = await get_override(db, template_type)
    if override is not None:
        await db.delete(override)
        platform_audit(
            db,
            request,
            context,
            "notification_template.reset",
            "notification_template",
            reason="Reset to built-in default.",
            new={"template_type": template_type},
        )
        await db.commit()
    return _template_response(template_type, None)


@router.post("/notification-templates/{template_type}/preview")
async def preview_notification_template(
    template_type: str,
    body: NotificationTemplatePreviewRequest,
    _: PlatformContext = Depends(require_roles(*OPERATORS)),
) -> NotificationTemplatePreviewResponse:
    default = TEMPLATES.get(template_type)
    if default is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That template does not exist.")
    sample = SAMPLE_VARIABLES[template_type]
    try:
        subject = substitute(body.subject, sample, default.allowed_variables)
        rendered_body = substitute(body.body, sample, default.allowed_variables)
    except UnknownTemplateVariable as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown template variable: {{{{{exc}}}}}. Allowed: "
            f"{', '.join(sorted(default.allowed_variables))}.",
        ) from exc
    return NotificationTemplatePreviewResponse(subject=subject, body=rendered_body)


@router.post("/notification-templates/{template_type}/test")
async def test_notification_template(
    template_type: str,
    body: NotificationTemplateTestRequest,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    require_recent_auth(context, settings)
    if template_type not in TEMPLATES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That template does not exist.")
    await enforce_rate_limit(request, settings, "platform-test-template", 3, 300)
    config = await resolve_smtp_config(settings, db)
    if not config.configured:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is not configured.")
    subject, message = await render_notification(
        db, template_type, SAMPLE_VARIABLES[template_type]
    )
    try:
        await asyncio.to_thread(send_email, config, str(body.recipient), subject, message)
    except Exception as exc:
        platform_audit(
            db,
            request,
            context,
            "notification_template.test_failed",
            "notification_template",
            reason=body.reason,
            new={"template_type": template_type},
            outcome="failure",
        )
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The test send failed.") from exc
    platform_audit(
        db,
        request,
        context,
        "notification_template.test_sent",
        "notification_template",
        reason=body.reason,
        new={"template_type": template_type},
    )
    await db.commit()
    return {"message": "Test email sent."}


@router.get("/incidents")
async def incidents(
    _: PlatformContext = Depends(require_roles(*ALL_ROLES)), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(PublicIncident).order_by(PublicIncident.starts_at.desc()).limit(100)
        )
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "message": row.message,
            "service": row.service,
            "state": row.state,
            "starts_at": row.starts_at,
            "resolved_at": row.resolved_at,
        }
        for row in rows
    ]


@router.post("/incidents", status_code=status.HTTP_201_CREATED)
async def create_incident(
    body: IncidentCreate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    row = PublicIncident(
        title=body.title.strip(),
        message=body.message.strip(),
        service=body.service,
        state=body.state,
        starts_at=body.starts_at or datetime.now(UTC),
        created_by=context.administrator.id,
    )
    db.add(row)
    await db.flush()
    platform_audit(
        db,
        request,
        context,
        "status.incident_created",
        "incident",
        row.id,
        reason=body.reason,
        new={"title": row.title, "service": row.service, "state": row.state.value},
    )
    await db.commit()
    return {"id": row.id, "title": row.title, "state": row.state}


@router.patch("/incidents/{incident_id}")
async def update_incident(
    incident_id: uuid.UUID,
    body: IncidentUpdate,
    request: Request,
    context: PlatformContext = Depends(require_roles(*OPERATORS)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_recent_auth(context, settings)
    row = await db.get(PublicIncident, incident_id, with_for_update=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That incident could not be found.")
    previous = {
        "message": row.message,
        "state": row.state.value,
        "resolved": row.resolved_at is not None,
    }
    row.message = body.message.strip()
    row.state = body.state
    row.resolved_at = datetime.now(UTC) if body.resolved else None
    platform_audit(
        db,
        request,
        context,
        "status.incident_updated",
        "incident",
        row.id,
        reason=body.reason,
        previous=previous,
        new={"message": row.message, "state": row.state.value, "resolved": body.resolved},
    )
    await db.commit()
    return {"id": row.id, "state": row.state, "resolved_at": row.resolved_at}
