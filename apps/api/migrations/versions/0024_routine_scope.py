"""Split household routines into explicit personal/household scope.

Routines previously had no scope concept: notification recipients came from
HouseholdRoutineMember (if any) else the whole household, with no way to mark a
routine as belonging to one person only. The web UI never populated member_ids,
so every routine was effectively household-wide. This adds an explicit
`routine_scope` enum and an `owner_user_id` column (set only for scope=personal,
never client-trusted) so notification targeting can be corrected in application
code. Existing rows default to scope=household / owner_user_id=NULL, preserving
current behaviour exactly for pre-existing data.

Revision ID: 0024_routine_scope
Revises: 0023_billing_readiness
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_routine_scope"
down_revision: str | None = "0023_billing_readiness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

routine_scope = postgresql.ENUM("personal", "household", name="routine_scope", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM("personal", "household", name="routine_scope").create(bind)

    op.add_column(
        "household_routines",
        sa.Column(
            "scope", routine_scope, nullable=False, server_default="household"
        ),
    )
    op.add_column(
        "household_routines",
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_household_routines_owner_user_id", "household_routines", ["owner_user_id"]
    )
    op.create_check_constraint(
        "ck_routine_scope_owner",
        "household_routines",
        "(scope = 'personal' AND owner_user_id IS NOT NULL) OR "
        "(scope = 'household' AND owner_user_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_routine_scope_owner", "household_routines", type_="check")
    op.drop_index("ix_household_routines_owner_user_id", table_name="household_routines")
    op.drop_column("household_routines", "owner_user_id")
    op.drop_column("household_routines", "scope")
    bind = op.get_bind()
    postgresql.ENUM(name="routine_scope").drop(bind)
