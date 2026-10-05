import uuid

from pydantic import EmailStr, Field

from mykhaya.models import SignupMode
from mykhaya.schemas import StrictModel


class SignupStateResponse(StrictModel):
    signup_mode: SignupMode
    registration_open: bool
    invitation_required: bool
    normal_signup_available: bool
    beta_joining_available: bool
    waitlist_available: bool
    joinable_count: int | None = None


class BetaWaitlistCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    country: str = Field(min_length=2, max_length=2)
    household_size: int | None = Field(default=None, ge=1, le=100)
    use_case: str | None = Field(default=None, max_length=500)
    marketing_consent: bool = False


class BetaWaitlistResponse(StrictModel):
    accepted: bool
    status: str


class BetaInvitationResponse(StrictModel):
    valid: bool
    programme: str | None = None
    expires_at: str | None = None


class BetaJoinRequest(StrictModel):
    home_name: str = Field(min_length=1, max_length=100)
    terms_version: str = Field(min_length=1, max_length=80)
    invitation_token: str | None = Field(default=None, min_length=32, max_length=500)


class BetaJoinResponse(StrictModel):
    home_id: uuid.UUID
    entitlement_source: str


class BetaInviteCreate(StrictModel):
    waitlist_entry_id: uuid.UUID


class BetaInviteResponse(StrictModel):
    invitation_id: uuid.UUID
    token: str
    expires_at: str


class BetaOverviewResponse(StrictModel):
    signup_mode: SignupMode
    max_homes: int
    joined: int
    reserved: int
    waiting: int
    joinable: int


class BetaProgrammeResponse(StrictModel):
    id: uuid.UUID
    slug: str
    name: str
    max_homes: int
    waitlist_enabled: bool
    show_remaining_publicly: bool
    invitation_ttl_days: int
    terms_version: str
    status: str


class BetaProgrammeUpdate(StrictModel):
    max_homes: int = Field(ge=1, le=1_000_000)
    waitlist_enabled: bool
    show_remaining_publicly: bool
    invitation_ttl_days: int = Field(ge=1, le=365)
    terms_version: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=10, max_length=500)


class BetaWaitlistItem(StrictModel):
    id: uuid.UUID
    name: str
    email: str
    country: str
    household_size: int | None
    joined_at: str
    status: str


class BetaWaitlistResponsePage(StrictModel):
    items: list[BetaWaitlistItem]
    total: int
    status: str | None = None
    search: str | None = None


class BetaInvitationItem(StrictModel):
    id: uuid.UUID
    applicant: str
    email: str
    status: str
    invited_at: str
    expires_at: str
    reservation_state: str
    accepted_home_id: uuid.UUID | None = None


class BetaInvitationResponsePage(StrictModel):
    items: list[BetaInvitationItem]
    total: int


class BetaCapacityExemptionUpdate(StrictModel):
    exempt: bool
    reason: str = Field(min_length=3, max_length=300)
