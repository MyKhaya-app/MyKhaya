# Google Sign-In Web Configuration

Configure Google separately for each MyKhaya environment. Never reuse DEV
client credentials, redirect URIs or secrets in PROD.

## Google Cloud Console

1. Create or select the environment's Google Cloud project.
2. Configure the OAuth consent screen, application name, support contact,
   authorised domains and privacy-policy/terms links required by Google.
3. Create a **Web application** OAuth client. Add the exact public origin to
   authorised JavaScript origins where the deployment requires it.
4. Add this exact authorised redirect URI:
   `https://<public-host>/api/v1/auth/google/callback`
5. Store the client secret in the deployment secret manager. It must never be
   committed, returned by PCC/API responses or logged.

## Environment variables

```text
MYKHAYA_GOOGLE_SIGN_IN_ENABLED=true
MYKHAYA_GOOGLE_CLIENT_ID=<web-client-id>
MYKHAYA_GOOGLE_CLIENT_SECRET=<secret>
MYKHAYA_GOOGLE_REDIRECT_URI=https://<public-host>/api/v1/auth/google/callback
```

`MYKHAYA_PUBLIC_WEB_URL` must match the public browser origin. The service
uses Google's OIDC issuer, token endpoint and JWKS endpoint by default. These
endpoints are deployment configuration overrides for testing only; production
must use Google's documented endpoints.

Google identity ownership is keyed only by the verified OIDC `sub` claim.
Email is verified and retained as provider metadata, but is never used for
automatic account linking or merging.

## Testing and rollback

Use synthetic accounts and a Google test project for local or DEV validation.
Do not use production accounts or credentials in local environments. A
cancelled, expired or replayed callback is single-use and must fail safely.

For live DEV verification, confirm the DEV origin, OAuth consent-screen test
user and exact DEV redirect URI first. Exercise sign-in, explicit recovery,
linking, MFA and disconnect with a synthetic DEV account, then verify the
resulting identity and session audit events in PCC. Record the client ID and
redirect URI used; do not reuse either in PROD.

## Troubleshooting

- A redirect mismatch means the Google Cloud Console URI does not exactly
  match `MYKHAYA_GOOGLE_REDIRECT_URI`, including scheme, host and path.
- A provider unavailable message means the feature is disabled or one of the
  required deployment settings is missing.
- Invalid, cancelled or expired callbacks are single-use; restart from the
  MyKhaya login page instead of reusing the callback URL.
- A linking conflict means the Google subject is already owned by another
  MyKhaya account. Do not merge or transfer it manually.

To disable the browser provider, set
`MYKHAYA_GOOGLE_SIGN_IN_ENABLED=false` and restart the affected deployment.
Existing linked identities and account data remain unchanged; disabling the
provider does not unlink or delete them.
