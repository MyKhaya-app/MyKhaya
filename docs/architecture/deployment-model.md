# Deployment Model

## Local development

Docker Compose runs Caddy, web, API, PostgreSQL, Redis, worker, scheduler and Mailpit with hot reload where appropriate.

## Home test server

Use production-like containers, persistent database volumes, non-default secrets, internal-only database and Redis networks, automated backups and local-network access controls.

## VPS

Use the same images behind Caddy. Only Caddy exposes public ports. Add TLS, Cloudflare where chosen, host firewalling, off-host encrypted backups, monitoring and staged upgrades.

For private alpha testing PostgreSQL may remain containerised. Before broad public use, managed PostgreSQL with point-in-time recovery is preferred where affordable.
