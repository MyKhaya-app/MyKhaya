# Native Apple Sign-In release-candidate repair

## Root cause

Release candidate `a15aa58e4d3fe16daf6524af1928d2377ec74734` omitted
`com.apple.developer.applesignin` from both `AppDebug.entitlements` and
`AppRelease.entitlements`. AuthenticationServices therefore fails before the
Apple UI is presented, commonly as `ASAuthorizationError.unknown` (1000).
The candidate's `NativeExternalAuthPlugin.swift` also discarded the underlying
error and returned one generic rejection.

The earlier correction is commit `32a3d5625e4b733a3626eea69f40f2e32d642e87`
on `dev`. The repair reuses that implementation and its tests; the correction
was not included when the release-candidate branch was assembled.

## Configuration and signing

The entitlement is on the main app target only. APNs and App Groups remain
environment-driven through `$(MYKHAYA_APNS_BUILD_ENVIRONMENT)` and
`$(MYKHAYA_APP_GROUP)`. DEV and PROD continue to use their existing bundle IDs,
URL schemes, hosts and App Groups from `Config/Environment-Dev.xcconfig` and
`Config/Environment-Prod.xcconfig`.

The Apple Developer App ID for each bundle must have Sign in with Apple enabled,
and the provisioning profile used for each DEV/PROD app must contain the
entitlement. This repository change does not modify Apple Developer portal
resources, certificates or signing credentials.

## Diagnostics and security

The native plugin now distinguishes cancellation, invalid transaction,
in-progress requests, invalid credentials and AuthenticationServices provider
errors. It returns a stable non-sensitive error code and, where available, the
numeric native error code. It never logs or includes identity tokens, nonces,
secrets or private user data. User-facing text remains understandable and does
not expose implementation details.

## Validation

Run from `apps/ios-shell`:

```sh
pnpm test
pnpm typecheck
sh scripts/validate-ios-environments.sh
```

On macOS, additionally build all four app configurations and inspect the
signed products, not just the unsigned source entitlements:

```sh
xcodebuild -project ios/App/App.xcodeproj -scheme MyKhaya-Dev -configuration Debug-Dev -sdk iphoneos build
xcodebuild -project ios/App/App.xcodeproj -scheme MyKhaya-Dev -configuration Release-Dev -sdk iphoneos build
xcodebuild -project ios/App/App.xcodeproj -scheme MyKhaya-Prod -configuration Debug-Prod -sdk iphoneos build
xcodebuild -project ios/App/App.xcodeproj -scheme MyKhaya-Prod -configuration Release-Prod -sdk iphoneos build
codesign -d --entitlements :- path/to/MyKhaya.app
```

Confirm the signed app contains `com.apple.developer.applesignin = [Default]`,
the expected `aps-environment`, bundle ID and App Group. Repeat on a physical
DEV iPhone and a signed PROD/TestFlight candidate. Cancelled, missing-capability
and provider-error paths should show the safe user message and preserve the
diagnostic code in local test instrumentation without logging credentials.
