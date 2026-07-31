# ADR 0008: Same-Origin Browser API and Explicit Proxy Trust

**Status:** Accepted

The browser calls `/api/v1` on the web origin. Caddy and the Next.js server route that path to FastAPI; `api.mykhaya.app` remains available for native and operational clients. Same-origin browser traffic simplifies cookie and CSRF boundaries without weakening API authorisation.

FastAPI trusts forwarded client information only from explicitly configured private proxy ranges. Cloudflare must not be enabled by accepting arbitrary forwarded headers: Caddy's trusted proxy ranges must first be pinned to Cloudflare's published networks and origin access must be restricted to Cloudflare plus operator access.
