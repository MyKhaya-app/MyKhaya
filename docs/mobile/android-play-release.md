# Android Play release runbook

This runbook applies to the production flavor only. The package IDs are
deliberately stable:

| Flavor | Application ID | Frontend origin |
| --- | --- | --- |
| DEV | `app.mykhaya.mobile` | `https://dev.mykhaya.app` |
| PROD | `app.mykhaya.mobile.prod` | `https://mykhaya.app` |

## First Internal Testing bundle

Before building, obtain the PROD Firebase file from the Firebase project that
owns the Android app `app.mykhaya.mobile.prod`. Place it locally at
`apps/android-shell/android/app/src/production/google-services.json`. Never use
the DEV file and never commit either file.

Create or obtain the permanent upload keystore locally. Keep it backed up in a
separate secure location. Copy
`apps/android-shell/android/app/keystore.properties.example` to
`apps/android-shell/android/app/keystore.properties` and set the real values,
or provide the equivalent `MYKHAYA_UPLOAD_*` environment variables. The
keystore, alias, and passwords are not repository configuration and must never
be committed.

Google Play App Signing should be enabled when the first bundle is uploaded.
Google Play then holds the app-signing key; the local key configured here is
the upload key used for future bundles. Do not rotate or replace either key
without completing the Play Console key-change workflow.

From `apps/android-shell/android`, with Java and the Android SDK configured:

```powershell
.\gradlew.bat bundleProductionRelease --no-daemon
```

The expected artifact is:

`apps/android-shell/android/app/build/outputs/bundle/productionRelease/app-production-release.aab`

The build fails closed if PROD Firebase configuration or release signing
material is missing. It does not upload or publish anything.

Validate the resulting bundle before manual upload:

```powershell
.\gradlew.bat :app:signingReport
apkanalyzer manifest application-id app\build\outputs\bundle\productionRelease\app-production-release.aab
```

Confirm the package is `app.mykhaya.mobile.prod`, the signing certificate is
the intended upload certificate, and the version code is unused in the PROD
Play Console. The corrective release currently declares `versionCode 31` and
`versionName 0.1.31`; Play Console remains the authority for whether 31 is
unused. Never reuse versionCode 30.

## Subsequent releases

Keep the same PROD application ID, upload keystore, key alias, and signing
identity. Increase `versionCode` for every Play upload; update `versionName`
according to the release version. Re-download neither the Firebase file nor a
new keystore unless the relevant project/key-management workflow explicitly
requires it. Run the same `bundleProductionRelease` command, upload the AAB in
Play Console, and create the next release in the appropriate test or
production track after review.

Changing the application ID creates a different Android app and will not
receive existing Play users' updates. Uninstalling the app during testing can
remove local app data; installing an update with the same package ID preserves
user data subject to normal Android upgrade rules. The shell loads the live
web frontend, so ordinary web changes do not require a new Play release.

## Key and data safety

Back up the upload keystore and its passwords in the approved secrets manager.
If the upload key is lost, use Play Console's upload-key reset process; do not
invent a new local key and silently continue. Never place private keys,
passwords, Firebase service-account JSON, or generated bundles in Git.
