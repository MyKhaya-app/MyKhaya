# Layout and Navigation

## Desktop

Use the mock-up's rounded left navigation rail, calm top bar and spacious central Home layout on wide screens. Navigation is generated from the server module registry: Home, enabled released modules, Household members and Settings. Hidden modules never appear. Home Admins also receive the household Khaya Control Centre; this is separate from the restricted platform operator Control Centre.

On phones, use a safe-area-aware bottom bar with no more than five contextual destinations. Calendar uses Month, Week, Day and Agenda views, remembers the chosen view, and defaults small screens to Agenda when no preference exists. Day details and event forms are accessible bottom sheets.

## Presentation families

### Mobile/native

The mobile/native presentation is app-like, stacked, compact and touch-first.
It uses the warm header, safe-area-aware fixed bottom navigation, mobile FAB
clearance and bottom sheets/full-height sheets. It is the protected baseline and
must not receive desktop rails, wide canvases, horizontal scroll, zoomed-out
content or desktop breakpoint leakage.

### Tablet

Tablet is the adaptive bridge: retain touch-friendly controls while using two
columns, wider Calendar/planning surfaces and expanded navigation where useful.
Do not assume tablet is either a stretched phone or a reduced desktop.

### Desktop consumer web

Consumer desktop web should deliberately use available width through wider Home
composition, Calendar grids, multi-column layouts, keyboard/mouse-efficient
forms and desktop dialogs or side panels. It must not be a narrow phone-width
centre column inside a large blank viewport.

### PCC

PCC is a separate desktop-first administrative surface. Consumer mobile layout
and navigation rules do not govern PCC unless explicitly requested.

## Mobile

Use a warm branded header, stacked cards and a bottom navigation bar with a central quick-add action. Mobile must be designed natively rather than simply shrinking the desktop layout.

## One question per screen

Every screen answers exactly one question — Home: what matters today?
Calendar: what is happening? Family: who is in my home? Settings: what can I
change? If a screen needs several sentences to explain its purpose, redesign
it rather than document around the problem. Full rationale in
`visual-identity.md`.

## Terminology

The main screen is Home. Do not use Dashboard, Workspace, Overview or Control Panel. Avoid tenant, RBAC, module and group ID in user-facing copy. Prefer "Your family" over "Household members" and "Manage your home" over "Control Centre" in household-facing copy — see `tone-and-copy.md`.
