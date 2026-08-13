"""Phase 6 of MyKhaya's commercial architecture: enforce calendar.max_calendars
against a real create-a-second-calendar endpoint. See
docs/architecture/commercial-entitlements.md "Calendar as proof of
architecture".

`home_calendars` already had a `(group_id, is_primary)` UniqueConstraint
(migration 0003) — a full unique constraint, not a partial one, so it
implicitly also capped a Home at exactly one `is_primary=False` row, which
would have blocked a third calendar. Replace it with a partial unique index
that only constrains `is_primary=True` rows: still exactly one primary
calendar per Home (unchanged invariant), but now any number of secondary
calendars. No data migration needed — every existing Home already has
exactly one HomeCalendar row (is_primary=True), which already satisfies the
new index.

Revision ID: 0022_multi_calendar_entitlement
Revises: 0021_stripe_billing
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_multi_calendar_entitlement"
down_revision: str | None = "0021_stripe_billing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_home_primary_calendar", "home_calendars", type_="unique")
    op.create_index(
        "ix_home_calendar_one_primary_per_group",
        "home_calendars",
        ["group_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )


def downgrade() -> None:
    op.drop_index("ix_home_calendar_one_primary_per_group", table_name="home_calendars")
    op.create_unique_constraint(
        "uq_home_primary_calendar", "home_calendars", ["group_id", "is_primary"]
    )
