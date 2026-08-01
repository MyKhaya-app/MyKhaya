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
