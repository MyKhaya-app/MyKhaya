# Production Installation and Operations

This runbook is for a clean Ubuntu 24.04 UK VPS only. It must never be run from
the persistent development server. Production uses the tagged repository release,
the production Compose overlay, and the ingress chain:

```text
Cloudflare -> NetBird Proxy -> Caddy -> web/API
```

## Installation

1. Provision a new Ubuntu 24.04 VPS with encrypted storage where available.
2. Create a non-root deployment user and install its SSH key.
3. Disable SSH password authentication and direct root login.
4. Configure a host firewall allowing only SSH from the operator range and the
   NetBird/Caddy ingress path. PostgreSQL, Redis, worker, and scheduler ports are
   never public.
5. Install Docker Engine and Docker Compose v2.
6. Clone the approved release tag and verify the tag and commit.
7. Copy `.env.production.example` to `.env`, generate every secret independently,
   and restrict `.env` to the deployment user (`chmod 600`).
8. Replace every placeholder, especially `MYKHAYA_ADMIN_ALLOWED_NETWORKS`,
   `MYKHAYA_TRUSTED_PROXY_CIDRS`, and `MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS`.
9. Configure NetBird and Cloudflare manually using the approved ingress runbook.
10. Run `make prod-config`.
11. Run `make prod-install`.
12. Bootstrap the first PCC owner once with `MYKHAYA_ADMIN_BOOTSTRAP_ENABLED=true`,
    enrol MFA, then disable the flag.
13. Run `make prod-health`, test email/push/Stripe, and perform a backup/restore
    rehearsal before accepting traffic.

## Updates and rollback

Set `MYKHAYA_PRODUCTION=1`, `MYKHAYA_RELEASE_TAG` to the approved exact tag, and
create `/var/lib/mykhaya/last-backup.ok` only after an encrypted off-host backup has
been verified. Then run `make prod-update`.

The command refuses dirty trees, non-release commits, missing configuration, and
missing backup evidence. For a compatible code-only rollback, redeploy the previous
tag. For an incompatible migration, stop writes and restore the verified PostgreSQL
backup before redeploying the previous tag. Do not improvise live Alembic downgrades.

## Backups

`make prod-backup` creates a PostgreSQL dump, avatar archive, and deployment manifest.
Copy these artifacts to encrypted off-host UK storage using the approved storage
tool, then create the backup marker. Plaintext secrets must never be placed in the
archive. Keep `MYKHAYA_SECRET_KEY` in the separate disaster-recovery secret record;
it is required to decrypt database-managed credentials after restore.

## Host hardening

Use key-only SSH, automatic security updates, UTC time synchronisation, Docker log
rotation, disk/memory monitoring, root-owned backup directories, and regular reboot
verification. Do not mount the Docker socket into application containers. Retain
the existing non-root, capability-dropping, read-only application containers.

## Fallback ingress

If NetBird fails, preserve the Caddy configuration and expose only Caddy through a
replacement upstream. Validate the same Host, scheme, client-IP, PCC, and security
header tests before switching DNS or proxy routing. No application redesign should
be required.
