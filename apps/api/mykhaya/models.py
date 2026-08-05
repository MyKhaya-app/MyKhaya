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
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship as orm_relationship

from mykhaya.db import Base
from mykhaya.ids import uuid7


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


class PlatformRole(StrEnum):
    owner = "platform_owner"
    administrator = "platform_administrator"
    support = "support_operator"
    security = "security_operator"
    readonly = "read_only_operator"


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
    # Assigned once at creation via mykhaya.member_colours.assign_member_colour.
    # Household-scoped, not global: the same person can hold a different
    # colour in a different home. See docs/design/visual-identity.md.
    colour: Mapped[str | None] = mapped_column(String(7))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    group: Mapped[Group] = orm_relationship(back_populates="memberships")
    user: Mapped[User] = orm_relationship(back_populates="memberships")


class HomeCalendar(UuidTimeMixin, Base):
    __tablename__ = "home_calendars"
    __table_args__ = (UniqueConstraint("group_id", "is_primary", name="uq_home_primary_calendar"),)
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
    color: Mapped[str] = mapped_column(String(7), default="#456B76")
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
    __table_args__ = (Index("ix_outbox_pending", "processed_at", "available_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    topic: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
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
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("group_memberships.id", ondelete="CASCADE"), unique=True, index=True
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
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL")
    )
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
        Index("ix_routine_group_enabled", "group_id", "enabled"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(String(1000))
    interval_weeks: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
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
