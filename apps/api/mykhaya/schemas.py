import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from mykhaya.models import (
    ChildAgeBand,
    ChildTransitionStatus,
    HouseholdRelationship,
    PermissionProfile,
    RecurrencePattern,
    Role,
)


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


class MobileSessionResponse(UserResponse):
    """Returned only by /auth/mobile/* endpoints - never by the browser /auth/* endpoints."""

    session_token: str


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
    relationship: HouseholdRelationship
    permission_profile: PermissionProfile
    capabilities: list[str]
    member_count: int


class MemberResponse(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    email: EmailStr | None
    role: Role
    relationship: HouseholdRelationship
    permission_profile: PermissionProfile
    permission_overrides: dict[str, bool]
    shared_resources: list[str]
    colour: str | None


class MemberRelationshipUpdate(StrictModel):
    relationship: HouseholdRelationship
    permission_profile: PermissionProfile | None = None
    permission_overrides: dict[str, bool] = Field(default_factory=dict)
    shared_resources: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


class InvitationCreate(StrictModel):
    group_id: uuid.UUID
    email: EmailStr
    relationship: HouseholdRelationship = HouseholdRelationship.partner
    shared_resources: list[str] = Field(default_factory=list, max_length=20)
    # Accepted during the compatibility window; authority is derived from relationship.
    role: Role | None = None


class InvitationResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    email: EmailStr
    role: Role
    relationship: HouseholdRelationship
    permission_profile: PermissionProfile
    shared_resources: list[str]
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
    relationship: HouseholdRelationship
    expires_at: datetime


class ChildCreate(StrictModel):
    display_name: str = Field(min_length=1, max_length=100)
    age_band: ChildAgeBand
    guardian_membership_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)


class ChildPermissionUpdate(StrictModel):
    permissions: dict[str, bool]
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


class ChildAgeBandUpdate(StrictModel):
    age_band: ChildAgeBand
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


class GuardianUpdate(StrictModel):
    guardian_membership_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


class ChildTransitionRequest(StrictModel):
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


class ChildDeleteRequest(ChildTransitionRequest):
    pass


class ChildResponse(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    age_band: ChildAgeBand
    permissions: dict[str, bool]
    guardian_membership_ids: list[uuid.UUID]
    transition_status: ChildTransitionStatus


class HouseholdModuleResponse(BaseModel):
    id: str
    name: str
    description: str
    category: str
    release_state: str
    enabled: bool
    toggleable: bool
    introduced_version: str | None
    dependencies: list[str]
    permissions: list[str]
    route: str | None


class HouseholdFeatureUpdate(StrictModel):
    enabled: bool
    reason: str = Field(min_length=10, max_length=500)
    confirmed: Literal[True]


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


class NotificationPreferencesResponse(BaseModel):
    push_enabled: bool
    in_app_enabled: bool
    event_reminders_enabled: bool
    event_invitations_enabled: bool
    event_changes_enabled: bool
    household_reminders_enabled: bool
    daily_briefing_enabled: bool
    briefing_time: str
    briefing_days: str
    empty_day_briefing_enabled: bool
    lock_screen_preview_level: str
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    quiet_hours_critical_only: bool


class NotificationPreferencesUpdate(StrictModel):
    push_enabled: bool
    in_app_enabled: bool
    event_reminders_enabled: bool
    event_invitations_enabled: bool
    event_changes_enabled: bool
    household_reminders_enabled: bool
    daily_briefing_enabled: bool
    briefing_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$")
    briefing_days: Literal["daily", "weekdays"]
    empty_day_briefing_enabled: bool
    lock_screen_preview_level: Literal["full", "title_only", "hidden"]
    quiet_hours_start: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$"
    )
    quiet_hours_end: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$"
    )
    quiet_hours_critical_only: bool


class NotificationResponse(BaseModel):
    id: uuid.UUID
    notification_type: str
    title: str
    body: str
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None
    deep_link_path: str
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    unread_count: int
    next_page: int | None


class PushSubscriptionKeys(StrictModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class PushSubscriptionCreate(StrictModel):
    endpoint: str = Field(min_length=1, max_length=4000)
    keys: PushSubscriptionKeys
    device_label: str | None = Field(default=None, max_length=120)
    user_agent: str | None = Field(default=None, max_length=300)


class PushSubscriptionResponse(BaseModel):
    id: uuid.UUID
    device_label: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime | None
    disabled_at: datetime | None


class PushPublicKeyResponse(BaseModel):
    configured: bool
    public_key: str | None
