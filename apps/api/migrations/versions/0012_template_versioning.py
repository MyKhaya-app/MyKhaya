"""Record which built-in template version a notification_templates override was based
on, so Platform Admin can eventually flag "this template has changed since your
override was saved" (Stage 9, deferred full compare/diff UI — see
docs/architecture/notification-engine.md).

Revision ID: 0012_template_versioning
Revises: 0011_notification_email_channel
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_template_versioning"
down_revision: str | None = "0011_notification_email_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_templates",
        sa.Column("based_on_default_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("notification_templates", "based_on_default_version")
