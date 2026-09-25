"""Add Driveway official lookup state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0096_driveway_lookup"
down_revision: str | None = "0095_plan_signup_controls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("lookup_provider", sa.String(40)))
    op.add_column("vehicles", sa.Column("lookup_status", sa.String(30)))
    op.add_column("vehicles", sa.Column("last_successful_lookup", sa.DateTime(timezone=True)))
    op.add_column("vehicles", sa.Column("tax_status", sa.String(30)))
    op.add_column("vehicles", sa.Column("tax_due_date", sa.Date()))
    op.add_column("vehicles", sa.Column("inspection_status", sa.String(30)))
    op.add_column("vehicles", sa.Column("inspection_due_date", sa.Date()))


def downgrade() -> None:
    for name in ("inspection_due_date", "inspection_status", "tax_due_date", "tax_status", "last_successful_lookup", "lookup_status", "lookup_provider"):
        op.drop_column("vehicles", name)
