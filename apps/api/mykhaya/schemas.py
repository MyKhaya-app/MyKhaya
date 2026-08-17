import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from mykhaya.colour_palette import ColourToken
from mykhaya.models import (
    ChildAgeBand,
    ChildTransitionStatus,
    HouseholdRelationship,
    PermissionProfile,
    RecurrencePattern,
    Role,
    RoutineReminderTiming,
    RoutineScope,
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
    # None for a managed Child: its User row carries a server-generated,
    # deliberately-undeliverable placeholder address (managed-child-*@managed.
    # mykhaya.invalid — see routers.children.create_child) that is an internal
    # implementation detail, not something meaningful to expose to any client —
    # see mykhaya.routers.auth.user_response, which nulls this based on the
    # authenticating Session's kind. A real adult account always returns its
    # validated email here, same as before.
    email: EmailStr | None
    display_name: str
    email_verified: bool
    birth_month: int | None = None
    birth_day: int | None = None
    birth_year: int | None = None
    # Cache-busting version for the avatar image URL, not the image itself — null
    # means "no custom avatar, show initials". See mykhaya/avatars/.
    avatar_version: str | None = None
    # "adult" or "managed_child" — set from the authenticating Session, never
    # inferred from the User row itself. The frontend uses this to hide adult-only
    # navigation/actions for a Child session; server-side capability checks are the
    # real enforcement, this is only for UI shaping.
    principal_type: str = "adult"


def _validate_birthday(birth_month: int | None, birth_day: int | None) -> None:
    if birth_month is None and birth_day is None:
        return
    if birth_month is None or birth_day is None:
        raise ValueError("birth_month and birth_day must be set together")
    days_in_month = {
        1: 31,
        2: 29,
        3: 31,
        4: 30,
        5: 31,
        6: 30,
        7: 31,
        8: 31,
        9: 30,
        10: 31,
        11: 30,
        12: 31,
    }
    if birth_day > days_in_month[birth_month]:
        raise ValueError("That is not a valid day for the selected month")


class UserBirthdayUpdate(StrictModel):
    birth_month: int | None = Field(default=None, ge=1, le=12)
    birth_day: int | None = Field(default=None, ge=1, le=31)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)

    @model_validator(mode="after")
    def check_valid_date(self) -> "UserBirthdayUpdate":
        _validate_birthday(self.birth_month, self.birth_day)
        return self


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
    # Shown to any existing member (the same trust boundary as member_count) so an
    # adult can hand it to a Child for sign-in — see mykhaya.security.generate_home_code.
    child_login_code: str


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
    colour: ColourToken | None
    avatar_version: str | None = None


class MemberColourUpdate(StrictModel):
    colour: ColourToken


class MemberRelationshipUpdate(StrictModel):
    relationship: HouseholdRelationship
    permission_profile: PermissionProfile | None = None
    permission_overrides: dict[str, bool] = Field(default_factory=dict)
    shared_resources: list[str] = Field(default_factory=list, max_length=20)
    # Optional: this is a routine household action, not an operator action — the user
    # is never prompted to justify it. See docs/security/threat-model.md.
    reason: str | None = Field(default=None, max_length=500)
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
    # Optional — see MemberRelationshipUpdate.reason above.
    reason: str | None = Field(default=None, max_length=500)
    confirmed: Literal[True]


class ChildAgeBandUpdate(StrictModel):
    age_band: ChildAgeBand
    reason: str | None = Field(default=None, max_length=500)
    confirmed: Literal[True]


class GuardianUpdate(StrictModel):
    guardian_membership_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    reason: str | None = Field(default=None, max_length=500)
    confirmed: Literal[True]


class ChildTransitionRequest(StrictModel):
    reason: str | None = Field(default=None, max_length=500)
    confirmed: Literal[True]


class ChildDeleteRequest(ChildTransitionRequest):
    pass


class ChildBirthdayUpdate(StrictModel):
    birth_month: int | None = Field(default=None, ge=1, le=12)
    birth_day: int | None = Field(default=None, ge=1, le=31)
    birthday_visible: bool
    reason: str | None = Field(default=None, max_length=500)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def check_valid_date(self) -> "ChildBirthdayUpdate":
        _validate_birthday(self.birth_month, self.birth_day)
        return self


class ChildResponse(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    age_band: ChildAgeBand
    permissions: dict[str, bool]
    guardian_membership_ids: list[uuid.UUID]
    transition_status: ChildTransitionStatus
    birth_month: int | None
    birth_day: int | None
    birthday_visible: bool
    # Managed Child sign-in — status only. The username is shown back so the
    # adult who configured it can see it; the PIN is never returned by any
    # endpoint, at any point, under any circumstances.
    login_enabled: bool
    login_username: str | None


class ChildLoginConfigure(StrictModel):
    """Covers enable, change-username-only, change-PIN-only and disable — see
    mykhaya.routers.children's login-config endpoint for the exact semantics of
    which fields are required in which combination."""

    enabled: bool
    username: str | None = Field(default=None, min_length=2, max_length=24)
    pin: str | None = Field(default=None, min_length=4, max_length=6)

    @field_validator("pin")
    @classmethod
    def pin_is_numeric(cls, value: str | None) -> str | None:
        if value is not None and not value.isdigit():
            raise ValueError("PIN must be 4 to 6 digits.")
        return value


class ChildLoginRequest(StrictModel):
    home_code: str = Field(min_length=4, max_length=10)
    username: str = Field(min_length=1, max_length=24)
    pin: str = Field(min_length=1, max_length=6)


class BirthdayEntry(BaseModel):
    owner_type: Literal["user", "child"]
    owner_id: uuid.UUID
    display_name: str
    month: int
    day: int
    next_occurrence_date: date


class BirthdayListResponse(BaseModel):
    items: list[BirthdayEntry]


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
    reason: str | None = Field(default=None, max_length=500)
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


class HomeCalendarCreate(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(value.strip().split())


class HomeCalendarDeleteRequest(StrictModel):
    # Optional — this is a routine household action, not an operator action.
    # See MemberRelationshipUpdate.reason.
    reason: str | None = Field(default=None, max_length=500)
    confirmed: Literal[True]


class HomeCalendarUpdate(StrictModel):
    # Deliberately colour-only — a shared calendar's `name` (in particular
    # the primary/system Home calendar's fixed "Home calendar" product
    # identity) is not user-editable data. StrictModel's extra="forbid"
    # means a client-supplied `name` is rejected outright (422), not merely
    # ignored, so this is structural enforcement, not a convention.
    color: ColourToken


class HomeCalendarResponse(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str
    is_primary: bool
    color: ColourToken
    # None for every shared/Home calendar in `items` below. Set only on the
    # `personal_calendar` object — included here (rather than a separate
    # response shape) so both cases share one type. See
    # HomeCalendar.owner_user_id.
    owner_user_id: uuid.UUID | None = None
    # "normal": full create/edit/delete access on Free or Family alike.
    # "read_only_due_to_plan": preserved after a downgrade left the Home with
    # more calendars than its plan allows — viewable, but its events can't be
    # created/edited/deleted, and no further calendar can be created, until
    # either the Home returns to Family or enough calendars are voluntarily
    # deleted to fall back within the limit. Derived fresh on every read from
    # current entitlement + current calendar count — never a persisted flag.
    # See docs/architecture/commercial-entitlements.md#calendar-as-proof-of-architecture.
    # A Personal Calendar is always "normal" — never entitlement-gated.
    commercial_access: Literal["normal", "read_only_due_to_plan"]
    created_at: datetime


class CalendarListResponse(BaseModel):
    # Shared/Home calendars only (owner_user_id is always None here) — the
    # resource /calendar/calendars manages and calendar.max_categories
    # counts. A Personal Calendar deliberately never appears in this list:
    # it isn't a Home-administered resource. See `personal_calendar` below.
    items: list[HomeCalendarResponse]
    limit: int | None
    # The requesting user's own Personal Calendar within this Home —
    # provisioned on demand if it doesn't exist yet (see
    # calendar_provisioning.ensure_personal_calendar). Always present for an
    # adult member; never another member's. None for a managed Child — see
    # calendar_provisioning's module docstring on why that's left an open
    # product decision rather than assumed either way.
    personal_calendar: HomeCalendarResponse | None


class CalendarUsageResponse(BaseModel):
    """Generic current-usage-vs-plan-limit shape (count / limit / over_limit)
    — originally built for calendar.max_categories, now reused as-is for any
    numeric-limited resource (see mykhaya.entitlements.member_usage,
    personal_routine_usage) rather than declaring a near-identical class per
    resource. Used by both the Platform Control Centre's commercial-detail
    diagnostics and the household Plan & Billing page's over-limit
    messaging, so every surface computes usage the same way."""

    count: int
    limit: int | None
    over_limit: bool


class EventLabelCreate(StrictModel):
    name: str = Field(min_length=1, max_length=40)
    color: ColourToken = ColourToken.teal

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(value.strip().split())


class EventLabelUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    color: ColourToken | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return " ".join(value.strip().split()) if value is not None else None


class EventLabelResponse(BaseModel):
    id: uuid.UUID
    name: str
    color: ColourToken
    is_active: bool
    sort_order: int
    # This is the actual user-facing "event category" resource
    # calendar.max_categories governs — see "Event categories are
    # CalendarEventLabel, not HomeCalendar" in
    # docs/architecture/commercial-entitlements.md. Same meaning as
    # HomeCalendarResponse.commercial_access: "normal" means usable now
    # (an active label within the plan's limit, or an inactive one that
    # could still be activated); "read_only_due_to_plan" means an active
    # label preserved past a downgrade beyond the limit, or an inactive
    # label that can't currently be activated. Derived fresh on every read,
    # never persisted. Only ever populated by the GET /event-labels listing
    # (the management surface) — None when a label is embedded on an
    # EventOccurrence or returned directly from create/update, neither of
    # which needs it (the settings page always reloads the list after a
    # mutation, which is where this is actually read).
    commercial_access: Literal["normal", "read_only_due_to_plan"] | None = None


def _require_tz_aware(value: datetime | None) -> datetime | None:
    # A naive datetime (no UTC offset in the wire representation) is
    # ambiguous about which instant it actually names — accepting one here
    # would leave the caller's local-timezone assumption to be silently
    # guessed by the DB driver rather than stated explicitly by the client.
    # Every calendar timestamp boundary must be an unambiguous instant; reject
    # naive values instead of guessing server/UTC intent.
    if value is not None and value.tzinfo is None:
        raise ValueError("must include a UTC offset (e.g. end in Z or +01:00)")
    return value


class EventCreate(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    start_at: datetime
    end_at: datetime
    timezone: str = Field(min_length=1, max_length=100)
    is_all_day: bool = False
    description: str | None = Field(default=None, max_length=2000)
    location_text: str | None = Field(default=None, max_length=200)
    label_id: uuid.UUID | None = None
    # Which HomeCalendar this event belongs to. Omitted (the common,
    # single-calendar case) defaults to the Home's primary calendar, exactly
    # as before this field existed. A Family Home with additional calendars
    # may target one explicitly; targeting a calendar the plan has left
    # read-only (see HomeCalendarResponse.commercial_access) is rejected.
    calendar_id: uuid.UUID | None = None
    member_ids: list[uuid.UUID] = Field(default_factory=list, max_length=25)
    reminder_minutes: int | None = Field(default=None, ge=0, le=10080)
    recurrence: RecurrencePattern = RecurrencePattern.none
    recurrence_interval: int = Field(default=1, ge=1, le=365)
    recurrence_until: datetime | None = None
    recurrence_count: int | None = Field(default=None, ge=1, le=1000)

    @field_validator("start_at", "end_at", "recurrence_until")
    @classmethod
    def tz_aware(cls, value: datetime | None) -> datetime | None:
        return _require_tz_aware(value)


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

    @field_validator("start_at", "end_at", "recurrence_until")
    @classmethod
    def tz_aware(cls, value: datetime | None) -> datetime | None:
        return _require_tz_aware(value)


class EventOccurrence(BaseModel):
    occurrence_id: str
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    title: str
    start_at: datetime
    end_at: datetime
    is_all_day: bool
    timezone: str
    description: str | None
    location_text: str | None
    label: EventLabelResponse | None
    # This event's calendar's own colour (HomeCalendar.color) — what it
    # should render as when `label` is None. A category's colour (label.color)
    # always takes precedence when a label is set; this is only the
    # fallback, but always populated so the frontend never needs its own
    # hardcoded default. Reused as-is for Personal Calendar events too
    # (unaffected by this feature — no UI exposes changing it, so it stays
    # whatever it always defaulted to).
    calendar_color: ColourToken
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


class RoutineCreate(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    scope: RoutineScope = RoutineScope.household
    interval_weeks: int = Field(default=1, ge=1, le=52)
    repeat_unit: Literal["daily", "weekly"] = "weekly"
    week_anchor_date: date
    reminder_timing: RoutineReminderTiming = RoutineReminderTiming.evening_before
    is_critical: bool = False
    pinned: bool = False
    start_date: date
    end_date: date | None = None
    member_ids: list[uuid.UUID] = Field(default_factory=list, max_length=25)

    @model_validator(mode="after")
    def _personal_has_no_explicit_members(self) -> "RoutineCreate":
        # A personal routine's only recipient is its owner (inferred from the
        # authenticated actor, never client input) — explicit member assignment is a
        # household-routine concept and would be misleading here.
        if self.scope == RoutineScope.personal and self.member_ids:
            raise ValueError("A personal routine cannot have explicit members")
        if self.repeat_unit == "daily" and self.interval_weeks != 1:
            raise ValueError("Daily routines must use an interval of one")
        return self


class RoutineUpdate(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    scope: RoutineScope = RoutineScope.household
    interval_weeks: int = Field(default=1, ge=1, le=52)
    repeat_unit: Literal["daily", "weekly"] = "weekly"
    week_anchor_date: date
    reminder_timing: RoutineReminderTiming = RoutineReminderTiming.evening_before
    is_critical: bool = False
    pinned: bool = False
    enabled: bool = True
    start_date: date
    end_date: date | None = None
    member_ids: list[uuid.UUID] = Field(default_factory=list, max_length=25)
    expected_updated_at: datetime

    @model_validator(mode="after")
    def _personal_has_no_explicit_members(self) -> "RoutineUpdate":
        if self.scope == RoutineScope.personal and self.member_ids:
            raise ValueError("A personal routine cannot have explicit members")
        if self.repeat_unit == "daily" and self.interval_weeks != 1:
            raise ValueError("Daily routines must use an interval of one")
        return self


class RoutineResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    scope: RoutineScope
    owner_user_id: uuid.UUID | None
    interval_weeks: int
    repeat_unit: Literal["daily", "weekly"]
    week_anchor_date: date
    reminder_timing: RoutineReminderTiming
    is_critical: bool
    pinned: bool
    enabled: bool
    start_date: date
    end_date: date | None
    member_ids: list[uuid.UUID]
    next_occurrence_date: date | None
    completed_today: bool
    created_by: uuid.UUID
    updated_at: datetime


class RoutineListResponse(BaseModel):
    items: list[RoutineResponse]


class RoutineCompletionRequest(StrictModel):
    occurrence_date: date


class NotificationPreferencesResponse(BaseModel):
    push_enabled: bool
    in_app_enabled: bool
    email_enabled: bool
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
    email_enabled: bool
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
