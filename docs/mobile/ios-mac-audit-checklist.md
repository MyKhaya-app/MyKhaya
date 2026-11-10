# iOS Mac and device audit checklist

The checklist for the Mac, Xcode, account and device checks listed in
[iOS Engineering Standards §10](../engineering/ios-engineering-standards.md#10-what-this-standard-has-and-has-not-verified).
None of it can be done from the Windows checkout. Record results in the
handoff format of [§11](../engineering/ios-engineering-standards.md#11-required-ios-engineering-handoff).

Rules for whoever runs it:

- Record what was actually run and seen. Mark a step **not run** rather than
  inferring its result from another step. A simulator result is not a device
  result, and an archive is not an upload.
- Never print or paste private keys, certificates, provisioning profile
  secrets, `.p8` contents, session or device tokens, or push tokens. The
  commands below print identifiers and entitlement values only.
- Do not upload to App Store Connect, submit for review, change signing in
  Xcode's GUI, or edit the xcconfigs as part of this audit. Any fix is a
  separate, reviewed change.
- Keep private family and child data out of screenshots. Use a test Home.

Commands run from `apps/ios-shell` unless stated. `$CFG` is one of
`Debug-Dev`, `Release-Dev`, `Debug-Prod`, `Release-Prod`.

## Audit header (record first)

| Field | Value |
|---|---|
| Date, auditor | |
| macOS (`sw_vers`), Xcode (`xcodebuild -version`), Node, pnpm | |
| Branch, local `HEAD`, `origin/dev` SHA, `origin/main` SHA | |
| DEV frontend/API SHA actually deployed (see [A5](#a-repository-and-tooling)) | |
| PROD frontend/API SHA actually deployed | |
| Committed DEV version (build) / PROD version (build) | |
| Latest DEV / PROD build in App Store Connect (read only) | |

## A. Repository and tooling

1. `git fetch origin && git status -sb && git status --short --untracked-files=all`.
   Record the branch, ahead/behind, and every modified or untracked path.
   Expected: on `dev`, level with `origin/dev`, clean.
2. `git status --short --ignored apps/ios-shell`. List every ignored path. Only
   generated content is expected (`MyKhayaWidgets/`, `ios/App/App/public`,
   `capacitor.config.json`, `config.xml`, `DerivedData`, `xcuserdata`, `Pods`,
   `build`, `node_modules`). **Flag any ignored Swift, plist, entitlements,
   xcconfig or scheme file:** that is native source that exists only on this Mac.
3. `git stash list`. Record any stashes that touch `apps/ios-shell`. Don't drop them.
4. `pnpm install --frozen-lockfile`.
5. Deployed SHAs. Signed in to each environment in Safari, open
   `https://dev.mykhaya.app/api/v1/health/build` and
   `https://mykhaya.app/api/v1/health/build`, and record `commit`, `version` and
   `channel`. That is the API's commit. Whoever has server access records the web
   image's commit with
   `docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' <web container>`.
   If either is unavailable, record `unverified`.

## B. Native sources

1. `bash scripts/install-widget-sources.sh`, then `git status --short`.
   Expected: no tracked change. A change means a committed copy was stale.
2. `for f in native/plugin/*.swift; do diff -q "$f" "ios/App/App/$(basename "$f")"; done`
   Expected: no output. CI also checks this (`src/native-source-copies.test.ts`).
3. `diff -r native/widgets MyKhayaWidgets`. Expected: no output. This
   untracked copy is checked **only** here.
4. Confirm Main.storyboard's bridge view controller is `MainViewController`:
   `grep -n 'customClass="MainViewController"' ios/App/App/Base.lproj/Main.storyboard`.
5. List every `*.swift` under `ios/App/App` and `MyKhayaWidgets`. Anything not
   produced from `native/` or by Capacitor is unreviewed native code. Flag it.

## C. Repository checks on the Mac

Record pass/fail and counts for each.

1. `pnpm --filter @mykhaya/ios-shell typecheck` and `pnpm --filter @mykhaya/ios-shell test`.
2. `sh scripts/validate-ios-environments.sh` (expands real build settings
   with `xcodebuild`). Expected: OK for all four configurations of both
   targets, and the schemes.
3. `cd native/WidgetCore && swift test`. Record the count.

## D. Schemes and build settings

1. `xcodebuild -list -project ios/App/App.xcodeproj`. Expected targets `App`
   and `MyKhayaWidgets`, configurations `Debug-Dev`, `Release-Dev`,
   `Debug-Prod`, `Release-Prod`, schemes `MyKhaya-Dev`, `MyKhaya-Prod`,
   `MyKhayaWidgets-Dev`, `MyKhayaWidgets-Prod`.
2. For each `$CFG` and each target:
   `xcodebuild -project ios/App/App.xcodeproj -target App -configuration $CFG -showBuildSettings | grep -E ' (PRODUCT_BUNDLE_IDENTIFIER|MYKHAYA_[A-Z_]+|MARKETING_VERSION|CURRENT_PROJECT_VERSION|DEVELOPMENT_TEAM|CODE_SIGN_STYLE|CODE_SIGN_ENTITLEMENTS|IPHONEOS_DEPLOYMENT_TARGET|TARGETED_DEVICE_FAMILY) ='`
   (repeat with `-target MyKhayaWidgets`). Compare with
   [iOS DEV and PROD apps](ios-environments.md). In particular:
   - the widget's bundle ID is the app's plus `.widgets`;
   - app and widget have the same version and build;
   - `MYKHAYA_APNS_BUILD_ENVIRONMENT` is `development` for `Debug-*` and
     `production` for `Release-*`;
   - nothing shows the other environment's values.
3. Open each scheme in Xcode (Product > Scheme > Edit Scheme, read only).
   Expected: Run uses `Debug-<env>` and Archive uses `Release-<env>`.

## E. Builds

1. Simulator builds of both apps:
   `xcodebuild -project ios/App/App.xcodeproj -scheme MyKhaya-Dev -configuration Debug-Dev -sdk iphonesimulator build`
   and the same for `MyKhaya-Prod`/`Debug-Prod`. Record the result and that the
   log contains "MyKhaya iOS environment OK".
2. Device build of DEV (`MyKhaya-Dev`, a connected iPhone) from Xcode. Record
   any signing or capability warnings verbatim, without profile contents.
3. Archive both, without uploading:
   `xcodebuild -project ios/App/App.xcodeproj -scheme MyKhaya-Dev -configuration Release-Dev -archivePath build/audit/MyKhaya-Dev.xcarchive archive`
   and the same for `MyKhaya-Prod`/`Release-Prod`. Record the results.
   `build/` is ignored. Delete the archives after the audit.

## F. Signing, entitlements and Info.plist (from the archives)

For each archive, set `APP=build/audit/<name>.xcarchive/Products/Applications/App.app`
and `WIDGET=$APP/PlugIns/MyKhayaWidgets.appex`.

1. Entitlements: `codesign -d --entitlements :- "$APP"` and the same for
   `"$WIDGET"`. Expected for the app: `aps-environment` = `production`, the
   environment's App Group, and the matching `application-identifier` and team.
   Expected for the widget: the same App Group and no `aps-environment`.
2. Signing identity: `codesign -dv "$APP" 2>&1 | grep -E 'Identifier|TeamIdentifier|Authority'`.
   Record the identifier, team and authority names only.
3. Provisioning: `security cms -D -i "$APP/embedded.mobileprovision" | plutil -extract Entitlements xml1 -o - -`.
   Record whether the profile's entitlements include `aps-environment` and the
   App Group, and its `application-identifier`. Do not paste the profile.
4. Info.plist: `plutil -p "$APP/Info.plist" | grep -E 'CFBundle(Identifier|DisplayName|ShortVersionString|Version)|MyKhaya|CFBundleURLSchemes' -A1`
   and `plutil -p "$WIDGET/Info.plist" | grep -E 'CFBundle(Identifier|ShortVersionString|Version)|MyKhaya'`.
   Expected: the environment's identity, `MyKhayaServerHost` set, the app and
   widget versions and builds equal, and only that environment's URL scheme.
5. `plutil -p "$APP/PrivacyInfo.xcprivacy"` is present. Note that
   `UIRequiredDeviceCapabilities` is still `armv7`, from the Capacitor template.
   Record whether Xcode's archive validation (Organizer > Validate App, which
   does not upload) warns about it. Don't run validation if it needs an upload.
6. Push capability: in the Apple Developer portal (read only), record whether
   both App IDs have Push Notifications and their App Groups enabled.

## G. Physical devices

Install DEV from Xcode (`Debug-Dev`). Install PROD only from TestFlight, and only
if an approved PROD build is already there. Record the device, iOS version,
screen and orientation for every row.

**Reading layout state.** On a `Debug-*` build, attach Safari's Web Inspector
(Develop > device > the app's page) and run:
`({cls: document.querySelector('.app-shell')?.className, w: innerWidth, h: innerHeight, right: getComputedStyle(document.documentElement).getPropertyValue('--safe-right')})`.
Release/TestFlight builds may not be inspectable. Record "not inspectable"
rather than guessing.

### G1. Identity and isolation

- DEV and PROD both installed side by side, with different names and icons.
- Each loads its own host: check the page URL in Web Inspector (DEV), or that
  a test account that exists only on one backend can sign in only to that app.
- Signing in to one does not sign in the other.
- A DEV widget tap opens DEV; a `mykhaya-prod://open?path=/` link (from Notes)
  opens only PROD, and `mykhaya://` only DEV.

### G2. Session, Keychain and biometrics (DEV, then PROD on TestFlight)

- Sign in, force-quit, relaunch: still signed in.
- Turn on Quick Sign-In. Cold launch prompts Face ID. **Cancel** offers retry
  or password and shows no data. A **failed** match does not unlock.
- Background for under 5 minutes: no prompt. Background for over 5 minutes: prompt.
- Sign out, relaunch: signed out, and widgets show "Open MyKhaya to sign in".
- Airplane mode at launch: the offline/retry state appears, not the Login screen.

### G3. Push

- DEV (`Debug-Dev`, sandbox): allow notifications, then cause a real
  notification for the test account on DEV (for example, a reminder due in a
  few minutes, created from another member). Confirm delivery, and that tapping
  it opens the right route.
- PROD (TestFlight, production APNs, PROD backend): same, **only after** the
  PROD APNs topic has been confirmed as `app.mykhaya.mobile.prod`.
- Record delivery and timing only, never tokens.

### G4. Widgets

- Add the Next Event, Calendar and To-do widgets. Their data matches the app.
  Taps deep-link correctly.
- On the lock screen, note what event and to-do titles reveal (redaction is not
  implemented; record for the privacy decision).

### G5. Layout matrix

For each row, screenshot Home, Calendar (month and day), More, a sheet, the
notifications tray and the profile sheet. Check for overlap of the dock, FABs
and header with content, horizontal scroll, and 44pt targets.

| Device / presentation | Expected classes | Result |
|---|---|---|
| Standard iPhone, portrait | none | |
| Standard iPhone, landscape, under 760pt wide | none | |
| Large iPhone, landscape, 760pt or wider | `native-wide-viewport` | |
| iPhone Duo, outer screen | `native-compact-rail native-right-column native-status-column` | |
| iPhone Duo, inner screen | `native-wide-viewport native-right-column native-status-column` | |
| iPad, full screen | `native-wide-viewport native-right-column` | |
| iPad, Stage Manager window around 600 × 700pt | `native-compact-rail native-right-column` | |

Also record:
- Duo status-indicator clearance against the measured values in the standard
  (about 165pt folded and 106pt unfolded, with a right inset of about 93pt on
  the outer screen);
- Dynamic Type at the largest accessibility size (Settings > Accessibility >
  Display & Text Size), kept distinct from browser zoom;
- the reported landscape FAB overlap and short-window rail/FAB collisions,
  reproduced or not.

### G6. Navigation

- A wishlist product link opens in the in-app browser, and the app returns
  intact afterwards.
- Settings > Billing > Upgrade or Manage billing (on a test Home): record what
  happens. It is expected to be blocked (ADR 0012). Do not complete a payment.

### G7. Forms and sheets (Copy Event reference)

The DEV app loads `https://dev.mykhaya.app` live, so it only shows these
changes once they are deployed there. Confirm the build first: on a Mac,
`curl -s https://dev.mykhaya.app/login | grep -o '/_next/static/css/[^"]*\.css'`,
then fetch each listed file and check that one contains
`sheet-follows-visual-viewport`. Record the CSS file names. If none contains
it, stop: the device is running a build without the fixes.

Open Calendar, choose an event, then Copy event. Run each step on the Duo
outer screen and inner screen, in portrait and landscape where the screen
allows it.

1. The sheet's header, title and close button are clear of the status
   indicator, and the close button works.
2. Cancel in the footer closes the sheet.
3. Date: tap it. The native picker opens. Choose a date. The value shows
   inside the field, and the field stays inside its card.
4. Start time and End time: the same as step 3 with the time picker. The two
   fields have a visible gap, or stack on narrow screens. Neither runs past
   the card.
5. One destination: Copy event is disabled until the date is valid, then
   copies.
6. Add another date twice (three destinations), each with different times.
   Scroll to every field and to Add another date. Remove destination works.
7. With a picker or the keyboard open, the footer (Copy event, Cancel) stays
   visible above it and the focused field is not covered.
8. Rotate, and fold or unfold, with the sheet open. Nothing moves under the
   status indicator, and the page does not scroll sideways.
9. Repeat steps 3 and 4 in one other module's date field (Budget or Driveway)
   to confirm the shared date/time styling there.

Record each step as passed, failed or not run, with a screenshot of any
failure.

## H. Close-out

1. Delete `build/audit`. Run `git status --short --untracked-files=all` and
   record it. Expected: unchanged from A1.
2. Write the §11 handoff. List every step as passed, failed, not run, or
   blocked, with the reason.
