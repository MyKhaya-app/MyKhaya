"""Add Driveway's additive reminder source-link and managed-category marker.

Phase 4: Driveway-generated reminders are ordinary Reminder rows with three
new nullable columns (source_type/source_id/source_event) that link them
back to a vehicle, plus a nullable managed_source marker on TodoCategory so
the auto-created "Vehicles" category can be delete-protected without relying
on its visible name. Every existing row has these columns null — no
behaviour change for standalone reminders/categories.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0093_driveway_reminder_links"
down_revision: str | None = "0092_driveway_vehicles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reminders", sa.Column("source_type", sa.String(20)))
    op.add_column("reminders", sa.Column("source_id", sa.UUID()))
    op.add_column("reminders", sa.Column("source_event", sa.String(30)))
    op.create_index(
        "ix_reminder_source_type_id", "reminders", ["source_type", "source_id"]
    )
    op.create_index(
        "uq_reminder_source_event_active",
        "reminders",
        ["source_type", "source_id", "source_event"],
        unique=True,
        postgresql_where=sa.text(
            "source_type IS NOT NULL AND source_event <> 'manual' AND enabled = true"
        ),
    )
    op.add_column("todo_categories", sa.Column("managed_source", sa.String(20)))


def downgrade() -> None:
    op.drop_column("todo_categories", "managed_source")
    op.drop_index("uq_reminder_source_event_active", table_name="reminders")
    op.drop_index("ix_reminder_source_type_id", table_name="reminders")
    op.drop_column("reminders", "source_event")
    op.drop_column("reminders", "source_id")
    op.drop_column("reminders", "source_type")
