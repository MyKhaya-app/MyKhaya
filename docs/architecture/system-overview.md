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
