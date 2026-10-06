"""Add programme scope and staged registration contexts to legal records."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0108_legal_scopes_contexts"
down_revision: str | None = "0107_founding_beta_phase1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    scope_enum = postgresql.ENUM(
        "global", "founding_beta", name="legal_document_scope", create_type=False
    )
    scope_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "legal_documents",
        sa.Column(
            "scope",
            postgresql.ENUM(
                "global", "founding_beta", name="legal_document_scope", create_type=False
            ),
            nullable=False,
            server_default="global",
        ),
    )
    op.execute(
        sa.text(
            "ALTER TYPE legal_acceptance_context "
            "ADD VALUE IF NOT EXISTS 'beta_registration'"
        )
    )
    op.execute(
        sa.text(
            "ALTER TYPE legal_acceptance_context "
            "ADD VALUE IF NOT EXISTS 'beta_enrolment'"
        )
    )
    op.execute(
        sa.text(
            "ALTER TYPE legal_acceptance_context "
            "ADD VALUE IF NOT EXISTS 'in_app_reacceptance'"
        )
    )


def downgrade() -> None:
    op.drop_column("legal_documents", "scope")
    # PostgreSQL does not safely remove enum labels; the additive labels remain
    # harmless for a downgrade and are removed with the base enum migration.
