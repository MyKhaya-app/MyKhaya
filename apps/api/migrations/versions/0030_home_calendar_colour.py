"""Merge point: reconnect the two branches that independently forked off
0028_personal_calendars.

History: this revision ID was briefly (and incorrectly) reused for the
schema change that actually belongs to 0029_home_calendar_colour — a
mid-development rename repointed this file after 0029_trusted_devices and
dropped the 0029_home_calendar_colour identity entirely, which orphaned any
database already stamped at that revision (deployment failure: "Can't
locate revision identified by '0029_home_calendar_colour'"). The schema
change (home_calendars.color) has been restored to its original home in
0029_home_calendar_colour.py, unchanged from how it was first deployed.

This revision's *identity* (0030_home_calendar_colour) is kept as-is rather
than renumbered, because some databases were already stamped at it while it
still carried the color-column upgrade — for those, this merge is correctly
a no-op continuation of a revision they've already applied. For a database
still at the orphaned 0029_home_calendar_colour, or a fresh database, this
merge (only reachable once both parent branches are applied) is what
reconnects them into one head.
"""

from collections.abc import Sequence

revision: str = "0030_home_calendar_colour"
down_revision: str | tuple[str, ...] | None = (
    "0029_home_calendar_colour",
    "0029_trusted_devices",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
