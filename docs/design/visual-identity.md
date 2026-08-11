# MyKhaya Visual Identity

## Authority

This is the entry point for MyKhaya's design system, the way
`docs/engineering/engineering-standards.md` is the entry point for engineering.
Read this first. The sibling files in `docs/design/` — `branding.md`,
`design-system.md`, `components.md`, `accessibility.md`,
`layout-and-navigation.md`, `tone-and-copy.md` — hold topic-level detail and
must not contradict this document; where they do, this document wins and the
sibling file needs updating, not the other way round.

This identity was reached through an explicit design-exploration pass (five
visual directions, a refinement round, then a synthesis called "Version D")
rather than picked from a template. The reasoning is worth preserving because
it explains *why*, not just *what*.

## The MyKhaya Promise

> MyKhaya exists to help households remember what matters.
>
> Every design decision should reduce cognitive load, create a sense of calm
> and make family life easier.
>
> The interface should feel warm, personal and thoughtfully crafted. It
> should never resemble enterprise software, an administration portal or a
> generic productivity application.
>
> When in doubt, prefer simplicity over functionality, clarity over
> cleverness, and people over technology.

Every rule below is downstream of this. If a proposed change satisfies a
rule below but violates the Promise, the Promise wins.

## What MyKhaya is

A family companion, not a family organiser. That distinction is load-bearing:
it's the test for whether a proposed feature belongs. "Would a beautifully
crafted family companion have a graph / a dashboard / a settings toggle for
this?" is a real design review question, not a rhetorical one. If the answer
is no, the feature needs a different shape or doesn't ship.

## Household-first principle

Every feature must answer: does this genuinely help a household coordinate
daily life? If not, it should be reconsidered or postponed — regardless of
how good an idea it is in isolation. This is the permanent filter new scope
gets run through, not a one-time review step.

## Home is the centre of the product, Calendar is a tool

Calendar is where a household plans. **Home is where it lives.** As MyKhaya
grows, Home should naturally surface calendar events, household routines,
birthdays and other things that matter today, without becoming cluttered —
Alyssa's swimming lesson, the recycling going out tonight, a medication
reminder, a delivery, a birthday tomorrow, alongside real calendar events.
Calendar remains essential, but it is not where the emotional weight of the
product lives — Home is. Every future feature (Shopping, Lists, Reminders)
should ask what its Home-screen presence looks like, not just what its own
dedicated screen looks like.

## One question per screen

Every screen answers exactly one question. If it needs five sentences to
explain what it's for, it gets redesigned, not documented harder.

| Screen | The one question |
|---|---|
| Home | What matters today? |
| Calendar | What is happening? |
| Family | Who is in my home? |
| Shopping *(future)* | What do we need? |
| Reminders *(future)* | What should I remember? |
| Settings | What can I change? |

This is the concrete, testable form of the neurodiversity commitment below —
not a separate mode, a discipline applied everywhere. See also: never more
than one primary action per screen, never more than one thing visually
competing for attention.

## Colour

The canonical palette in `design-system.md` (sage, terracotta, mustard,
cream, slate) remains the foundation. On top of it, MyKhaya has two distinct
colour identities, both drawn from one shared curated palette
(`mykhaya.colour_palette.ColourToken` / `packages/design-tokens`,
18 muted tokens — red, coral, orange, amber, yellow, lime, green, emerald,
teal, cyan, sky, blue, indigo, violet, purple, pink, rose, slate):

**Member colour** — each family member owns one personal colour, chosen by
themselves or set by a Home Admin, used everywhere *that person* appears:
their avatar, member indicators, ownership dots, filters. Not their calendar
events — see below. "Blue means Joshua" in every screen where identity is
the point.

**Calendar/category colour** — each calendar or category (Family, School,
Work, ...) owns its own colour, set by a Home Admin, and *that* is what
determines an event's colour on Calendar — not who created it. Colour
consistency across a multi-day event's continuation segments matters as much
as the colour choice itself: one event, one colour, every day it spans.

Keeping these separate is deliberate: a household's shared calendar needs to
read as a shared calendar, scannable by category, independent of whichever
member happens to have created a given event.

Both pickers are the same compact swatch grid
(`components/colour-swatch-picker.tsx`) — one palette, one picker, wherever
a colour is chosen.

## Typography

One display face, used sparingly; one UI face, used for everything a person
actually has to read quickly.

- **Display** (`ui-rounded`, falling back to the system sans): reserved for
  the Home greeting name and equivalent one-off hero moments. Never used in
  navigation, lists, forms, buttons or settings.
- **UI** (system sans — the existing `-apple-system` / `SF Pro Text` /
  Inter stack): everything else. Calendar, Family, Settings, event titles,
  card headings, button labels. This split exists specifically so density
  and personality don't trade off against each other — the screens people
  live in stay fast to scan, and the one screen that should feel like
  a kept object still does.
- Ink is a dark forest charcoal (`#233028`), never near-black. A small,
  deliberate warmth difference that reads immediately even though the
  contrast ratio barely changes.

## Cards

Soft shadow-lift, not hairline borders (the "Option B" read from the
refinement round won on perceived quality): 20–22px radius, generous
internal padding (~18px), warm white or linen fill against the cream page,
no visible grey border. See `components.md` for the implementation-level
spec — it should match this, not the older, tighter version.

## Avatars

Bigger than earlier drafts, and load-bearing. Family is the product, not
events or buttons — avatars should be one of the first things visible on
Home (see: the family strip, directly under the greeting, before any card).
Initials-only until real profile photos exist; never invent a fake photo.

## Empty states

Reassuring, never technical, rotated rather than static so the app doesn't
repeat itself:

- 🌿 Your day's looking nice and calm.
- ✨ Nothing planned just yet.
- ☀️ Enjoy the quieter day.

An empty day is good news. The copy should say so, not report zero rows.

## Writing style

The interface talks to the person using it, never describes its own data
model back to them. See `tone-and-copy.md` for the full standard; the
Version D additions:

| System language | Family language |
|---|---|
| Household members | Your family |
| Home Administration / Control Centre | Manage your home |
| Upcoming | Coming up |
| Quick actions | Around the house |

## Motion

Subtle, never decorative for its own sake: card press states, nav
active-state transitions, bottom-sheet presentation. Always gated behind
`prefers-reduced-motion`. An orchestrated moment (one page-load sequence)
beats scattered micro-animations everywhere.

## Accessibility and neurodiversity

Full detail in `accessibility.md`; this system's specific angle: reducing
cognitive load is achieved through mainstream design discipline — spacing,
hierarchy, single-accent restraint, one primary action, natural language,
progressive disclosure — not a bolted-on "ADHD mode." A neurodivergent user
and a busy parent glancing at their phone for four seconds benefit from
exactly the same discipline. Colour-as-identity (member colours) must never
be the *only* signal — always paired with initials or a name, per the
existing no-colour-only-status rule.

## Mobile-first

See `layout-and-navigation.md`. Nothing in Version D changes the underlying
rule: design the phone layout first, verify it, then widen for tablet and
desktop as an expanded version of the same layout — never a separate one.

## Things MyKhaya deliberately does not do

- No graphs, charts, or analytics-style dashboards on Home or Family.
- No free-form colour picker for either identity or categories — always the
  one curated palette, never an arbitrary hex value a person types in.
- No enterprise/admin visual language (dense tables, dark technical panels,
  corporate iconography) anywhere in the household-facing product. That
  register is reserved for the operator-only platform Control Centre, which
  is intentionally a different visual system.
- No feature added because "an app like this usually has one." Every
  addition has to answer a real question a household actually has.
- No fabricated data, fake photos, or UI for features that don't exist yet
  (a permission-request button that doesn't lead anywhere, a nav item for an
  unbuilt module). If it's not real, it's not in the product yet, however
  good it would look in a mock-up.

## On the household-memory idea

Noted for the roadmap, not designed yet: Today showing bins night,
medication, a delivery, a birthday, alongside events — MyKhaya as the
household's actual memory, not just its calendar. Genuinely the strongest
idea raised during this exploration. It touches real, currently-nonexistent
data models (recurring household routines, reminders, deliveries) and
deserves its own scoping and security/data-model pass before design work
starts, rather than being sketched into an identity document as if it
already existed.
