import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from mykhaya.models import RecurrencePattern, Role


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=128)
    invitation_token: str | None = Field(default=None, min_length=30, max_length=500)

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


class InvitationListItem(InvitationResponse):
    accepted_at: datetime | None
    revoked_at: datetime | None
    inviter_display_name: str
    join_link: str | None = None


class InvitationTokenPreview(BaseModel):
    group_id: uuid.UUID
    group_name: str
    invited_by_display_name: str
    email: EmailStr
    role: Role
    expires_at: datetime


class InvitationResend(StrictModel):
    invitation_id: uuid.UUID


class InvitationRevoke(StrictModel):
    invitation_id: uuid.UUID


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


class EventLabelCreate(StrictModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(default="#456B76", min_length=7, max_length=7)


class EventLabelResponse(BaseModel):
    id: uuid.UUID
    name: str
    color: str
    is_active: bool
    sort_order: int


class EventCreate(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    start_at: datetime
    end_at: datetime
    timezone: str = Field(min_length=1, max_length=100)
    is_all_day: bool = False
    description: str | None = Field(default=None, max_length=2000)
    location_text: str | None = Field(default=None, max_length=200)
    label_id: uuid.UUID | None = None
    member_ids: list[uuid.UUID] = Field(default_factory=list, max_length=25)
    reminder_minutes: int | None = Field(default=None, ge=0, le=10080)
    recurrence: RecurrencePattern = RecurrencePattern.none
    recurrence_interval: int = Field(default=1, ge=1, le=365)
    recurrence_until: datetime | None = None
    recurrence_count: int | None = Field(default=None, ge=1, le=1000)


class EventUpdate(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    start_at: datetime
    end_at: datetime
    timezone: str = Field(min_length=1, max_length=100)
    is_all_day: bool = False
    description: str | None = Field(default=None, max_length=2000)
    location_text: str | None = Field(default=None, max_length=200)
    label_id: uuid.UUID | None = None
    member_ids: list[uuid.UUID] = Field(default_factory=list, max_length=25)
    reminder_minutes: int | None = Field(default=None, ge=0, le=10080)
    recurrence: RecurrencePattern = RecurrencePattern.none
    recurrence_interval: int = Field(default=1, ge=1, le=365)
    recurrence_until: datetime | None = None
    recurrence_count: int | None = Field(default=None, ge=1, le=1000)
    expected_updated_at: datetime


class EventOccurrence(BaseModel):
    occurrence_id: str
    event_id: uuid.UUID
    title: str
    start_at: datetime
    end_at: datetime
    is_all_day: bool
    timezone: str
    description: str | None
    location_text: str | None
    label: EventLabelResponse | None
    member_ids: list[uuid.UUID]
    recurrence: RecurrencePattern
    reminder_minutes: int | None
    created_by: uuid.UUID
    updated_at: datetime


class EventActivityResponse(BaseModel):
    id: uuid.UUID
    action: str
    summary: str
    actor_user_id: uuid.UUID | None
    created_at: datetime


class EventDetailResponse(BaseModel):
    event: EventOccurrence
    activity: list[EventActivityResponse]


class EventListResponse(BaseModel):
    items: list[EventOccurrence]
    next_page: int | None


class HomeSummaryResponse(BaseModel):
    home_name: str
    member_count: int
    pending_invitations: int | None
    today_events: list[EventOccurrence]
    next_event: EventOccurrence | None
