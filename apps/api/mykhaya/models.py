import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mykhaya.db import Base
from mykhaya.ids import uuid7


class Role(StrEnum):
    owner = "owner"
    administrator = "administrator"
    adult_member = "adult_member"
    member = "member"
    guest = "guest"


class PlatformRole(StrEnum):
    owner = "owner"
    administrator = "administrator"
    support_operator = "support_operator"
    read_only_operator = "read_only_operator"


class TokenPurpose(StrEnum):
    verify_email = "verify_email"
    reset_password = "reset_password"


class FeatureFlagKey(StrEnum):
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
    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


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
    memberships: Mapped[list["Membership"]] = relationship(back_populates="group")


class PlatformMembership(UuidTimeMixin, Base):
    __tablename__ = "platform_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_platform_membership_user"),
        Index("ix_platform_membership_role", "role"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[PlatformRole] = mapped_column(Enum(PlatformRole, name="platform_role"))


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
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    group: Mapped[Group] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Invitation(UuidTimeMixin, Base):
    __tablename__ = "group_invitations"
    __table_args__ = (Index("ix_invitation_group_email", "group_id", "email"),)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[Role] = mapped_column(Enum(Role, name="membership_role", create_type=False))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeatureFlag(UuidTimeMixin, Base):
    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint("key", name="uq_feature_flag_key"),
        Index("ix_feature_flag_enabled", "enabled"),
    )
    key: Mapped[FeatureFlagKey] = mapped_column(Enum(FeatureFlagKey, name="feature_key"))
    display_name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_by_platform_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class FeatureFlagHomeOverride(UuidTimeMixin, Base):
    __tablename__ = "feature_flag_home_overrides"
    __table_args__ = (
        UniqueConstraint("feature_flag_id", "group_id", name="uq_feature_override_home_flag"),
        Index("ix_feature_override_group", "group_id"),
    )
    feature_flag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feature_flags.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_by_platform_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


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
