"""Persist explicit Family sponsorship decisions for memberships and invites.

Revision ID: 0066_family_sponsorship_choices
Revises: 0065_home_entitlement_grants
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066_family_sponsorship_choices"
down_revision: str | None = "0065_home_entitlement_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "group_memberships",
        sa.Column("family_sponsorship_decided", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "group_invitations",
        sa.Column("family_sponsorship", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("group_invitations", "family_sponsorship")
    op.drop_column("group_memberships", "family_sponsorship_decided")
