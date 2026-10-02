"""Add Personal/Household scope to Lists."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0073_list_scope"
down_revision: str | None = "0072_list_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

routine_scope = postgresql.ENUM("personal", "household", name="routine_scope", create_type=False)


def upgrade() -> None:
    op.add_column(
        "household_lists",
        sa.Column("scope", routine_scope, nullable=False, server_default="household"),
    )
    op.create_index(
        "ix_household_list_group_scope_active",
        "household_lists",
        ["group_id", "scope", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_household_list_group_scope_active", table_name="household_lists")
    op.drop_column("household_lists", "scope")
