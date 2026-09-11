# ADR 0013: Hybrid web and native presentation

**Status:** Accepted

## Decision

MyKhaya supports both browser/PWA use and native shells while keeping exactly
one primary consumer frontend: `apps/web`. The Capacitor iOS shell in
`apps/ios-shell` loads the live deployed frontend and supplies a native runtime
boundary; it is not a duplicated feature client.

The current native/mobile presentation is protected. Tablet and desktop browser
layouts may use different composition and the available viewport width, but
must not alter mobile geometry, safe areas, fixed navigation, sheets, viewport
scaling or touch behaviour. Viewport/media-query rules control responsive
layout; `isNativeShell()` and `nativePlatform()` control genuinely native
behaviour.

## Reconciliation with earlier ADRs

ADR 0011's principle remains accepted: there is no duplicated native feature
frontend and no second consumer frontend. ADR 0012 subsequently introduced the
live Capacitor shell as a native wrapper around `apps/web`. ADR 0013 supersedes
any older interpretation that MyKhaya has no native shipping surface, while
leaving the one-frontend principle unchanged.

The shell does not create a new hostname architecture, duplicate authentication
or business logic, or require separate consumer feature implementations.

## Avatar selection: native Capacitor picker vs. browser file input

Profile-avatar photo *selection* uses a different mechanism per presentation
family; everything downstream of getting a `File` is shared (see "Shared
binary upload processing" below).

- **Web/PWA/browser** (`isNativeShell()` false): the existing hidden HTML
  `<input type="file" accept="image/*">` — one for "Take photo"
  (`capture="environment"`), one for "Choose from library". Unchanged by this
  decision.
- **Native iOS shell** (`isNativeShell()` true): the official Capacitor
  Camera plugin (`@capacitor/camera`, its current `takePhoto`/
  `chooseFromGallery` API, not the deprecated `getPhoto({source: ...})` it
  replaces), via `apps/web/components/native-avatar-picker.ts`. The native
  shell never renders or invokes the hidden HTML input at all — the two
  paths are a structural `if (isNativeShell()) { …Capacitor… } else { …HTML
  input… }` branch in `app/settings/profile/page.tsx`, using the existing
  `isNativeShell()` helper, not a new detection mechanism.

**Why the change.** The HTML file input's iOS Photos-library selection proved
unreliable in the native WKWebView shell specifically: taking a new photo
worked, but selecting an existing Photos-library image did not, independent
of `accept` permutations, and independent of the fact that backend HEIF
decoding (`pillow-heif`) was already confirmed working. This reflects
documented WebKit inconsistency in how a WKWebView-hosted file input
represents/transcodes a Photos-library asset — behaviour MyKhaya does not
control and, inside the native shell specifically, cannot reliably work
around from the web layer. The native Capacitor Camera plugin uses Apple's
own native pickers (`UIImagePickerController` for the camera,
`PHPickerViewController` for the gallery) instead of a WKWebView form
control, sidestepping that inconsistency entirely. **The web/PWA HTML input
path is retained as-is** — this WebKit behaviour is specific to the native
shell's WKWebView hosting a file input from a remote origin, not a general
mobile-Safari/PWA defect, so there is no reason to change the browser path.

**No client-side HEIC decoding, on either path.** The native picker result
is converted into a `Blob`/`File` (see "Native full-resolution asset read"
below) and handed to the API exactly like an HTML-input `File` is. Any
HEIC→JPEG conversion for a Photos-library asset happens inside the Camera
plugin's own native (Swift/ImageIO) code — never in MyKhaya's JavaScript.
`native-avatar-picker.ts` does not call `createImageBitmap`, `Image`, or
canvas on the selected asset.

**Native asset result type.** `takePhoto`/`chooseFromGallery` return a
`MediaResult` (`{ webPath, uri, metadata: { format, size }, thumbnail }`).
`thumbnail` is a low-resolution base64 preview and is never used as the
upload source.

**Native full-resolution asset read: `uri` via the Filesystem plugin, never
`fetch(webPath)`.** An earlier version of this feature read upload bytes via
`fetch(result.webPath)`. That broke both Take Photo and Choose from Photos
on physical TestFlight builds — the picker succeeded but every selection
then failed with "We couldn't read that photo." **Root cause:** `webPath`
is documented by `@capacitor/camera` only as "a path that can be used to
set the `src` attribute of a media item for efficient loading and
rendering" — a display/preview convenience, never a documented
fetch-for-bytes contract. Capacitor's own docs say that when full-resolution
image *bytes* are required on native, read the returned `uri` via the
Filesystem plugin instead. This is exactly the configuration MyKhaya's
shell uses: `server.url` points at a **remote** origin
(`https://dev.mykhaya.app` / `https://mykhaya.app`, see ADR 0012 — not
Capacitor's default bundled-app local origin), and `webPath` reliability is
tied to that local-origin model. `native-avatar-picker.ts` now reads
`result.uri` via `Filesystem.readFile({ path: uri })` (no `directory` —
`uri` is used as an absolute native file reference) and decodes the
resulting base64 string into a `Blob` itself (`atob` + `Uint8Array`, fully
local/synchronous, no further network-ish call of the kind that made
`webPath` unreliable in the first place). `webPath` is retained on the type
only for its documented display/preview purpose; nothing in the avatar flow
currently renders a picker preview, so it isn't read at all today. `uri`'s
*value* is still never logged (only its presence, as `hasUri`) — see
"Native diagnostics" below.

A 20 MiB original (the documented avatar upload ceiling) becomes a ~27 MiB
base64 string crossing the Capacitor JS bridge. This is a real, one-off,
in-memory cost, but reliability was prioritised over avoiding it: the
alternative (continuing to rely on `fetch(webPath)`) is the API this ADR
already documents Capacitor does not support for this configuration, not a
choice available to "optimise back to."

**Native diagnostics.** `native-avatar-picker.ts` logs (never photo bytes,
base64 payloads, EXIF/GPS, auth tokens, or raw URI/path values — only their
presence as booleans) each stage separately, so a real device failure can be
attributed to the exact stage rather than collapsed into one generic
category: picker call started/returned (`stage: "picker"`, with
`source: "camera"|"photos"`), the received `MediaResult`'s `hasUri`/
`hasWebPath`/`metadata.format`/`metadata.size` (`native-asset-received`),
the Filesystem read attempt and its outcome (`stage: "filesystem-read"`,
`native-uri-read-started`/`-succeeded`/`-failed`), and Blob/File construction
(`stage: "blob-construction"`, `native-blob-created` or
`native-blob-construction-failed`). All of these still funnel into the same
four user-facing categories (cancel/permission/read/upload) — the added
granularity is for `console.debug` diagnosis, not new UI states.

**Native error handling.** The plugin returns a structured `CameraErrorCode`
(e.g. `OS-PLUG-CAMR-0006` = take-photo cancelled, `OS-PLUG-CAMR-0003` =
camera permission denied) — never a raw native message or filesystem path
surfaced to the user. `native-avatar-picker.ts` maps these to: cancellation
(no error shown, matching the HTML input's own silent-cancel behaviour),
permission denial (a MyKhaya-worded message naming Settings), or a generic
"couldn't read that photo" message for every other native failure. Upload
failures after a valid `File` is obtained continue to use the existing
backend error-mapping in `components/avatar-upload.ts`, unchanged.

**Permissions.** `chooseFromGallery` presents `PHPickerViewController`,
Apple's privacy-preserving picker — the OS runs it out-of-process and only
hands the app the specific item(s) the user picks, without the app itself
needing broad Photos-library authorization for that flow. `Info.plist`
still declares `NSCameraUsageDescription` and `NSPhotoLibraryUsageDescription`
(present since before this change, with MyKhaya-specific wording) because
the Camera plugin's other, still-shipped legacy methods (`getPhoto`,
`pickImages`, `pickLimitedLibraryPhotos`) and OS-level prompts can still
reference them; no broader or additional permission was added for this
change, and `NSPhotoLibraryAddUsageDescription` (needed only for saving
*into* the library) was deliberately not added since MyKhaya never writes to
the user's Camera Roll here (`saveToGallery: false`).

**Plugin ownership.** `apps/ios-shell` loads the live `apps/web` origin
remotely (see "Decision" above) rather than bundling it, so `npx cap sync
ios` (run from `apps/ios-shell`) only discovers native plugins declared in
*that* package's own `package.json` — a plugin declared only in `apps/web`'s
dependencies (needed there so its TypeScript API can be imported/typechecked)
is invisible to native auto-linking. This was the confirmed root cause of an
earlier TestFlight build's persistent-login/biometric failures, and is now a
regression test (`apps/ios-shell/src/plugin-ownership.test.ts`): every native
plugin `apps/web` imports at runtime must also be an explicit `apps/ios-shell`
dependency at a matching version, `@capacitor/camera` and
`@capacitor/filesystem` included.

**Privacy manifest.** `@capacitor/filesystem`'s `readFile` uses a
"required reason" API (`NSPrivacyAccessedAPICategoryFileTimestamp`) Apple's
App Store Connect can reject a binary over at upload/validation if the app
doesn't declare it. `ios/App/App/PrivacyInfo.xcprivacy` declares it (reason
code `C617.1`, no tracking, no collected data types). The file exists on
disk in the repo; registering it in the Xcode project's Copy Bundle
Resources build phase is a Mac-only step
(`ruby scripts/add-privacy-manifest.rb`, modelled on the existing
`add-app-target-sources.rb`) — see the Mac checklist for when to run it.

## Shared binary upload processing

Shared browser and native-shell uploads pass the resulting `File` through the
same `apps/web` API-client path, regardless of which selection mechanism
above produced it. The native transport must preserve `FormData` as
multipart and must not force a JSON content type. For profile avatars, the
API is the single image-processing authority: it validates image bytes,
supports the configured JPEG/PNG/WebP and HEIF formats, strips metadata,
normalises orientation, crops, resizes, and stores WebP. A failed upload must
leave the existing avatar reference unchanged.

Avatar upload resource limits are independent of the reduced stored output:
the default multipart file ceiling is 20 MiB and decoded images are limited to
40 million pixels before full loading. These limits protect request and memory
resources while allowing ordinary high-resolution phone originals to be uploaded
and reduced server-side. Exceeding the transport or decoded-pixel ceiling is a
resource-limit error, not an unsupported-format error.

The web/PWA avatar file inputs use `accept="image/*"`, never an enumerated
MIME list (not even `image/heic,image/heif` alongside it). WKWebView's iOS
Photos-library transcoding behaviour is sensitive to which image MIME types
`accept` declares — explicitly enumerating HEIC/HEIF has been observed to
change whether iOS hands the picker the original bytes or a transcoded JPEG
for a given asset, and that behaviour is not something MyKhaya controls or
can rely on. `accept` is picker guidance only ("let the user choose an
image"), never validation: the API decodes and validates the real bytes
regardless of what the browser declares or what iOS did or didn't transcode,
including the ISO-BMFF "sequence" container variants
(`image/heic-sequence`, `image/heif-sequence`) a Live Photo or burst-style
HEIC asset may report — acceptance is decode-result based (Pillow's own
resolved `image.format`), never MIME-string based.

## Presentation families

Mobile/native is app-like, stacked, touch-first and safe-area aware. Its current
header, bottom navigation, sheets, FAB clearance, keyboard behaviour, viewport
model and density are the protected baseline.

Browser/tablet/desktop is adaptive and spacious. It may use wider shells,
multi-column layouts, split list/detail views, desktop dialogs/panels and
keyboard/mouse-efficient forms. It must not simply centre a phone-width app in
empty desktop space.

Feature logic, API access, authentication, authorization, entitlements,
validation, domain state and data models remain shared. Presentation-specific
wrappers and composition are allowed when they do not duplicate business logic.

## Verification

Every user-facing UI change must be checked for both presentation families and
at the relevant phone, tablet and desktop widths. Physical iPhone review is
required before release where the native shell can be affected. No horizontal
scroll, zoomed-out page, safe-area regression, bottom-nav overlap or desktop
layout leakage may be introduced into the native experience.

PCC remains a separate desktop-first administrative surface. Consumer mobile
layout rules do not govern PCC unless explicitly requested.

## Consequences

Ordinary consumer UI changes remain web changes in `apps/web` and reach the live
shell through its deployed origin. Native-only capabilities and shell
configuration remain in `apps/ios-shell`. The protected mobile baseline and
wide-screen adaptation must be reviewed together, but they do not need to share
identical markup or geometry.
