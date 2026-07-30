# ADR 0006: Opaque Rotating Sessions

**Status:** Accepted

Browser authentication uses high-entropy opaque session tokens in `Secure`, `HttpOnly` cookies. Only a keyed hash is stored server-side. Sessions rotate after authentication and periodically, support per-device revocation, and are checked against current account and Home membership state. Unsafe cookie-authenticated requests require a matching double-submit CSRF token and an allowed origin. This avoids long-lived browser-readable credentials while preserving native-client evolution through a separate secure-storage flow.

