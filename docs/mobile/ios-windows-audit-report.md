# MyKhaya iOS Windows audit report

**Audit date:** 28 October 2026
**Audited revision:** `dev` = `origin/dev` = `1eef539d37eb8102c69536b039afc259b8d1e30b`;
`origin/main` = `2f46a33c2ea9cdf9861e61e1a7c21d73bdae89d8` (tag `v0.10.9`).
Later commits are not covered.
**Environment:** Windows 11 checkout, VS Code, Git Bash/PowerShell, Docker Desktop.
No Mac, Xcode, Apple account or device access.
**Governing standards:** [iOS Engineering Standards](../engineering/ios-engineering-standards.md),
[iOS DEV and PROD apps](ios-environments.md),
[Mac and device audit checklist](ios-mac-audit-checklist.md).

## Verification status

| Level | Status | Meaning |
|---|---|---|
| Repository: source, configuration, docs, git history | **Verified** | Read directly from the files and history at the audited revision |
| Windows-runnable tests and CI | **Verified** | Results recorded in §7; Linux CI jobs as reported by GitHub Actions |
| Mac and Xcode: `swift test`, `validate-ios-environments.sh` with real `xcodebuild`, builds, archives | **Not verified** | Outstanding; see §11 |
| Signing, certificates, provisioning, App Store Connect, TestFlight | **Not verified** | Outstanding; see §11 |
| Physical devices: iPhone, iPhone Duo, iPad, push, Face ID, widgets | **Not verified** | Outstanding; browser and CSS tests are not device evidence |
| Live servers: PROD APNs topic, deployed frontend SHAs | **Not verified** | Needs a separately authorised read-only check; see §8 |

Findings marked "confirmed (code analysis)" were derived from source and, where
stated, simulated with a standards-compliant URL parser. They are not device
observations.

During the audit, two unauthenticated GET requests were made to the public
`/api/v1/health/build` endpoints on DEV and PROD. Both returned 401 and no data.
No other server was contacted.

## 1. Executive summary

- **The repository's native iOS code is consistent and nothing appears lost.**
  - `dev` and `main` have identical native code (`apps/ios-shell/{ios,native,scripts}`).
  - All Duo, version-numbering and DEV/PROD work is on `main` through PR #30 (`2f46a33`, tag `v0.10.9`).
  - The one iOS stash and the two unmerged iOS branches contain nothing missing from `dev`, except one undocumented Mac convention (§3).
- **The DEV/PROD identity matrix matches the repository exactly,** and the automated checks enforce it: 100 ios-shell tests, CI job green.
- **Two CI gates are red:**
  - `quality` on `dev` (`1eef539`) fails on API formatting in the event-copy work. As a result, **API type checks and tests did not run** on `dev`'s head.
  - `release-validation` has failed on **every tag from `v0.10.5` to `v0.10.9`** because `pnpm` is missing on the runner.
- **New findings:**
  - **iPhone landscape layout (likely defect, from the CSS).** On almost every current iPhone in landscape, the rail sits inside the right safe area and overlaps the floating Add buttons.
  - **Widget deep link (low-severity, from the code).** A crafted link can bounce the user from the app to an arbitrary website in Safari.
  - **Stripe and App Review (risk).** Stripe upgrade is offered inside the iOS app without native gating, which needs a decision against App Review's in-app purchase rule.
- **Still unverified:** the live PROD APNs topic, deployed frontend SHAs, and every Mac, Xcode, signing and device check.
- **Recommendation:** **ready for Mac verification. Not ready for App Store submission** (§12).

## 2. Git repository state and commit reconciliation

| Item | Value at audit |
|---|---|
| Branch | `dev` |
| Local `HEAD` | `1eef539d37eb8102c69536b039afc259b8d1e30b` |
| `origin/dev` | `1eef539d37eb8102c69536b039afc259b8d1e30b` (level, nothing ahead or behind) |
| `origin/main` | `2f46a33c2ea9cdf9861e61e1a7c21d73bdae89d8` (PR #30, tag `v0.10.9`) |
| Working tree | clean: nothing staged, unstaged or untracked |
| Ignored native paths | only `apps/ios-shell/native/WidgetCore/.build/` (SwiftPM build output). No ignored Swift, plist, entitlements, xcconfig or scheme files |
| Open PRs | none. Last merged to `main`: #30 (27 Oct), #29 (27 Oct), #28 "iPhone Duo layouts, Xcode 27.1 build fix, 0.1.33 (112)" (24 Oct) |
| Stashes | 3 (§3) |
| Stale local `main` | `421ad6b`, 540 commits behind `origin/main`. Harmless, but don't build PROD from it |

**Commits on `dev` that aren't on `main`** (none of them changes native code):

| Commit | Content | iOS impact |
|---|---|---|
| `60dc0da` | iOS engineering standards; links in AGENTS.md, PROMPT-HEADER.md and the standards index | docs |
| `18e7330` | CI `ios-shell` job (typecheck and tests) | CI |
| `58ec41b` | `src/native-source-copies.test.ts` (Swift copy drift) | test |
| `8489c08` | Stale doc fixes (mobile-standards, ADR 0012, Mac checklist, ios-widgets); comment-only change to `src/config.ts` | docs |
| `ffb540d` | PROD APNs topic: examples, README, and the `validate_backend_config.py` guard with tests | deploy tooling |
| `d4832d4` | `docs/mobile/ios-mac-audit-checklist.md` | docs |
| `1eef539` | Calendar event copy (API, web calendar page, `styles.css`, api-client, shared-types, test) | none: its CSS adds no `native-*` selectors or media queries. It fails CI formatting (§7) |

`main` has no commits that `dev` lacks apart from the PR #30 merge commit.

**Other local branches with commits that aren't on `dev`:**

| Branch | Upstream | Unmerged commits | Assessment |
|---|---|---|---|
| `release/ios-stage2-prod` | `origin/release/ios-stage2-prod` | `9223e63` (9 Oct, "prepare stage 2 production validation candidate", 150 files), `c9b3c29` (9 Oct, "COmmit", 12 Android generated files) | `9223e63` is a snapshot of `dev`'s iOS work rebased onto the old `main` (`421ad6b`). Every file it touches exists on `dev`, and `dev` was already further ahead on 9 October. **Superseded.** Its only unique content is the doc section in §3. `c9b3c29` commits generated Android build output, including `apps/android-shell/android/local.properties`, which holds a local SDK path and no secret, and is ignored on `dev`. **Obsolete; hygiene only.** |
| `feature/build-metadata-health-security` | **none (local only)** | `9223e63`, `c9b3c29`, `8c2b81c` (11 Oct, build metadata and health) | `8c2b81c` is superseded on `dev` by `8248194`/`2d2d14a` and by `prod-deploy.sh update`, which replaced its `prod-update.sh`. It doesn't fix the `pnpm` release failure. **Superseded.** |
| `feature/multi-node-platform`, `pr-assets/marketing-homepage` | remote | 1 and 3 | not iOS |

## 3. Historical stash findings

| Stash | Identity | Created | Base | Files |
|---|---|---|---|---|
| `stash@{0}` | `e707ceba2787` "codex: preserve iOS Stage 2 audit edits before release branch" | 2026-10-09 09:30 +01:00 | `2e534ee` (`dev`, 8 Oct) | `apps/ios-shell/scripts/mac-bootstrap.sh` (+13/−4), `docs/mobile/ios-environments.md` (+28). No index changes and no untracked part |
| `stash@{1}` | `018dcf498dd3` | 2026-09-09 | `3573729` | API notifications, wishlists, routines page, `styles.css`. **Not iOS** |
| `stash@{2}` | `ae738f5cf2f6` "On main: confirm" | 2026-08-01 | old `main` | `apps/web/app/calendar/page.tsx`. **Not iOS** |

No stash content contains secrets. Stash indices can change; identify stashes by
message and commit identity.

**`stash@{0}` (`e707ceba2787`), change by change:**

| Change | Classification | Evidence |
|---|---|---|
| `mac-bootstrap.sh`: refuse to run DEV off `dev` or PROD off `main` (`EXPECTED_BRANCH`) | **Superseded** | `db8a48b` (9 Oct 11:08, two hours later) requires an explicit `MYKHAYA_IOS_REF`, never switches branches, refuses when `HEAD` ≠ the selected ref, and requires an explicit ref for production. That's stricter |
| `mac-bootstrap.sh`: refuse a dirty working copy | **Already implemented** | current `mac-bootstrap.sh`, "== 1. Repo state ==" |
| `mac-bootstrap.sh`: `git fetch` + `git pull --ff-only origin <branch>` | **Superseded / obsolete** | the current script deliberately never pulls; the operator checks out the ref |
| `ios-environments.md`: new section "Mac working-copy release discipline", describing **two Mac checkouts**: `~/Developer/MyKhaya` (DEV, `dev`) and `~/Developer/Mykhaya-prod` (PROD, `main` only) | **Potentially useful, needs review** | not in any tracked document on `dev` or `main`. It also appears in `9223e63`. Its `git switch` steps contradict the current "never switch for you" design, so adopt the convention, not the commands. **Whether the Mac still uses two checkouts can only be confirmed on the Mac** |

**Conflicts:** none, if the stash stays unapplied. Applying it would revert `db8a48b`'s ref-selection logic, so **don't pop it**.

## 4. Architecture and DEV/PROD audit

**Verified in the repository:**
- **Identity matrix:** `Environment-{Dev,Prod}.xcconfig` match `ios-environments.md` exactly:
  - names `MyKhaya-Dev` and `MyKhaya`;
  - bundles `app.mykhaya.mobile` and `app.mykhaya.mobile.prod`, plus `.widgets`;
  - App Groups `group.app.mykhaya.mobile` and `group.app.mykhaya.mobile.prod`;
  - schemes `mykhaya` and `mykhaya-prod`;
  - hosts `dev.mykhaya.app` and `mykhaya.app`;
  - team `M86392YDLQ`, automatic signing.
- **Versions:** DEV `0.1.35 (1)` ≥ PROD `0.1.34 (1)`, per the rule in `versioning-and-releases.md`.
- **Build configurations:** each of the four (`Debug-Dev`, `Release-Dev`, `Debug-Prod`, `Release-Prod`) has the right base xcconfig.
- **Schemes:**
  - `MyKhaya-Dev` and `MyKhaya-Prod` run and test on `Debug-*`, and profile and archive on `Release-*`;
  - `MyKhayaWidgets-*` build the widget alone.
- **Targets:**
  - App: iOS 15.0, iPhone and iPad.
  - Widget: iOS 16.0, iPhone only.
  - Both take their bundle IDs from `$(MYKHAYA_APP_BUNDLE_ID)`.
- **Entitlements:**
  - `AppDebug`/`AppRelease`: `aps-environment = $(MYKHAYA_APNS_BUILD_ENVIRONMENT)`, which is development for Debug and production for Release, plus the App Group.
  - Widget: the App Group only.
- **Info.plist:** environment keys come from build settings; the app registers only its own URL scheme.
- **Host selection and navigation:**
  - `MainViewController.instanceDescriptor()` loads `https://$(MYKHAYA_SERVER_HOST)`, allows only that host, and calls `fatalError` if the configuration is invalid.
  - The web API origin is derived from the page host (`packages/api-client/src/native-config.ts`).
  - `capacitor.config.json` is generated, git-ignored and not authoritative.
- **No hard-coded identifiers in shared native code** (`src/ios-environments.test.ts`).
- **Native sources:** the four `native/plugin/*.swift` files match their copies in `ios/App/App/`. This is now enforced in CI, and the test was shown to fail on a planted mismatch in an isolated copy.

**Contradictions:**
1. **iPhone landscape is part of the wide layout, but the code comments and standards say otherwise.**
   - `NATIVE_WIDE_QUERY` (`min-width: 760px`, `apps/web/components/native-layout.ts`) matches every current non-SE iPhone in landscape (812–956pt wide). So they all get the rail layout instead of the bottom bar, as a deliberate design (`01cea34`).
   - But the "Native rail presentations" comment in `apps/web/app/styles.css` says `.native-wide-viewport` is "Duo unfolded, iPad" and that "ordinary iPhones keep the compact baseline".
   - `ios-engineering-standards.md` §4 says "760pt or wider (larger models)".
   - `mobile-standards.md` treats the fixed bottom navigation as the protected phone baseline.
   - **The owner needs to decide whether iPhone landscape belongs to the protected baseline.**
2. **Debug logging in production:** `[BIOMETRIC DEBUG]` and `[NATIVE_BOOT]` logs run unconditionally in production builds (`native-auth.ts`, `native-biometric.ts`, `MainViewController.swift`). They contain no sensitive data (only booleans, codes and a query-free path), but they conflict with `engineering-standards.md`: "Do not expose debug behaviour in production".
3. **Release documentation:** `docs/operations/release-process.md` has no iOS content. The iOS release steps exist only in `ios-engineering-standards.md` §8 and `ios-environments.md`.

## 5. Native authentication and security findings

| Area | Finding | Status |
|---|---|---|
| Keychain | session and TrustedDevice tokens stored as separate items, `whenUnlockedThisDeviceOnly`, `sync: false` on every call; a read failure keeps the credential (`keychain-native-session-store.ts`) | verified (code) |
| Biometrics | the gate runs before the bearer session is read; cancel or failure never unlocks; 5-minute re-lock after backgrounding (`BIOMETRIC_LOCK_TIMEOUT_MS`) | verified (code); device unverified |
| Enrolment binding | Keychain items aren't bound to `biometryCurrentSet` (the plugin has no `SecAccessControl`); documented in ADR 0012 | known limitation |
| Logout | revokes and cleans up push, calls API logout, then in a `finally` disables biometric sign-in and replaces the widget snapshot with a signed-out one (`native-auth.ts`) | verified (code) |
| Push | APNs environment comes from the signed build (`NativePushEnvironmentPlugin`), stored per device; tokens and raw errors are never logged | verified (code) |
| Push-tap routing | `safeNativePushPath` allows only listed prefixes and rejects `//` and `\` | verified |
| **Widget deep link** | `WidgetDeepLinkRoute.path` (`native/WidgetCore/.../MyKhayaEnvironment.swift`) rejects `//` but **not `\`**. `WidgetBridgePlugin.handleOpenURL` escapes only `'` before `location.assign('<path>')`. `mykhaya://open?path=%2F%5C%5Cevil.example%2Fx` resolves to `https://evil.example/x` (resolved with Node's WHATWG URL parser, the same standard WebKit follows). Capacitor then hands a disallowed top-level host to `UIApplication.shared.open`, which opens Safari. Any web page or app can fire the scheme. No script injection is possible, because `'` is escaped and backslash tricks only cause syntax errors | **low severity; confirmed by code analysis, unverified on a device** |
| External links | `openExternalUrl` → `Browser.open`; only the app's own host is allowed for navigation | verified |
| Stripe billing | `settings/billing/page.tsx` sets `window.location.href` to Stripe with no native gating, so it's blocked by the allow-list and Capacitor would open it in Safari | open (ADR 0012); see §10 R5 |
| Diagnostics | no tokens or personal data in native logs; debug logs on in production (§4) | low |

## 6. iPhone Duo implementation review

The browser checks below are not physical Duo validation.

**Implemented** (CSS, `AppShell`, tests):
- **Layout states:** `native-compact-rail` (outer screen), `native-wide-viewport` (unfolded and iPad), `native-right-column`, and `native-status-column` (Duo only, set when there's a right safe-area inset).
- **Header pill:** one shared notifications/profile pill in the shell header on every Duo route (`3118574`, the `app-shell.test.tsx` cases); no per-page duplicates.
- **Right-hand column:** one column for the pill or tools, the floating Add buttons and the rail, sharing `--native-rail-centre`, with the upper group capped by `--native-upper-max`.
- **Measured clearances:** about 165pt folded and about 106pt unfolded.
- **Calendar:** in wide layouts its FAB is hidden in favour of the toolbar Add button; on the outer screen the tools pill takes the column.
- **Overlays:** the header is raised above the rail so its sheets can cover it.

**Tests:** 29 native, layout and auth test files in `apps/web`, 317 tests, passing locally on `1eef539`. CI's web step passed on `1eef539`.

**Risks found in the CSS:**
- **iPhone landscape (likely defect; unverified on a device).** On larger iPhones in landscape (assumed iPhone 15: 852×393pt, side insets 59pt, bottom 21pt):
  - The rail uses `right: var(--native-rail-inset)` = 8px. That puts it 8–68px from the edge, **inside the 59pt right safe area**, because nothing in the wide-only or short-screen rules adds `--safe-right`.
  - `.rr-fab` keeps its portrait position (`right: max(1rem, safe-right)` = 59px, bottom ≈ 107px). It **overlaps the rail by about 9px**, and the rail (z-index 19) is drawn over it (z-index 8).
  - This affects Budget, Driveway, Lists, Meal Plans and Routines & Reminders, and matches the reported landscape FAB overlap.
  - No test covers FAB placement in iPhone landscape; `styles-native-wide-home.test.ts` tests only the right-column FAB.
- **Short Duo screens (risk).** Calendar tools on the outer screen shrink to 36–40px (`--native-tool-size`) and scroll when space runs out. That's below the 44pt target size the standards require. Unverified.
- **iPad Stage Manager (risk).** A 450–759 × 450–800pt window gets `native-compact-rail` without a status column. It has never been checked visually.
- **Selector sprawl (maintainability).** 104 rule lines use `native-wide-viewport` without a column guard, so each one also affects iPhone landscape. Any new rule intended only for the Duo or iPad must add `native-right-column`.

**Not checkable on Windows:** physical Duo geometry, the drawn status indicator, scrolling feel and preserved navigation state.

## 7. CI and test results

| Check | Commit | Result |
|---|---|---|
| `quality` / `ios-shell` job | `1eef539` | **success** (typecheck, 100 tests) |
| `quality` / `application`: compose, deploy validation, Alembic, **web lint/type/tests/build** | `1eef539` | success |
| `quality` / `application`: **API lint, formatting, types and tests** | `1eef539` | **failure**: `ruff format --check` wants to reformat `mykhaya/routers/calendar.py` and `mykhaya/schemas.py`; **mypy and pytest never ran** |
| `quality` / `application`: production images, migration rollback | `1eef539` | **skipped** (after the failure) |
| `security` | `1eef539` | success |
| `quality` | `60dc0da` | cancelled (superseded by a newer push) |
| `quality`, `security` | `main` `2f46a33` | success |
| `release-validation` | tags `v0.10.5`–`v0.10.9` | **failure on every one**: `make: pnpm: No such file or directory` (`stable-release.yml` runs `make test` without installing pnpm) |

GitHub Actions run IDs: `quality` on `1eef539` = 40740326180; `release-validation` on `v0.10.9` = 40562897527.

**Run locally on Windows at `1eef539`:**
- ios-shell: typecheck clean, 100/100 tests.
- `infrastructure/tests`: 78/78.
- `apps/web` native, layout and auth subset: 317/317.
- Drift test: on an isolated `git archive` copy in Docker, a planted copy mismatch and an unlisted `native/plugin` file produced exactly 3 expected failures.

**Not run:**
- API pytest locally (it needs the Docker test stack, and isn't iOS-specific).
- Playwright e2e (needs a running stack).
- **Mac-only checks, all outstanding:** `swift test`, `validate-ios-environments.sh` with real `xcodebuild`, Xcode builds.

## 8. Production APNs repository findings

**Verified in the repository (`ffb540d`):**
- **Bundle IDs:** DEV and PROD are distinguished. `.env.production.example` and the ios-shell README use `app.mykhaya.mobile.prod`.
- **The guard** in `infrastructure/scripts/validate_backend_config.py`:
  - **Real settings:** it starts the worker image with the merged `compose.yml` + `compose.production.yml` and the production `.env` (`MYKHAYA_PRODUCTION=1`, `run --rm --no-deps`, isolated project name), and reads `environment` and `apns_bundle_id` from the worker's own settings.
  - **Missing or wrong topics fail:** an unset or empty `MYKHAYA_APNS_BUNDLE_ID` falls back to the DEV bundle through `compose.yml`, and any value other than `app.mykhaya.mobile.prod` fails when the environment is `production` and APNs delivery is on.
  - **Order:**
    - `prod-deploy.sh update` validates before `build`, `migrate` and `up -d`;
    - `prod-install.sh` validates before starting any service;
    - `make prod-config` only validates.
  - **DEV is unaffected:** `compose.dev.yml` pins `development`.
  - **APNs off:** production with delivery off isn't checked, consistent with the README.
- **Remaining defaults:** the `compose.yml` worker fallback and the `apns_bundle_id` code default in `Settings` are still `app.mykhaya.mobile`, by design, so production must set the value explicitly.
- **Side effect:** if the live PROD `.env` has the wrong topic with delivery on, **the next production deploy will stop at this guard.**

**Unverified:** the live PROD topic. **To check later,** once the PROD host and compose directory are known and the owner has authorised a read-only session:
1. Run `python -c "from mykhaya.config import get_settings as g; s=g(); print(s.environment, s.apns_delivery_configured, s.apns_bundle_id)"` inside the `worker` and `api` containers.
2. Count iOS rows in `native_push_devices` grouped by `apns_environment` and `disabled_source`, with the min/max `disabled_at`. Counts only.
3. Count the `reason` values of `apns_delivery_failed` in the worker logs since 2026-10-01, looking especially for `DeviceTokenNotForTopic`, and whether they start after 4 October (the PROD bundle split).
4. Alternatively, `MYKHAYA_PRODUCTION=1 make prod-config` runs the new guard read-only.

## 9. Apple release readiness

| Item | Status | Where verified |
|---|---|---|
| PROD scheme `MyKhaya-Prod` → archive `Release-Prod` | present | repo |
| Version and build (`Environment-Prod.xcconfig` 0.1.34 (1)); widget inherits; target overrides rejected by the build phase and tests | present | repo |
| Signing references (team, automatic) | present | repo. **Certificates and profiles: Mac only** |
| Entitlements (production `aps-environment` for Release, App Group) | present | repo. **Signed values: Mac only** |
| Privacy manifest | app has one (`NSPrivacyAccessedAPICategoryFileTimestamp` C617.1); Capacitor ships its own; widget uses no required-reason APIs | repo |
| Usage descriptions (Camera, Photo Library, Face ID) | present | repo |
| `ITSAppUsesNonExemptEncryption` | **absent**, so App Store Connect asks the export-compliance question on every upload | repo |
| `UIRequiredDeviceCapabilities = armv7` | leftover from the Capacitor template; effect on validation unknown | **Mac (archive validation)** |
| Reviewer access | `docs/operations/apple-testflight-review-fixture.md` (demo/test Homes) | repo |
| Release procedure | `ios-engineering-standards.md` §8 and §11; missing from `release-process.md` | repo |
| Archive, upload, TestFlight, App Store Connect build numbers, APNs key | **not verified** | Mac or accounts |
| Deployed frontend SHA | **not verified**: `/api/v1/health/build` needs a session (returned 401); the web image's revision label is readable only on the server | browser session or server |

## 10. Prioritised defect and risk register

| # | Severity | Issue | Type | Evidence | User impact | Action | Mac? | PROD change? | Blocks App Store? |
|---|---|---|---|---|---|---|---|---|---|
| R1 | High | Live PROD APNs topic unknown | unverified risk | repo defaults were the DEV bundle until `ffb540d`; live value unchecked | if wrong: no PROD push, and registrations disabled | run the §8 checks | no | maybe (`.env`) | **yes**, until verified |
| R2 | High | `dev` CI red; API types and tests not run on head | confirmed | run 40740326180 | none yet; blocks promotion | `ruff format` the two files, re-run CI | no | no | blocks promotion to `main` |
| R3 | Medium | `release-validation` fails on every tag (no pnpm) | confirmed | runs for `v0.10.5`–`v0.10.9` | release gate gives no signal | install pnpm/Node in `stable-release.yml` | no | no | indirectly (release gate) |
| R4 | Medium | iPhone landscape: rail in the right safe area; FAB overlaps the rail | likely defect (CSS analysis) | §6 geometry | controls under the sensor housing or rounded corner; Add button partly covered | add `safe-right` to the wide/short rail inset and FAB rules; add a test; check on device | **yes** (to confirm) | no | recommended before submission (landscape is enabled) |
| R5 | Medium | Stripe upgrade offered inside the iOS app; navigation blocked or bounced to Safari | confirmed (code) plus policy risk | `billing/page.tsx`, no `isNativeShell` gating | broken upgrade flow; possible rejection under App Review's in-app purchase rule (3.1.1) | product/legal decision: hide or adapt billing in the native shell | no | no | **likely yes** until decided |
| R6 | Low | Widget deep link: `\` lets a crafted link open an external site in Safari | confirmed (code analysis) | §5 | phishing assist; no data exposure | reject `\` in `WidgetDeepLinkRoute.path` (like `safeNativePushPath`), add an XCTest | **yes** (Swift) | no | no |
| R7 | Medium | Docs and code comments contradict on iPhone landscape | confirmed | §4.1 | future regressions | owner decision, then fix the comment, standard §4 and mobile-standards | no | no | no |
| R8 | Medium | Face ID not bound to the enrolled biometric set | known limitation | ADR 0012 | a new enrolment can unlock | design a native Keychain bridge plus an ADR | yes | no | no |
| R9 | Low | Widget titles visible in StandBy and on the iPad lock screen (no `.privacySensitive()`; Home Screen families only) | known limitation | `native/widgets` | event/to-do titles visible on a locked device | product decision | yes | no | no |
| R10 | Medium | Dynamic Type and text scaling, Duo short-screen 36px tools, Stage Manager narrow windows | unverified risks | §6 | readability and targets | device checks (checklist G5) | yes | no | possibly (accessibility review) |
| R11 | Low | Debug console logs in production builds | confirmed | §4.2 | none (no sensitive data) | gate behind a debug flag | no | no | no |
| R12 | Low | `ITSAppUsesNonExemptEncryption` missing; `armv7` capability | confirmed (plist) | §9 | upload friction | Mac validation, then plist change | yes | no | no |
| R13 | Low | Two-checkout Mac convention undocumented; release-process.md has no iOS steps | confirmed | §3, §9 | handoff errors | confirm on the Mac, then document | yes (confirm) | no | no |
| R14 | Low | `origin/release/ios-stage2-prod` holds a superseded snapshot and generated Android files; local-only `feature/build-metadata-health-security` superseded | confirmed | §2 | confusion | owner decides whether to delete | no | no | no |
| R15 | Medium | Deployed DEV/PROD frontend SHAs unknown | unverified | §9 | can't prove the reviewed UI is live | record them during the Mac audit | no | no | yes (for evidence) |
| R16 | Info | Xcode copies vs sources | **resolved** for tracked copies (CI) | `58ec41b` | none | `diff -r native/widgets MyKhayaWidgets` on the Mac | yes | no | no |

## 11. Outstanding Mac/Xcode checks

Follow [ios-mac-audit-checklist.md](ios-mac-audit-checklist.md) in full. Use `dev` (`1eef539` or later) for DEV and `origin/main` (`2f46a33`, `v0.10.9`) for PROD; their native code is identical. Add these items found by this audit:

1. **Mac checkouts:** record whether `~/Developer/MyKhaya` (`dev`) and `~/Developer/Mykhaya-prod` (`main`) both exist, and their branch, `HEAD`, status and stashes. Look for iOS work that exists only on the Mac.
2. **R4 landscape check:** on a 760pt+ iPhone in landscape (DEV, Debug, Web Inspector attached), record `.app-shell` classes, `--safe-right`, the rail's `getBoundingClientRect()` and `.rr-fab`'s, on Budget, Driveway, Lists, Meal Plans and Routines. Screenshot with the sensor housing on each side.
3. **R6 deep link:** on DEV, open `mykhaya://open?path=%2F%5C%5Cexample.com%2F` from Notes and record whether Safari opens `example.com`. Use only a harmless domain.
4. **R12:** run Organizer > Validate App on the `Release-Prod` archive, which doesn't upload, and record any `armv7` or encryption warnings.
5. **R10:** Calendar tools at 36px on the outer screen, the largest Dynamic Type size, and a Stage Manager window around 600×700.
6. **Record:** deployed SHAs (checklist A5), the App Store Connect latest builds (read only), and the Xcode version. PR #28 mentions an "Xcode 27.1 build fix", so confirm the build works on the Mac's current Xcode.

**Don't:** upload, change signing in the Xcode GUI, edit xcconfigs, or pop `stash@{0}` (§3).

Record results in the handoff format of
[iOS Engineering Standards §11](../engineering/ios-engineering-standards.md#11-required-ios-engineering-handoff),
marking every step as passed, failed, not run, or blocked.

## 12. Recommended next actions and release recommendation

1. **R2:** format the event-copy files and get `quality` green on `dev`, including API tests.
2. **R1:** identify the PROD host and run the read-only §8 checks.
3. **R5:** decide how billing behaves in the native shell before any App Store submission.
4. **R3:** fix `stable-release.yml` so tag validation actually runs.
5. **Mac audit (§11),** then fix R4 and R6 (native rebuild for R6), and settle R7.
6. **Then** archive `Release-Prod` for TestFlight, with separate approval for each step.

| Recommendation | Verdict | Reason |
|---|---|---|
| Ready for Mac verification | **Yes** | native code is identical on `dev` and `main`; all Windows-runnable iOS checks pass; nothing is lost; the checklist and this report give the Mac session full context |
| Not ready for Mac verification | — | — |
| Ready for App Store submission | **No** | — |
| Not ready for App Store submission | **Yes** | no Xcode, signing, archive or device evidence; live PROD push unverified (R1); billing and in-app-purchase decision open (R5); likely landscape overlap (R4); `dev` CI red (R2) and the release gate broken (R3); deployed frontend SHA unknown (R15) |
