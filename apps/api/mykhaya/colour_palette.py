"""The one curated colour palette shared by member identity and calendar
categories. A stable token (e.g. "emerald") is what's persisted and passed
across the API — never a raw hex value — so the actual shade can be tuned
centrally later without a data migration. See docs/design/visual-identity.md.

Mirrored by hand in packages/design-tokens/src/index.ts, the same way other
shared vocabulary (HouseholdRelationship, PermissionProfile, ...) is mirrored
between the Python schemas and packages/shared-types. Keep the two in sync.
"""

from enum import StrEnum


class ColourToken(StrEnum):
    red = "red"
    coral = "coral"
    orange = "orange"
    amber = "amber"
    yellow = "yellow"
    lime = "lime"
    green = "green"
    emerald = "emerald"
    teal = "teal"
    cyan = "cyan"
    sky = "sky"
    blue = "blue"
    indigo = "indigo"
    violet = "violet"
    purple = "purple"
    pink = "pink"
    rose = "rose"
    slate = "slate"


# Muted, warm-paper-compatible shades — distinct enough to tell apart at a
# glance, restrained enough not to compete with the terracotta brand accent.
# Several values intentionally match the colours already in use before this
# palette existed (the 4 starter member colours, the default label colours)
# so the migration backfill preserves people's existing identity colour
# rather than silently reassigning everyone.
PALETTE_HEX: dict[ColourToken, str] = {
    ColourToken.red: "#B8433A",
    ColourToken.coral: "#D97757",
    ColourToken.orange: "#C97A2E",
    ColourToken.amber: "#D9A83E",
    ColourToken.yellow: "#BFA23A",
    ColourToken.lime: "#7C9A4E",
    ColourToken.green: "#5C8A54",
    ColourToken.emerald: "#3F7A5C",
    ColourToken.teal: "#456B76",
    ColourToken.cyan: "#2E8B99",
    ColourToken.sky: "#4C7FA6",
    ColourToken.blue: "#3D6FB0",
    ColourToken.indigo: "#5A63A8",
    ColourToken.violet: "#8B6BA8",
    ColourToken.purple: "#7A5C99",
    ColourToken.pink: "#B85C8A",
    ColourToken.rose: "#A03F6A",
    ColourToken.slate: "#62706F",
}

# Cycled deterministically by mykhaya.member_colours.assign_member_colour so
# members of the same home never collide while the palette has spare
# capacity. Order matters only for which colour a household's Nth member
# gets by default — not a stability guarantee for any individual.
MEMBER_COLOUR_CYCLE: list[ColourToken] = list(ColourToken)

DEFAULT_LABEL_COLOUR = ColourToken.teal
