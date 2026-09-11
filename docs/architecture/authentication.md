# Authentication Architecture

Initial authentication supports registration, email verification, sign-in, sign-out, refresh or server session rotation, password reset, session listing and per-device revocation.

Email verification is controlled by `MYKHAYA_EMAIL_VERIFICATION_ENABLED` and defaults
to enabled. Disabling it skips verification-token delivery, marks newly registered
accounts as verified, and permits existing unverified accounts to sign in. This is
intended for local development; deployments that rely on email identity must keep it
enabled.

Browser authentication uses Secure, HttpOnly, appropriately scoped cookies and CSRF protection where required. Mobile clients use secure platform storage.

Reusable tokens are high entropy, expiring, revocable and stored only as hashes. Account status and Home membership are checked server-side for protected operations rather than trusted solely from long-lived token claims.

Platform administration does not use this session. It has separate identities, `mk_admin_*` host-only cookies, idle and absolute deadlines, recent-auth state, revocation and mandatory-MFA enforcement as documented in `administrative-authentication.md`.

The provider-neutral identity foundation stores optional Apple and Google
identities in `external_identities`. The stable key is `(provider,
provider_subject)`; provider email is nullable metadata only, so Apple private
relay addresses are supported without using email for implicit account linking.
The table is additive. Apple sign-in and authenticated Apple linking use the
existing browser session issuer; native bearer, managed-child and
platform-administrator authentication remain separate. Apple identities are
never linked from an email match alone.

Phase 2/3 currently exposes only centralized provider configuration health. The
deployment-only `MYKHAYA_APPLE_*` and `MYKHAYA_GOOGLE_*` settings use secret
typed fields where applicable; no provider secret is stored in
`platform_settings` or returned by an API. The provider-status routes and PCC
Authentication & Security view do not expose provider secrets. Apple is enabled
only when its deployment configuration is complete and the server-side
ceremony is explicitly enabled; Google remains framework/configuration-only.
The default Apple callback is
`{MYKHAYA_PUBLIC_WEB_URL}/api/v1/auth/apple/callback`; deployments may set
`MYKHAYA_APPLE_REDIRECT_URI` when their registered Apple Service ID uses a
different canonical public origin. That exact URI must be registered in Apple
Developer.

Consumer browser MFA uses the existing Phase 4.5 pre-auth handoff when
`MYKHAYA_BROWSER_MFA_HANDOFF_ENABLED=true`; the setting remains false by
default. Phase 5A supports only authenticator-app TOTP and verified-account
email codes. TOTP secrets are encrypted with the application secret using a
purpose-specific HKDF/Fernet key, while email challenge codes are stored only
as keyed hashes in short-lived, single-use database records. Both methods
complete by consuming the pre-auth transaction and issuing the ordinary
opaque browser session. Native bearer sessions, managed-child authentication,
and Platform Control Centre MFA are separate flows.
