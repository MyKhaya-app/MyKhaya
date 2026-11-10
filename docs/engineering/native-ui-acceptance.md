# Native UI acceptance checklist

The hands-on check that stands between automated evidence and a native
release. It applies the rules in [Mobile Standards](mobile-standards.md) and
[iOS Engineering Standards §6](ios-engineering-standards.md#6-physical-validation-and-acceptance)
to the consumer forms in [Forms](../design/forms.md).

## Kinds of evidence

Record which kind each result is. They are not interchangeable.

| Kind | What it is | What it can prove |
|---|---|---|
| Browser automation | The responsive audit and layout harness in Chromium, with simulated safe areas and touch emulation | Containment, overflow, overlap, reachability, 16px text on touch profiles, sheet and footer geometry. Not WKWebView, not a keyboard, not a picker. |
| Simulator or emulator | Xcode's iOS Simulator, or an Android Virtual Device | Real WebView rendering, pickers, keyboard resizing and the Android back button. Not real safe areas on the Duo, touch feel or performance. |
| Physical device | A real iPhone, iPhone Duo, iPad or Android phone running the DEV app | Everything above, plus safe areas, the Duo's status overlay, keyboard feel and focus zoom. **Native acceptance needs this.** |

Never record browser or simulator results as device results.

### What Chromium touch emulation does not show

The audit's phone, Duo and iPad profiles turn on Chromium's touch
emulation, so the page matches `(hover: none) and (pointer: coarse)` as it
would on a device. That is all it changes. It is still desktop Chromium:

- **iOS (WKWebView):** no focus zoom happens in Chromium at all; the audit
  can only measure that text is 16px, not that iOS leaves the page alone.
  The native date, time and select pickers, the keyboard and its accessory
  bar, `env(safe-area-inset-*)`, the Duo's status overlay, rubber-band
  scrolling and WebKit's own control sizing are not reproduced. Safe areas
  are simulated with fixed `--safe-*` values.
- **Android (Android System WebView):** the same engine family as Chromium,
  but the keyboard resizing the WebView, the system back button, the
  status and navigation bars and the native file and photo chooser are not
  reproduced.

Each of these is a device check in the list below.

## Before you start

1. Confirm what is deployed. On the DEV app, open **More → About MyKhaya**. Signed
   in, a development build shows:
   - **Web build:** the frontend commit and build time;
   - **API build:** the API commit and build time.

   Note both. A push to `dev` is not a deployment: the Web build must match
   the commit under review.
2. Note the device, OS version, app build (the iOS or Android app row on
   About), orientation, and for the Duo which screen.
3. Use the synthetic test account and disposable records whose names start
   `Native QA`. Never send a real invitation, support request or
   notification:
   - for invitations and support forms, test validation and stop before
     sending;
   - saving a planned meal or wishlist notifies the other Home members, so
     use a Home with no other real members, or delete the notifications
     afterwards.
4. Delete every disposable record when you finish.

## Presentations to cover

| Presentation | iOS | Android |
|---|---|---|
| Standard phone, portrait | iPhone | Phone |
| Standard phone, landscape | iPhone, including a 760pt+ model | Phone |
| iPhone Duo outer (closed) screen | Duo | — |
| iPhone Duo inner (unfolded) screen | Duo | — |
| Folding and unfolding with a form open | Duo | — |
| Rotating with a form open | iPhone | Phone |
| Tablet, and a split or Stage Manager window | iPad | Optional |

## Checks for every form

For each form below, on each presentation:

- [ ] Opens with its title, Close or Cancel, and its primary action visible.
- [ ] Nothing extends past the sheet or card; the page never scrolls
      sideways.
- [ ] Every field is labelled; errors appear under their field, and a
      failed save appears above the action.
- [ ] **No zoom on focus:** tapping a text field, select or textarea does
      not zoom the page, and the page is not zoomed after the keyboard
      closes.
- [ ] The keyboard does not cover the focused field or the primary action;
      the sheet scrolls to reveal it. Dismissing the keyboard restores the
      layout.
- [ ] Long forms scroll vertically, and the footer stays clear of the home
      indicator.
- [ ] Close and Cancel stay clear of the status bar, the Dynamic Island and
      the Duo's status overlay.
- [ ] Rotating, or folding or unfolding the Duo, keeps the typed values.
- [ ] Date and time fields open the native picker, and the chosen value
      shows in the field.
- [ ] Number and money fields show a numeric or decimal keyboard and keep
      pence.
- [ ] Photo and file fields open the native picker, and the chosen image
      shows.
- [ ] Android only: the system back button closes an open sheet first, then
      goes back a page; it never leaves the app from inside a form.
- [ ] Android only: content clears the status and navigation bars.

## Forms

| Area | Forms |
|---|---|
| Calendar | Create event, Edit event, Copy event (several dates, different times), all-day and multi-day events, Add a Home calendar, the share invitation, New Calendar Tag |
| Routines, Reminders and Settings | Routine, Reminder and To-do (create and edit), Notification preferences, Profile birthday, a failed save |
| Driveway | Add vehicle, Edit details, MOT nudge, Add reminder, vehicle cards on a narrow phone |
| Budget | Income and spending (add and edit), Update actual amount, planned amount, Add category, Set up next month, pence amounts |
| Meal Plans | Planned meal and saved meal (add and edit), Import recipe, Plan this meal, Add ingredients to list, photo selection, Filter meals |
| Lists and Wishlists | New and edit list, list items, New and edit wishlist, wishlist items with price and link, Share |
| Members and Support | Member invitation with the Family access checkbox, Contact support, Report a bug, a request reply (validation only) |
| Sign-in MFA challenge | With consumer MFA Required: native password, Apple and Google sign-in each show only the "Additional verification required" challenge. No email/password form or provider buttons are underneath. The code field stays visible above the keyboard, errors appear inside the challenge, and "Use a different sign-in method" brings the form back. See [Consumer MFA enforcement](consumer-mfa-enforcement.md). |
| Calendar toolbar (not a form) | The Everyone and view pickers and the Tags pill: no zoom when opened, each picker's native list opens and applies, the pills wrap to a second row only when there is no room, month navigation stays on one row, and nothing is cut off. Check portrait, landscape, both Duo screens and after folding. |

## Recording results

Add a row per device and presentation. Keep private family and child data
out of screenshots.

| Date | Web build | API build | Device and OS | App build | Presentation | Kind | Result | Notes |
|---|---|---|---|---|---|---|---|---|

## Status

| Date | Web build | What ran | Kind | Result |
|---|---|---|---|---|
| 2026-11-01 | `78d2105` + Phase 3 changes, local | Full responsive audit with touch profiles; layout harness | Browser automation | See the Phase 3 report. |
| 2026-11-02 | `78d2105` + Phase 3 and Calendar toolbar changes, local | Full responsive audit including the Calendar toolbar section; layout harness | Browser automation | See the Phase 3 toolbar report. Not deployed to DEV. |
| 2026-11-01 | — | Android emulator (Pixel 6 AVD, Android 16, Google APIs image) | Emulator | **Not run.** The image has no usable browser (Chrome is a library stub), and the Android shell only loads the live DEV or PROD frontend, so local changes cannot be shown in it. A Google Play image, or a DEV deployment, is needed. |
| — | — | iOS Simulator | Simulator | **Not run.** Needs a Mac with Xcode. |
| — | — | Every presentation above | Physical device | **Not run.** Native acceptance is not complete. |
## Subsequent user-reported evidence

The Owner/user reported that **MyKhaya-Dev iOS v0.1.36 (Build 1)** was
distributed through TestFlight, installed and physically tested on an iPhone,
and that the physical-device test passed. The same report says Apple and Google
sign-in had previously been confirmed against live DEV.

This is recorded as user-provided acceptance evidence, not independent agent
verification. It does not establish that every checklist presentation or native
capability was covered. APNs delivery, widgets, Face ID/Keychain persistence,
iPad/Duo layouts, keyboard/picker behaviour and the deployed web SHA remain
unverified unless separately recorded.

Android remains unaccepted. Minimum outstanding evidence is a DEV or PROD
physical-device/Play Internal Testing run covering Firebase project and
`google-services.json` identity, FCM registration and delivery, notification
permission/channels, foreground/background/terminated delivery, tap routing,
biometric resume re-lock and predictive back behaviour.
