"""Preserve provider precision for first-registration dates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0131_registration_precision"
down_revision: str | None = "0130_driveway_provider_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vehicles", sa.Column("first_registration_precision", sa.String(10), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("vehicles", "first_registration_precision")
