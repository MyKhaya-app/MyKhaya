"""Store Stripe subscription changes scheduled for a future period boundary."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0120_subscription_changes"
down_revision: str | None = "0119_showcase_demo_homes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLAN = postgresql.ENUM("free", "family", "ultimate", name="subscription_plan", create_type=False)
_INTERVAL = postgresql.ENUM("month", "year", name="billing_interval", create_type=False)


def upgrade() -> None:
    op.add_column("home_subscriptions", sa.Column("pending_plan", _PLAN, nullable=True))
    op.add_column(
        "home_subscriptions", sa.Column("pending_billing_interval", _INTERVAL, nullable=True)
    )
    op.add_column(
        "home_subscriptions", sa.Column("pending_effective_at", sa.DateTime(timezone=True))
    )
    op.add_column("home_subscriptions", sa.Column("stripe_schedule_id", sa.String(255)))
    op.create_index(
        "ix_home_subscriptions_stripe_schedule_id",
        "home_subscriptions",
        ["stripe_schedule_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_home_subscriptions_stripe_schedule_id", table_name="home_subscriptions")
    op.drop_column("home_subscriptions", "stripe_schedule_id")
    op.drop_column("home_subscriptions", "pending_effective_at")
    op.drop_column("home_subscriptions", "pending_billing_interval")
    op.drop_column("home_subscriptions", "pending_plan")
