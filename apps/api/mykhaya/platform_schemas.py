import uuid
from datetime import datetime
from typing import Any, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from mykhaya.models import FeatureKey, PlatformRole, ServiceState
from mykhaya.module_registry import ReleaseState
from mykhaya.schemas import StrictModel


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


class SensitiveActionRequest(StrictModel):
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return " ".join(value.strip().split())


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
