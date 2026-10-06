"""Persist PCC Home migration package state and dry-run bindings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0112_home_migration_packages"
down_revision: str | None = "0111_home_migration_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_migration_packages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("migration_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("package_checksum", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(80), nullable=False, unique=True),
        sa.Column("source_home_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("dry_run_checksum", sa.String(64)),
        sa.Column("dry_run_report", sa.JSON()),
        sa.Column("completed_report", sa.JSON()),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_home_migration_packages_package_checksum",
        "home_migration_packages",
        ["package_checksum"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_home_migration_packages_package_checksum", table_name="home_migration_packages"
    )
    op.drop_table("home_migration_packages")
