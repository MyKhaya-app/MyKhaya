# iOS Home Screen Widgets (Phase 5)

Native WidgetKit/SwiftUI Home Screen widgets for MyKhaya — Next Event,
Calendar, and To-do (Routines & Reminders). Builds on
[ADR 0012](../architecture/adr/0012-capacitor-ios-shell.md) and the
[Mac handoff checklist](ios-shell-mac-checklist.md); read those first.

## Why this doc exists, and its central constraint

Widget development needs a real Xcode project (`ios/`), which is generated
**only on a Mac**, one time, via `npx cap add ios` — it does not exist in
this repository on an ordinary Windows checkout (see ADR 0012,
"Windows-first development"). WidgetKit, SwiftUI, and `xcodebuild` cannot
run on Windows at all. This phase therefore follows the same pattern
already established for Keychain/biometrics/APNs (ADR 0012 Phase 4):

- Everything expressible in TypeScript is implemented and tested on
  Windows (`apps/web/components/widget-snapshot.ts`,
  `widget-bridge.ts`, and their `vitest` suites).
- Real, complete Swift sources are written and committed under
  `apps/ios-shell/native/` — production code, not pseudocode — but they
  cannot be compiled or unit-tested until a Mac generates the `ios/`
  project.
- An idempotent script (`scripts/install-widget-sources.sh`, chained into
  `scripts/mac-bootstrap.sh`) copies those sources into the generated
  project and creates/configures the widget extension target.

**Nothing here has been built, run, or verified by Xcode/`xcodebuild`/a
simulator.** Every claim below about behaviour is a claim about what the
code is written to do, not a claim it has been observed to do. See
"Verification status" at the end of this document.

## Architecture

```
apps/web (TypeScript, live frontend, runs in the WKWebView)
  widget-snapshot.ts   — pure snapshot shaping (buildWidgetSnapshot)
  widget-bridge.ts     — fetches via the same `api` client every other
                          page uses, calls the native plugin
        |
        | Capacitor plugin call: WidgetBridge.setSnapshot({ json })
        v
apps/ios-shell/native/plugin/WidgetBridgePlugin.swift (main app target)
        |
        | WidgetSnapshotStore.save() — atomic file write
        v
App Group container (group.app.mykhaya.mobile)
        |
        | WidgetSnapshotStore.load() — read-only
        v
apps/ios-shell/native/widgets/ (MyKhayaWidgets extension target)
  Timeline/*Provider.swift — WidgetKit TimelineProvider
  Views/*.swift            — SwiftUI rendering
  NextEventWidget.swift / CalendarWidget.swift / TodoWidget.swift
  MyKhayaWidgetsBundle.swift — @main entry point
```

The widget extension never talks to the network, never authenticates, and
never imports any auth/Keychain code. It only reads the file
`WidgetSnapshotStore` wrote.

## Repository-managed native source location

```
apps/ios-shell/native/
  WidgetCore/                  — local Swift Package: MyKhayaWidgetCore
    Package.swift
    Sources/MyKhayaWidgetCore/
      WidgetSnapshot.swift       — Codable mirror of widget-snapshot.ts
      WidgetSnapshotStore.swift  — App Group read/write, atomic, versioned
      CalendarLayout.swift       — monthGridDays/dayKey/eventsByDay
      EventDisplay.swift         — currentlyShownEvent/eventTimeLabel/dueLabel
    Tests/MyKhayaWidgetCoreTests/
      WidgetSnapshotTests.swift
      CalendarLayoutTests.swift
      EventDisplayTests.swift
  widgets/
    MyKhayaWidgetsBundle.swift
    NextEventWidget.swift
    CalendarWidget.swift
    TodoWidget.swift
    Shared/
      DeepLink.swift              — mykhaya:// URL builder
      Color+Hex.swift
    Timeline/
      NextEventProvider.swift
      CalendarProvider.swift
      TodoProvider.swift
    Views/
      NextEventViews.swift
      CalendarViews.swift
      TodoViews.swift
  plugin/
    WidgetBridgePlugin.swift   — installed into the App target
    MainViewController.swift  — installed into the App target
```

`native/` sources (including the `WidgetCore` package) are the source of
truth; `scripts/install-widget-sources.sh` installs/updates copies of the
`widgets/`/`plugin/` sources into the committed `ios/` project and links
the `WidgetCore` package into both the `App` and `MyKhayaWidgets` Xcode
targets — idempotently, safe to re-run any time after a `git pull`.

### Why a separate local Swift Package, not just files under `native/widgets/`

`WidgetSnapshot`/`WidgetSnapshotStore` and the pure calendar/event/to-do
display helpers used to be plain files compiled separately into both the
`App` and `MyKhayaWidgets` targets. They were extracted into the
`MyKhayaWidgetCore` local Swift Package (`native/WidgetCore/`) specifically
so they can be unit-tested: **an app extension's own compiled code cannot
be an XCTest host** — a hosted test bundle (`TEST_HOST` pointed at the
built `.appex`) and a logic-only test bundle both fail identically at link
time (`ld: symbol(s) not found for architecture arm64`), because an
extension isn't an independently launchable process XCTest can attach to
or link against. A local Swift Package's library product compiles into
each importing target exactly as the old loose files did, but also has its
own test target that `swift test`/`xcodebuild test` can run directly and
independently of either app target. `WidgetKit`, `SwiftUI`-specific
rendering, `TimelineProvider` conformance, and the `Widget`/`WidgetBundle`
structs themselves remain in `native/widgets/` — they're WidgetKit
lifecycle code, not portable domain logic, and have no independent
existence outside the extension that hosts them.

## Adding another MyKhaya widget later

1. Add a `Widget` struct next to `NextEventWidget.swift` (own kind string,
   `configurationDisplayName`, `supportedFamilies`).
2. Add its `TimelineProvider` under `Timeline/` and SwiftUI views under
   `Views/` — reuse `WidgetSnapshotStore.load()` and the existing
   `WidgetSnapshot` fields; extend the schema (bump
   `WIDGET_SNAPSHOT_SCHEMA_VERSION` in both `widget-snapshot.ts` and
   `widgetSnapshotSchemaVersion` in `WidgetSnapshot.swift`) only if a truly
   new field is needed.
3. List the new `Widget` in `MyKhayaWidgetsBundle.swift`.
4. Re-run `scripts/install-widget-sources.sh` on the Mac — no target
   changes are needed for a widget that reuses the existing extension.

## Shared data model — what is stored, what is not

`WidgetSnapshot` (TS: `widget-snapshot.ts`; Swift: `Shared/WidgetSnapshot.swift`,
kept in sync by hand):

```ts
{
  schemaVersion: number,
  generatedAt: string,        // ISO-8601 UTC
  signedIn: boolean,
  activeHome: { id, displayName } | null,
  upcomingEvents: WidgetEvent[],   // next 3, not-yet-finished
  todayEvents: WidgetEvent[],      // spans today (all-day/multi-day aware)
  monthEvents: WidgetEvent[],      // current month, capped at 250
  todoItems: WidgetTodoItem[],     // overdue, then today, then upcoming; capped at 12
}
```

`WidgetEvent`: `id, title, startAt, endAt, isAllDay, timezone, colorHex,
deepLink`. `WidgetTodoItem`: `id, kind (routine|reminder), title, dueAt,
overdue, scope, deepLink`.

**Never stored**: bearer/refresh tokens, session cookies, PINs, Keychain
material, APNs device tokens, biometric data, passwords, raw backend
metadata (member IDs, permission overrides, calendar sharing internals,
recurrence rules, etc.). Every field above is exactly what a widget needs
to render — not a serialisation of `EventOccurrence`/`Routine`/`Reminder`
from `@mykhaya/shared-types`. `widget-snapshot.test.ts` asserts the
encoded JSON never contains the substrings `token`, `password`, `cookie`,
`secret`, `pin`, `bearer`.

Storage is one atomically-written JSON file in the App Group container
(`Data.write(options: .atomic)`), not scattered `UserDefaults` keys — see
`WidgetSnapshotStore.swift`.

**Corruption/mismatch handling** (`WidgetSnapshotStore.load()`): a missing
file, undecodable JSON, or a `schemaVersion` that doesn't match the
extension's own `widgetSnapshotSchemaVersion` all collapse to the
signed-out placeholder — never a crash, never a guess at an incompatible
shape.

## App Group

Identifier: **`group.app.mykhaya.mobile`** — derived from the existing
`app.mykhaya.mobile` bundle ID (ADR 0012), not invented independently.
Configured on both the `App` target and the `MyKhayaWidgets` extension
target by `scripts/setup-widget-extension.rb`.

## Authentication and data fetching — no parallel auth

`widget-bridge.ts`'s `syncWidgetSnapshot()` calls the exact same `api`
client (`@mykhaya/api-client`) every other MyKhaya page already uses —
`api.homes()`, `api.listEvents()`, `api.routines()`, `api.reminders()` —
inside the authenticated WKWebView, using whatever session
`native-auth.ts` already established (Keychain-backed bearer token, never
touched by this feature). The widget extension itself makes **no network
calls and holds no credentials** — it only reads the file the app already
wrote. No new backend endpoint was added; visibility/authorization is
exactly whatever the existing endpoints already enforce for the signed-in
user.

## Refresh triggers

`syncWidgetSnapshot()` is called from:

- `native-auth.ts`: after `bootstrapNativeSession()` restores a session,
  after `nativeLogin()`/`nativeChildLogin()` succeed.
- `use-active-home.ts`: whenever `activeHomeId` changes (covers both an
  explicit Home switch and the initial selection).
- `app/calendar/page.tsx`'s `load()` — the one function every
  create/update/delete event handler already calls afterwards.
- `app/settings/routines-reminders/page.tsx`'s `loadRoutines()` /
  `loadReminders()` — likewise the shared post-mutation reload point for
  create/update/complete/uncomplete on both domains.

`clearWidgetSnapshot()` is called from `native-auth.ts`'s `nativeLogout()`,
in a `finally` block so it runs even if the network logout call failed.

Calls are coalesced through a module-level `inFlight` promise chain so a
mutation immediately followed by its own reload can't produce two
overlapping writes; a `clearWidgetSnapshot()` always waits for, then wins
over, whatever sync was in flight — a slow pre-logout fetch can never
un-clear the signed-out state.

Every function is a no-op outside the native shell (`isNativeShell()`
guard) and never throws — a widget-refresh failure must never surface as
an error in an unrelated user-facing flow like login or saving an event.

## Timeline refresh strategy

Classic `TimelineProvider` (not `AppIntentTimelineProvider`, which needs
iOS 17+) — see the deployment-target note below. Each provider requests
its next refresh at the soonest of: the currently-shown event's end time
(Next Event only), the next local midnight, or a ceiling (30 minutes for
Next Event/To-do, 6 hours for Calendar) so an idle widget still
periodically re-checks a snapshot the app wrote in the background.
**WidgetKit — not this code — decides actual refresh timing**; none of
this is a promise of minute-by-minute updates.

## Next Event widget

Small: date, next event (title, time or "All day", category colour).
Medium: up to 3 upcoming events. "Upcoming" = not yet finished
(`endAt > now`), so a currently-running event is included, not skipped —
and a finished-earlier-today event still appears in `todayEvents` even
though it drops out of `upcomingEvents`. All-day/multi-day events are
matched by local day range, not by comparing raw timestamps (the classic
bug this avoids: treating an all-day event as a midnight-timed one).
Tapping a specific event uses `widgetURL`/`Link` to
`mykhaya://open?path=/calendar?event=<id>` — see "Deep links" below.

## Calendar widget

Medium: current week, 7 columns, up to 3 colour dots/day. Large: current
month, a fixed 6-row/7-column grid (`monthGridDays`) so every month
(5-week or 6-week) renders consistently; out-of-month days are dimmed, not
omitted. Each day cell shows up to 2 colour bars plus a `+N` overflow
label rather than attempting to draw every event — the deliberate
"condensed representation" the task required. Multi-day events are
expanded to appear under every day they span (`eventsByDay`).

## To-do widget

Small: total count, overdue count, next item title. Medium: up to 4 items.
Large: up to 8 items, with a header. Ordering (already computed in
`widget-snapshot.ts`): overdue first, then due today, then upcoming;
completed and disabled items excluded. Both routines and reminders are
represented with a `kind` field and a distinct icon. **Completion is not
implemented from the widget in this phase** — see "Known limitations".

## Active Home handling

`activeHome` is written into every snapshot. `use-active-home.ts` triggers
a resync whenever `activeHomeId` changes, so switching Home overwrites the
entire snapshot (events, todos, the Home identity itself) — there is no
per-Home partial state that could leak Home A's data after switching to
Home B; the file is always fully replaced, never merged.

## Logout behaviour

`nativeLogout()` calls `clearWidgetSnapshot()`, which asks the native
plugin to write `WidgetSnapshot.signedOut()` and reload every widget
timeline. Every widget's view falls back to a neutral "Open MyKhaya to
sign in" state (tapping it opens `mykhaya://open?path=/login`) — no
household data persists after logout.

## Deep links

MyKhaya's existing deep-link registry
(`apps/api/mykhaya/notifications/deep_links.py`) resolves a logical
target to an **`https://`** app path — fine for a push notification or
email, where nothing needs to "know" the app exists yet. A Home Screen
widget is different: tapping an `https://` URL with no Associated
Domains/Universal Links configured (ADR 0012 explicitly defers this) would
open Safari, not MyKhaya.

`widget-snapshot.ts` still produces exactly the same app-relative paths
the notification resolver would (`/calendar?event=<id>`,
`/home?routine=<id>`, `/settings/reminders?reminder=<id>`) — same
registry, same logic, reused rather than duplicated. `Shared/DeepLink.swift`
wraps that path in one small, additive URL Scheme,
`mykhaya://open?path=<path>`, registered in `Info.plist`
(`CFBundleURLTypes` — not an Associated Domain, no Apple Developer portal
step). `WidgetBridgePlugin.swift` observes Capacitor's own
`.capacitorOpenURL` notification (already posted by the untouched,
storyboard-owned `SceneDelegateProxy.shared.scene(_:openURLContexts:)`
forwarding — the same "observe a notification Capacitor already posts"
pattern `ensure-apns-appdelegate.sh` uses for APNs) and, for the
`mykhaya` scheme only, navigates the existing WKWebView with
`window.location.assign(path)` — a same-origin relative navigation, so it
needs no knowledge of which environment (dev/prod) is currently loaded.

This is a **new, additive native capability**, flagged explicitly per the
task's "genuine architectural" callout: it does not touch, weaken, or
duplicate the existing `https://` deep-link resolver used by push/email;
it only gives a widget tap a way to reach the app at all.

## Privacy / Lock Screen redaction

Not implemented in this phase. Apple's actual mechanism is
`.privacySensitive()` (SwiftUI) plus `redactPrivateFields` config on
`WidgetConfiguration` / `ActivityConfiguration`-style APIs, which redact
marked content when the device is locked. None of the views here use it
yet — MyKhaya's widget content (event titles, to-do titles) is treated the
same as any other Home Screen widget content (e.g. Apple's own Calendar
widget, Reminders widget), which does not redact by default either.
**Recommended Phase 2 follow-up**: mark event/todo titles
`.privacySensitive()` if user feedback wants stricter Lock Screen
behaviour — this is a small, additive SwiftUI modifier change, not an
architecture change.

## Deployment target

No `ios/` project exists in this repo to read an authoritative minimum iOS
version from. The widget extension is written against classic
`TimelineProvider`/`StaticConfiguration` (works from iOS 14) and set to a
conservative **iOS 16.0** floor in `setup-widget-extension.rb`
(`WIDGET_DEPLOYMENT_TARGET`). The script prints the *main* app target's
actual `IPHONEOS_DEPLOYMENT_TARGET` for comparison the first time it runs
on a Mac — **read that output and adjust `WIDGET_DEPLOYMENT_TARGET` if the
main target's minimum is different**, then re-run.

## Mac bootstrap integration

`scripts/mac-bootstrap.sh` now runs `scripts/install-widget-sources.sh`
(step "5c-widgets") immediately after the existing APNs/storyboard/Face ID
steps, before the simulator build. That script:

1. Refuses to run off macOS or without `ios/` already generated.
2. Copies `native/widgets/` into `ios/App/MyKhayaWidgets/` and
   `native/plugin/*.swift` + the two `Shared/` files
   (`WidgetSnapshot.swift`, `WidgetSnapshotStore.swift`, needed by the main
   app target's own `WidgetBridgePlugin.swift`) into `ios/App/App/`.
3. Runs `scripts/add-app-target-sources.rb` to add those 4 files to the
   `App` target's source build phase.
4. Points `Main.storyboard`'s bridge view controller at the new
   `MainViewController` class instead of Capacitor's default
   `CAPBridgeViewController` (idempotent, grep-guarded — same style as
   `ensure-storyboard-scene-delegate.sh`).
5. Registers the `mykhaya://` URL scheme in `Info.plist`.
6. Runs `scripts/setup-widget-extension.rb` (the `xcodeproj` gem — already
   present via CocoaPods, see below) to create/update the
   `MyKhayaWidgets` target: bundle ID, deployment target, entitlements
   file, Info.plist, App Group capability on **both** targets, and the
   "Embed App Extensions" build phase on `App`.
7. Prints the resulting `App.entitlements` so `aps-environment` can be
   visually confirmed still present.

### Why the `xcodeproj` Ruby gem, not manual `project.pbxproj` editing

Creating a genuinely new Xcode target (its own Info.plist, entitlements,
build settings, embed phase) safely from a script needs a structured API,
not text substitution against `project.pbxproj` — the task's own
instructions warn against exactly that. `xcodeproj` is the gem CocoaPods
itself is built on; anyone following the existing Mac checklist
(`brew install cocoapods`) already has it. No new toolchain dependency was
introduced.

## APNs / Face ID preservation

- `setup-widget-extension.rb` only **adds** the
  `com.apple.security.application-groups` key to
  `ios/App/App/App.entitlements`; it never removes or rewrites
  `aps-environment`, and prints the file's `aps-environment` presence
  explicitly after every run.
- `ensure-apns-appdelegate.sh` and `ensure-storyboard-scene-delegate.sh`
  are untouched. `MainViewController` is a **subclass** of
  `CAPBridgeViewController`, not a replacement — every existing bridge
  behaviour those two scripts protect (storyboard-owned lifecycle, APNs
  `NotificationCenter` forwarding) is unaffected; the only override added
  is `capacitorDidLoad()`, purely for plugin registration.
- The App Group container is never used for anything Keychain-related.
  `KeychainNativeSessionStoreStore`/`@aparajita/capacitor-secure-storage`
  are completely untouched by this feature.

## Verification status — what is proven, what is not

**Proven on Windows** (`pnpm --filter <pkg> test`/`typecheck`):
`widget-snapshot.ts`'s event selection, calendar-month shaping, to-do
ordering, and no-secrets assertions; `widget-bridge.ts`'s native-shell
gating, Home fallback, and logout-wins-over-sync behaviour; the full
`apps/web` TypeScript project still typechecks cleanly after every wiring
change.

**Proven on a Mac** (real `xcodebuild`, not a claim): `App` and
`MyKhayaWidgets` both build successfully for the iOS Simulator, with
`MyKhayaWidgets.appex` embedded via a real "Embed App Extensions" build
phase; `setup-widget-extension.rb` produces a valid, buildable target with
correct bundle ID/deployment target/entitlements/`Info.plist`; the
`MyKhayaWidgetCore` package's 36-test XCTest suite (Codable round-trip,
schema version/corruption handling, calendar month-grid shaping across
different first-weekdays and month lengths, event-day grouping including
multi-day spans, event time/due-date display labels, BST/UTC boundary
parsing) passes via `xcodebuild test`; the full install pipeline
(`install-widget-sources.sh` → `setup-widget-extension.rb` →
`link-widget-core-package.rb` → `ensure-widget-schemes.rb`) is idempotent —
run twice in direct succession with zero duplicate targets, file
references, package dependencies, or schemes.

**Still not provable without a physical device or a signed-in real
backend session**: TestFlight archiving with the new target embedded
(needs a Distribution certificate/profile, not yet attempted); the
`mykhaya://` deep link actually opening the app and navigating the WebView
against a real signed-in session; `WidgetCenter.shared.reloadAllTimelines()`
visibly refreshing a Home-Screen-pinned widget after a real calendar/
routine/reminder change; active-Home switching and logout clearing against
real backend data. See "Manual Mac verification checklist" below for
exactly what's been walked through in the Simulator vs. what still needs a
signed-in session.

## Manual Mac verification checklist

Run **after** `scripts/mac-bootstrap.sh` (which now includes widget
install) or `scripts/install-widget-sources.sh` standalone if `ios/`
already exists:

1. `cd apps/ios-shell && xcodebuild -list -project ios/App/App.xcodeproj`
   — confirm `MyKhayaWidgets` appears as a target/scheme.
2. Open in Xcode (`npx cap open ios`). Confirm both `App` and
   `MyKhayaWidgets` targets show the **App Groups** capability
   (`group.app.mykhaya.mobile`) under Signing & Capabilities, and `App`
   still shows **Push Notifications**.
3. Build the `App` scheme for the simulator — this also builds and embeds
   `MyKhayaWidgets`. Fix any Swift compile errors surfaced here (this is
   the first real compile these files will ever undergo).
4. Run on a simulator, sign in, select a Home.
5. Long-press the Home Screen → + → search "MyKhaya" → confirm all three
   widgets (Next Event, Calendar, To-do) appear with their configured
   sizes.
6. Add each widget; confirm it renders real data, not the placeholder.
7. Create/edit/delete a calendar event in the app; confirm the relevant
   widget updates within a reasonable time (WidgetKit's own scheduling —
   not instant).
8. Add/complete a reminder or routine; confirm the To-do widget updates.
9. Switch active Home; confirm the previous Home's data disappears from
   every widget.
10. Tap a Next Event widget's event; confirm the app opens (or comes to
    foreground) at that event.
11. Force-kill and relaunch the app; confirm widgets keep working.
12. Log out; confirm every widget falls back to "Open MyKhaya to sign in"
    and stays that way after relaunch.
13. Log back in; confirm widgets recover.
14. Test light mode, dark mode, a long event/reminder title (no overlap/
    clipping), and an empty Home (no events, no to-dos).
15. `xcodebuild archive` for a Release configuration; confirm the archive
    contains `MyKhayaWidgets.appex` and that `codesign -d --entitlements
    :- <path>` on both the app and the appex show the expected
    entitlements (App Groups on both; `aps-environment` on `App` only).

## Apple Developer portal / TestFlight

- The `group.app.mykhaya.mobile` App Group and the
  `app.mykhaya.mobile.widgets` App ID need registering in the Apple
  Developer portal before a **device/TestFlight** build (simulator builds
  need no signing at all, same as the existing checklist's Step 4).
  Xcode's own "Register this identifier"/"Fix Issue" prompts handle this
  once a paid team is selected — same flow already documented for the main
  app's bundle ID.
- **Do this only after Anthony confirms** it, same standing requirement
  ADR 0012 already states for `app.mykhaya.mobile` itself.
- TestFlight: once both App IDs are registered and both targets sign
  successfully, an ordinary archive/upload picks up the widget extension
  automatically (it's embedded in the app bundle) — no separate submission
  step.

## Known limitations

- Nothing in this feature has been compiled or run — see "Verification
  status" above.
- To-do completion is view-only from the widget in this phase (see the
  task's own guidance: implementing it safely would need Apple's
  interactive-widget `AppIntent` architecture plus a decision about
  running an authenticated mutation from the widget extension process,
  which is materially more architecture than this phase's scope).
- No Lock Screen privacy redaction yet (`.privacySensitive()`).
- Deployment target (16.0) is a documented assumption, not read from a
  real project — verify against the actual `ios/` project on first Mac run.
- Android widgets are explicitly out of scope; nothing here should make
  them harder later (`WidgetSnapshot`'s shape has no iOS-specific
  concepts — a hypothetical Android implementation could reuse the exact
  same `widget-snapshot.ts` output).

## Recommended Phase 2 enhancements

- Interactive to-do completion via `AppIntent` + `WidgetKit`'s interactive
  widget support (iOS 17+), reusing the existing `api.completeRoutine`/
  `completeReminder` calls from a lightweight App Intent that shares
  `native-auth.ts`'s session — needs its own security review given it
  would be the first widget-extension code to touch authenticated state.
- Lock Screen / StandBy widget families.
- `.privacySensitive()` redaction for event/todo titles.
- Binding the Keychain session to `biometryCurrentSet` (ADR 0012 already
  flags this as a separate follow-up, unrelated to widgets).
- Confirm the real deployment target once a Mac has generated `ios/`, and
  consider `AppIntentTimelineProvider` if that target is iOS 17+.
