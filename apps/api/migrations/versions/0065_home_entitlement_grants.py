"""Add explicit Home-scoped Family sponsorship grants.

Home subscriptions remain Home-owned billing state. This table records only a
deliberate, revocable decision to sponsor a Family entitlement for a specific
user in that same Home. Existing Homes receive no grants, so this migration
does not alter existing access or membership.

Revision ID: 0065_home_entitlement_grants
Revises: 0064_free_demo_managed_type
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065_home_entitlement_grants"
down_revision: str | None = "0064_free_demo_managed_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_entitlement_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column(
            "source_group_id",
            sa.Uuid(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipient_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entitlement_key", sa.String(100), nullable=False, server_default="family"),
        sa.Column(
            "granted_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_home_entitlement_grants_source_group_id",
        "home_entitlement_grants",
        ["source_group_id"],
    )
    op.create_index(
        "ix_home_entitlement_grants_recipient_user_id",
        "home_entitlement_grants",
        ["recipient_user_id"],
    )
    op.create_index(
        "uq_home_entitlement_grant_active",
        "home_entitlement_grants",
        ["source_group_id", "recipient_user_id", "entitlement_key"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_home_entitlement_grants_revoked_at",
        "home_entitlement_grants",
        ["revoked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_home_entitlement_grants_revoked_at", table_name="home_entitlement_grants")
    op.drop_index("uq_home_entitlement_grant_active", table_name="home_entitlement_grants")
    op.drop_index(
        "ix_home_entitlement_grants_recipient_user_id", table_name="home_entitlement_grants"
    )
    op.drop_index(
        "ix_home_entitlement_grants_source_group_id", table_name="home_entitlement_grants"
    )
    op.drop_table("home_entitlement_grants")
