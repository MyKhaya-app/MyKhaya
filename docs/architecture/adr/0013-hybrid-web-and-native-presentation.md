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

## Shared binary upload processing

Shared browser and native-shell uploads pass the selected browser `File` through
the same `apps/web` API-client path. The native transport must preserve
`FormData` as multipart and must not force a JSON content type. For profile
avatars, the API is the single image-processing authority: it validates image
bytes, supports the configured JPEG/PNG/WebP and HEIF formats, strips metadata,
normalises orientation, crops, resizes, and stores WebP. The frontend does not
attempt HEIC/HEIF decoding with `createImageBitmap`, `Image`, or canvas because
WKWebView support varies between Photos-library assets; relying on that client
conversion would make native and browser behaviour diverge. A failed upload
must leave the existing avatar reference unchanged.

Avatar upload resource limits are independent of the reduced stored output:
the default multipart file ceiling is 20 MiB and decoded images are limited to
40 million pixels before full loading. These limits protect request and memory
resources while allowing ordinary high-resolution phone originals to be uploaded
and reduced server-side. Exceeding the transport or decoded-pixel ceiling is a
resource-limit error, not an unsupported-format error.

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
