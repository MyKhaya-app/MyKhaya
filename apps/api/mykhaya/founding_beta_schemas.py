import uuid
from urllib.parse import urlsplit

from pydantic import EmailStr, Field, field_validator

from mykhaya.models import SignupMode
from mykhaya.schemas import StrictModel

# Hosts an iPhone app link may point at: a TestFlight public link during the
# beta, or the App Store listing once the app is live.
IOS_APP_LINK_HOSTS = frozenset({"testflight.apple.com", "apps.apple.com"})


def _https_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("Enter a full https:// link.")
    if parts.username or parts.password:
        raise ValueError("The link must not contain a username or password.")
    return value


def normalise_app_link(value: str | None, *, ios: bool) -> str | None:
    """Empty means "not set". iPhone links must be https on TestFlight or the
    App Store; Android links may be any https URL."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    _https_url(value)
    if ios and (urlsplit(value).hostname or "").lower() not in IOS_APP_LINK_HOSTS:
        raise ValueError("Use a testflight.apple.com or apps.apple.com link.")
    return value


class SignupStateResponse(StrictModel):
    signup_mode: SignupMode
    registration_open: bool
    invitation_required: bool
    normal_signup_available: bool
    beta_joining_available: bool
    waitlist_available: bool
    joinable_count: int | None = None
    beta_terms_version: str | None = None
    # Site-wide app links (see BetaProgramme.ios_app_url/android_app_url).
    ios_app_url: str | None = None
    android_app_url: str | None = None


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
    # Required for a new Beta Home; ignored when an eligible existing Free
    # Home is enrolled (that Home keeps its own name).
    home_name: str | None = Field(default=None, min_length=1, max_length=100)
    # Optional: the current Founding Beta Terms are normally accepted in the
    # continuation's Terms step (POST /legal/acceptances) before joining. A
    # client may instead send the current version here to accept and join in
    # one call; an already-satisfied acceptance is never recorded twice.
    terms_version: str | None = Field(default=None, min_length=1, max_length=80)
    invitation_token: str | None = Field(default=None, min_length=32, max_length=500)


class BetaJoinResponse(StrictModel):
    home_id: uuid.UUID
    entitlement_source: str


class BetaEligibilityResponse(StrictModel):
    eligible: bool
    home_id: uuid.UUID | None = None
    home_name: str | None = None
    reason: str | None = None


class BetaPendingResponse(StrictModel):
    pending: bool
    home_name: str | None = None
    terms_version: str | None = None


class BetaTermsStatus(StrictModel):
    document_key: str
    display_name: str
    version_id: uuid.UUID
    version: str
    satisfied: bool


class BetaContinuationResponse(StrictModel):
    """Everything the authenticated Founding Beta continuation needs to pick
    its step: welcome + Terms -> Home -> confirm -> done."""

    # This account was created through the Founding Beta and has not enrolled
    # yet: route it to the continuation instead of normal onboarding.
    pending: bool
    enrolled: bool
    enrolled_home_id: uuid.UUID | None = None
    # The current Founding Beta Terms and whether this user has accepted that
    # exact version (None when no Beta Terms document is published).
    terms: BetaTermsStatus | None = None
    eligible: bool
    home_id: uuid.UUID | None = None
    home_name: str | None = None
    reason: str | None = None


class BetaInviteCreate(StrictModel):
    waitlist_entry_id: uuid.UUID


class BetaInviteResponse(StrictModel):
    invitation_id: uuid.UUID
    token: str
    expires_at: str


class BetaOverviewResponse(StrictModel):
    signup_mode: SignupMode
    invitation_required: bool
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
    ios_app_url: str | None = None
    android_app_url: str | None = None
    status: str


class BetaProgrammeUpdate(StrictModel):
    max_homes: int = Field(ge=1, le=1_000_000)
    waitlist_enabled: bool
    show_remaining_publicly: bool
    invitation_ttl_days: int = Field(ge=1, le=365)
    terms_version: str = Field(min_length=1, max_length=80)
    # Optional: omitted = unchanged; "" or null = cleared (link hidden).
    ios_app_url: str | None = Field(default=None, max_length=500)
    android_app_url: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("ios_app_url")
    @classmethod
    def _ios_app_url(cls, value: str | None) -> str | None:
        return normalise_app_link(value, ios=True)

    @field_validator("android_app_url")
    @classmethod
    def _android_app_url(cls, value: str | None) -> str | None:
        return normalise_app_link(value, ios=False)


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
