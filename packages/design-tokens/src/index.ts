// Kept in sync with tokens.css by hand — same keys, same values, TS just
// exposes them as JS values (e.g. for inline style props) instead of CSS vars.
export const colour = {
  sage: "#7D8F7A",
  sageDark: "#566B58",
  sageSoft: "#E7EBE4",
  forest: "#3F5442",
  forestDark: "#33452F",
  terracotta: "#E07A5F",
  mustard: "#E9B44C",
  cream: "#F2EDE3",
  creamLight: "#FAF7F1",
  slate: "#233028",
  muted: "#62706F",
  white: "#FFFEFB",
  danger: "#A33E2B",
} as const;

// The one curated colour palette shared by member identity and calendar
// categories. Member colour still persists a stable token (e.g. "emerald");
// calendar/category colour persists the resolved hex value directly (see
// mykhaya.colour_palette.HexColour) with an optional custom colour on top —
// this array is the preset swatch set offered before "Custom" in either
// picker. Mirrored by hand from mykhaya.colour_palette.PALETTE_HEX (Python);
// keep the two in sync. See docs/design/visual-identity.md.
export const PALETTE_KEYS = [
  "red", "coral", "rust", "orange", "amber", "yellow", "olive", "lime",
  "green", "emerald", "jade", "teal", "cyan", "sky", "blue", "azure",
  "indigo", "periwinkle", "violet", "purple", "plum", "pink", "magenta",
  "rose", "slate", "stone", "charcoal",
] as const;

export type ColourKey = (typeof PALETTE_KEYS)[number];

export const PALETTE_HEX: Record<ColourKey, string> = {
  red: "#B8433A",
  coral: "#D97757",
  rust: "#9C5223",
  orange: "#C97A2E",
  amber: "#D9A83E",
  yellow: "#BFA23A",
  olive: "#8C9138",
  lime: "#7C9A4E",
  green: "#5C8A54",
  emerald: "#3F7A5C",
  jade: "#2F7A6A",
  teal: "#456B76",
  cyan: "#2E8B99",
  sky: "#4C7FA6",
  blue: "#3D6FB0",
  azure: "#3E5FA0",
  indigo: "#5A63A8",
  periwinkle: "#6C63B5",
  violet: "#8B6BA8",
  purple: "#7A5C99",
  plum: "#6B4C87",
  pink: "#B85C8A",
  magenta: "#9C2F6E",
  rose: "#A03F6A",
  slate: "#62706F",
  stone: "#8A7F6E",
  charcoal: "#4A4F4E",
};

// Mirrors mykhaya.colour_palette.DEFAULT_LABEL_COLOUR_HEX — the initial
// colour a new Calendar Tag/Home calendar gets before anyone customises it.
export const DEFAULT_CALENDAR_COLOUR: string = PALETTE_HEX.teal;

function isColourKey(value: string): value is ColourKey {
  return Object.prototype.hasOwnProperty.call(PALETTE_HEX, value);
}

function hashPalette(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return PALETTE_HEX[PALETTE_KEYS[hash % PALETTE_KEYS.length]!];
}

/** Resolves a persisted colour value (a palette token like "emerald", a raw
 *  `#RRGGBB` string from data that predates the palette, or nothing) to an
 *  actual CSS colour. `seed` (e.g. a user id) drives the deterministic
 *  fallback used when there's no persisted colour at all yet. */
export function resolveColour(value: string | null | undefined, seed = ""): string {
  if (value) {
    if (isColourKey(value)) return PALETTE_HEX[value];
    if (/^#[0-9a-fA-F]{6}$/.test(value)) return value;
  }
  return hashPalette(seed);
}

/** Relative luminance (sRGB, unlinearised approximation — good enough for
 *  picking readable text on a solid fill, not a WCAG-precise calculation). */
export function contrastText(hex: string): string {
  const value = hex.replace("#", "");
  if (value.length !== 6) return "#FFFEFB";
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.6 ? "#233028" : "#FFFEFB";
}

export const radius = { small: 10, card: 22, shell: 24, hero: 32 } as const;
export const spacing = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 } as const;
export const font = {
  family: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif",
  familyDisplay: "ui-rounded, Inter, ui-sans-serif, system-ui, -apple-system, sans-serif",
  hero: "2.75rem",
  display: "1.75rem",
  title: "1.375rem",
  heading: "1.0625rem",
  body: "0.9375rem",
  small: "0.8125rem",
  micro: "0.6875rem",
} as const;
