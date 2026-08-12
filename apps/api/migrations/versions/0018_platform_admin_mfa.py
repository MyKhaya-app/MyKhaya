"""Platform administrator MFA: WebAuthn passkeys, TOTP authenticator app, recovery
codes, a session-level MFA-flow status, and backup-run tracking for the Platform
Control Centre's health cards.

- platform_administrators gains totp_secret_encrypted / totp_enabled /
  totp_verified_at. mfa_enrolled already existed but nothing could ever set it —
  this migration doesn't touch its meaning, only adds the credential storage that
  the new enrollment endpoints will use to earn that flag honestly.
- platform_sessions gains status (full / pending_mfa / mfa_setup_required),
  defaulted and backfilled to 'full' for every existing session — every session
  that exists today was authenticated under the old all-or-nothing model, which
  is exactly what 'full' means.
- admin_webauthn_credentials, admin_recovery_codes: new, additive, one row per
  credential/code.
- backup_runs: new, additive — written by infrastructure/scripts/backup.sh on
  completion, read by the Control Centre's Backup Service health card.

Revision ID: 0018_platform_admin_mfa
Revises: 0017_child_login_uniqueness
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_platform_admin_mfa"
down_revision: str | None = "0017_child_login_uniqueness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "platform_administrators", sa.Column("totp_secret_encrypted", sa.Text(), nullable=True)
    )
    op.add_column(
        "platform_administrators",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "platform_administrators",
        sa.Column("totp_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    postgresql.ENUM("full", "pending_mfa", "mfa_setup_required", name="platform_session_status").create(
        bind
    )
    op.add_column(
        "platform_sessions",
        sa.Column(
            "status",
            postgresql.ENUM(
                "full",
                "pending_mfa",
                "mfa_setup_required",
                name="platform_session_status",
                create_type=False,
            ),
            nullable=False,
            server_default="full",
        ),
    )

    op.create_table(
        "admin_webauthn_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column(
            "administrator_id",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_id", sa.String(255), nullable=False, unique=True),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_admin_webauthn_credentials_administrator_id",
        "admin_webauthn_credentials",
        ["administrator_id"],
    )
    op.create_index(
        "ix_admin_webauthn_credentials_credential_id",
        "admin_webauthn_credentials",
        ["credential_id"],
        unique=True,
    )

    op.create_table(
        "admin_recovery_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column(
            "administrator_id",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_admin_recovery_codes_administrator_id", "admin_recovery_codes", ["administrator_id"]
    )
    op.create_index(
        "ix_admin_recovery_codes_code_hash", "admin_recovery_codes", ["code_hash"], unique=True
    )

    op.create_table(
        "backup_runs",
        # Unlike every other table, rows here are also inserted via a raw psql
        # INSERT from infrastructure/scripts/backup.sh, outside the ORM — so id
        # needs a server-side default, not just SQLAlchemy's Python-side uuid7.
        # gen_random_uuid() has been a core Postgres function (no extension
        # required) since Postgres 13.
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("detail", sa.String(500), nullable=True),
    )
    op.create_index("ix_backup_runs_started_at", "backup_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_backup_runs_started_at", table_name="backup_runs")
    op.drop_table("backup_runs")

    op.drop_index("ix_admin_recovery_codes_code_hash", table_name="admin_recovery_codes")
    op.drop_index("ix_admin_recovery_codes_administrator_id", table_name="admin_recovery_codes")
    op.drop_table("admin_recovery_codes")

    op.drop_index(
        "ix_admin_webauthn_credentials_credential_id", table_name="admin_webauthn_credentials"
    )
    op.drop_index(
        "ix_admin_webauthn_credentials_administrator_id", table_name="admin_webauthn_credentials"
    )
    op.drop_table("admin_webauthn_credentials")

    op.drop_column("platform_sessions", "status")
    bind = op.get_bind()
    postgresql.ENUM(name="platform_session_status").drop(bind)

    op.drop_column("platform_administrators", "totp_verified_at")
    op.drop_column("platform_administrators", "totp_enabled")
    op.drop_column("platform_administrators", "totp_secret_encrypted")
