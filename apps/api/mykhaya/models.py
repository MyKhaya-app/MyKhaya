import secrets
import uuid
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship as orm_relationship

from mykhaya.colour_palette import DEFAULT_LABEL_COLOUR, ColourToken
from mykhaya.db import Base
from mykhaya.ids import uuid7

# Duplicated from mykhaya.security._HOME_CODE_ALPHABET deliberately: security.py
# imports models for its User/Session lookups, so models.py cannot import back from
# it without a circular import. This is only a Python-side ORM default (a safety net
# for direct Group(...) construction, e.g. in tests) — the real, uniqueness-checked
# code generation for the API-facing create-Home flow lives in
# mykhaya.routers.groups._unique_home_code / mykhaya.security.generate_home_code.
_HOME_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _default_child_login_code() -> str:
    return "".join(secrets.choice(_HOME_CODE_ALPHABET) for _ in range(8))


class RecurrencePattern(StrEnum):
    none = "none"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"
    weekdays = "weekdays"


class Role(StrEnum):
    owner = "owner"
    administrator = "administrator"
    adult_member = "adult_member"
    member = "member"
    guest = "guest"


class HouseholdRelationship(StrEnum):
    home_admin = "home_admin"
    partner = "partner"
    child = "child"
    extended_family = "extended_family"
    friend = "friend"
    review_required = "review_required"


class PermissionProfile(StrEnum):
    home_admin = "home_admin"
    standard_partner = "standard_partner"
    child_restricted = "child_restricted"
    explicit_sharing = "explicit_sharing"
    review_required = "review_required"


class ChildAgeBand(StrEnum):
    under_13 = "under_13"
    age_13_15 = "13_to_15"
    age_16_17 = "16_to_17"


class ChildTransitionStatus(StrEnum):
    child = "child"
    review_due = "review_due"
    converted = "converted"


class TokenPurpose(StrEnum):
    verify_email = "verify_email"
    reset_password = "reset_password"


class SessionKind(StrEnum):
    """What kind of principal a Session authenticates — never inferred from the
    User row itself (a managed Child has a perfectly normal User row; the
    session is what marks it as restricted). See docs on managed Child sign-in."""

    adult = "adult"
    managed_child = "managed_child"


class PlatformRole(StrEnum):
    owner = "platform_owner"
    administrator = "platform_administrator"
    support = "support_operator"
    security = "security_operator"
    readonly = "read_only_operator"


class PlatformSessionStatus(StrEnum):
    """Where a PlatformSession sits in the MFA login flow — never inferred from
    PlatformAdministrator.mfa_enrolled alone, since that would let a session
    minted before an MFA policy change silently keep full access. See
    mykhaya.platform_security.platform_context and the login endpoint."""

    # Password verified, second factor verified (or none was required) — full
    # Control Centre access, subject to the normal role/step-up checks.
    full = "full"
    # Password verified, administrator has an enrolled second factor that has not
    # yet been presented this login. Can only reach the MFA-verification
    # endpoints and logout.
    pending_mfa = "pending_mfa"
    # Password verified, admin_mfa_required policy applies to this administrator
    # and they have no enrolled second factor yet. Can only reach MFA-enrollment
    # endpoints and logout — never ordinary Control Centre routes.
    mfa_setup_required = "mfa_setup_required"


class ServiceState(StrEnum):
    operational = "operational"
    degraded = "degraded_performance"
    partial_outage = "partial_outage"
    major_outage = "major_outage"
    maintenance = "maintenance"


class FeatureKey(StrEnum):
    calendar = "calendar"
    tasks = "tasks"
    shopping = "shopping"
    meals = "meals"
    plans = "plans"
    wish_lists = "wish_lists"
    notifications = "notifications"
    external_sharing = "external_sharing"


class UuidTimeMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(UuidTimeMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str | None] = mapped_column(String(100))
    birth_month: Mapped[int | None] = mapped_column(Integer)
    birth_day: Mapped[int | None] = mapped_column(Integer)
    birth_year: Mapped[int | None] = mapped_column(Integer)
    # A new random UUID per upload, not the user's id — a fresh, unpredictable filename
    # each time so a changed avatar naturally invalidates any cached/versioned URL.
    # Never the client-supplied filename. The actual image bytes live on disk under the
    # avatar storage directory (mykhaya/avatars/), never in the database.
    avatar_key: Mapped[str | None] = mapped_column(String(64))
    avatar_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    memberships: Mapped[list["Membership"]] = orm_relationship(back_populates="user")


class AuthIdentity(UuidTimeMixin, Base):
    __tablename__ = "auth_identities"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    password_hash: Mapped[str] = mapped_column(Text)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(UuidTimeMixin, Base):
    __tablename__ = "sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(300), default="Unknown device")
    ip_prefix: Mapped[str | None] = mapped_column(String(80))
    # Set once at issuance from the credential path that authenticated it (adult
    # email/password vs managed Child username/PIN) — never inferred from the User
    # row, so a route can never accidentally treat a managed Child session as an
    # ordinary adult's just because the underlying User looks normal.
    kind: Mapped[SessionKind] = mapped_column(
        Enum(SessionKind, name="session_kind"),
        default=SessionKind.adult,
        server_default=SessionKind.adult.value,
    )


class ActionToken(UuidTimeMixin, Base):
    __tablename__ = "action_tokens"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[TokenPurpose] = mapped_column(Enum(TokenPurpose, name="token_purpose"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Group(UuidTimeMixin, Base):
    __tablename__ = "groups"
    name: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A short, random, non-sequential code — never the Home name or id — that a
    # managed Child types in alongside their username/PIN to identify which Home
    # they belong to at sign-in, without exposing membership or enumerating real
    # Homes. Visible to any existing member of the Home (the same trust boundary
    # as member_count etc.), not a secret in itself; brute-forcing it still has to
    # clear the child-login rate limits same as the username/PIN. See
    # mykhaya.security.generate_home_code.
    child_login_code: Mapped[str] = mapped_column(
        String(10), unique=True, index=True, default=_default_child_login_code
    )
    memberships: Mapped[list["Membership"]] = orm_relationship(back_populates="group")


class Membership(UuidTimeMixin, Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_membership_group_user"),
        Index("ix_membership_group_role", "group_id", "role"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(Enum(Role, name="membership_role"))
    relationship: Mapped[HouseholdRelationship] = mapped_column(
        Enum(HouseholdRelationship, name="household_relationship"),
        default=HouseholdRelationship.review_required,
    )
    permission_profile: Mapped[PermissionProfile] = mapped_column(
        Enum(PermissionProfile, name="permission_profile"),
        default=PermissionProfile.review_required,
    )
    permission_overrides: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    shared_resources: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Assigned once at creation via mykhaya.member_colours.assign_member_colour,
    # editable afterwards by the person themselves or a Home Admin. A palette
    # token, never a raw hex value — see mykhaya.colour_palette. Household-scoped,
    # not global: the same person can hold a different colour in a different
    # home. See docs/design/visual-identity.md.
    colour: Mapped[ColourToken | None] = mapped_column(Enum(ColourToken, name="colour_token"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    group: Mapped[Group] = orm_relationship(back_populates="memberships")
    user: Mapped[User] = orm_relationship(back_populates="memberships")


class HomeCalendar(UuidTimeMixin, Base):
    __tablename__ = "home_calendars"
    # Partial unique index, not a plain UniqueConstraint: exactly one primary
    # calendar per Home is still enforced, but any number of secondary
    # (is_primary=False) calendars is now allowed — see migration
    # 0022_multi_calendar_entitlement and
    # docs/architecture/commercial-entitlements.md#calendar-as-proof-of-architecture.
    __table_args__ = (
        Index(
            "ix_home_calendar_one_primary_per_group",
            "group_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), default="Home Calendar")
    timezone: Mapped[str] = mapped_column(String(100), default="Europe/London")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class CalendarEventLabel(UuidTimeMixin, Base):
    __tablename__ = "calendar_event_labels"
    __table_args__ = (
        UniqueConstraint("group_id", "name", name="uq_event_label_group_name"),
        Index("ix_event_label_group_sort", "group_id", "sort_order"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(40))
    # A palette token, never a raw hex value — see mykhaya.colour_palette. The
    # same shared palette as member colours, but this is the calendar/category
    # identity colour: event bars are coloured by their label, not by who
    # created them. See docs/design/visual-identity.md.
    color: Mapped[ColourToken] = mapped_column(
        Enum(ColourToken, name="colour_token", create_type=False),
        default=DEFAULT_LABEL_COLOUR,
        server_default=DEFAULT_LABEL_COLOUR.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, default=100, server_default="100")


class CalendarEvent(UuidTimeMixin, Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        Index("ix_calendar_event_group_start", "group_id", "start_at"),
        Index("ix_calendar_event_group_end", "group_id", "end_at"),
        Index("ix_calendar_event_group_active", "group_id", "deleted_at"),
        CheckConstraint("char_length(title) >= 1", name="ck_calendar_event_title_nonempty"),
        CheckConstraint("end_at >= start_at", name="ck_calendar_event_valid_range"),
        CheckConstraint("recurrence_interval >= 1", name="ck_calendar_event_recur_interval"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    calendar_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("home_calendars.id", ondelete="CASCADE"), index=True
    )
    label_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calendar_event_labels.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str | None] = mapped_column(String(2000))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    timezone: Mapped[str] = mapped_column(String(100), default="Europe/London")
    location_text: Mapped[str | None] = mapped_column(String(200))
    reminder_minutes: Mapped[int | None] = mapped_column(Integer)
    recurrence: Mapped[RecurrencePattern] = mapped_column(
        Enum(RecurrencePattern, name="recurrence_pattern"),
        default=RecurrencePattern.none,
        server_default=RecurrencePattern.none.value,
    )
    recurrence_interval: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    recurrence_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recurrence_count: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    last_edited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class CalendarEventMember(UuidTimeMixin, Base):
    __tablename__ = "calendar_event_members"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_event_member"),
        Index("ix_event_member_group_user", "group_id", "user_id"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class CalendarEventActivity(UuidTimeMixin, Base):
    __tablename__ = "calendar_event_activity"
    __table_args__ = (Index("ix_event_activity_event_created", "event_id", "created_at"),)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(String(300))


class Invitation(UuidTimeMixin, Base):
    __tablename__ = "group_invitations"
    __table_args__ = (Index("ix_invitation_group_email", "group_id", "email"),)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[Role] = mapped_column(Enum(Role, name="membership_role", create_type=False))
    relationship: Mapped[HouseholdRelationship] = mapped_column(
        Enum(HouseholdRelationship, name="household_relationship", create_type=False)
    )
    permission_profile: Mapped[PermissionProfile] = mapped_column(
        Enum(PermissionProfile, name="permission_profile", create_type=False)
    )
    shared_resources: Mapped[list[str]] = mapped_column(JSON, default=list)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_group_created", "group_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[uuid.UUID | None]
    request_id: Mapped[str | None] = mapped_column(String(80))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_pending", "processed_at", "available_at"),
        UniqueConstraint("dedupe_key", name="uq_outbox_events_dedupe_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    topic: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    # Durable identity for a scheduled occurrence. Nullable because ordinary
    # transactional notifications do not have a recurring schedule identity.
    dedupe_key: Mapped[str | None] = mapped_column(String(255))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500))


class WorkerJobRecord(Base):
    __tablename__ = "worker_job_records"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    outbox_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="SET NULL"), unique=True
    )
    topic: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(500))


class PlatformAdministrator(UuidTimeMixin, Base):
    __tablename__ = "platform_administrators"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[PlatformRole] = mapped_column(
        Enum(
            PlatformRole,
            name="platform_role",
            values_callable=lambda enum: [item.value for item in enum],
        )
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # True once at least one second factor (TOTP or a WebAuthn credential) is
    # enrolled. Never set directly by an endpoint that isn't the enrollment
    # completion itself — see mykhaya.platform_mfa.
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Encrypted with the same mykhaya.secrets_crypto approach as the SMTP/VAPID
    # secrets — never plaintext at rest, never returned by any endpoint once set.
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    totp_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformAdministratorInvitation(UuidTimeMixin, Base):
    """The only normal path to a new PlatformAdministrator row besides the
    one-time bootstrap script — see mykhaya.routers.platform's
    /administrators/invitations endpoints. The token itself is never stored:
    only its HMAC (token_hash, same convention as Session/ActionToken), and it
    is genuinely random (secrets.token_urlsafe) rather than derived from this
    row's id, specifically so reissuing can invalidate the previous token by
    simply overwriting token_hash — the old raw value stops matching anything."""

    __tablename__ = "platform_administrator_invitations"
    email: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[PlatformRole] = mapped_column(
        Enum(
            PlatformRole,
            name="platform_role",
            values_callable=lambda enum: [item.value for item in enum],
            create_type=False,
        )
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformSession(UuidTimeMixin, Base):
    __tablename__ = "platform_sessions"
    administrator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(300), default="Unknown device")
    source_ip: Mapped[str] = mapped_column(String(64))
    status: Mapped[PlatformSessionStatus] = mapped_column(
        Enum(PlatformSessionStatus, name="platform_session_status"),
        default=PlatformSessionStatus.full,
        server_default=PlatformSessionStatus.full.value,
    )


class AdminWebAuthnCredential(UuidTimeMixin, Base):
    """A registered passkey/security key for a platform administrator. Standard
    WebAuthn public-key credential storage — see mykhaya.platform_mfa. Never
    stores a private key; the private key never leaves the authenticator."""

    __tablename__ = "admin_webauthn_credentials"
    administrator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="CASCADE"), index=True
    )
    # Base64url-encoded credential ID, as returned by the authenticator — the
    # handle used to look up this credential on every authentication attempt.
    credential_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    public_key: Mapped[str] = mapped_column(Text)
    sign_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Chosen by the administrator at registration time (e.g. "YubiKey 5C",
    # "iPhone Face ID") — display only, never used for lookup.
    label: Mapped[str] = mapped_column(String(100))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminRecoveryCode(UuidTimeMixin, Base):
    __tablename__ = "admin_recovery_codes"
    administrator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="CASCADE"), index=True
    )
    # HMAC-SHA256 (mykhaya.security.hash_secret), same convention as session/
    # action tokens — a recovery code is a high-entropy single-use secret, not a
    # low-entropy PIN, so it doesn't need pwdlib's slower password hashing.
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackupRun(UuidTimeMixin, Base):
    """One row per backup attempt, written by infrastructure/scripts/backup.sh on
    completion — see docs/operations/backup-and-restore.md. The application never
    triggers a backup itself; this table only records outcomes so the Control
    Centre can show authoritative last-success/overdue state instead of assuming
    health from the presence of a backup directory."""

    __tablename__ = "backup_runs"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    # Free-text but never a raw stack trace or secret — the script only ever
    # writes short, fixed operational messages here.
    detail: Mapped[str | None] = mapped_column(String(500))


class AdministrativeAuditEvent(Base):
    __tablename__ = "administrative_audit_events"
    __table_args__ = (
        Index("ix_admin_audit_created", "created_at"),
        Index("ix_admin_audit_target", "target_type", "target_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    administrator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )
    administrator_role: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[uuid.UUID | None]
    outcome: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(String(500))
    source_ip: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(80))
    session_reference: Mapped[str | None] = mapped_column(String(64))
    previous_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    new_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_category: Mapped[str | None] = mapped_column(String(80))


class AdministrativeNote(UuidTimeMixin, Base):
    __tablename__ = "administrative_notes"
    __table_args__ = (Index("ix_admin_note_target", "target_type", "target_id"),)
    administrator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="RESTRICT")
    )
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[uuid.UUID]
    body: Mapped[str] = mapped_column(String(1000))


class SecurityEvent(Base):
    __tablename__ = "security_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    outcome: Mapped[str] = mapped_column(String(30))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    administrator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )
    source_ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(80))
    safe_detail: Mapped[str | None] = mapped_column(String(500))


class SmtpConnectionSecurity(StrEnum):
    none = "none"
    starttls = "starttls"
    tls = "tls"


class PlatformSmtpSettings(UuidTimeMixin, Base):
    """Platform-Admin-managed SMTP configuration. Single row; app logic enforces that.

    Used only when no MYKHAYA_SMTP_* environment override is active — see
    mykhaya.mailer.resolve_smtp_config and docs/architecture/platform-control-centre.md.
    """

    __tablename__ = "platform_smtp_settings"
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    host: Mapped[str] = mapped_column(String(255), default="", server_default="")
    port: Mapped[int] = mapped_column(Integer, default=587, server_default="587")
    connection_security: Mapped[SmtpConnectionSecurity] = mapped_column(
        Enum(
            SmtpConnectionSecurity,
            name="smtp_connection_security",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=SmtpConnectionSecurity.starttls,
        server_default=SmtpConnectionSecurity.starttls.value,
    )
    auth_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    username: Mapped[str | None] = mapped_column(String(320))
    encrypted_password: Mapped[str | None] = mapped_column(Text)
    sender_name: Mapped[str] = mapped_column(
        String(100), default="MyKhaya", server_default="MyKhaya"
    )
    sender_email: Mapped[str] = mapped_column(String(320), default="", server_default="")
    reply_to: Mapped[str | None] = mapped_column(String(320))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    updated_by_administrator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )


class PlatformSetting(UuidTimeMixin, Base):
    __tablename__ = "platform_settings"
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )


class FeatureFlag(UuidTimeMixin, Base):
    __tablename__ = "feature_flags"
    key: Mapped[FeatureKey] = mapped_column(Enum(FeatureKey, name="feature_key"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    release_state: Mapped[str | None] = mapped_column(String(30))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )


class FeatureOverride(UuidTimeMixin, Base):
    __tablename__ = "feature_overrides"
    __table_args__ = (UniqueConstraint("feature_key", "group_id", name="uq_feature_group"),)
    feature_key: Mapped[FeatureKey] = mapped_column(
        Enum(FeatureKey, name="feature_key", create_type=False)
    )
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class ChildProfile(UuidTimeMixin, Base):
    __tablename__ = "child_profiles"
    __table_args__ = (
        # Denormalized from Membership.group_id (a membership never moves between
        # Homes, so this is safe to duplicate) specifically so this uniqueness can be
        # a real database constraint rather than a check-then-write application
        # query: Postgres serialises the two concurrent inserts/updates and rejects
        # whichever loses the race with a real IntegrityError, so
        # "Home + username_normalised" can never end up duplicated even under
        # concurrent requests. NULLs (login not configured) are exempt as usual —
        # Postgres unique indexes never treat two NULLs as equal.
        UniqueConstraint(
            "group_id", "username_normalised", name="uq_child_login_username_per_home"
        ),
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("group_memberships.id", ondelete="CASCADE"), unique=True, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    age_band: Mapped[ChildAgeBand] = mapped_column(Enum(ChildAgeBand, name="child_age_band"))
    permissions: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    transition_status: Mapped[ChildTransitionStatus] = mapped_column(
        Enum(ChildTransitionStatus, name="child_transition_status"),
        default=ChildTransitionStatus.child,
    )
    birth_month: Mapped[int | None] = mapped_column(Integer)
    birth_day: Mapped[int | None] = mapped_column(Integer)
    birth_year: Mapped[int | None] = mapped_column(Integer)
    birthday_visible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Managed Child sign-in (optional, parent-configured) — the Child remains this
    # same managed identity, never converted into a normal email/password User.
    # Username uniqueness within the Home is a real database constraint — see
    # uq_child_login_username_per_home above — backed by an application-layer
    # pre-check in children.py for a friendly error message on the common case.
    login_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    username_normalised: Mapped[str | None] = mapped_column(String(32))
    # A pwdlib hash (the same hasher as adult passwords, see mykhaya.security), never
    # the raw PIN. Cleared whenever login is disabled — see children.py's disable path.
    pin_hash: Mapped[str | None] = mapped_column(Text)
    login_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GuardianAssignment(UuidTimeMixin, Base):
    __tablename__ = "guardian_assignments"
    __table_args__ = (
        UniqueConstraint("child_profile_id", "guardian_membership_id", name="uq_child_guardian"),
    )
    child_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("child_profiles.id", ondelete="CASCADE"), index=True
    )
    guardian_membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("group_memberships.id", ondelete="CASCADE"), index=True
    )
    assigned_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )


class PublicIncident(UuidTimeMixin, Base):
    __tablename__ = "public_incidents"
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(String(1000))
    service: Mapped[str] = mapped_column(String(40))
    state: Mapped[ServiceState] = mapped_column(
        Enum(
            ServiceState,
            name="service_state",
            values_callable=lambda enum: [item.value for item in enum],
        )
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="RESTRICT")
    )


class OperationalHeartbeat(Base):
    __tablename__ = "operational_heartbeats"
    service: Mapped[str] = mapped_column(String(40), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_detail: Mapped[str | None] = mapped_column(String(300))


# --- Notification Engine -----------------------------------------------------
# Every channel (email/push/in-app) and every future notification-producing
# module (calendar, household routines, birthdays, invitations, ...) shares
# this schema. See mykhaya/notifications/engine.py and
# docs/architecture/notification-engine.md.


class NotificationChannel(StrEnum):
    email = "email"
    push = "push"
    in_app = "in_app"


class NotificationDeliveryStatus(StrEnum):
    queued = "queued"
    sent = "sent"
    failed = "failed"
    cancelled = "cancelled"


class LockScreenPreviewLevel(StrEnum):
    full = "full"
    title_only = "title_only"
    hidden = "hidden"


class BriefingDays(StrEnum):
    daily = "daily"
    weekdays = "weekdays"


class RoutineReminderTiming(StrEnum):
    evening_before = "evening_before"
    same_day = "same_day"
    both = "both"


class RoutineScope(StrEnum):
    """Personal: owned by exactly one member, notifications go only to that owner.
    Household: Home-level, notifications go to explicit HouseholdRoutineMember
    assignees or (if none) the whole household. See
    docs/architecture/notification-engine.md and mykhaya.notifications.routines."""

    personal = "personal"
    household = "household"


class PushSubscription(UuidTimeMixin, Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (Index("ix_push_subscriptions_user", "user_id", "disabled_at"),)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh_key: Mapped[str] = mapped_column(String(255))
    auth_key: Mapped[str] = mapped_column(String(255))
    device_label: Mapped[str | None] = mapped_column(String(120))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_reason: Mapped[str | None] = mapped_column(String(200))


class Notification(UuidTimeMixin, Base):
    """In-app notification centre row."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_recipient_created", "recipient_user_id", "created_at"),
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    notification_type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(500))
    related_entity_type: Mapped[str | None] = mapped_column(String(50))
    related_entity_id: Mapped[uuid.UUID | None]
    deep_link: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationDelivery(Base):
    """One row per recipient per channel per attempt-group — the diagnostics/timeline
    backbone. A single OutboxEvent can fan out to many rows (e.g. push to N devices)."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index("ix_notification_deliveries_attempted", "attempted_at"),
        Index("ix_notification_deliveries_recipient", "recipient_user_id", "channel"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel")
    )
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    notification_type: Mapped[str] = mapped_column(String(100), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True)
    outbox_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="SET NULL")
    )
    push_subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("push_subscriptions.id", ondelete="SET NULL")
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[NotificationDeliveryStatus] = mapped_column(
        Enum(NotificationDeliveryStatus, name="notification_delivery_status"),
        default=NotificationDeliveryStatus.queued,
        server_default=NotificationDeliveryStatus.queued.value,
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sanitised_failure_reason: Mapped[str | None] = mapped_column(String(300))
    used_template_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )


class NotificationPreferences(UuidTimeMixin, Base):
    __tablename__ = "notification_preferences"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Default off, unlike push_enabled/in_app_enabled — email is an explicit opt-in
    # "also send me an email" channel for optional notification types, not a third
    # always-on channel that would triple send volume for every reminder/briefing/
    # routine/birthday. MANDATORY_EMAIL_TYPES (verification, reset, invitation) always
    # send by email regardless of this toggle. See docs/architecture/notification-engine.md.
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    event_reminders_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    event_invitations_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    event_changes_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    household_reminders_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    daily_briefing_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    briefing_time: Mapped[time] = mapped_column(
        Time, default=time(7, 30), server_default="07:30:00"
    )
    briefing_days: Mapped[BriefingDays] = mapped_column(
        Enum(BriefingDays, name="briefing_days"),
        default=BriefingDays.daily,
        server_default=BriefingDays.daily.value,
    )
    empty_day_briefing_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    lock_screen_preview_level: Mapped[LockScreenPreviewLevel] = mapped_column(
        Enum(LockScreenPreviewLevel, name="lock_screen_preview_level"),
        default=LockScreenPreviewLevel.title_only,
        server_default=LockScreenPreviewLevel.title_only.value,
    )
    quiet_hours_start: Mapped[time | None] = mapped_column(Time)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time)
    quiet_hours_critical_only: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )


class HouseholdRoutine(UuidTimeMixin, Base):
    __tablename__ = "household_routines"
    __table_args__ = (
        CheckConstraint("char_length(title) >= 1", name="ck_routine_title_nonempty"),
        CheckConstraint("interval_weeks >= 1", name="ck_routine_interval_weeks"),
        CheckConstraint("repeat_unit IN ('daily', 'weekly')", name="ck_routine_repeat_unit"),
        # A personal routine must have an owner to notify; a household routine's
        # recipients come from HouseholdRoutineMember/whole-household instead, so it
        # must not carry a single owner that notification targeting could mistake for
        # the recipient. See mykhaya.notifications.routines._recipients_for.
        CheckConstraint(
            "(scope = 'personal' AND owner_user_id IS NOT NULL) OR "
            "(scope = 'household' AND owner_user_id IS NULL)",
            name="ck_routine_scope_owner",
        ),
        Index("ix_routine_group_enabled", "group_id", "enabled"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(String(1000))
    scope: Mapped[RoutineScope] = mapped_column(
        Enum(RoutineScope, name="routine_scope"),
        default=RoutineScope.household,
        server_default=RoutineScope.household.value,
    )
    # Set only for scope=personal — the sole notification recipient. Never trusted
    # from client input; always inferred from the authenticated actor. Distinct from
    # created_by, which is audit attribution and exists for every routine regardless
    # of scope.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    interval_weeks: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Weekly is the legacy behaviour. Daily routines keep the same anchor/date
    # bounds while using a separate unit so existing interval_weeks data remains
    # backwards compatible.
    repeat_unit: Mapped[str] = mapped_column(String(10), default="weekly", server_default="weekly")
    week_anchor_date: Mapped[date] = mapped_column(Date)
    reminder_timing: Mapped[RoutineReminderTiming] = mapped_column(
        Enum(RoutineReminderTiming, name="routine_reminder_timing"),
        default=RoutineReminderTiming.evening_before,
        server_default=RoutineReminderTiming.evening_before.value,
    )
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class HouseholdRoutineMember(UuidTimeMixin, Base):
    __tablename__ = "household_routine_members"
    __table_args__ = (UniqueConstraint("routine_id", "user_id", name="uq_routine_member"),)
    routine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household_routines.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )


class HouseholdRoutineCompletion(UuidTimeMixin, Base):
    __tablename__ = "household_routine_completions"
    __table_args__ = (
        UniqueConstraint("routine_id", "occurrence_date", name="uq_routine_occurrence"),
    )
    routine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household_routines.id", ondelete="CASCADE"), index=True
    )
    occurrence_date: Mapped[date] = mapped_column(Date, index=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlatformPushSettings(UuidTimeMixin, Base):
    """Platform-Admin-managed Web Push (VAPID) configuration. Single row; app logic
    enforces that. Same environment-wins precedence model as PlatformSmtpSettings."""

    __tablename__ = "platform_push_settings"
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    vapid_public_key: Mapped[str | None] = mapped_column(Text)
    encrypted_vapid_private_key: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(String(320))
    updated_by_administrator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )


class StripeMode(StrEnum):
    test = "test"
    live = "live"


class PlatformStripeSettings(UuidTimeMixin, Base):
    """Platform-Admin-managed Stripe configuration. Single row; app logic enforces
    that. Unlike PlatformSmtpSettings/PlatformPushSettings, this row — once
    `enabled` — takes precedence *over* the MYKHAYA_STRIPE_* environment
    variables, not the other way round; see mykhaya.billing.config.resolve_stripe_config
    and docs/architecture/platform-control-centre.md#stripe-configuration-precedence.

    Test and Live credentials are stored in entirely separate columns so switching
    `mode` can never mix them, and each mode's secret/webhook columns are encrypted
    independently (mykhaya.secrets_crypto.encrypt_stripe_secret) — this migration
    only creates the ciphertext columns, it never writes a plaintext value.
    """

    __tablename__ = "platform_stripe_settings"
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    mode: Mapped[StripeMode] = mapped_column(
        Enum(
            StripeMode,
            name="stripe_mode",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=StripeMode.test,
        server_default=StripeMode.test.value,
    )
    test_publishable_key: Mapped[str | None] = mapped_column(String(200))
    encrypted_test_secret_key: Mapped[str | None] = mapped_column(Text)
    encrypted_test_webhook_secret: Mapped[str | None] = mapped_column(Text)
    test_family_monthly_price_id: Mapped[str | None] = mapped_column(String(200))
    test_family_annual_price_id: Mapped[str | None] = mapped_column(String(200))
    live_publishable_key: Mapped[str | None] = mapped_column(String(200))
    encrypted_live_secret_key: Mapped[str | None] = mapped_column(Text)
    encrypted_live_webhook_secret: Mapped[str | None] = mapped_column(Text)
    live_family_monthly_price_id: Mapped[str | None] = mapped_column(String(200))
    live_family_annual_price_id: Mapped[str | None] = mapped_column(String(200))
    updated_by_administrator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )


class NotificationTemplate(UuidTimeMixin, Base):
    """Override-only: trusted default copy lives in code
    (mykhaya/notifications/default_templates.py). A row here exists only once a Platform
    Admin has customised that template_type/channel; deleting the row resets to default."""

    __tablename__ = "notification_templates"
    __table_args__ = (
        UniqueConstraint("template_type", "channel", name="uq_template_type_channel"),
    )
    template_type: Mapped[str] = mapped_column(String(60), index=True)
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_template_channel")
    )
    subject: Mapped[str | None] = mapped_column(String(200))
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Which mykhaya.notifications.default_templates.DEFAULT_TEMPLATE_VERSION this
    # override was saved against — lets a future admin UI flag "the built-in wording
    # has changed since you customised this" without diffing text.
    based_on_default_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_by_administrator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )


class NotificationTemplateRevision(Base):
    """Snapshot of the previous override, kept on every save so a bad edit is one click
    from recovery. The code default itself never needs versioning here."""

    __tablename__ = "notification_template_revisions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_templates.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str | None] = mapped_column(String(200))
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    replaced_by_administrator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )


# ---------------------------------------------------------------------------
# Commercial: plans, subscriptions, entitlements. See
# docs/architecture/commercial-entitlements.md. A subscription belongs to a
# Home (Group), never to an individual user — every member inherits the
# Home's commercial capabilities, subject to their normal permissions.
# Deliberately a separate layer from FeatureKey/FeatureOverride (platform
# feature flags) and Capability (Home/user permissions): a feature can be
# globally enabled but still unavailable to a Free Home, and a Family
# subscription never grants a permission a role wouldn't otherwise have.
# ---------------------------------------------------------------------------


class SubscriptionPlan(StrEnum):
    free = "free"
    family = "family"


class SubscriptionProvider(StrEnum):
    free = "free"
    complimentary = "complimentary"
    stripe = "stripe"
    # Reserved for later phases — not implemented, not selectable via any
    # current API. Present now so the enum doesn't need a migration when
    # they arrive.
    apple = "apple"
    google = "google"


class SubscriptionStatus(StrEnum):
    """Normalised regardless of provider — mykhaya.entitlements.effective_plan
    is the single place that decides which of these count as "paying"."""

    active = "active"
    trialing = "trialing"
    past_due = "past_due"
    cancel_at_period_end = "cancel_at_period_end"
    cancelled = "cancelled"


class BillingInterval(StrEnum):
    """Monthly vs. annual are two billing intervals of the same `family`
    plan — never separate MyKhaya plans. Null on HomeSubscription for
    free/complimentary, where no billing interval applies."""

    month = "month"
    year = "year"


class HomeSubscription(UuidTimeMixin, Base):
    """One row per Home — the authoritative commercial state. Only ever
    written through mykhaya.entitlements or a privileged Platform Control
    Centre pathway; never accepts client-submitted plan/provider/status
    (see routers.groups, which never exposes these fields on ordinary Home
    update endpoints, and routers.platform's complimentary-grant endpoint,
    which is the only writer of provider=complimentary)."""

    __tablename__ = "home_subscriptions"
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), unique=True, index=True
    )
    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan, name="subscription_plan"),
        default=SubscriptionPlan.free,
        server_default=SubscriptionPlan.free.value,
    )
    provider: Mapped[SubscriptionProvider] = mapped_column(
        Enum(SubscriptionProvider, name="subscription_provider"),
        default=SubscriptionProvider.free,
        server_default=SubscriptionProvider.free.value,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status"),
        default=SubscriptionStatus.active,
        server_default=SubscriptionStatus.active.value,
    )
    # Nominally responsible member for billing/plan questions — informational only
    # in Phase 1 (no billing exists yet); not required for Free or Complimentary.
    billing_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # External-provider metadata — meaningless for free/complimentary, populated
    # only once Stripe (Phase 3) actually creates a customer/subscription. Kept
    # minimal deliberately: Stripe remains authoritative for anything MyKhaya
    # doesn't itself need for entitlement resolution or admin visibility.
    # Unique: one Stripe Customer must never be attached to more than one Home.
    external_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    external_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    # The exact Stripe Price this subscription is actually billed against right
    # now — never the currently-configured signup price. A later change to
    # Settings.stripe_family_*_price_id only affects new Checkout Sessions;
    # this column is how an existing subscriber's grandfathered price is known.
    external_price_id: Mapped[str | None] = mapped_column(String(255), index=True)
    billing_interval: Mapped[BillingInterval | None] = mapped_column(
        Enum(BillingInterval, name="billing_interval")
    )
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Complimentary access — a first-class MyKhaya concept, not a fake/100%-off
    # Stripe subscription. Only ever set via the Platform Control Centre.
    complimentary_reason: Mapped[str | None] = mapped_column(String(200))
    # Operator-only context (e.g. "friend of the founder, see ticket #123") —
    # never returned to household users. See routers.platform's household-facing
    # response builder, which omits this field entirely for non-admin callers.
    complimentary_note: Mapped[str | None] = mapped_column(String(1000))
    complimentary_granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )
    complimentary_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Null = never expires. Evaluated dynamically at resolution time
    # (mykhaya.entitlements.effective_plan) — no scheduler needed to "notice"
    # an expiry; the very next resolution after the timestamp passes simply
    # stops returning Family.
    complimentary_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HomeSubscriptionEvent(Base):
    """Append-only, structured commercial-state history — separate from the
    free-text metadata on AuditEvent/AdministrativeAuditEvent so a future
    billing-support investigation can query "every plan/provider/status
    transition for this Home" directly, without parsing JSON blobs. Written
    by mykhaya.entitlements.record_subscription_event alongside (not instead
    of) the normal platform_audit()/audit() call for whatever action caused
    the change."""

    __tablename__ = "home_subscription_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(60))
    from_plan: Mapped[SubscriptionPlan | None] = mapped_column(
        Enum(SubscriptionPlan, name="subscription_plan", create_type=False)
    )
    to_plan: Mapped[SubscriptionPlan | None] = mapped_column(
        Enum(SubscriptionPlan, name="subscription_plan", create_type=False)
    )
    from_provider: Mapped[SubscriptionProvider | None] = mapped_column(
        Enum(SubscriptionProvider, name="subscription_provider", create_type=False)
    )
    to_provider: Mapped[SubscriptionProvider | None] = mapped_column(
        Enum(SubscriptionProvider, name="subscription_provider", create_type=False)
    )
    from_status: Mapped[SubscriptionStatus | None] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status", create_type=False)
    )
    to_status: Mapped[SubscriptionStatus | None] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status", create_type=False)
    )
    actor_administrator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_administrators.id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(String(300))


class StripeWebhookEvent(Base):
    """Durable, transactional deduplication for Stripe webhook delivery —
    Stripe retries events, and can deliver the same event more than once even
    without a retry (see docs/architecture/commercial-entitlements.md#webhooks).
    The unique constraint on stripe_event_id, inserted in the same transaction
    as any resulting HomeSubscription mutation, is the actual safety
    mechanism — not an in-memory cache. Deliberately minimal: no full webhook
    payload is stored, only enough to dedupe and to support troubleshooting a
    failed/ignored event."""

    __tablename__ = "stripe_webhook_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    stripe_event_id: Mapped[str] = mapped_column(String(255), unique=True)
    event_type: Mapped[str] = mapped_column(String(100))
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), index=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "processed" | "ignored" (valid event, no handler / no material change).
    # A processing failure never reaches this table at all — see
    # StripeWebhookFailure below and the module docstring on
    # mykhaya.billing.webhooks for why (a committed row here would
    # permanently deduplicate away Stripe's retry of a failed attempt).
    outcome: Mapped[str] = mapped_column(String(20))
    # Unused by any current writer — retained only so an already-deployed
    # database column isn't dropped and recreated without cause. See
    # StripeWebhookFailure.error_message for where failure detail actually
    # lives (Phase 7).
    error_message: Mapped[str | None] = mapped_column(String(500))


class StripeWebhookFailure(Base):
    """Append-only observability log for a webhook processing *failure*
    (Phase 7) — deliberately separate from StripeWebhookEvent, which must
    stay reserved for successful dedup so a failed attempt keeps being
    retried by Stripe rather than being permanently swallowed (see
    mykhaya.billing.webhooks's module docstring). This table is never
    consulted for dedup/authorization — only for Platform Control Centre
    diagnostics (docs/architecture/commercial-entitlements.md#webhook-observability).
    The same stripe_event_id may appear here more than once if Stripe
    retries and it fails again each time — that repetition is itself a
    useful signal, not a bug."""

    __tablename__ = "stripe_webhook_failures"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    stripe_event_id: Mapped[str | None] = mapped_column(String(255), index=True)
    event_type: Mapped[str | None] = mapped_column(String(100))
    # Sanitised troubleshooting context only — never a raw Stripe payload.
    error_message: Mapped[str] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
