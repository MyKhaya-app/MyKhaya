"""Store calendar/category colours as real hex values, not palette tokens.

`home_calendars.color` and `calendar_event_labels.color` move off the shared
`colour_token` enum onto a plain `varchar(7)` hex string (e.g. "#3F7A5C"), so
a custom colour never has to correspond to a predefined palette identifier —
see mykhaya.colour_palette.HexColour and the expanded PALETTE_HEX (~27
presets now, up from 18). This is the mirror image of migration
0015_colour_palette's original hex-to-token move, applied only to these two
columns; `group_memberships.colour` (member identity colour) is deliberately
untouched and stays on the `colour_token` enum — this feature only concerns
calendar/category colour.

Backfill is exact and non-destructive: every existing enum value has exactly
one defined hex equivalent in PALETTE_HEX (the same values migration 0015
introduced, unchanged), so every existing calendar/category keeps the
precise colour it already had — this is a storage-format change, not a
recolour.

Revision ID: 0045_calendar_colour_hex
Revises: 0044_calendar_share_categories
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0045_calendar_colour_hex"
down_revision: str | None = "0044_calendar_share_categories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Token -> hex, duplicated here rather than imported from mykhaya.colour_palette:
# migrations must keep working exactly as written even if the live palette
# module's values change later. Only the original 18 tokens can actually
# appear in a pre-migration database (the palette has since grown to ~27 for
# the picker's expanded preset set, but those newer tokens were never a
# storable enum value here — they were added as hex-only presets), so this
# map only needs to cover those 18.
TOKEN_HEX = {
    "red": "#B8433A", "coral": "#D97757", "orange": "#C97A2E", "amber": "#D9A83E",
    "yellow": "#BFA23A", "lime": "#7C9A4E", "green": "#5C8A54", "emerald": "#3F7A5C",
    "teal": "#456B76", "cyan": "#2E8B99", "sky": "#4C7FA6", "blue": "#3D6FB0",
    "indigo": "#5A63A8", "violet": "#8B6BA8", "purple": "#7A5C99", "pink": "#B85C8A",
    "rose": "#A03F6A", "slate": "#62706F",
}
DEFAULT_HEX = TOKEN_HEX["teal"]


def _case_sql(column: str) -> str:
    whens = " ".join(f"WHEN '{token}' THEN '{hex_value}'" for token, hex_value in TOKEN_HEX.items())
    return f"(CASE {column}::text {whens} END)"


def upgrade() -> None:
    op.execute("ALTER TABLE home_calendars ALTER COLUMN color DROP DEFAULT")
    op.execute(
        f"ALTER TABLE home_calendars ALTER COLUMN color TYPE varchar(7) "
        f"USING {_case_sql('color')}"
    )
    op.execute(f"ALTER TABLE home_calendars ALTER COLUMN color SET DEFAULT '{DEFAULT_HEX}'")
    op.execute(
        "ALTER TABLE home_calendars ADD CONSTRAINT ck_home_calendar_colour_hex "
        "CHECK (color ~ '^#[0-9A-Fa-f]{6}$')"
    )

    op.execute("ALTER TABLE calendar_event_labels ALTER COLUMN color DROP DEFAULT")
    op.execute(
        f"ALTER TABLE calendar_event_labels ALTER COLUMN color TYPE varchar(7) "
        f"USING {_case_sql('color')}"
    )
    op.execute(f"ALTER TABLE calendar_event_labels ALTER COLUMN color SET DEFAULT '{DEFAULT_HEX}'")
    op.execute(
        "ALTER TABLE calendar_event_labels ADD CONSTRAINT ck_event_label_colour_hex "
        "CHECK (color ~ '^#[0-9A-Fa-f]{6}$')"
    )
    # Note: the shared colour_token enum type itself is NOT dropped here —
    # group_memberships.colour still uses it.


def downgrade() -> None:
    # Any hex value that doesn't exactly match one of the 18 original tokens
    # (i.e. any genuinely custom colour picked after this feature shipped)
    # has no token to round-trip to — falls back to the same default token
    # migration 0015 used, a cosmetic recolour on downgrade only, matching
    # that migration's own stated policy for unrecognised values.
    hex_to_token = {hex_value: token for token, hex_value in TOKEN_HEX.items()}
    case_sql = " ".join(
        f"WHEN '{hex_value}' THEN '{token}'" for hex_value, token in hex_to_token.items()
    )

    op.execute("ALTER TABLE calendar_event_labels DROP CONSTRAINT ck_event_label_colour_hex")
    op.execute("ALTER TABLE calendar_event_labels ALTER COLUMN color DROP DEFAULT")
    op.execute(
        "ALTER TABLE calendar_event_labels ALTER COLUMN color TYPE colour_token "
        f"USING (CASE color {case_sql} ELSE 'teal' END)::colour_token"
    )
    op.execute("ALTER TABLE calendar_event_labels ALTER COLUMN color SET DEFAULT 'teal'")

    op.execute("ALTER TABLE home_calendars DROP CONSTRAINT ck_home_calendar_colour_hex")
    op.execute("ALTER TABLE home_calendars ALTER COLUMN color DROP DEFAULT")
    op.execute(
        "ALTER TABLE home_calendars ALTER COLUMN color TYPE colour_token "
        f"USING (CASE color {case_sql} ELSE 'teal' END)::colour_token"
    )
    op.execute("ALTER TABLE home_calendars ALTER COLUMN color SET DEFAULT 'teal'")
