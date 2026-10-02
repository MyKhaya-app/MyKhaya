"""Add managed Demo/Test Home records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051_managed_demo_homes"
down_revision: str | None = "0050_calendar_event_exceptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "managed_demo_homes",
        sa.Column("fixture_key", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column(
            "fixture_type",
            sa.Enum("apple_review", "demo", "qa_test", name="managed_demo_type"),
            nullable=False,
        ),
        sa.Column(
            "home_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("enabled", "disabled", "expired", name="managed_demo_status"),
            nullable=False,
            server_default="enabled",
        ),
        sa.Column("template_version", sa.String(40), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("refreshed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("fixture_key", name="uq_managed_demo_fixture_key"),
        sa.UniqueConstraint("home_id"),
        sa.UniqueConstraint("owner_user_id"),
    )
    op.create_index("ix_managed_demo_homes_fixture_key", "managed_demo_homes", ["fixture_key"])
    op.create_index("ix_managed_demo_homes_home_id", "managed_demo_homes", ["home_id"])
    op.create_index("ix_managed_demo_homes_owner_user_id", "managed_demo_homes", ["owner_user_id"])
    op.create_index("ix_managed_demo_homes_expires_at", "managed_demo_homes", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_managed_demo_homes_expires_at", table_name="managed_demo_homes")
    op.drop_index("ix_managed_demo_homes_owner_user_id", table_name="managed_demo_homes")
    op.drop_index("ix_managed_demo_homes_home_id", table_name="managed_demo_homes")
    op.drop_index("ix_managed_demo_homes_fixture_key", table_name="managed_demo_homes")
    op.drop_table("managed_demo_homes")
    sa.Enum(name="managed_demo_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="managed_demo_type").drop(op.get_bind(), checkfirst=True)
