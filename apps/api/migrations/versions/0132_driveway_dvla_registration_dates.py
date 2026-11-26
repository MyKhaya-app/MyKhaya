"""Store DVLA registration-date provenance separately from first registration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0132_dvla_registration_dates"
down_revision: str | None = "0131_registration_precision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column("first_registration_with_dvla_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "vehicles",
        sa.Column("first_registration_with_dvla_precision", sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vehicles", "first_registration_with_dvla_precision")
    op.drop_column("vehicles", "first_registration_with_dvla_date")
