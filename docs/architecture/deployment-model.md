# Deployment Model

## Local development

Docker Compose runs Caddy, web, API, PostgreSQL, Redis, worker, scheduler and Mailpit with hot reload where appropriate.

## Home test server

Use production-like containers, persistent database volumes, non-default secrets, internal-only database and Redis networks, automated backups and local-network access controls.

## VPS

Use the same images behind Caddy. Only Caddy exposes public ports. Add TLS, Cloudflare where chosen, host firewalling, off-host encrypted backups, monitoring and staged upgrades.

For private alpha testing PostgreSQL may remain containerised. Before broad public use, managed PostgreSQL with point-in-time recovery is preferred where affordable.

## Hosted domains

Caddy terminates TLS and routes `mykhaya.app`, `admin.mykhaya.app` and `status.mykhaya.app`. The API and data services remain internal. Admin source networks are enforced in FastAPI after trusted-proxy-aware client resolution and should also be restricted at the VPN, identity-aware gateway or firewall. The first status version shares the application stack; independent static/edge hosting is required for stronger failure independence.
