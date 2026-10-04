"""Add isolated metadata for Legal & Compliance test activity."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0103_legal_test_mode"
down_revision: str | None = "0102_phase5_legal_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "legal_document_versions",
        sa.Column("is_test", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "legal_acceptances",
        sa.Column("is_test", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index("ix_legal_document_versions_test", "legal_document_versions", ["is_test"])
    op.create_index("ix_legal_acceptances_test", "legal_acceptances", ["is_test"])


def downgrade() -> None:
    op.drop_index("ix_legal_acceptances_test", table_name="legal_acceptances")
    op.drop_index("ix_legal_document_versions_test", table_name="legal_document_versions")
    op.drop_column("legal_acceptances", "is_test")
    op.drop_column("legal_document_versions", "is_test")
