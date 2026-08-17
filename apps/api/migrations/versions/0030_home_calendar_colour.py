"""Add a configurable colour to home_calendars.

Every calendar (shared Home calendars and Personal Calendars alike) now
carries its own `color` — the colour an event on it renders with when it
carries no CalendarEventLabel (label_id IS NULL). Defaults to the same
"teal" every uncategorised event already rendered as (see
mykhaya.colour_palette.DEFAULT_LABEL_COLOUR), so this is additive: nothing
changes visually until a user with calendar.edit_all deliberately changes a
shared calendar's colour via the new colour-only update endpoint (see
routers.calendar.update_calendar) — `name` is not editable through that
endpoint at all, by design (the Home calendar's name is a fixed product
concept, not user data).

Revision ID: 0030_home_calendar_colour
Revises: 0029_trusted_devices
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_home_calendar_colour"
down_revision: str | None = "0029_trusted_devices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The colour_token enum type already exists (see migration 0015) —
# create_type=False so this column addition never tries to redefine it.
colour_token = postgresql.ENUM(name="colour_token", create_type=False)


def upgrade() -> None:
    op.add_column(
        "home_calendars",
        sa.Column("color", colour_token, nullable=False, server_default="teal"),
    )


def downgrade() -> None:
    op.drop_column("home_calendars", "color")
