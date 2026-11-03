# Authentication Architecture

## Product activity and authentication timestamps

`User.last_login_at` records session establishment. `Session.last_seen_at` and
trusted-device timestamps describe authentication/session use. They are not
product activity signals.

`User.last_activity_at` is the product-level Last Active value. It is advanced
only by the authenticated, content-free `POST /api/v1/activity/heartbeat`
endpoint, using server time and the central five-minute throttle. Ordinary
authenticated API reads, bootstrap, polling, token renewal, push registration,
and background jobs do not advance it. The consumer app sends heartbeats only
while authenticated and foreground/visible, using the shared browser
visibility and Capacitor app-state lifecycle handling.

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
never linked from an email match alone. An unlinked Apple callback creates a
short-lived, single-use recovery transaction containing verified provider
metadata only; the browser must explicitly choose existing-account linking or
new registration before a `User` row is created.

Database ownership, provider-subject lookup, metadata refresh, linking,
concurrency conflict handling and safe unlinking live in the provider-neutral
`mykhaya.external_identities` service. Provider boundaries supply only a
verified stable subject and provider metadata. Unlinking refuses to remove a
user's final usable password, passkey or external identity. Apple retains its
own OAuth state, nonce, code exchange, JWT validation and recovery-transaction
storage; a future Google ceremony can use the same identity service without
introducing a second account-linking policy.

Phase 3 exposes Apple web sign-in, explicit recovery choices and authenticated
Sign-in Methods management. Phase 4 adds Google web sign-in through the same
provider-neutral identity, recovery, legal-consent, MFA and session-completion
boundaries. The
deployment-only `MYKHAYA_APPLE_*` and `MYKHAYA_GOOGLE_*` settings use secret
typed fields where applicable; no provider secret is stored in
`platform_settings` or returned by an API. The provider-status routes and PCC
Authentication & Security view do not expose provider secrets. Apple is enabled
only when its deployment configuration is complete and the server-side
ceremony is explicitly enabled; Google is enabled only when its deployment
configuration is complete and explicitly enabled.
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
and Platform Control Centre MFA are separate flows. Browser passkey login uses
the same completion seam as password and Apple login: when browser MFA is
required, a passkey establishes pre-authentication but does not silently bypass
the configured second-factor policy. Browser trusted-device renewal is blocked
and the device revoked when a required browser MFA policy becomes active, so a
previously issued renewal credential cannot bypass the new policy.
