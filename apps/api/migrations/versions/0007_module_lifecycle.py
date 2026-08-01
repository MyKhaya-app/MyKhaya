"""Add operator-managed module lifecycle state.

Revision ID: 0007_module_lifecycle
Revises: 0006_household_relationships
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_module_lifecycle"
down_revision: str | None = "0006_household_relationships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("feature_flags", sa.Column("release_state", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("feature_flags", "release_state")
