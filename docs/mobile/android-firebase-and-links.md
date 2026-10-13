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
   `android/gradlew.bat assembleDevelopmentDebug` and install the APK. The
   build verifies the DEV JSON contains an Android client for
   `app.mykhaya.mobile`; a missing or mismatched file fails with an actionable
   error instead of silently producing an APK without Firebase configuration.

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

The currently generated DEV debug APK was signed by the local Android debug
keystore with SHA-256 certificate fingerprint
`1D:08:3A:BE:13:0E:C9:91:29:C6:D0:90:3A:CD:15:E0:E5:52:5C:84:E6:8F:7F:14:07:5B:3A:E3:90:8E:3C:74`.
This fingerprint is machine-specific unless the same debug keystore is used.
Publish the following at `https://dev.mykhaya.app/.well-known/assetlinks.json`
only when that is the certificate used by the installed DEV APK; replace it
for a shared, release, or CI signing key.

```json
[
  {
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
      "namespace": "android_app",
      "package_name": "app.mykhaya.mobile",
      "sha256_cert_fingerprints": [
        "1D:08:3A:BE:13:0E:C9:91:29:C6:D0:90:3A:CD:15:E0:E5:52:5C:84:E6:8F:7F:14:07:5B:3A:E3:90:8E:3C:74"
      ]
    }
  }
]
```

Repeat for PROD at `https://mykhaya.app/.well-known/assetlinks.json` with
package `app.mykhaya.mobile.prod` and the production certificate. Until this
is done, ordinary HTTPS links remain safe browser links and the app's native
startup/auth gate is unchanged.

## Build and install

From the repository root in PowerShell:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Eclipse Adoptium\jdk-21.0.12.101-hotspot'
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
Set-Location apps\android-shell\android
.\gradlew.bat assembleDevelopmentDebug
adb install -r app\build\outputs\apk\development\debug\app-development-debug.apk
```

The exact DEV APK path is
`apps/android-shell/android/app/build/outputs/apk/development/debug/app-development-debug.apk`.

## Physical-device validation

Use a real DEV account and a second authenticated session or backend test
trigger. Do not paste registration tokens into tickets or logs.

1. Confirm the device is visible and install the DEV APK:

   ```powershell
   adb devices
   adb install -r app\build\outputs\apk\development\debug\app-development-debug.apk
   adb shell pm clear app.mykhaya.mobile
   ```

2. Launch the app, complete login and MFA, allow Android notification
   permission, enable biometric authentication, close/reopen the app, and
   confirm the session persists.
3. Put the app in the background and then resume it. Confirm the configured
   lifecycle re-lock occurs after the security timeout and that Android Back
   returns through the expected web/native history without exiting unexpectedly.
4. Toggle airplane mode: verify cached/session-safe screens remain usable,
   requests fail clearly while offline, and data/push registration recover when
   connectivity returns.
5. Send a DEV push for each channel/type and verify foreground delivery,
   background delivery, and delivery after force-stop/relaunch as supported by
   the Android OS. Confirm the notification channel is `general`, `reminders`,
   or `calendar_family` as appropriate and that channel settings are visible.
6. Tap each notification and verify its safe internal deep link routes to the
   intended screen. Verify external or malformed paths are not navigated to.
7. Force a token refresh or reinstall the app, confirm the backend registration
   is updated, then log out and confirm the device registration is deleted and
   no further authenticated push is delivered.

Useful diagnostics:

```powershell
adb logcat -c
adb logcat -v threadtime | Select-String -Pattern 'FirebaseMessaging|FIS|Capacitor|PushNotifications|MyKhaya|Notification'
adb shell dumpsys notification --noredact | Select-String -Pattern 'app.mykhaya.mobile|general|reminders|calendar_family'
adb shell pm dump app.mykhaya.mobile | Select-String -Pattern 'permission|POST_NOTIFICATIONS|dev.mykhaya.app'
adb shell am force-stop app.mykhaya.mobile
adb shell monkey -p app.mykhaya.mobile 1
```

The app diagnostics intentionally report registration state, platform, and
timestamps rather than FCM tokens, credentials, or private keys. A Firebase
project, backend service-account configuration, signing certificate, and
physical device are required for end-to-end delivery.
