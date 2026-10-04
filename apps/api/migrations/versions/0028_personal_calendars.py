"""Add a private Personal Calendar per household member.

Introduces `home_calendars.owner_user_id` (NULL = existing shared/Home
calendar, unchanged behaviour; non-NULL = that member's private Personal
Calendar — the structural privacy boundary application code enforces, see
routers.calendar and notifications.visibility.can_view_event). A plain
UniqueConstraint("group_id", "owner_user_id") is sufficient (not a partial
index): SQL treats NULLs as distinct from each other, so it only ever
constrains the non-NULL (personal) rows to one per member per Home.

Backfill: creates one Personal Calendar for every existing *adult* (non-child)
active membership that doesn't already have one. Managed child accounts are
deliberately excluded — there is no established product rule yet for parent
visibility into a child's calendar, so this migration does not invent one
(see the accompanying task's final report). Idempotent: re-running this
migration (or the equivalent application-level `ensure_personal_calendar`
helper, called on every future membership creation) can never create a
duplicate, because of the unique constraint.

No existing event, calendar, or label data is touched, renamed, or
reinterpreted — the frontend's "Family calendar" default option was
confirmed (see investigation) to be a purely synthetic `label_id: null`
choice with no backing `HomeCalendar`/`CalendarEventLabel` row, so there is
nothing ambiguous to migrate or reclassify as private.

Revision ID: 0028_personal_calendars
Revises: 0027_platform_stripe_settings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_personal_calendars"
down_revision: str | None = "0027_platform_stripe_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "home_calendars",
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
    )
    op.create_index("ix_home_calendars_owner_user_id", "home_calendars", ["owner_user_id"])
    op.create_unique_constraint(
        "uq_home_calendar_owner", "home_calendars", ["group_id", "owner_user_id"]
    )

    # Backfill: one Personal Calendar per existing adult (non-child), active
    # membership, skipping any that (improbably, but for idempotency) already
    # has one. Raw SQL against the tables as they exist today, not the ORM
    # models — the standard Alembic data-migration approach, so this stays
    # correct even as the models evolve later.
    op.execute(
        """
        INSERT INTO home_calendars (id, created_at, updated_at, group_id, name, timezone,
                                     is_primary, owner_user_id)
        SELECT gen_random_uuid(), now(), now(), m.group_id, 'Personal calendar',
               'Europe/London', false, m.user_id
        FROM group_memberships m
        WHERE m.removed_at IS NULL
          AND m.relationship <> 'child'
          AND NOT EXISTS (
              SELECT 1 FROM home_calendars hc
              WHERE hc.group_id = m.group_id AND hc.owner_user_id = m.user_id
          )
        """
    )


def downgrade() -> None:
    op.drop_constraint("uq_home_calendar_owner", "home_calendars", type_="unique")
    op.drop_index("ix_home_calendars_owner_user_id", table_name="home_calendars")
    # Personal-calendar rows (and, via calendar_events.calendar_id ON DELETE
    # CASCADE, every event ever created on one) are removed on downgrade —
    # there is no shared-calendar equivalent to fall back to, since these
    # rows only ever existed because of this migration.
    op.execute("DELETE FROM home_calendars WHERE owner_user_id IS NOT NULL")
    op.drop_column("home_calendars", "owner_user_id")
