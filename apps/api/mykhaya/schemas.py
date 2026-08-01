import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from mykhaya.models import FeatureFlagKey, PlatformRole, Role


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(value.strip().split())


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenRequest(StrictModel):
    token: str = Field(min_length=30, max_length=500)


class ForgotRequest(StrictModel):
    email: EmailStr


class ResetRequest(TokenRequest):
    password: str = Field(min_length=12, max_length=128)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    email_verified: bool


class GroupCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(value.strip().split())


class GroupUpdate(GroupCreate):
    pass


class GroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    role: Role
    member_count: int


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: EmailStr
    role: Role


class MemberRoleUpdate(StrictModel):
    role: Role


class InvitationCreate(StrictModel):
    group_id: uuid.UUID
    email: EmailStr
    role: Role = Role.adult_member


class InvitationResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    email: EmailStr
    role: Role
    expires_at: datetime


class InvitationAccept(StrictModel):
    token: str = Field(min_length=30, max_length=500)


class SessionResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user_agent: str
    current: bool


class MessageResponse(BaseModel):
    message: str


class RegistrationResponse(MessageResponse):
    verification_required: bool


class HomeFeatureResponse(BaseModel):
    key: FeatureFlagKey
    enabled: bool
    source: str


class HomeFeaturesEnvelope(BaseModel):
    home_id: uuid.UUID
    features: list[HomeFeatureResponse]


class PlatformFeatureResponse(BaseModel):
    key: FeatureFlagKey
    display_name: str
    description: str
    globally_enabled: bool


class PlatformFeatureUpdate(StrictModel):
    enabled: bool
    reason: str = Field(min_length=10, max_length=300)
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Please confirm before saving this change.")
        return value


class PlatformFeatureOverrideResponse(BaseModel):
    key: FeatureFlagKey
    home_id: uuid.UUID
    enabled: bool
    source: str


class PlatformFeatureOverrideUpdate(StrictModel):
    enabled: bool
    reason: str = Field(min_length=10, max_length=300)
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Please confirm before saving this change.")
        return value


class PlatformOperatorResponse(BaseModel):
    user_id: uuid.UUID
    role: PlatformRole
