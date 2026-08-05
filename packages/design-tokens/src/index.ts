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

// Identity belongs to a person, not an event category — see
// docs/design/visual-identity.md. Cycle this list until member.colour
// exists as a real, persisted field.
export const memberColours = ["#5C8A54", "#8B6BA8", "#D9A83E", "#4C7FA6"] as const;

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
