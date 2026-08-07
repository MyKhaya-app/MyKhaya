"""Add the email channel toggle to notification preferences.

Stage 8 of the Communications milestone: email becomes a real notify() channel,
alongside push and in-app, rather than three modules calling send_email() directly.
See docs/architecture/notification-engine.md. Defaults to disabled — unlike
push_enabled/in_app_enabled, email is an explicit opt-in "also email me" channel for
optional notification types, not a third always-on channel that would triple send
volume for every reminder/briefing/routine/birthday. Mandatory system emails
(verification, password reset, household invitations) always send regardless of this
toggle — see MANDATORY_EMAIL_TYPES in mykhaya/notifications/engine.py.

Revision ID: 0011_notification_email_channel
Revises: 0010_notification_engine
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_notification_email_channel"
down_revision: str | None = "0010_notification_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_preferences",
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("notification_preferences", "email_enabled")
