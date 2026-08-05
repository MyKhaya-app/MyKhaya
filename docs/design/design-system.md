# MyKhaya Design System

> See `visual-identity.md` first — it is the entry point and source of truth
> for the overall system (the MyKhaya Promise, one-question-per-screen,
> family colours, typography split, Version D). This file holds the
> underlying palette and identity rules that document builds on.

## Absolute identity rule

MyKhaya must not look like Kaya.

Kaya is an infrastructure and administration platform. MyKhaya is a consumer lifestyle and coordination product. They share engineering discipline, not visual design.

Do not reuse Kaya navigation, components, spacing, cards, dark technical styling, dense layouts, terminology or admin-dashboard patterns.

## Canonical palette

- Sage Green `#7D8F7A`
- Terracotta `#E07A5F`
- Mustard `#E9B44C`
- Cream `#F2EDE3`
- Slate `#1F2933`

Use central semantic tokens and accessible derived shades. Ink/body text
should read as a dark forest charcoal (`#233028`) rather than near-black —
see `visual-identity.md`.

## Member colours

Separate from the palette above: each family member owns one colour,
assigned once, used everywhere that member appears (avatar, their events on
Calendar, their items on any future per-person list) — never a
category-based colour scheme. Starter set and full rationale in
`visual-identity.md`. This is a real `member.colour` field to design when
that work starts, not a client-side hash.

## Visual language

- Warm cream page surfaces
- Soft white cards
- Gentle shadows
- Rounded corners
- Calm sage navigation and primary actions
- Terracotta and mustard for friendly emphasis
- Slate typography
- Generous spacing
- Simple outlined icons
- Minimal visual noise

## Prohibited substitutions

No generic SaaS templates, default Tailwind appearance, Material defaults, Bootstrap-like controls, corporate dashboards, dark infrastructure panels or Kaya-derived components.
