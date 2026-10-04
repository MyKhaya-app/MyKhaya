# Deployment Model

## Local development

Docker Compose runs Caddy, web, API, PostgreSQL, Redis, worker, scheduler and Mailpit with hot reload where appropriate.

### Trusted-proxy boundary

The API only trusts `X-Forwarded-For`/`X-Forwarded-Proto` (`mykhaya.security.resolve_client_ip`/`resolve_forwarded_proto`) when the immediate socket peer is inside `MYKHAYA_TRUSTED_PROXY_CIDRS` — that peer is always Caddy, since only Caddy publishes a host port and `api`/`web` are otherwise unreachable from outside the Compose network. For both local workflows (`compose.override.yml`/`compose.override.yml.example` for the plain workstation flow, `compose.dev.yml` for the persistent dev server), this is a **pinned `/32` address**, not the `edge`/`app` network's subnet:

- The `edge`/`app` networks are given a fixed, explicit `ipam.config.subnet` (`10.77.0.0/24`/`10.77.1.0/24`) purely so Caddy can be given a static, known-in-advance address (`10.77.0.250`/`10.77.1.250`) on each — without this, Docker's auto-assigned subnet is whatever its default address-pool happens to allocate that day, which is not guaranteed to land in any particular range and is not something a fresh checkout can predict in advance.
- **Trusting the whole subnet was tried and rejected.** `edge` is deliberately non-internal (api/worker/scheduler need it for outbound SMTP/Web Push/APNs/FCM/OIDC traffic), so it has a real gateway — and that gateway address is what Docker's own NAT makes *every* host-published-port request appear to originate from. A trust boundary keyed on the whole `/24` would treat that gateway as just another trusted hop in the `X-Forwarded-For` chain and let a forged header from an ordinary external request walk straight past it to an attacker-supplied value — confirmed live with a forged `X-Forwarded-For`/`X-Forwarded-Proto` request before switching to the current `/32`-per-container form, which excludes the gateway by construction.
- Both networks' addresses are trusted, not only the one Caddy's connection to `api` is currently observed to use (`edge`), because which of a multi-homed container's networks Docker's embedded DNS/routing picks for an outbound connection is an implementation detail of container attach order, not a documented contract.
- `data` is never pinned or trusted here — it never carries the Caddy→api hop this boundary is about.

Production (`compose.production.yml`) is unaffected by any of this — it inherits `compose.yml`'s unpinned network definitions and sets its own `MYKHAYA_TRUSTED_PROXY_CIDRS`/`MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS` from the host's real NetBird-facing addresses after live validation (see that file's own comments); the two environments' Docker networks are never shared or compared.

## Home test server

Use production-like containers, persistent database volumes, non-default secrets, internal-only database and Redis networks, automated backups and local-network access controls.

## VPS

Use the same images behind Caddy. Only Caddy exposes public ports. Add TLS, Cloudflare where chosen, host firewalling, off-host encrypted backups, monitoring and staged upgrades.

For private alpha testing PostgreSQL may remain containerised. Before broad public use, managed PostgreSQL with point-in-time recovery is preferred where affordable.

## Hosted domains

Caddy terminates TLS and routes `mykhaya.app`, `admin.mykhaya.app` and `status.mykhaya.app`. The API and data services remain internal. Admin source networks are enforced in FastAPI after trusted-proxy-aware client resolution and should also be restricted at the VPN, identity-aware gateway or firewall. The first status version shares the application stack; independent static/edge hosting is required for stronger failure independence.
