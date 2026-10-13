# Android DEV Firebase and App Links handoff

The Android shell is repository-ready for FCM and environment-specific HTTPS
App Links. Credentials and signing material are intentionally not committed.

## DEV FCM setup

1. In Firebase Console, register an Android app with package
   `app.mykhaya.mobile`.
2. Download its `google-services.json` to
   `apps/android-shell/android/app/src/development/google-services.json`.
   This path is gitignored. Do not place service-account private keys in the
   Android project.
3. Configure the backend's FCM service-account values locally:
   `MYKHAYA_FCM_DELIVERY_CONFIGURED=true`, `MYKHAYA_FCM_PROJECT_ID`,
   `MYKHAYA_FCM_CLIENT_EMAIL`, and `MYKHAYA_FCM_PRIVATE_KEY`.
4. Run `npx cap sync android`, then
   `android/gradlew.bat assembleDevelopmentDebug` and install the APK.

The Capacitor Push Notifications plugin supplies Firebase Messaging on
Android. `apps/web/components/native-push.ts` requests Android 13+
`POST_NOTIFICATIONS`, registers the token, handles refresh events, and routes
notification taps through the shared safe internal-path allowlist. The backend
uses the same token registration and centralized notification engine as iOS.

## App Links

The Android manifest has an `autoVerify` HTTPS intent filter whose host is
selected by the Gradle flavor:

| Flavor | Application ID | Host |
| --- | --- | --- |
| development | `app.mykhaya.mobile` | `dev.mykhaya.app` |
| production | `app.mykhaya.mobile.prod` | `mykhaya.app` |

After a DEV signing certificate exists, publish this JSON at
`https://dev.mykhaya.app/.well-known/assetlinks.json`, replacing the example
fingerprint with the SHA-256 fingerprint of the certificate used to sign the
installed DEV APK. Do not publish placeholder fingerprints.

```json
[
  {
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
      "namespace": "android_app",
      "package_name": "app.mykhaya.mobile",
      "sha256_cert_fingerprints": ["REPLACE_WITH_DEV_CERT_SHA256"]
    }
  }
]
```

Repeat for PROD at `https://mykhaya.app/.well-known/assetlinks.json` with
package `app.mykhaya.mobile.prod` and the production certificate. Until this
is done, ordinary HTTPS links remain safe browser links and the app's native
startup/auth gate is unchanged.

## Physical-device validation

On an Android 13+ device verify permission prompt and denial/settings flow;
foreground, background and terminated push delivery; channel assignment;
notification tap routing; token refresh; logout cleanup; biometric unlock;
the five-minute re-lock; and Android Back/predictive Back. A Firebase project,
backend service-account configuration, signing certificate and physical
device are required for these checks.
