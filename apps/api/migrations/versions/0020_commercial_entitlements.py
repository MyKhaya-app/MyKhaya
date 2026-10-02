"""Phase 1 of MyKhaya's commercial architecture: plans, Home-level
subscriptions and a structured commercial-state history. Stripe integration
is Phase 3 and is not touched here — see
docs/architecture/commercial-entitlements.md.

Every existing Home is backfilled to plan=free, provider=free,
status=active. Nothing in the application currently enforces any
entitlement/limit against a live endpoint (see the architecture doc's
"Calendar as proof of architecture" section), so this backfill changes
nothing about what any existing Home can actually do today — Free is fully
functional in Phase 1. No grandfathering to Family was needed for that
reason.

Revision ID: 0020_commercial_entitlements
Revises: 0019_platform_admin_invitations
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_commercial_entitlements"
down_revision: str | None = "0019_platform_admin_invitations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# postgresql.ENUM (not the generic sa.Enum) with create_type=False, matching
# every other migration in this repo that reuses one enum type across
# multiple columns (see 0015_colour_palette.py, 0019's platform_role reuse) —
# the generic sa.Enum wrapper does not reliably honour create_type=False when
# embedded in an op.create_table() column here, and re-attempts CREATE TYPE
# for every column that references it regardless of the flag.
_SUBSCRIPTION_PLAN = postgresql.ENUM(
    "free", "family", name="subscription_plan", create_type=False
)
_SUBSCRIPTION_PROVIDER = postgresql.ENUM(
    "free",
    "complimentary",
    "stripe",
    "apple",
    "google",
    name="subscription_provider",
    create_type=False,
)
_SUBSCRIPTION_STATUS = postgresql.ENUM(
    "active",
    "trialing",
    "past_due",
    "cancel_at_period_end",
    "cancelled",
    name="subscription_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    _SUBSCRIPTION_PLAN.create(bind)
    _SUBSCRIPTION_PROVIDER.create(bind)
    _SUBSCRIPTION_STATUS.create(bind)

    op.create_table(
        "home_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column(
            "group_id",
            sa.Uuid(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "plan",
            _SUBSCRIPTION_PLAN,
            nullable=False,
            server_default="free",
        ),
        sa.Column(
            "provider",
            _SUBSCRIPTION_PROVIDER,
            nullable=False,
            server_default="free",
        ),
        sa.Column(
            "status",
            _SUBSCRIPTION_STATUS,
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "billing_owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_customer_id", sa.String(255), nullable=True),
        sa.Column("external_subscription_id", sa.String(255), nullable=True, unique=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("complimentary_reason", sa.String(200), nullable=True),
        sa.Column("complimentary_note", sa.String(1000), nullable=True),
        sa.Column(
            "complimentary_granted_by",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("complimentary_granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("complimentary_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_home_subscriptions_group_id", "home_subscriptions", ["group_id"], unique=True
    )
    op.create_index(
        "ix_home_subscriptions_external_customer_id",
        "home_subscriptions",
        ["external_customer_id"],
    )

    op.create_table(
        "home_subscription_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("from_plan", _SUBSCRIPTION_PLAN, nullable=True),
        sa.Column("to_plan", _SUBSCRIPTION_PLAN, nullable=True),
        sa.Column("from_provider", _SUBSCRIPTION_PROVIDER, nullable=True),
        sa.Column("to_provider", _SUBSCRIPTION_PROVIDER, nullable=True),
        sa.Column("from_status", _SUBSCRIPTION_STATUS, nullable=True),
        sa.Column("to_status", _SUBSCRIPTION_STATUS, nullable=True),
        sa.Column(
            "actor_administrator_id",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(300), nullable=True),
    )
    op.create_index(
        "ix_home_subscription_events_group_created",
        "home_subscription_events",
        ["group_id", "created_at"],
    )

    # Backfill: every existing Home gets an explicit Free/free/active row —
    # see the module docstring for why this is safe and requires no
    # grandfathering.
    groups = sa.table("groups", sa.column("id", sa.Uuid()))
    home_subscriptions = sa.table(
        "home_subscriptions",
        sa.column("id", sa.Uuid()),
        sa.column("group_id", sa.Uuid()),
        sa.column("plan", _SUBSCRIPTION_PLAN),
        sa.column("provider", _SUBSCRIPTION_PROVIDER),
        sa.column("status", _SUBSCRIPTION_STATUS),
    )
    existing_group_ids = [row[0] for row in bind.execute(sa.select(groups.c.id))]
    if existing_group_ids:
        bind.execute(
            sa.insert(home_subscriptions),
            [
                {
                    "id": uuid.uuid4(),
                    "group_id": group_id,
                    "plan": "free",
                    "provider": "free",
                    "status": "active",
                }
                for group_id in existing_group_ids
            ],
        )


def downgrade() -> None:
    op.drop_index("ix_home_subscription_events_group_created", table_name="home_subscription_events")
    op.drop_table("home_subscription_events")
    op.drop_index("ix_home_subscriptions_external_customer_id", table_name="home_subscriptions")
    op.drop_index("ix_home_subscriptions_group_id", table_name="home_subscriptions")
    op.drop_table("home_subscriptions")
    op.execute("DROP TYPE subscription_status")
    op.execute("DROP TYPE subscription_provider")
    op.execute("DROP TYPE subscription_plan")
