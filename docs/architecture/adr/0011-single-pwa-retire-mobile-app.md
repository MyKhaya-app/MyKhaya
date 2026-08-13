# ADR 0011: Single Responsive PWA — Retire apps/mobile as a Native Client

**Status:** Accepted (Anthony, 2026-08-05, as part of the MyKhaya mobile-first product reset).

## Decision

MyKhaya will ship as one responsive Progressive Web App (`apps/web`), installable on mobile, tablet and desktop. `apps/mobile` (Expo/React Native) is retired as a product surface: no further feature development, and the app itself is to be removed once the PWA reaches equivalent installability and core-journey coverage. There will not be a second frontend, a duplicated mobile codebase, or platform-specific native builds for the first release or the foreseeable roadmap beyond it.

## Context

`apps/mobile` was scaffolded to explore a native client and currently contains a single screen (API health check plus sign-in/out) — no calendar, family, or settings functionality exists there. Recent history (`92567f9`, `20e84df`, `b78cb06`) is dominated by Expo SDK version churn and Metro/pnpm resolution fixes rather than product features; the only substantive feature commit against it implemented [ADR 0010](./0010-mobile-bearer-session-tokens.md)'s bearer-token authentication.

Maintaining two frontends (a Next.js PWA and an Expo native app) means two component systems, two navigation models, two accessibility surfaces, and two places for the approved MyKhaya brand to drift out of sync — directly contrary to the design-system and mobile-first goals of this reset. A PWA served from `apps/web`, built mobile-first with proper safe-area handling, offline support, and installability, covers the same "feels like an installed app" goal without that duplication.

## What this does and does not affect

- **Retired**: `apps/mobile` as a shipping product surface. Its Expo scaffold, screens, and Expo-specific build tooling are removed from active development; the directory is deleted once the PWA covers sign-in at parity (tracked separately, not blocking this ADR).
- **Not retired by this decision**: the bearer-token authentication mechanism described in ADR 0010 (`apps/api/mykhaya/security.py`, `routers/auth.py`, `dependencies.py`, `schemas.py`, `resolve_session`, `/auth/mobile/*` endpoints). That mechanism is server-side, already reviewed, tested, and generically useful for any non-cookie client (a future native client, a future first-party API consumer) — it is not exclusively "for `apps/mobile`" and removing it is not required to retire the app. It is left in place, unused, until there is a concrete reason to remove it. Doing otherwise would be scope creep beyond what this reset requires.
- `docs/mobile/expo-go-setup.md` and `docs/mobile/expo-and-device-development-audit.md` become historical records of the native-client exploration; they should be marked superseded rather than deleted outright, so the reasoning captured in ADR 0010 and this ADR remains traceable.
- `docs/engineering/mobile-standards.md` needs review against this decision — standards written for a native Expo app (platform-specific build/release process, app-store considerations) no longer apply; anything about mobile *web* UX (touch targets, safe areas, responsive breakpoints) is retained and should move under `frontend-standards.md` or an equivalent PWA-focused section rather than a separate "mobile" standards doc implying a separate codebase.

## Alternatives considered

- **Keep both surfaces.** Rejected: doubles the maintenance burden the design-system requirement in this reset is explicitly trying to eliminate, for a native app that currently has no functionality beyond what the PWA will provide anyway.
- **Pause the decision, keep apps/mobile untouched, revisit later.** Considered, but the reset's own mandate ("no React Native... one maintainable application") is unambiguous, and apps/mobile has no functionality that would be lost by stopping work on it now versus later — deferring only prolongs the two-codebase problem without benefit.

## Consequences

- `apps/mobile`'s workspace entry, CI steps (if any target it specifically), and Expo-specific dependencies are removed as part of the reset's consolidation stage, not this ADR — deletion scope is confirmed with Anthony before any files are removed.
- Future native-client work, if ever pursued again, starts from this ADR and ADR 0010 rather than from scratch.
