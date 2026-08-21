"""Add the 'adult' value to the household_relationship enum.

Purely additive: no existing row's relationship column changes, no other
enum (permission_profile, membership_role) is touched. A newly created Adult
membership/invitation reuses PermissionProfile.standard_partner (Partner's
default) via mykhaya.household_permissions.default_profile — that mapping is
plain Python, not a database concern, so it needs no migration of its own.

PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as long
as the new value isn't *used* in that same transaction, which holds here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0038_household_adult"
down_revision: str | None = "0037_list_item_details"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE household_relationship ADD VALUE IF NOT EXISTS 'adult'")


def downgrade() -> None:
    # PostgreSQL has no ALTER TYPE ... DROP VALUE — removing an enum value
    # safely means rebuilding the type, which would require every dependent
    # column/constraint to be dropped and recreated. Since this migration
    # never assigns 'adult' to any row itself, there is nothing unsafe about
    # leaving the value defined on downgrade; a genuine rollback that must
    # also erase any 'adult' rows created in the meantime is an operational
    # decision, not something this migration can do automatically.
    pass
