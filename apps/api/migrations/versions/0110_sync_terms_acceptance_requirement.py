"""Keep Terms signup gating aligned with published legal content."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0110_terms_acceptance_sync"
down_revision: str | None = "0109_legal_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Require Terms only when the canonical document has published content."""
    op.execute(
        sa.text(
            """
            UPDATE legal_documents AS document
            SET acceptance_required = EXISTS (
                SELECT 1
                FROM legal_document_versions AS version
                WHERE version.document_id = document.id
                  AND version.status = 'published'
            )
            WHERE document.key = 'terms'
            """
        )
    )


def downgrade() -> None:
    """Leave legal-document gating unchanged on downgrade.

    The previous migration's state is not safely reconstructable after Terms
    may have been published or archived by an operator.
    """
