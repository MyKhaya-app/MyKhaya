"""The one curated colour palette shared by member identity and calendar
categories. Member colour still persists a stable token (e.g. "emerald") —
see `MEMBER_COLOUR_CYCLE`/`assign_member_colour`. Calendar/category colour
(`HomeCalendar.color`, `CalendarEventLabel.color`) persists the resolved hex
value directly instead (see `HexColour`), with an optional custom colour on
top of these presets — see docs/design/visual-identity.md and ADR-equivalent
notes in the calendar colour migration (0045_calendar_colour_hex).

Mirrored by hand in packages/design-tokens/src/index.ts, the same way other
shared vocabulary (HouseholdRelationship, PermissionProfile, ...) is mirrored
between the Python schemas and packages/shared-types. Keep the two in sync.
"""

import re
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator


class ColourToken(StrEnum):
    red = "red"
    coral = "coral"
    rust = "rust"
    orange = "orange"
    amber = "amber"
    yellow = "yellow"
    olive = "olive"
    lime = "lime"
    green = "green"
    emerald = "emerald"
    jade = "jade"
    teal = "teal"
    cyan = "cyan"
    sky = "sky"
    blue = "blue"
    azure = "azure"
    indigo = "indigo"
    periwinkle = "periwinkle"
    violet = "violet"
    purple = "purple"
    plum = "plum"
    pink = "pink"
    magenta = "magenta"
    rose = "rose"
    slate = "slate"
    stone = "stone"
    charcoal = "charcoal"


# Muted, warm-paper-compatible shades — distinct enough to tell apart at a
# glance, restrained enough not to compete with the terracotta brand accent.
# The original 18 values are unchanged (existing member colours and any
# pre-migration calendar/category data depend on them); the rest were added
# to widen the calendar/category preset palette to ~24-30 colours with a
# useful spread across warm, cool, and neutral families without crowding
# near-identical shades next to an existing one.
PALETTE_HEX: dict[ColourToken, str] = {
    ColourToken.red: "#B8433A",
    ColourToken.coral: "#D97757",
    ColourToken.rust: "#9C5223",
    ColourToken.orange: "#C97A2E",
    ColourToken.amber: "#D9A83E",
    ColourToken.yellow: "#BFA23A",
    ColourToken.olive: "#8C9138",
    ColourToken.lime: "#7C9A4E",
    ColourToken.green: "#5C8A54",
    ColourToken.emerald: "#3F7A5C",
    ColourToken.jade: "#2F7A6A",
    ColourToken.teal: "#456B76",
    ColourToken.cyan: "#2E8B99",
    ColourToken.sky: "#4C7FA6",
    ColourToken.blue: "#3D6FB0",
    ColourToken.azure: "#3E5FA0",
    ColourToken.indigo: "#5A63A8",
    ColourToken.periwinkle: "#6C63B5",
    ColourToken.violet: "#8B6BA8",
    ColourToken.purple: "#7A5C99",
    ColourToken.plum: "#6B4C87",
    ColourToken.pink: "#B85C8A",
    ColourToken.magenta: "#9C2F6E",
    ColourToken.rose: "#A03F6A",
    ColourToken.slate: "#62706F",
    ColourToken.stone: "#8A7F6E",
    ColourToken.charcoal: "#4A4F4E",
}

# Cycled deterministically by mykhaya.member_colours.assign_member_colour so
# members of the same home never collide while the palette has spare
# capacity. Order matters only for which colour a household's Nth member
# gets by default — not a stability guarantee for any individual.
MEMBER_COLOUR_CYCLE: list[ColourToken] = list(ColourToken)

DEFAULT_LABEL_COLOUR = ColourToken.teal
# The hex a new calendar/category colour column actually stores/defaults to
# (see HomeCalendar.color / CalendarEventLabel.color) — resolved once here
# rather than repeating PALETTE_HEX[DEFAULT_LABEL_COLOUR] at every call site.
DEFAULT_LABEL_COLOUR_HEX: str = PALETTE_HEX[DEFAULT_LABEL_COLOUR]

HEX_COLOUR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def normalise_calendar_colour(value: str) -> str:
    """Validator for calendar/category colour input (HomeCalendar.color,
    CalendarEventLabel.color) — accepts either a preset palette token name
    (kept for backward compatibility with any existing client still sending
    one, e.g. "emerald") or a standard 6-digit hex colour, always resolving
    to hex before storage: the whole point of this field is that a custom
    colour never has to correspond to a predefined palette identifier.
    Rejects anything else (never arbitrary CSS colour syntax)."""
    if value in ColourToken.__members__:
        return PALETTE_HEX[ColourToken(value)]
    if HEX_COLOUR_PATTERN.match(value):
        return value.upper()
    raise ValueError(
        "Colour must be a preset name or a 6-digit hex value, e.g. #E27658"
    )


# Calendar/category colour field type — a real hex string, not a palette
# token. Used by HomeCalendarUpdate/Response, EventLabelCreate/Update/Response,
# EventOccurrence.calendar_color, and CalendarShareResponse.calendar_color.
# Deliberately distinct from ColourToken, which member colour fields still use.
HexColour = Annotated[str, AfterValidator(normalise_calendar_colour)]
