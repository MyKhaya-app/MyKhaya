"""Add the expanded palette tokens to the shared colour_token enum.

mykhaya.colour_palette.ColourToken grew from the 18 tokens migration
0015_colour_palette created to 27, but Membership.colour still stores the
token in the colour_token Postgres enum. Assigning one of the new tokens
(e.g. `rust` to the next family member) therefore failed with
`invalid input value for enum colour_token`.

PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as long
as the new value isn't *used* in that same transaction, which holds here.

Revision ID: 0105_colour_token_expansion
Revises: 0104_budget_income_receipts
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0105_colour_token_expansion"
down_revision: str | None = "0104_budget_income_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here rather than imported from mykhaya.colour_palette: a migration
# must keep meaning exactly what it meant when it was written.
NEW_COLOUR_TOKENS = [
    "rust",
    "olive",
    "jade",
    "azure",
    "periwinkle",
    "plum",
    "magenta",
    "stone",
    "charcoal",
]


def upgrade() -> None:
    for token in NEW_COLOUR_TOKENS:
        op.execute(f"ALTER TYPE colour_token ADD VALUE IF NOT EXISTS '{token}'")  # noqa: S608


def downgrade() -> None:
    # No ALTER TYPE ... DROP VALUE in PostgreSQL — see migration
    # 0038_household_adult's downgrade for the same reasoning. This
    # migration never assigns any of these values to a row itself, so
    # leaving them defined on downgrade is not unsafe.
    pass
