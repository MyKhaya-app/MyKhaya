# Expo and Device Development Audit

Status: Phase 1–2 audit only. No Expo configuration, EAS linkage, or dependency
versions have been changed as part of this document. This is an inspection
record to inform the checkpoint decision described in the Result section.

## Baseline (Phase 1)

Recorded on 2026-08-04 from a clean `dev` checkout at commit `fcef5f2`
(`origin/dev` matched exactly, no fetch was required).

| Item | Value |
| --- | --- |
| Branch created | `feature/mobile-calendar-foundation` (from `dev` @ `fcef5f2`) |
| Node.js | v24.18.1 (repo requires `>=22.13.0` via `package.json#engines`) |
| Package manager | pnpm, pinned via `packageManager: pnpm@10.14.0` in root `package.json` |
| Python | 3.14.2 |
| Expo SDK | `~53.0.20` |
| React Native | `0.79.5` |
| React | `19.0.0` |
| Expo Router | `~5.1.4` |

**Environment note:** `corepack enable` fails on this machine with
`EPERM: operation not permitted, open 'C:\Program Files\nodejs\pnpx'`
because the Node install directory isn't writable by the current user.
Workaround used throughout: `npx --yes pnpm@10.14.0 <command>`, which
resolves to the same pinned version. This does not change any project
configuration; it's a local tooling note for whoever runs these commands
next. `pnpm install --frozen-lockfile` was run successfully via this
workaround (762 packages, lockfile unchanged).

## Confirmed working behaviour

- The workspace installs cleanly with `pnpm install --frozen-lockfile` against
  the committed lockfile — no resolution changes.
- `apps/mobile` is a real, minimal Expo Router app (not a placeholder stub):
  `app/_layout.tsx` (root `Stack`) and `app/index.tsx` (a static "Good
  evening" home screen) exist and use `expo-router/entry` as the app entry.
- The app already depends on the shared workspace packages
  (`@mykhaya/api-client`, `@mykhaya/design-tokens`, `@mykhaya/shared-types`),
  though `app/index.tsx` does not currently call any of them beyond reading
  `Constants.expoConfig.extra.mykhayaVersion`.
- `expo-secure-store` is installed and referenced in `app.config.ts` plugins,
  but no code in `apps/mobile` currently calls it — the on-screen text
  ("Credentials will be stored only in platform secure storage") is aspirational,
  not yet implemented.
- `packages/design-tokens` already defines the approved MyKhaya palette
  (`sage`, `sageDark`, `terracotta`, `mustard`, `cream`, `slate`, `white`) plus
  spacing and radius scales, matching the CSS custom properties used by the
  web app (`tokens.css`). `apps/mobile/app/index.tsx` does **not** use these
  tokens — its `StyleSheet.create` block hardcodes hex colours directly
  (`#7D8F7A`, `#FAF7F1`, etc.), which happen to match the token values by
  coincidence, not by import.
- A real Calendar implementation already exists on `apps/api`
  (`mykhaya/routers/calendar.py`, migration `0003_calendar_module.py`,
  `tests/test_calendar.py`) and `apps/web` (`app/calendar/`, including a
  Playwright spec `e2e/household-calendar.spec.ts`). Mobile has no calendar
  code at all yet. A full cross-stack audit is Phase 6 and is deliberately
  out of scope for this document.
- `docs/engineering/mobile-standards.md` already documents several
  Calendar-specific mobile UI rules (compact month-cell indicators, full-height
  sheets for creation/editing, 44×44 touch targets, `prefers-reduced-motion`)
  that should govern Phase 8 onward.

## Defects and gaps found

1. **`app.json` and `app.config.ts` duplicate the same static config.**
   `expo-doctor` flags this directly: *"You have an app.json file in your
   project, but your app.config.ts is not using the values from it."*
   Right now both files happen to agree, but `app.config.ts` is the one Expo
   actually evaluates (dynamic config takes precedence), so `app.json` is
   dead weight that will silently drift. Recommended fix: delete the static
   `app.json` and keep only `app.config.ts`, which already has the
   version-file-reading logic `app.json` can't express. This is a config-only
   fix; scoping it into Phase 3/4 rather than doing it unprompted here.
2. **Missing required peer dependency: `expo-linking`.** `expo-router`
   requires it; `expo-doctor` warns the app *"may crash outside of Expo Go"*
   without it. Fix is `npx expo install expo-linking` — a targeted, justified
   addition, not scope creep.
3. **`react-native@0.79.5` vs Expo SDK 53's expected `0.79.6`.** A patch-level
   mismatch, not a compatibility blocker by itself; `npx expo install --check`
   would resolve it.
4. **No `eas.json`.** The project has never been linked to an EAS project —
   confirmed by absence of both `eas.json` and any `extra.eas.projectId` in
   `app.config.ts`/`app.json`. Phase 3 (EAS linking) is a clean, no-conflict
   operation — there is no existing link to accidentally overwrite.
5. **No LAN-safe API configuration exists yet.** There is no `EXPO_PUBLIC_*`
   usage anywhere in `apps/mobile`, no `.env.example` for mobile, and no code
   reading an API base URL. A physical phone cannot currently reach any
   backend from this app because there is no networking code at all yet —
   this needs to be built (Phase 4), not merely fixed.
6. **No showcase, no UI kit, no navigation shell beyond a single screen.**
   Confirms Phases 8–13 are genuinely greenfield within `apps/mobile`, not
   partially built.

## Compatibility risk: Expo Go (the material blocker)

Checked live (outside training-data cutoff) via Expo's own changelog and
search results, since this is time-sensitive and directly affects whether
Expo Go is viable at all right now:

- As of August 2026, the current Expo SDK release is **SDK 57**, and Expo
  Go's own policy is to support only the current SDK generation (Expo's
  May 2026 changelog describes SDK 54 remaining available while 55/56 were
  rolling out — i.e. Expo Go tracks a moving window of one to two recent
  SDKs, not an open-ended range).
- This repository is pinned to **SDK 53** — four major SDK releases behind
  current. Per Expo's own support model, and the GitHub issue observed during
  this search (*"Project is incompatible with this version of Expo Go"* for
  even a one-version gap in some cases), **SDK 53 should be assumed
  incompatible with the Expo Go app Anthony would install today.** This was
  not tested against a live device in this pass (no physical phone available
  in this environment) — it's a policy-based risk assessment, not a
  confirmed device failure. Phase 4/30 device testing must verify this
  directly before relying on the conclusion.
- `npx expo-doctor` did **not** flag the SDK-vs-Expo-Go gap itself (it only
  checks internal package/SDK consistency, not the live Expo Go app version),
  so the doctor output alone is not sufficient evidence either way.

Sources:
- [Expo Go and the App Store in May 2026 — Expo changelog](https://expo.dev/changelog/expo-go-and-app-store-may-2026)
- [Expo SDK 57 — Expo changelog](https://expo.dev/changelog/sdk-57)

## Assumptions

- No physical device or Mac was available in this environment for Phase 30
  manual testing; all findings above are static/config analysis plus one
  live web search, not device confirmation.
- `MYKHAYA_DEV_HOST_PORT=8080` (from `.env.dev.example`) is assumed to be the
  correct backend port for a future mobile `EXPO_PUBLIC_API_BASE_URL`, since
  the web README documents `http://localhost:8080/api/v1/health/live` as the
  liveness endpoint. Needs confirmation before Phase 4 implementation.
- No Expo account credentials are available to this agent. Phase 3 (`eas
  init`) requires an authenticated Expo CLI session under Anthony's own
  account and cannot be completed by this agent.

## Recommended changes (not yet made)

- Remove `app.json`, keep `app.config.ts` as the single source of Expo
  config (Defect 1).
- Add `expo-linking` as a direct dependency (Defect 2).
- Run `npx expo install --check` to align `react-native` to `0.79.6`
  (Defect 3) — patch-level only, not a major-version upgrade, so it doesn't
  trigger the Phase 4 "impact report before upgrading" requirement.
- Decide, with Anthony, between two paths before any further mobile UI work:
  - **(A) Upgrade SDK 53 → 57.** A four-major-version jump touching Expo,
    React Native, React, Expo Router and every Expo package in between.
    This is exactly the scenario Phase 4 describes as requiring "an impact
    report before upgrading" with full lint/typecheck/test coverage on both
    workspaces — it is not something to do opportunistically inside this
    same pass.
  - **(B) Use an EAS development build instead of Expo Go for now**, per the
    brief's own fallback instruction ("If a safe SDK upgrade cannot be
    completed during this task, document the blocker and establish an EAS
    development-build route instead"). This unblocks Phase 5 immediately
    without a risky multi-version upgrade, at the cost of Anthony needing to
    install a custom dev client once (via `eas build --profile development`)
    rather than using the plain Expo Go app.

## Changes made in this document's scope

- Created feature branch `feature/mobile-calendar-foundation` from `dev`.
- Ran `pnpm install --frozen-lockfile` (no lockfile changes).
- Ran `npx expo-doctor` (read-only diagnostic).
- No source files under `apps/mobile`, `app.json`, `app.config.ts`,
  `package.json`, or any other tracked file were modified.
