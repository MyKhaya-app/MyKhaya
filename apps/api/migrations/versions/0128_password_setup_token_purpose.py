"""Add a distinct password-setup action-token purpose.

Password setup is intentionally separate from password reset: the former may
create the first local credential, while the latter requires one to exist.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0128_password_setup_purpose"
down_revision: str | None = "0127_audit_events_actor_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE token_purpose ADD VALUE IF NOT EXISTS 'setup_password'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in-place. The value is
    # unused by older application code, so rollback leaves the additive enum
    # member in place rather than risking token-table data loss.
    pass
