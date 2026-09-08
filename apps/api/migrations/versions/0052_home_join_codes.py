"""Add Home join codes and join requests."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052_home_join_codes"
down_revision: str | None = "0051_managed_demo_homes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

home_join_request_status = postgresql.ENUM(
    "pending", "approved", "declined", "cancelled", name="home_join_request_status", create_type=False
)
household_relationship = postgresql.ENUM(
    "home_admin",
    "partner",
    "adult",
    "child",
    "extended_family",
    "friend",
    "review_required",
    name="household_relationship",
    create_type=False,
)


def upgrade() -> None:
    op.add_column("groups", sa.Column("join_code_hash", sa.String(64), nullable=True))
    op.add_column("groups", sa.Column("join_code_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "groups", sa.Column("join_code_generated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint("uq_groups_join_code_hash", "groups", ["join_code_hash"])
    op.create_index(
        "ix_groups_join_code_hash", "groups", ["join_code_hash"], unique=True
    )

    bind = op.get_bind()
    home_join_request_status.create(bind)
    # household_relationship already exists (see 0006_household_relationships) —
    # referenced here with create_type=False, never (re)created.

    op.create_table(
        "home_join_requests",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method", sa.String(20), nullable=False, server_default="join_code"),
        sa.Column("status", home_join_request_status, nullable=False, server_default="pending"),
        sa.Column("relationship", household_relationship, nullable=True),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_home_join_requests_group_id", "home_join_requests", ["group_id"])
    op.create_index("ix_home_join_requests_user_id", "home_join_requests", ["user_id"])
    op.create_index(
        "ix_home_join_request_group_status", "home_join_requests", ["group_id", "status"]
    )
    op.create_index(
        "uq_home_join_request_pending_group_user",
        "home_join_requests",
        ["group_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_home_join_request_pending_group_user", table_name="home_join_requests")
    op.drop_index("ix_home_join_request_group_status", table_name="home_join_requests")
    op.drop_index("ix_home_join_requests_user_id", table_name="home_join_requests")
    op.drop_index("ix_home_join_requests_group_id", table_name="home_join_requests")
    op.drop_table("home_join_requests")
    home_join_request_status.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_groups_join_code_hash", table_name="groups")
    op.drop_constraint("uq_groups_join_code_hash", "groups", type_="unique")
    op.drop_column("groups", "join_code_generated_at")
    op.drop_column("groups", "join_code_encrypted")
    op.drop_column("groups", "join_code_hash")
