# Expo and Device Development Audit

Status: **`apps/mobile` is back on Expo SDK 53** as of the SDK rollback
(see "SDK rollback: 57 → 53" below). The "SDK upgrade outcome" section
further down is kept as an accurate historical record of the 53→57 upgrade
that was done, decided against, and reverted — read it for that history,
not as the current state. EAS linkage (Phase 3) has not been done — it
requires an authenticated Expo CLI session under Anthony's own account.

## SDK rollback: 57 → 53

The SDK 53→57 upgrade below was completed and merged (`dev` PR #5), but
before any physical-device testing had happened, Anthony decided the
upgrade introduced unnecessary development-build complexity too early —
the mobile product hadn't yet been validated on a phone at all. This is a
**deliberate stabilisation step for early development, not a permanent
architecture decision.** `apps/mobile` will very likely need to move to a
newer SDK and/or an EAS development build again once native functionality
grows beyond what Expo Go supports.

Current facts (checked live, time-sensitive — see the "Compatibility risk"
section below for how this was established for SDK 57; the same source
applies here):

- The **Expo Go app on the App Store / Play Store currently supports SDK
  54** as its baseline generation (moving forward over time as newer SDKs
  roll out) — not SDK 53.
- **Android**: Expo officially supports installing SDK-specific Expo Go
  builds outside the Play Store version, so a SDK-53-compatible Expo Go can
  still be installed and used on Android today. See
  [expo-go-setup.md](./expo-go-setup.md#android-sdk-53-expo-go-installation)
  for exact steps.
- **iPhone**: Apple's platform restrictions mean only the current Play
  Store / App Store version of Expo Go can be installed on a physical
  device — there is no supported way to sideload an older SDK-specific
  Expo Go build on iOS. iPhone testing against SDK 53 is not possible via
  plain Expo Go; it would require an EAS development build (a future,
  separate piece of work) or a temporary SDK bump for that test only.
- A development build will still eventually be needed for any serious
  native-module development (push notifications, custom native code) —
  SDK 53 + Expo Go remains a stabilisation step for the early UI/Calendar
  work, not the end state.

Package versions restored (from `apps/mobile/package.json` at commit
`bfc4d0d`, the last commit before the 53→57 upgrade began — used as the
source of truth per instruction, not reconstructed from memory):

| Package | Restored (SDK 53) | Was (SDK 57) |
| --- | --- | --- |
| expo | ~53.0.20 | ~57.0.10 |
| react | 19.0.0 | 19.2.3 |
| react-native | 0.79.6 | 0.86.2 |
| expo-router | ~5.1.4 | ~57.0.10 |
| expo-constants | ~17.1.8 | ~57.0.9 |
| expo-secure-store | ~14.2.3 | ~57.0.1 |
| expo-status-bar | ~2.2.3 | ~57.0.1 |
| expo-linking | ~7.1.7 | ~57.0.5 |
| react-native-screens | ~4.11.1 | ~4.26.2 |
| react-native-safe-area-context | 5.4.0 | 5.7.0 |
| @types/react | ~19.0.10 | ~19.2.18 |
| typescript | ~5.8.3 | ~6.0.3 |
| @expo/metro-runtime | *(removed — not required below SDK 54)* | ~57.0.8 |

`@types/node` (`22.17.0`) and `tsconfig.json`'s `"types": ["node"]` were
**kept** — that fixed a pre-existing, SDK-independent typecheck gap (see
"SDK upgrade outcome" below) that has nothing to do with which Expo SDK is
installed. `app.config.ts`'s `expo-status-bar` plugin registration was
**removed** — that was an SDK 57-specific requirement (`expo install --fix`
detected it needed adding at that step); SDK 53 doesn't need or want it.

**Preserved untouched**: `apps/mobile/src/auth/`, `apps/mobile/src/api/`,
`apps/mobile/src/config/`, the mobile sign-in screen, ADR 0010 and the
whole mobile bearer-token authentication implementation (both `apps/api`
and `apps/mobile` sides) — none of that is SDK-version-dependent. See the
final rollback report for full verification detail.

`pnpm-lock.yaml` was restored from `bfc4d0d`'s exact lockfile (rather than
letting pnpm re-resolve, which left stale SDK 57-era transitive entries -
e.g. `react-native-reanimated`, `react-native-worklets`, a newer `metro` -
causing peer-dependency errors and an `expo-doctor` failure) plus the
`@types/node` addition. Diff against `bfc4d0d`: **3 lines** (exactly the
`@types/node` entry) — confirming no other package in the workspace drifted.

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

## SDK upgrade outcome

Anthony chose the upgrade path at the Phase 2 checkpoint. Completed using
Expo's documented incremental process (one major version at a time, `npx
expo install --fix` + `npx expo-doctor` after each step, per
[the official upgrade walkthrough](https://docs.expo.dev/workflow/upgrading-expo-sdk-walkthrough/)):

| Step | Expo | React Native | React | Expo Router | expo-doctor |
| --- | --- | --- | --- | --- | --- |
| Before | 53.0.20 | 0.79.5 | 19.0.0 | 5.1.4 | 18/18 (after doctor fixes) |
| 53 → 54 | 54.0.x | 0.81.5 | 19.1.0 | 6.0.24 | 18/18 |
| 54 → 55 | 55.0.x | 0.83.10 | 19.2.0 | ~55.0.17 | 19/19 |
| 55 → 56 | 56.0.18 | 0.85.3 | 19.2.3 | ~56.2.17 | 21/21 |
| 56 → 57 | 57.0.10 | 0.86.2 | 19.2.3 | ~57.0.10 | 20/20 |

Per-step manual interventions beyond `expo install --fix` (none silently
skipped or unrelated-package upgraded):
- Added `@expo/metro-runtime` (new required peer of `expo-router` from SDK 54
  onward, not auto-installed by `--fix`).
- Added `expo-status-bar` to the `plugins` array in `app.config.ts` — SDK 57
  requires it to be registered as a config plugin; `expo install --fix`
  detected this but can't write to a dynamic (`.ts`) config automatically.
- `typescript` moved from `5.8.3` to `6.0.3` as an explicit consequence of
  `expo install --fix` on SDK 56 — this is what SDK 56/57 declare as their
  expected version, not an incidental bump.
- **Unrelated pre-existing gap found and fixed**: `apps/mobile/typecheck`
  could never have passed — `app.config.ts` uses `node:fs`, `node:path` and
  `__dirname` but `@types/node` was never a dependency and `tsconfig.json`
  had no `"types"` entry. Added `@types/node` as a dev dependency and
  `"types": ["node"]` to `tsconfig.json` so `typecheck` actually runs clean.
  This predates the SDK upgrade (confirmed against the pre-upgrade
  `app.config.ts`/`tsconfig.json`, which were unchanged by the version bumps)
  and was necessary to get an honest validation baseline, so it's included
  here rather than silently left broken.

**Known peer-dependency noise, not a real defect**: from SDK 56 onward, the
`expo` package pulls in `@expo/ui` as a transitive dependency, which in turn
pulls in Radix UI web components expecting `react-dom`. This app has no
`react-dom` dependency (it's pure React Native) and doesn't use `@expo/ui`.
`pnpm add`/`expo install` print peer-dependency warnings for this on every
install; `expo-doctor` does **not** flag it as an issue (confirmed 20/20 on
SDK 57), and it does not affect `lint`, `typecheck`, or `expo start`.

**Also confirmed no cross-workspace regression**: `pnpm -r lint` and
`pnpm -r typecheck` pass across all 8 workspace projects (mobile's dependency
bumps are scoped to `apps/mobile/package.json` only, per pnpm's strict
per-package resolution — nothing in `apps/web` or `packages/*` moved).
`apps/web`'s vitest suite passes (7/7) and its production build
(`next build`) succeeds. `apps/api`'s Docker-based test suite was **not**
run in this pass — no Python/API code was touched, and the suite requires
building containers that aren't exercised by a mobile-only dependency change.

**Still not done**: physical-device confirmation that Expo Go now actually
opens the app (Phase 30) — no phone or device emulator was available in this
environment. The SDK-53-was-incompatible conclusion in the section above was
policy-based; the SDK-57-is-compatible expectation after this upgrade is
also not yet device-confirmed. This must be verified once Phase 3 (EAS
linking, which needs Anthony's own Expo login) and Phase 4 (LAN dev config)
are in place.

**Superseded**: this SDK 53→57 upgrade was subsequently rolled back — see
"SDK rollback: 57 → 53" near the top of this document for the current state
and why.

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
