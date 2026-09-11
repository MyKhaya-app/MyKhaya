"""Add the explicit Family retention lifecycle state machine.

Revision ID: 0067_family_retention_lifecycle
Revises: 0066_family_sponsorship_choices
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0067_family_retention_lifecycle"
down_revision: str | None = "0066_family_sponsorship_choices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE home_retention_state AS ENUM "
        "('retained_free', 'restored', 'purge_pending', 'purged'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    retention_state_column = postgresql.ENUM(
        "retained_free",
        "restored",
        "purge_pending",
        "purged",
        name="home_retention_state",
        create_type=False,
    )

    op.create_table(
        "home_retention_lifecycles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("home_id", sa.Uuid(), nullable=False),
        sa.Column("state", retention_state_column, server_default="retained_free", nullable=False),
        sa.Column("family_expired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["home_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("home_id", name="uq_home_retention_lifecycle_home"),
    )
    op.create_index(
        "ix_home_retention_lifecycles_home_id", "home_retention_lifecycles", ["home_id"], unique=False
    )
    op.create_index(
        "ix_home_retention_due",
        "home_retention_lifecycles",
        ["state", "retention_deadline"],
        unique=False,
    )

    op.create_table(
        "home_retention_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("lifecycle_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relationship",
            postgresql.ENUM(name="household_relationship", create_type=False),
            nullable=False,
        ),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["lifecycle_id"], ["home_retention_lifecycles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["membership_id"], ["group_memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lifecycle_id", "membership_id", name="uq_retention_membership"),
    )
    op.create_index(
        "ix_home_retention_memberships_lifecycle_id",
        "home_retention_memberships",
        ["lifecycle_id"],
        unique=False,
    )
    op.create_index(
        "ix_home_retention_memberships_membership_id",
        "home_retention_memberships",
        ["membership_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_home_retention_memberships_membership_id", table_name="home_retention_memberships")
    op.drop_index("ix_home_retention_memberships_lifecycle_id", table_name="home_retention_memberships")
    op.drop_table("home_retention_memberships")
    op.drop_index("ix_home_retention_due", table_name="home_retention_lifecycles")
    op.drop_index("ix_home_retention_lifecycles_home_id", table_name="home_retention_lifecycles")
    op.drop_table("home_retention_lifecycles")
    sa.Enum(name="home_retention_state").drop(op.get_bind(), checkfirst=True)
