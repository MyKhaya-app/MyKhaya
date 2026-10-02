"""Add the user's browser MFA preference.

The value is nullable for existing users and is advisory only; the API always
validates it against the effective policy and currently usable methods.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078_consumer_mfa_preference"
down_revision: str | None = "0077_native_push_disabled_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferred_mfa_method", sa.String(10), nullable=True))
    op.create_check_constraint(
        "ck_users_preferred_mfa_method",
        "users",
        "preferred_mfa_method IS NULL OR preferred_mfa_method IN ('totp', 'email')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_preferred_mfa_method", "users", type_="check")
    op.drop_column("users", "preferred_mfa_method")
