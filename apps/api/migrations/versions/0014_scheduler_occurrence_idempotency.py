"""Add durable scheduler occurrence identity and execution start time.

Revision ID: 0014_scheduler_idempotency
Revises: 0013_user_avatar
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_scheduler_idempotency"
down_revision: str | None = "0013_user_avatar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("dedupe_key", sa.String(length=255), nullable=True))
    op.create_unique_constraint("uq_outbox_events_dedupe_key", "outbox_events", ["dedupe_key"])
    op.add_column(
        "worker_job_records", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("worker_job_records", "started_at")
    op.drop_constraint("uq_outbox_events_dedupe_key", "outbox_events", type_="unique")
    op.drop_column("outbox_events", "dedupe_key")
