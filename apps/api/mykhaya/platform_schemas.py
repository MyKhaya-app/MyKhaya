import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from mykhaya.models import FeatureKey, PlatformRole, ServiceState
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


class FeatureFlagUpdate(StrictModel):
    enabled: bool
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


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
