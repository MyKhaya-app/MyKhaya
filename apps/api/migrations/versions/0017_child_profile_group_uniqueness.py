"""Enforce managed-Child login-username uniqueness within a Home as a real database
constraint, not just a check-then-write application query.

child_profiles.group_id is denormalized from group_memberships.group_id (a membership
never moves between Homes, so duplicating it is safe) purely so a genuine composite
unique constraint can exist: (group_id, username_normalised). Postgres serialises two
concurrent inserts/updates racing for the same (Home, username) pair and rejects
whichever loses, so the invariant holds even under concurrent requests — not just
"usually true because of an application-level pre-check". NULLs (a Child with sign-in
never configured) are exempt as usual, since Postgres never treats two NULLs as equal
in a unique index.

Revision ID: 0017_child_login_uniqueness
Revises: 0016_managed_child_login
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_child_login_uniqueness"
down_revision: str | None = "0016_managed_child_login"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("child_profiles", sa.Column("group_id", sa.Uuid(), nullable=True))
    bind.execute(
        sa.text(
            "UPDATE child_profiles SET group_id = group_memberships.group_id "
            "FROM group_memberships "
            "WHERE group_memberships.id = child_profiles.membership_id"
        )
    )
    op.alter_column("child_profiles", "group_id", nullable=False)
    op.create_index("ix_child_profiles_group_id", "child_profiles", ["group_id"])
    op.create_foreign_key(
        "fk_child_profiles_group_id",
        "child_profiles",
        "groups",
        ["group_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_child_login_username_per_home",
        "child_profiles",
        ["group_id", "username_normalised"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_child_login_username_per_home", "child_profiles", type_="unique"
    )
    op.drop_constraint("fk_child_profiles_group_id", "child_profiles", type_="foreignkey")
    op.drop_index("ix_child_profiles_group_id", table_name="child_profiles")
    op.drop_column("child_profiles", "group_id")
