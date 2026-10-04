# UI platform standards

## Governing decision

MyKhaya has one shared consumer frontend, `apps/web`, with two deliberate
presentation families:

- mobile/native: fixed, app-like, touch-first and safe-area aware;
- browser/tablet/desktop: adaptive, spacious and designed to use available width.

The native Capacitor shell in `apps/ios-shell` loads the deployed `apps/web`
frontend. It is a wrapper and native capability boundary, not a second
frontend. Shared business logic and feature behaviour remain in `apps/web`.

> Mobile is fixed and app-like. Desktop is adaptive and spacious. Neither is
> allowed to compromise the other.

## Protected mobile baseline

Unless a task explicitly requests a mobile/native change, preserve the current
mobile header, safe-area handling, content width, spacing, bottom navigation,
bottom sheets, FAB clearance, touch targets, keyboard behaviour, viewport model,
sticky/fixed positioning, density and mobile navigation destinations.

Mobile must not acquire horizontal scrolling, zoomed-out pages, desktop
sidebars, desktop-width canvases, header or bottom-nav overlap, safe-area
clipping, hidden content, or desktop breakpoint leakage into WKWebView.

## Wide-screen adaptation

Tablet and desktop may use wider shells, multi-column Home and Calendar layouts,
split list/detail surfaces, navigation rails or sidebars, wider forms, and
desktop dialogs or panels. Do not merely centre the mobile app in a large blank
viewport or leave consumer pages constrained to a phone-width column.

Use mobile/base CSS as the protected baseline and add scoped `min-width`
enhancements. Prefer page, module or explicit wide-shell selectors. Avoid broad
global changes to buttons, cards, containers, typography, safe areas or fixed
positioning when a scoped rule is sufficient. Do not use CSS zoom, transform
scaling or routine `!important` responsive overrides.

## Shared logic and presentation composition

Keep API access, authentication, authorization, entitlements, domain state,
validation, mutations, data models, semantic content and feature logic shared.
Presentation-specific composition is encouraged where it improves each mode,
for example a mobile stacked layout versus a desktop grid, or a mobile
bottom-sheet versus a desktop dialog/panel. Do not duplicate business logic.

Use viewport/media queries for responsive layout. Use only the canonical
`isNativeShell()` and `nativePlatform()` helpers for genuinely native
capabilities or runtime behaviour. Native detection is not an authorization
boundary and must not replace responsive CSS.

## Breakpoints and navigation

Verify phone widths at 320, 375, 390 and 430px; tablet at 768 and 1024px; and
desktop at 1280, 1440 and, where materially relevant, 1920px. Mobile/native
uses the safe-area-aware bottom navigation and compact stacked composition.
Tablet is an adaptive bridge. Consumer desktop may use deliberate wide
navigation and information layouts. PCC remains a separate desktop-first
surface and is not governed by consumer mobile constraints.

## Sheets, dialogs and focus

Use full-height bottom sheets for mobile flows where the existing mobile
pattern requires them. Desktop may use dialogs, side panels or split surfaces,
but must preserve keyboard access, focus management, readable forms and clear
escape/close behaviour. Keyboard and focus behaviour must be checked for web
layouts; mobile sheets must retain safe-area and keyboard clearance.

## Verification and no-bleed-over rule

Every user-facing UI change is classified as mobile-only, wide-screen-only,
shared behaviour, or shared component with presentation-specific layout. Verify
the affected phone, tablet and desktop widths, and both native/browser modes
where the change can affect the shell. Include automated 390x844 and 1440x900
coverage where visual regression tooling exists. Physical iPhone review is
mandatory before release for changes capable of affecting the native shell.

No desktop change may alter the protected mobile/native geometry or behaviour.
No mobile change may force the browser/tablet/desktop experience to remain a
narrow phone layout. Shared CSS/layout changes require explicit impact review.

## PCC separation

PCC is a distinct privileged management-plane UI and remains desktop-first.
Consumer mobile presentation rules, navigation and layout assumptions must not
be reused in PCC unless explicitly requested and separately reviewed.
