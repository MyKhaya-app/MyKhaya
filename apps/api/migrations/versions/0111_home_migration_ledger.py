"""Record completed cross-environment Home migrations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0111_home_migration_ledger"
down_revision: str | None = "0110_terms_acceptance_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_migration_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("migration_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("source_home_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("target_home_id", sa.Uuid(), nullable=False),
        sa.Column("package_checksum", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("home_migration_ledger")
