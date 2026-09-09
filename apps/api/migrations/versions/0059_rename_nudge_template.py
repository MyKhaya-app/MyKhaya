"""Rename the Daily Nudge Summary notification_templates row key.

The "nudges.morning_briefing" template_type was introduced alongside the
Daily Briefing regression (see 0058's context) and, once PCC titleCase()s a
template_type into a display label, read as "Nudges Morning Briefing" —
easily confused with Daily Briefing's own "Morning briefing" wording. The
notification_type has always been the unambiguous "daily_nudge_summary"; this
renames the template_type to match it 1:1, so PCC displays "Daily Nudge
Summary" instead.

notification_templates is override-only (a row exists only once a Platform
Admin has customised that template_type/channel — see
mykhaya.models.NotificationTemplate's docstring), so this is a pure key
rename of any override/revision rows that may exist under the old key. No
override existed as of this migration; the UPDATE is a no-op if so, and a
safe rename if one was created between deploy and this migration running.

Revision ID: 0059_rename_nudge_template
Revises: 0058_daily_nudge_summary
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059_rename_nudge_template"
down_revision: str | None = "0058_daily_nudge_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KEY = "nudges.morning_briefing"
NEW_KEY = "daily_nudge_summary"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE notification_templates SET template_type = :new_key "
            "WHERE template_type = :old_key"
        ).bindparams(new_key=NEW_KEY, old_key=OLD_KEY)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE notification_templates SET template_type = :old_key "
            "WHERE template_type = :new_key"
        ).bindparams(old_key=OLD_KEY, new_key=NEW_KEY)
    )
