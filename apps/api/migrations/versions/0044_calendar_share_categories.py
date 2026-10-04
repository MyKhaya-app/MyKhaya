"""Add CalendarShare.category_ids: an optional filter restricting an external
Home-calendar share to specific categories (CalendarEventLabel ids), instead of
exposing every event on the calendar. NULL (the default, and every existing row's
value) means "entire calendar" — unchanged behaviour for every share created before
this migration. Additive only — one nullable JSON column, no other schema change.

Revision ID: 0044_calendar_share_categories
Revises: 0043_calendar_sharing
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_calendar_share_categories"
down_revision: str | None = "0043_calendar_sharing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("calendar_shares", sa.Column("category_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("calendar_shares", "category_ids")
