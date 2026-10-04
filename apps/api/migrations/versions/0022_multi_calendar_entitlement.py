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
    # The restored (group_id, is_primary) constraint also caps a Home at exactly one
    # non-primary calendar, which this migration's upgrade deliberately lifted. A Home
    # that has since created more than one secondary calendar cannot be represented
    # under the old schema, so collapse the surplus rather than fail the downgrade:
    # keep each Home's oldest secondary calendar, move every event on the others onto
    # the Home's primary calendar, and only then delete the (now empty) surplus
    # calendars. No event is lost; only the surplus calendars' own names are. (The
    # DELETE is limited to Homes that do have a primary calendar, so a Home that
    # somehow lacks one is left alone and fails loudly at the constraint below
    # instead of cascading its events away.)
    op.execute(
        """
        WITH surplus AS (
            SELECT id, group_id FROM (
                SELECT id, group_id,
                       row_number() OVER (PARTITION BY group_id ORDER BY created_at, id) AS rn
                FROM home_calendars
                WHERE NOT is_primary
            ) ranked
            WHERE rn > 1
        )
        UPDATE calendar_events
        SET calendar_id = primary_calendar.id
        FROM surplus
        JOIN home_calendars AS primary_calendar
          ON primary_calendar.group_id = surplus.group_id AND primary_calendar.is_primary
        WHERE calendar_events.calendar_id = surplus.id
        """
    )
    op.execute(
        """
        DELETE FROM home_calendars AS surplus_calendar
        WHERE surplus_calendar.id IN (
            SELECT id FROM (
                SELECT id,
                       row_number() OVER (PARTITION BY group_id ORDER BY created_at, id) AS rn
                FROM home_calendars
                WHERE NOT is_primary
            ) ranked
            WHERE rn > 1
        )
        AND EXISTS (
            SELECT 1 FROM home_calendars AS primary_calendar
            WHERE primary_calendar.group_id = surplus_calendar.group_id
              AND primary_calendar.is_primary
        )
        """
    )
    op.create_unique_constraint(
        "uq_home_primary_calendar", "home_calendars", ["group_id", "is_primary"]
    )
