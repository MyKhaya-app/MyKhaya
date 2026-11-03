# Apple Sign-In Web Configuration

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
MYKHAYA_APPLE_TEAM_ID=<Team ID>
MYKHAYA_APPLE_KEY_ID=<Key ID>
MYKHAYA_APPLE_PRIVATE_KEY=<secret .p8 contents>
MYKHAYA_APPLE_REDIRECT_URI=https://<public-host>/api/v1/auth/apple/callback
```

`MYKHAYA_PUBLIC_WEB_URL` must match the public origin used by the callback and
the browser redirects. The client ID fallback is retained for deployments that
already use `MYKHAYA_APPLE_CLIENT_ID`, but a web Services ID is preferred.

## Troubleshooting and rollback

- A disabled or incomplete provider reports Apple as unavailable and leaves
  password sign-in usable.
- A callback mismatch means the exact callback URL is not registered for the
  same Services ID; correct Apple Developer configuration and restart the
  deployment.
- A cancelled, expired or failed flow is single-use and can be retried from
  the login or Security page.
- If Apple must be disabled, set `MYKHAYA_APPLE_SIGN_IN_ENABLED=false` and
  restart the affected environment. Existing linked identities and account
  data are preserved; disabling the provider does not unlink or delete them.
