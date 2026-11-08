"""Record provider message identifiers for evidence email delivery."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0124_legal_evidence_provider_msg"
down_revision: str | None = "0123_legal_acceptance_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "legal_acceptance_evidence",
        sa.Column("provider_message_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "notification_deliveries", sa.Column("provider_message_id", sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("notification_deliveries", "provider_message_id")
    op.drop_column("legal_acceptance_evidence", "provider_message_id")
