"""Add durable identity for consumer Home onboarding retries."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0121_onboarding_home_idempotency"
down_revision: str | None = "0120_subscription_changes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("groups", sa.Column("onboarding_key", sa.String(64), nullable=True))
    op.add_column("groups", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True)))
    op.create_index(
        "uq_groups_created_by_onboarding_key",
        "groups",
        ["created_by", "onboarding_key"],
        unique=True,
        postgresql_where=sa.text("onboarding_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_groups_created_by_onboarding_key", table_name="groups")
    op.drop_column("groups", "onboarding_completed_at")
    op.drop_column("groups", "onboarding_key")
