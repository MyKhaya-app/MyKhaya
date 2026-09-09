"""Allow Routines and Reminders to use the existing Home-scoped Nudge categories.

Revision ID: 0060_nudge_categories
Revises: 0059_rename_nudge_template
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060_nudge_categories"
down_revision: str | None = "0059_rename_nudge_template"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable columns preserve every existing uncategorised Routine/Reminder.
    # The FK points at the existing Home-scoped todo_categories table; no rows
    # are backfilled or assigned by this migration.
    op.add_column("household_routines", sa.Column("category_id", sa.Uuid(), nullable=True))
    op.create_index("ix_household_routines_category_id", "household_routines", ["category_id"])
    op.create_foreign_key(
        "fk_household_routines_category_id",
        "household_routines",
        "todo_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("reminders", sa.Column("category_id", sa.Uuid(), nullable=True))
    op.create_index("ix_reminders_category_id", "reminders", ["category_id"])
    op.create_foreign_key(
        "fk_reminders_category_id",
        "reminders",
        "todo_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_reminders_category_id", "reminders", type_="foreignkey")
    op.drop_index("ix_reminders_category_id", table_name="reminders")
    op.drop_column("reminders", "category_id")
    op.drop_constraint("fk_household_routines_category_id", "household_routines", type_="foreignkey")
    op.drop_index("ix_household_routines_category_id", table_name="household_routines")
    op.drop_column("household_routines", "category_id")
