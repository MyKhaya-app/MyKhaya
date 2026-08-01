# System Overview

MyKhaya is a containerised modular monolith with separate web, API, worker and scheduler processes.

```text
Browser / Mobile
       |
Cloudflare later
       |
     Caddy
   /       \
Next.js   FastAPI
             |
      PostgreSQL + Redis
             |
       Worker / Scheduler
```

## Technology choices

- Web: Next.js and TypeScript
- Mobile: Expo and React Native
- API: FastAPI and Python
- Persistence: PostgreSQL
- Cache and coordination: Redis
- Jobs: durable worker queue
- Reverse proxy: Caddy
- Deployment: Docker Compose initially

The same production images must run on the home test server and VPS. Environment configuration changes; source architecture does not.

## Feature flag control plane

- Feature flags are stored centrally in the API database and default to disabled.
- Evaluation is server-side, with optional Home-level overrides for controlled rollout.
- User clients fetch Home feature availability from the API, so navigation and module access are driven by authoritative backend state.
- Platform operators manage global flags and Home overrides through privileged API endpoints that require confirmation and an audit reason.
- Unknown feature keys fail closed and are treated as disabled.
