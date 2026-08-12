"""Platform Administrator invitations — the normal, ongoing way to add a new
Platform Administrator through the Control Centre, replacing direct database
manipulation for anything after the very first (bootstrap) Owner.

Revision ID: 0019_platform_admin_invitations
Revises: 0018_platform_admin_mfa
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_platform_admin_invitations"
down_revision: str | None = "0018_platform_admin_mfa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_administrator_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "platform_owner",
                "platform_administrator",
                "support_operator",
                "security_operator",
                "read_only_operator",
                name="platform_role",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "invited_by",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_platform_administrator_invitations_email",
        "platform_administrator_invitations",
        ["email"],
    )
    op.create_index(
        "ix_platform_administrator_invitations_token_hash",
        "platform_administrator_invitations",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_administrator_invitations_token_hash",
        table_name="platform_administrator_invitations",
    )
    op.drop_index(
        "ix_platform_administrator_invitations_email",
        table_name="platform_administrator_invitations",
    )
    op.drop_table("platform_administrator_invitations")
