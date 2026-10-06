# Frontend Standards

- Use Next.js App Router and strict TypeScript.
- Use generated API clients and explicit response models.
- Use central design tokens; never scatter raw brand colours.
- Components must be accessible, responsive and keyboard usable.
- Authentication secrets must not be stored in browser localStorage.
- Protected routes do not replace API authorisation.
- Avoid generic dashboard templates and third-party design systems that conflict with the approved design.
- Implement loading, empty, success and failure states deliberately.
- Do not use broad CSP exceptions to fix implementation problems.
- Test critical journeys with Playwright.

## Hybrid presentation contract

MyKhaya has one shared frontend with separate presentation families. Mobile and
native are fixed, app-like and touch-first. Browser/tablet/desktop is adaptive,
spacious and must use available width intentionally. Desktop must not remain a
phone-width centred column, and mobile must not inherit desktop geometry.

Use mobile/base CSS as the protected baseline, then add scoped `min-width`
enhancements for wider screens. Keep business logic, API access, authentication,
permissions, entitlements, domain state and mutations shared. Presentation-
specific wrappers, grids, dialogs and panels are acceptable when they do not
duplicate business logic.

Use `isNativeShell()` and `nativePlatform()` from
`components/native-runtime.ts` for genuinely native behaviour. Use viewport and
media queries for layout. Both modes must be verified, including phone,
tablet and desktop widths; physical iPhone review remains required where the
native shell can be affected. PCC remains separate and desktop-first.

## Shared module controls

Reuse established MyKhaya interaction patterns across modules. Segmented
selectors use the shared `.rr-segmented` container and `.rr-segment` buttons,
with the appropriate active-state class. A module's primary create action uses
the shared `.rr-fab` floating `+ Add` control, including its bottom-navigation
and safe-area clearance. Do not introduce an inline module-specific `+ New`
variant when the module has a single primary creation flow; preserve the
existing search, content width, and module-specific content around these
shared controls.

## Unresolved authorisation and entitlement state

Asynchronous state that decides what a user may see (session, role, plan,
entitlements, feature settings, current Home) is modelled as
`loading | ready | error` (`apps/web/components/resolvable.ts`), never as a
boolean whose initial value means "allowed" or "denied".

`UNKNOWN → RESOLVING → RESOLVED → RENDER`; never `ASSUME → RENDER → FETCH → CORRECT`.

- Render the stable shell immediately; show a same-sized skeleton/placeholder
  (not a full-screen spinner) for unresolved sensitive content.
- Consumer plan/feature state comes from `useHomeAccess()`
  (`components/home-access.tsx`): one per-Home cached resolution shared by nav,
  dock, More and Home. Do not add new per-page `billingStatus`/`featureMatrix`
  fetches with `useState(false)` defaults.
- PCC session state comes from `usePlatformSession()`
  (`components/platform-session.ts`); `PlatformShell` renders nothing
  privileged until it is `authenticated`.
- Gate before render; do not render protected content and redirect from
  `useEffect` afterwards. Client-side gating is presentation only — the API
  remains the authorisation boundary.
- `e2e/auth-state-flicker.spec.ts` guards this with delayed mocked APIs and a
  MutationObserver.

### Follow-up (not yet done)

- Physical iPhone / native-shell validation of the new startup and nav states.
- Cold-load layout shift (Home sections, Family tab); consider persisting the
  last-known plan per Home.
- Migrate remaining feature pages (Calendar, Lists, Driveway, Meal Plans,
  Wishlists, Nudges, Members, and the Home dashboard's own matrix, `api.me`
  and meal-card fetches) onto `useHomeAccess()` where useful.
- Call `HomeAccessProvider.refresh()` after checkout and complimentary-plan
  changes.
