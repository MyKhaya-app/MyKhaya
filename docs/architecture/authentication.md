# Authentication Architecture

Initial authentication supports registration, email verification, sign-in, sign-out, refresh or server session rotation, password reset, session listing and per-device revocation.

Browser authentication uses Secure, HttpOnly, appropriately scoped cookies and CSRF protection where required. Mobile clients use secure platform storage.

Reusable tokens are high entropy, expiring, revocable and stored only as hashes. Account status and Home membership are checked server-side for protected operations rather than trusted solely from long-lived token claims.
