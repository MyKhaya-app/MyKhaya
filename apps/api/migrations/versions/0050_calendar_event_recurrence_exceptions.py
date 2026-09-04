"""Add calendar_event_exceptions for per-occurrence recurring-event edit/delete."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision string kept <=32 chars per repo convention (see 0049's own
# comment/history) — the descriptive name lives in the filename instead.
revision: str = "0050_calendar_event_exceptions"
down_revision: str | None = "0049_list_wishlist_notify_prefs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_event_exceptions",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurrence_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("title", sa.String(180)),
        sa.Column("description", sa.String(2000)),
        sa.Column("start_at", sa.DateTime(timezone=True)),
        sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("is_all_day", sa.Boolean()),
        sa.Column("location_text", sa.String(200)),
        sa.Column("calendar_id", sa.Uuid(), sa.ForeignKey("home_calendars.id", ondelete="SET NULL")),
        sa.Column("label_id", sa.Uuid(), sa.ForeignKey("calendar_event_labels.id", ondelete="SET NULL")),
        sa.Column("reminder_minutes", sa.Integer()),
        sa.Column("member_ids", sa.JSON()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("last_edited_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # The core invariant: at most one exception row per (event, canonical
        # occurrence) — see the model's own docstring for why this is what
        # makes double-submit/retry safe rather than a source of duplicates.
        sa.UniqueConstraint("event_id", "occurrence_start", name="uq_event_exception_occurrence"),
    )
    op.create_index("ix_event_exception_event", "calendar_event_exceptions", ["event_id"])
    op.create_index("ix_calendar_event_exceptions_group_id", "calendar_event_exceptions", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_calendar_event_exceptions_group_id", table_name="calendar_event_exceptions")
    op.drop_index("ix_event_exception_event", table_name="calendar_event_exceptions")
    op.drop_table("calendar_event_exceptions")
