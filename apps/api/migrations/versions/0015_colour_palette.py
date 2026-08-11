"""Move member and calendar/category colours onto the shared colour_token enum.

Both `group_memberships.colour` and `calendar_event_labels.color` moved from
a raw `#RRGGBB` string to a stable palette token (see
mykhaya.colour_palette.ColourToken) — the actual shade can now be retuned
centrally later without another data migration, and the two colour surfaces
share one palette rather than each inventing its own.

Backfill is best-effort and non-destructive: the handful of hex values this
codebase has ever actually assigned (the 4 starter member colours, the 7
default category colours) are mapped to their closest/matching new token so
existing people and categories keep the same colour identity they already
had. Any other value (e.g. a hex picked ad hoc against the old free-form API
before this palette existed) falls back to a sensible default token rather
than failing the migration — a cosmetic recolour, not data loss, and there
is no production data yet at this project stage.

Revision ID: 0015_colour_palette
Revises: 0014_scheduler_occurrence_idempotency
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_colour_palette"
down_revision: str | None = "0014_scheduler_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLOUR_TOKENS = [
    "red", "coral", "orange", "amber", "yellow", "lime", "green", "emerald",
    "teal", "cyan", "sky", "blue", "indigo", "violet", "purple", "pink",
    "rose", "slate",
]

# Token -> representative hex, used only by downgrade() to produce a plausible
# raw colour again. Deliberately duplicated here rather than imported from
# mykhaya.colour_palette: migrations must keep working exactly as written
# even if the live palette module's values change later.
TOKEN_HEX = {
    "red": "#B8433A", "coral": "#D97757", "orange": "#C97A2E", "amber": "#D9A83E",
    "yellow": "#BFA23A", "lime": "#7C9A4E", "green": "#5C8A54", "emerald": "#3F7A5C",
    "teal": "#456B76", "cyan": "#2E8B99", "sky": "#4C7FA6", "blue": "#3D6FB0",
    "indigo": "#5A63A8", "violet": "#8B6BA8", "purple": "#7A5C99", "pink": "#B85C8A",
    "rose": "#A03F6A", "slate": "#62706F",
}

# Legacy raw-hex -> new token, for values this codebase has actually assigned.
MEMBER_HEX_TO_TOKEN = {
    "#5C8A54": "green",
    "#8B6BA8": "violet",
    "#D9A83E": "amber",
    "#4C7FA6": "sky",
}
LABEL_HEX_TO_TOKEN = {
    "#456B76": "teal",       # Family
    "#7A5C99": "purple",     # School
    "#476A3A": "emerald",    # Work
    "#A05A2C": "orange",     # Appointment
    "#A03F6A": "rose",       # Birthday
    "#336D9A": "blue",       # Activity
    "#666666": "slate",      # Other
}
DEFAULT_LABEL_TOKEN = "teal"


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*COLOUR_TOKENS, name="colour_token").create(bind)

    # --- group_memberships.colour (nullable) ---
    for hex_value, token in MEMBER_HEX_TO_TOKEN.items():
        op.execute(
            f"UPDATE group_memberships SET colour = '{token}' WHERE colour = '{hex_value}'"
        )
    # Anything else non-null is an unrecognised value (shouldn't exist in
    # practice, since assign_member_colour only ever picked from the 4 starter
    # hexes above) — clear it rather than fail the migration; the person can
    # simply choose a colour again from the new picker.
    known = "', '".join(MEMBER_HEX_TO_TOKEN.values())
    op.execute(
        f"UPDATE group_memberships SET colour = NULL "
        f"WHERE colour IS NOT NULL AND colour NOT IN ('{known}')"
    )
    op.execute(
        "ALTER TABLE group_memberships "
        "ALTER COLUMN colour TYPE colour_token USING colour::colour_token"
    )

    # --- calendar_event_labels.color (not null, has a default) ---
    for hex_value, token in LABEL_HEX_TO_TOKEN.items():
        op.execute(
            f"UPDATE calendar_event_labels SET color = '{token}' WHERE color = '{hex_value}'"
        )
    known = "', '".join(LABEL_HEX_TO_TOKEN.values())
    op.execute(
        f"UPDATE calendar_event_labels SET color = '{DEFAULT_LABEL_TOKEN}' "
        f"WHERE color NOT IN ('{known}')"
    )
    op.execute("ALTER TABLE calendar_event_labels ALTER COLUMN color DROP DEFAULT")
    op.execute(
        "ALTER TABLE calendar_event_labels "
        "ALTER COLUMN color TYPE colour_token USING color::colour_token"
    )
    op.execute(
        f"ALTER TABLE calendar_event_labels ALTER COLUMN color SET DEFAULT '{DEFAULT_LABEL_TOKEN}'"
    )


def downgrade() -> None:
    case_sql = " ".join(f"WHEN '{token}' THEN '{hex_value}'" for token, hex_value in TOKEN_HEX.items())

    op.execute(
        "ALTER TABLE group_memberships ALTER COLUMN colour TYPE varchar(7) "
        f"USING (CASE colour::text {case_sql} END)"
    )
    op.execute("ALTER TABLE calendar_event_labels ALTER COLUMN color DROP DEFAULT")
    op.execute(
        "ALTER TABLE calendar_event_labels ALTER COLUMN color TYPE varchar(7) "
        f"USING (CASE color::text {case_sql} END)"
    )
    op.execute("ALTER TABLE calendar_event_labels ALTER COLUMN color SET DEFAULT '#456B76'")

    bind = op.get_bind()
    postgresql.ENUM(name="colour_token").drop(bind)
