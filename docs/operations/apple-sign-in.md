# Apple Sign-In Configuration

This runbook enables the browser Apple flow for one environment. Configure DEV
and PROD as separate Apple registrations and separate MyKhaya deployments; do
not reuse a DEV callback or key in PROD.

## Apple Developer configuration

1. In Apple Developer, create or select the environment's App ID and enable
   **Sign in with Apple**.
2. Create a **Services ID** for the web client and associate it with that App
   ID. The Services ID is the value used for `MYKHAYA_APPLE_SERVICE_ID`.
3. Record the Apple Developer **Team ID** and create a Sign in with Apple key.
   Record its **Key ID** and download the `.p8` private key once. Store the key
   in the deployment secret manager; never commit it or paste it into logs.
4. Configure the Services ID domain and return URL. The default callback is:
   `https://<public-host>/api/v1/auth/apple/callback`.
   If the registered URL differs, set `MYKHAYA_APPLE_REDIRECT_URI` to that
   exact HTTPS URL.
5. Configure Apple's private email relay for the sender addresses used by the
   deployment. Email delivery requires authenticated sender infrastructure
   (SPF, DKIM and the deployment's approved sender/return-path configuration).
   Private relay addresses are retained as provider metadata and must not be
   treated as account ownership keys.

## Environment variables

Set these only in the environment's secret/configuration store:

```text
MYKHAYA_APPLE_SIGN_IN_ENABLED=true
MYKHAYA_APPLE_SERVICE_ID=<environment Services ID>
MYKHAYA_APPLE_NATIVE_CLIENT_ID=<environment iOS App ID / client ID>
MYKHAYA_APPLE_TEAM_ID=<Team ID>
MYKHAYA_APPLE_KEY_ID=<Key ID>
MYKHAYA_APPLE_REDIRECT_URI=https://<public-host>/api/v1/auth/apple/callback
MYKHAYA_NATIVE_APPLE_RETURN_URI=<Android native return URI>
```

`MYKHAYA_PUBLIC_WEB_URL` must match the public origin used by the callback and
the browser redirects. `MYKHAYA_APPLE_SERVICE_ID` is the preferred web client
identifier. `MYKHAYA_APPLE_CLIENT_ID` remains a backward-compatible fallback
when the Services ID is unset; do not configure both as competing web clients.
`MYKHAYA_APPLE_NATIVE_CLIENT_ID` is separate and is required for native iOS
Apple assertions.

The signing key must come from exactly one of these sources:

```text
# Backward-compatible environment source; actual multiline PEM contents.
MYKHAYA_APPLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----"

# Preferred file source; the API reads the PEM contents, never returns the path
# contents, and never serializes the key.
MYKHAYA_APPLE_PRIVATE_KEY_FILE=/run/secrets/mykhaya-apple/apple-sign-in.p8
```

The file must be an unencrypted PKCS#8 PEM containing an EC P-256 private key.
Literal `\n` characters are not converted for this Apple setting; use real PEM
line breaks. The API rejects missing, unreadable, malformed, invalid or
conflicting key sources before Apple signing can be enabled. Apple remains
disabled by default when `MYKHAYA_APPLE_SIGN_IN_ENABLED` is unset or false.

## DEV file placement and Compose mount

The Compose API tier mounts the optional host directory
`${MYKHAYA_APPLE_KEY_HOST_DIR:-./secrets/apple}` read-only at
`/run/secrets/mykhaya-apple`. The directory may be absent when Apple is
disabled; Compose creates an empty directory for the optional mount and the API
does not read a key unless `MYKHAYA_APPLE_PRIVATE_KEY_FILE` is set.

For DEV, create the file on the deployment host, outside the repository when
possible:

```text
/etc/mykhaya/dev/apple/apple-sign-in.p8
```

Set the host-side Compose variable and API setting:

```dotenv
MYKHAYA_APPLE_KEY_HOST_DIR=/etc/mykhaya/dev/apple
MYKHAYA_APPLE_PRIVATE_KEY_FILE=/run/secrets/mykhaya-apple/apple-sign-in.p8
```

The host directory must be owned by the deployment account/root as appropriate,
with directory mode `0700` and key-file mode `0600`. The container must be able
to read the file using the API process UID; do not make the key world-readable
and do not place it in the image, repository, backup set, logs or web bundle.
The container mount is read-only, and the application container filesystem is
also read-only.

For the confirmed DEV registration, the values are:

```dotenv
MYKHAYA_APPLE_SERVICE_ID=app.mykhaya.auth.dev
MYKHAYA_APPLE_NATIVE_CLIENT_ID=app.mykhaya.mobile
MYKHAYA_APPLE_TEAM_ID=M86392YDLQ
MYKHAYA_APPLE_KEY_ID=JS8D8TTA92
MYKHAYA_APPLE_REDIRECT_URI=https://dev.mykhaya.app/api/v1/auth/apple/callback
MYKHAYA_NATIVE_APPLE_RETURN_URI=app.mykhaya.mobile://auth/callback
```

`MYKHAYA_APPLE_CLIENT_ID` may remain unset for this configuration because the
Services ID is present.

## Native callback separation

Browser Apple sign-in always uses the HTTPS callback above and a browser
session. Native flows use the existing platform-specific paths:

- iOS Apple uses the native AuthenticationServices assertion directly.
- Android Apple uses the HTTPS callback and then the configured native return
  URI (`MYKHAYA_NATIVE_APPLE_RETURN_URI`).

Set the return URI separately in each environment, for example
`mykhaya://auth/callback` for DEV iOS and
`app.mykhaya.mobile://auth/callback` for DEV Android. Production must use its
distinct registered schemes, such as `mykhaya-prod://auth/callback` and
`app.mykhaya.mobile.prod://auth/callback`.

The API records the native platform, environment and transaction together; it
does not infer the platform from the URI. A native app generates a fresh
high-entropy redemption verifier before starting authentication, keeps it in
memory, and never puts it in a callback URI. The API stores only its SHA-256
hash and requires the verifier for exchange, recovery and MFA redemption.
Transactions expire and are single-use. Losing the app's in-memory verifier
therefore fails safely without issuing a session.

## Troubleshooting and rollback

- A disabled or incomplete provider reports Apple as unavailable and leaves
  password sign-in usable.
- A callback mismatch means the exact callback URL is not registered for the
  same Services ID; correct Apple Developer configuration and restart the API
  deployment. A configuration change requires an API restart/redeploy, but no
  web rebuild or native app rebuild when native identifiers and URL schemes are
  unchanged.
- A cancelled, expired or failed flow is single-use and can be retried from
  the login or Security page.
- If Apple must be disabled, set `MYKHAYA_APPLE_SIGN_IN_ENABLED=false` and
  restart the affected environment. Existing linked identities and account
  data are preserved; disabling the provider does not unlink or delete them.

## Rotation and rollback

1. Place the replacement DEV `.p8` beside the current file with mode `0600`.
2. Validate it with the API configuration check before changing the active
   filename. Never print the key or copy it into `.env`.
3. Replace the file atomically on the host, preserving ownership and mode.
4. Restart the API and check `/api/v1/auth/providers`; a complete but disabled
   configuration reports `state: "disabled"`, while enabled configuration
   reports `state: "enabled"`.
5. Exercise a disposable DEV Apple flow and monitor only safe status/error
   diagnostics.

To roll back, restore the previous file atomically and restart the API. If the
provider must be stopped immediately, set
`MYKHAYA_APPLE_SIGN_IN_ENABLED=false` and restart; existing identities remain
untouched. Remove retired key files only after the replacement has been
verified and any operational retention requirement is satisfied.
