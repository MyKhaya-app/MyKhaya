import uuid
from datetime import datetime
from typing import Any, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from mykhaya.models import (
    BillingInterval,
    FeatureKey,
    PlatformRole,
    ServiceState,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
)
from mykhaya.module_registry import ReleaseState
from mykhaya.schemas import CalendarUsageResponse, StrictModel


class PlatformLoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PlatformReauthenticateRequest(StrictModel):
    password: str = Field(min_length=1, max_length=128)


class PlatformActorResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: PlatformRole
    mfa_enrolled: bool
    # "full": ordinary Control Centre access. "pending_mfa": password verified,
    # a second factor is enrolled and must now be presented. "mfa_setup_required":
    # password verified, policy requires MFA and none is enrolled yet — only
    # enrollment endpoints are reachable until one is set up. The frontend
    # branches its post-login screen on this field.
    session_status: Literal["full", "pending_mfa", "mfa_setup_required"]
    # Only populated at "pending_mfa" (i.e. after password verification for
    # this exact account) — the login page uses this to show only the
    # fallback methods that genuinely exist, instead of always rendering
    # "use an authenticator app" / "use a recovery code" regardless of
    # whether either was ever set up. Safe to disclose here: the caller has
    # already proven the password for this specific account, so this isn't
    # an account-enumeration channel.
    available_factors: list[Literal["passkey", "totp", "recovery_code"]] = []
    # Only populated once, atomically with the response that completes an
    # administrator's *first* MFA factor — never retrievable again afterwards.
    # See routers.platform._issue_recovery_codes_if_first_factor.
    recovery_codes: list[str] | None = None


class SensitiveActionRequest(StrictModel):
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return " ".join(value.strip().split())


class TotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TotpCodeRequest(StrictModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TotpDisableRequest(SensitiveActionRequest):
    pass


class WebAuthnRegistrationOptionsResponse(BaseModel):
    options_json: str


class WebAuthnRegistrationVerifyRequest(StrictModel):
    label: str = Field(min_length=1, max_length=100)
    credential_json: str = Field(min_length=1, max_length=10_000)


class WebAuthnCredentialResponse(BaseModel):
    id: uuid.UUID
    label: str
    created_at: datetime
    last_used_at: datetime | None


class WebAuthnCredentialRename(StrictModel):
    label: str = Field(min_length=1, max_length=100)


class WebAuthnAuthenticationOptionsResponse(BaseModel):
    options_json: str


class WebAuthnAssertionRequest(StrictModel):
    credential_json: str = Field(min_length=1, max_length=10_000)


class RecoveryCodesResponse(BaseModel):
    codes: list[str]


class RecoveryCodeStatusResponse(BaseModel):
    remaining: int


class RecoveryCodeVerifyRequest(StrictModel):
    code: str = Field(min_length=1, max_length=32)


class AdministratorSecurityResponse(BaseModel):
    """The full detail view — Owner only (PCC-SEC-006). Includes raw session
    IP/user-agent/session-ID data, which is more than a non-Owner role needs
    to do its job; see AdministratorSecuritySummaryResponse for what
    Administrator/Security see instead."""

    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: PlatformRole
    is_active: bool
    mfa_enrolled: bool
    totp_enabled: bool
    totp_verified_at: datetime | None
    webauthn_credentials: list[WebAuthnCredentialResponse]
    recovery_codes_remaining: int
    sessions: list[dict[str, Any]]


class AdministratorSecuritySummaryResponse(BaseModel):
    """The reduced detail view returned to the Administrator/Security roles
    (PCC-SEC-006): enough for security operations — is MFA enrolled, is the
    account active, how many active sessions, when it was last active — but
    without raw session IPs/user-agents/session IDs or per-credential labels,
    which those roles don't need to do their job. Never returned for an Owner
    target; Administrator/Security have no visibility into an Owner's
    security detail at all, mirroring the same boundary as the MFA-reset
    authorization fix (PCC-SEC-001)."""

    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: PlatformRole
    is_active: bool
    mfa_enrolled: bool
    totp_enabled: bool
    totp_verified_at: datetime | None
    webauthn_credential_count: int
    recovery_codes_remaining: int
    active_session_count: int
    last_seen_at: datetime | None


class AdministratorUpdate(SensitiveActionRequest):
    is_active: bool | None = None
    role: PlatformRole | None = None


class AdministratorMfaResetRequest(SensitiveActionRequest):
    pass


class MfaPolicyUpdate(SensitiveActionRequest):
    required: bool


class MfaPolicyResponse(BaseModel):
    required: bool
    # True when MYKHAYA_ADMIN_MFA_REQUIRED already forces this on — the toggle
    # is then read-only in the UI, since no database setting can weaken it.
    environment_enforced: bool


class AdministratorInvitationCreate(SensitiveActionRequest):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    role: PlatformRole


InvitationState = Literal["pending", "accepted", "expired", "revoked"]


class AdministratorInvitationResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: PlatformRole
    state: InvitationState
    invited_by_display_name: str | None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class AdministratorInvitationPreview(BaseModel):
    email: EmailStr
    display_name: str
    role: PlatformRole
    invited_by_display_name: str | None
    expires_at: datetime


class AdministratorInvitationAccept(StrictModel):
    token: str = Field(min_length=30, max_length=500)
    # Platform Administrator accounts are the highest-privilege identity in
    # MyKhaya — held to the same minimum length as the one-time bootstrap
    # script (mykhaya.bootstrap_platform_owner), not the lower bar used for
    # ordinary household passwords.
    password: str = Field(min_length=16, max_length=128)


class NoteRequest(StrictModel):
    body: str = Field(min_length=2, max_length=1000)


class SettingUpdate(StrictModel):
    value: bool | int | str | list[str]
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


class ModuleUpdate(StrictModel):
    enabled: bool
    release_state: ReleaseState
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


class FeatureFlagUpdate(StrictModel):
    enabled: bool
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


class TestEmailRequest(SensitiveActionRequest):
    recipient: EmailStr


class SmtpSettingsUpdate(SensitiveActionRequest):
    enabled: bool
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    connection_security: Literal["none", "starttls", "tls"] = "starttls"
    auth_enabled: bool = False
    username: str | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, max_length=1000)
    sender_name: str = Field(default="MyKhaya", max_length=100)
    sender_email: str = Field(default="", max_length=320)
    reply_to: str | None = Field(default=None, max_length=320)
    timeout_seconds: int = Field(default=10, ge=1, le=60)

    @field_validator("sender_email", "reply_to")
    @classmethod
    def validate_email_fields(cls, value: str | None) -> str | None:
        if not value:
            return value
        try:
            validate_email(value, check_deliverability=False)
        except EmailNotValidError as exc:
            raise ValueError("Enter a valid email address") from exc
        return value

    @model_validator(mode="after")
    def validate_enabled_requirements(self) -> "SmtpSettingsUpdate":
        if self.enabled:
            if not self.host.strip():
                raise ValueError("Host is required when SMTP is enabled")
            if not self.sender_email.strip():
                raise ValueError("Sender email is required when SMTP is enabled")
            if self.auth_enabled and not (self.username and self.username.strip()):
                raise ValueError("Username is required when authentication is enabled")
        return self


class PushVapidSettingsUpdate(SensitiveActionRequest):
    enabled: bool
    subject: str | None = Field(default=None, max_length=320)

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str | None) -> str | None:
        if not value:
            return value
        if value.startswith("mailto:"):
            candidate = value[len("mailto:") :]
        elif value.startswith("https://"):
            return value
        else:
            candidate = value
        try:
            validate_email(candidate, check_deliverability=False)
        except EmailNotValidError as exc:
            raise ValueError(
                "The VAPID contact must be a mailto: address or an https:// URL"
            ) from exc
        return value if value.startswith("mailto:") else f"mailto:{value}"

    @model_validator(mode="after")
    def validate_enabled_requirements(self) -> "PushVapidSettingsUpdate":
        if self.enabled and not (self.subject and self.subject.strip()):
            raise ValueError("A contact address is required when push is enabled")
        return self


class PushGenerateKeysRequest(SensitiveActionRequest):
    rotate: bool = False


class PushTestRequest(SensitiveActionRequest):
    recipient: EmailStr


class IncidentCreate(StrictModel):
    title: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=3, max_length=1000)
    service: Literal[
        "web_application",
        "authentication",
        "api",
        "email_delivery",
        "notifications",
        "background_processing",
    ]
    state: ServiceState
    starts_at: datetime | None = None
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


class IncidentUpdate(StrictModel):
    message: str = Field(min_length=3, max_length=1000)
    state: ServiceState
    resolved: bool = False
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


class PageResponse(BaseModel):
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int


class FeatureEvaluationResponse(BaseModel):
    feature: FeatureKey
    enabled: bool


class FeatureMatrixResponse(BaseModel):
    features: list[FeatureEvaluationResponse]


class NotificationTemplateResponse(BaseModel):
    template_type: str
    channel: str
    description: str
    allowed_variables: list[str]
    default_subject: str
    default_body: str
    subject: str
    body: str
    is_override: bool
    enabled: bool
    is_stale: bool
    updated_at: datetime | None


class NotificationTemplateUpdate(SensitiveActionRequest):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    enabled: bool = True


class NotificationTemplatePreviewRequest(StrictModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)


class NotificationTemplatePreviewResponse(BaseModel):
    subject: str
    body: str


class NotificationTemplateTestRequest(SensitiveActionRequest):
    recipient: EmailStr


class ServiceStatusResponse(BaseModel):
    status: Literal["running", "stale", "unavailable"]
    last_heartbeat: datetime | None
    detail: str


class TransportStatusResponse(BaseModel):
    configured: bool
    status: Literal["connected", "not_configured"]


class CommunicationsHealthResponse(BaseModel):
    overall: Literal["healthy", "degraded", "unhealthy"]
    worker: ServiceStatusResponse
    scheduler: ServiceStatusResponse
    smtp: TransportStatusResponse
    push: TransportStatusResponse
    queue_depth: int
    queue_status: Literal["healthy", "warning"]
    queue_reason: str | None
    average_latency_seconds: float | None
    deliveries_today: int
    failures_today: int
    retries_today: int


class TimelineEntryResponse(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    notification_type: str
    label: str
    channel: str
    status: str
    friendly_status: str
    recipient_display_name: str | None
    retry_count: int


class TimelineResponse(BaseModel):
    items: list[TimelineEntryResponse]
    next_page: int | None


class DiagnosticsEntryResponse(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    notification_type: str
    label: str
    channel: str
    status: str
    recipient_email: str | None
    sanitised_failure_reason: str | None
    retry_count: int
    idempotency_key: str


class DiagnosticsResponse(BaseModel):
    items: list[DiagnosticsEntryResponse]
    next_page: int | None


class HomeSubscriptionResponse(BaseModel):
    """Platform-Admin-only view of a Home's commercial state — everything
    Phase 2's subscription management UI will need to display. Never
    returned from any household-facing endpoint."""

    plan: SubscriptionPlan
    provider: SubscriptionProvider
    status: SubscriptionStatus
    billing_owner_user_id: uuid.UUID | None
    external_customer_id: str | None
    external_subscription_id: str | None
    # The exact Stripe Price this subscription is actually billed against —
    # never the currently-configured signup price (see "Price increases and
    # grandfathering" in docs/architecture/commercial-entitlements.md).
    external_price_id: str | None
    billing_interval: BillingInterval | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    complimentary_reason: str | None
    complimentary_note: str | None
    complimentary_granted_by: uuid.UUID | None
    complimentary_granted_by_display_name: str | None
    complimentary_granted_at: datetime | None
    complimentary_expires_at: datetime | None
    effective_plan: SubscriptionPlan
    # Populated only when effective_plan differs from plan — e.g. "Complimentary
    # access expired". None when the effective plan matches the stored one.
    effective_status_reason: str | None


class GrantComplimentaryRequest(SensitiveActionRequest):
    complimentary_reason: str = Field(min_length=1, max_length=200)
    complimentary_note: str | None = Field(default=None, max_length=1000)
    expires_at: datetime | None = None


class RevokeComplimentaryRequest(SensitiveActionRequest):
    pass


class SubscriptionSummaryResponse(BaseModel):
    """Backend-computed factual counts only. Still no MRR/ARR: with multiple
    historical Stripe Prices, currencies and billing intervals possibly in
    play, a single blended revenue figure would be non-trivial to compute
    correctly — see "Platform summary metrics" in
    docs/architecture/commercial-entitlements.md. Never calculated from a
    hard-coded plan price."""

    total_homes: int
    free: int
    family: int
    complimentary: int
    complimentary_expired: int
    past_due: int
    cancelled: int
    stripe_total: int
    stripe_active_family: int
    stripe_monthly: int
    stripe_annual: int
    stripe_cancelling: int


class SubscriptionListItem(BaseModel):
    id: uuid.UUID
    name: str
    stored_plan: SubscriptionPlan
    provider: SubscriptionProvider
    status: SubscriptionStatus
    effective_plan: SubscriptionPlan
    effective_status_reason: str | None
    complimentary_expires_at: datetime | None
    member_count: int
    last_commercial_change: datetime | None


class SubscriptionListResponse(BaseModel):
    items: list[SubscriptionListItem]
    page: int
    page_size: int
    total: int


class EntitlementsResponse(BaseModel):
    plan: SubscriptionPlan
    booleans: dict[str, bool]
    limits: dict[str, int | None]


class SubscriptionEventResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    event_type: str
    from_plan: SubscriptionPlan | None
    to_plan: SubscriptionPlan | None
    from_provider: SubscriptionProvider | None
    to_provider: SubscriptionProvider | None
    from_status: SubscriptionStatus | None
    to_status: SubscriptionStatus | None
    actor_administrator_id: uuid.UUID | None
    actor_display_name: str | None
    reason: str | None


class HomeAdministratorSummary(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str


class WebhookEventSummary(BaseModel):
    """A single recorded Stripe webhook delivery — never the raw payload,
    only enough for an operator to answer "did this Home's payment webhook
    arrive, and what happened." See
    docs/architecture/commercial-entitlements.md#webhook-observability."""

    id: uuid.UUID
    stripe_event_id: str
    event_type: str
    received_at: datetime
    outcome: str


class WebhookFailureSummary(BaseModel):
    id: uuid.UUID
    stripe_event_id: str | None
    event_type: str | None
    error_message: str
    occurred_at: datetime


class StripeWebhookHealthResponse(BaseModel):
    configured: bool
    state: str
    reason: str | None
    last_event_at: datetime | None
    recent_failure_count: int
    recent_events: list[WebhookEventSummary]
    recent_failures: list[WebhookFailureSummary]


class StripePriceInfo(BaseModel):
    """The actual amount this specific subscription is billed, resolved live
    from Stripe — never a hard-coded figure. None when the Home has no
    Stripe price on record, or Stripe couldn't be reached."""

    currency: str
    unit_amount: int
    formatted_amount: str


class SubscriptionDetailResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    member_count: int
    administrators: list[HomeAdministratorSummary]
    subscription: HomeSubscriptionResponse
    entitlements: EntitlementsResponse
    # Diagnostic only: lets an operator see "this Home has more event
    # categories than its plan allows" without a manual query. Never a
    # control — there is no unlock action here, only the existing
    # Complimentary grant or a real Stripe upgrade change what a Home is
    # entitled to.
    calendar_usage: CalendarUsageResponse
    member_usage: CalendarUsageResponse
    # Informational aggregate only (personal routines are a per-person
    # limit) — see mykhaya.entitlements.personal_routines_total.
    personal_routines_total: int
    # Support diagnostics for "I paid but I'm still on Free" (Phase 7) — the
    # most recent webhook deliveries MyKhaya recorded for this specific
    # Home, so an operator can see whether Stripe's webhook actually arrived
    # without database access.
    recent_webhook_events: list[WebhookEventSummary]
    history: list[SubscriptionEventResponse]
    stripe_price: StripePriceInfo | None = None
    # Built from validated Stripe object IDs already stored on this Home —
    # never round-tripped through a client-supplied value. Test-mode Stripe
    # Dashboard links only, matching this phase's test-mode-only scope.
    stripe_dashboard_customer_url: str | None = None
    stripe_dashboard_subscription_url: str | None = None
