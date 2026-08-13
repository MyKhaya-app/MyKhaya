"""Add member colour to group memberships.

Colour belongs to the relationship with a household, not the person
globally, so it lives on Membership rather than User — see
docs/design/visual-identity.md. Nullable and unbackfilled: existing
memberships keep the frontend's client-side colour hash as a fallback
until they're next touched by an assignment path (invite accept, child
creation, home creation), which is non-destructive and requires no data
migration.

Revision ID: 0008_member_colour
Revises: 0007_module_lifecycle
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_member_colour"
down_revision: str | None = "0007_module_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("group_memberships", sa.Column("colour", sa.String(7), nullable=True))


def downgrade() -> None:
    op.drop_column("group_memberships", "colour")
