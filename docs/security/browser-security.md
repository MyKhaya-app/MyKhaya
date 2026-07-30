# Browser Security

Implement CSP, `frame-ancestors`, HSTS in HTTPS environments, MIME-sniffing protection, referrer policy, permissions policy, secure cookies, CSRF controls, strict CORS allow-lists, safe redirect validation and cache controls for authenticated responses.

Do not store authentication secrets in localStorage. Do not permanently allow broad CSP values such as `unsafe-inline`, `unsafe-eval` or wildcard origins to resolve implementation issues. Add automated header tests.
