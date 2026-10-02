"""Add the provider-neutral external identity foundation.

This is an additive schema change only.  It creates no identities and does not
alter existing users, authentication methods, Homes, memberships or sessions.

Revision ID: 0068_external_identities
Revises: 0067_family_retention_lifecycle
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0068_external_identities"
down_revision: str | None = "0067_family_retention_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_EXTERNAL_IDENTITY_PROVIDER = postgresql.ENUM(
    "apple", "google", name="external_identity_provider", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    _EXTERNAL_IDENTITY_PROVIDER.create(bind)
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", _EXTERNAL_IDENTITY_PROVIDER, nullable=False),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(320), nullable=True),
        sa.Column(
            "provider_email_verified", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_subject", name="uq_external_identity_provider_subject"
        ),
    )
    op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_external_identities_user_id", table_name="external_identities")
    op.drop_table("external_identities")
    _EXTERNAL_IDENTITY_PROVIDER.drop(op.get_bind())
