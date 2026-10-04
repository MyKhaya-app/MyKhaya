"""Add the backend foundation for the Founding Beta programme."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0107_founding_beta_phase1"
down_revision: str | None = "0106_calendar_personal_prefs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    for enum in (
        postgresql.ENUM("active", "archived", name="beta_programme_status"),
        postgresql.ENUM("waiting", "invited", "joined", "expired", "declined", "removed", name="beta_waitlist_status"),
        postgresql.ENUM("reserved", "redeemed", "expired", "cancelled", name="beta_invitation_status"),
    ):
        enum.create(bind, checkfirst=True)

    op.add_column("home_subscriptions", sa.Column("complimentary_source", sa.String(length=80)))
    op.add_column("support_ticket_diagnostics", sa.Column("beta_programme", sa.String(length=80)))
    op.add_column("support_ticket_diagnostics", sa.Column("entitlement_source", sa.String(length=80)))
    programme_status = postgresql.ENUM("active", "archived", name="beta_programme_status", create_type=False)
    waitlist_status = postgresql.ENUM("waiting", "invited", "joined", "expired", "declined", "removed", name="beta_waitlist_status", create_type=False)
    invitation_status = postgresql.ENUM("reserved", "redeemed", "expired", "cancelled", name="beta_invitation_status", create_type=False)

    op.create_table(
        "beta_programmes",
        *(_timestamps()),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("max_homes", sa.Integer(), nullable=False),
        sa.Column("waitlist_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("show_remaining_publicly", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("terms_version", sa.String(80), nullable=False),
        sa.Column("invitation_ttl_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column("status", programme_status, server_default="active", nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL")),
        sa.UniqueConstraint("slug", name="uq_beta_programmes_slug"),
    )
    op.create_index("ix_beta_programmes_slug", "beta_programmes", ["slug"], unique=True)
    op.create_table(
        "beta_waitlist_entries",
        *(_timestamps()),
        sa.Column("programme_id", sa.Uuid(), sa.ForeignKey("beta_programmes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("household_size", sa.Integer()),
        sa.Column("use_case", sa.String(500)),
        sa.Column("marketing_consent", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("status", waitlist_status, server_default="waiting", nullable=False),
        sa.UniqueConstraint("programme_id", "normalized_email", name="uq_beta_waitlist_programme_email"),
    )
    op.create_index("ix_beta_waitlist_programme_id", "beta_waitlist_entries", ["programme_id"])
    op.create_index("ix_beta_waitlist_programme_status", "beta_waitlist_entries", ["programme_id", "status"])
    op.create_table(
        "beta_invitations",
        *(_timestamps()),
        sa.Column("programme_id", sa.Uuid(), sa.ForeignKey("beta_programmes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("waitlist_entry_id", sa.Uuid(), sa.ForeignKey("beta_waitlist_entries.id", ondelete="SET NULL")),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", invitation_status, server_default="reserved", nullable=False),
        sa.Column("accepted_home_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="SET NULL")),
        sa.Column("invited_by", sa.Uuid(), sa.ForeignKey("platform_administrators.id", ondelete="SET NULL")),
        sa.UniqueConstraint("token_hash", name="uq_beta_invitations_token_hash"),
    )
    op.create_index("ix_beta_invitations_programme_id", "beta_invitations", ["programme_id"])
    op.create_index("ix_beta_invitations_programme_status", "beta_invitations", ["programme_id", "status"])
    op.create_table(
        "beta_pending_registrations",
        *(_timestamps()),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("programme_id", sa.Uuid(), sa.ForeignKey("beta_programmes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("home_name", sa.String(100), nullable=False),
        sa.Column("terms_version", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invitation_token_hash", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("token_hash", name="uq_beta_pending_registration_token"),
    )
    op.create_index("ix_beta_pending_registration_user_id", "beta_pending_registrations", ["user_id"])
    op.create_index("ix_beta_pending_registration_user_expires", "beta_pending_registrations", ["user_id", "expires_at"])
    op.create_table(
        "beta_enrollments",
        *(_timestamps()),
        sa.Column("programme_id", sa.Uuid(), sa.ForeignKey("beta_programmes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("home_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("joined_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("joined_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("terms_version", sa.String(80), nullable=False),
        sa.Column("source_invitation_id", sa.Uuid(), sa.ForeignKey("beta_invitations.id", ondelete="SET NULL")),
        sa.Column("capacity_exempt", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.UniqueConstraint("programme_id", "home_id", name="uq_beta_enrollment_programme_home"),
        sa.UniqueConstraint("programme_id", "joined_user_id", name="uq_beta_enrollment_programme_user"),
        sa.UniqueConstraint("programme_id", "normalized_email", name="uq_beta_enrollment_programme_email"),
    )
    op.create_index("ix_beta_enrollments_programme_id", "beta_enrollments", ["programme_id"])
    op.create_index("ix_beta_enrollments_home_id", "beta_enrollments", ["home_id"])
    op.create_index("ix_beta_enrollments_joined_user_id", "beta_enrollments", ["joined_user_id"])
    op.create_index("ix_beta_enrollment_programme_counted", "beta_enrollments", ["programme_id", "capacity_exempt"])
    op.execute(
        "INSERT INTO platform_settings (id, created_at, updated_at, key, value) "
        "VALUES (gen_random_uuid(), now(), now(), 'signup_mode', '{\"value\": \"normal\"}') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO beta_programmes (id, created_at, updated_at, slug, name, max_homes, waitlist_enabled, "
        "show_remaining_publicly, terms_version, invitation_ttl_days, status) "
        "VALUES (gen_random_uuid(), now(), now(), 'founding-beta', 'Founding Beta', 100, true, false, '1.1', 7, 'active')"
    )


def downgrade() -> None:
    op.drop_table("beta_enrollments")
    op.drop_table("beta_pending_registrations")
    op.drop_table("beta_invitations")
    op.drop_table("beta_waitlist_entries")
    op.drop_table("beta_programmes")
    op.drop_column("home_subscriptions", "complimentary_source")
    op.drop_column("support_ticket_diagnostics", "entitlement_source")
    op.drop_column("support_ticket_diagnostics", "beta_programme")
    # Leave an administrator-created setting untouched on downgrade. The row
    # is harmless without the Beta tables and deleting it would be destructive
    # if an operator had changed the bootstrap value after deployment.
    postgresql.ENUM(name="beta_invitation_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="beta_waitlist_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="beta_programme_status").drop(op.get_bind(), checkfirst=True)
