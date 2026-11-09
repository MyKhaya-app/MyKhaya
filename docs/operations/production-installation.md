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
   and restrict `.env` to the deployment user (`chmod 600`). This `.env` is the
   single mutable deployment configuration; do not edit tracked Compose files.
8. Replace every placeholder, especially `MYKHAYA_ADMIN_ALLOWED_NETWORKS`,
   `MYKHAYA_TRUSTED_PROXY_CIDRS`, and `MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS`.
9. Configure NetBird and Cloudflare manually using the approved ingress runbook.
10. Run `make prod-config`.
11. Run `make prod-install`.
12. Bootstrap the first PCC owner once with `MYKHAYA_ADMIN_BOOTSTRAP_ENABLED=true`,
    enrol MFA, then disable the flag.
13. Run `make prod-health`, test email/push/Stripe, and perform a backup/restore
    rehearsal before accepting traffic.

See [Deployment configuration ownership](../architecture/deployment-configuration.md)
for the configuration inventory, PCC precedence rules, and migration procedure
for installations that previously edited `compose.production.yml` locally.

## BETA promotion readiness

This section is an acceptance gate for promoting the validated DEV release to
PROD. It does not replace the supported `make prod-config`, `make prod-install`,
and `make prod-update` commands, and it must be completed by an operator on the
separately hosted PROD server. This repository has not inspected that host.

### Required production configuration

Before enabling traffic, verify the production `.env` contains approved values
for the public/admin/API URLs, CORS and trusted hosts, exact Cloudflare/NetBird
and Caddy trusted CIDRs, secure cookies, SMTP, backup encryption recipients,
field-encryption settings, and `MYKHAYA_ADMIN_MFA_REQUIRED=true` with bootstrap
disabled after the first owner is enrolled. Provider-specific requirements are:

- Apple: a PROD Services ID/client identity, team/key metadata, private-key file
  supplied outside Git, the exact HTTPS callback, and the distinct native return
  URI. Do not reuse DEV registrations or keys.
- Google: a PROD web and native client identity, client secret supplied outside
  Git, the exact HTTPS callback, and the distinct native return URI.
- APNs/FCM: production bundle/project identity and credentials, with FCM locked
  to `mykhaya-prod`; never place a service-account file in the repository.
- Stripe: live-mode key and webhook signing secret only when the billing flags are
  deliberately enabled; verify webhook IP controls and acquisition policy first.

The tracked `.env.production.example` is a schema/example only. Blank values and
placeholders in it are intentional and must be replaced only on the PROD host.

### Read-only operator verification

Run from the approved release checkout on PROD. These checks deliberately report
presence, identity, status, or revision only; never print `.env`, private keys,
tokens, client secrets, webhook secrets, or full Compose configuration.

```sh
git branch --show-current
git rev-parse --verify HEAD
git status --porcelain
docker compose -f compose.yml -f compose.production.yml config --quiet
python3 infrastructure/scripts/validate_backend_config.py
docker compose -f compose.yml -f compose.production.yml ps
docker compose -f compose.yml -f compose.production.yml run --rm --no-deps migrate alembic current
docker compose -f compose.yml -f compose.production.yml run --rm --no-deps migrate alembic heads
```

For non-secret settings, report only whether a key is present and, where safe,
its boolean/host identity. Do not use `grep KEY .env` because it prints values.
For example:

```sh
for key in MYKHAYA_ENVIRONMENT MYKHAYA_PUBLIC_WEB_URL MYKHAYA_NATIVE_API_URL \
  MYKHAYA_APPLE_SIGN_IN_ENABLED MYKHAYA_APPLE_REDIRECT_URI \
  MYKHAYA_NATIVE_APPLE_RETURN_URI MYKHAYA_GOOGLE_SIGN_IN_ENABLED \
  MYKHAYA_GOOGLE_REDIRECT_URI MYKHAYA_NATIVE_GOOGLE_RETURN_URI \
  MYKHAYA_ADMIN_MFA_REQUIRED MYKHAYA_FCM_PROJECT_ID \
  MYKHAYA_APNS_BUNDLE_ID MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED; do
  if grep -q "^${key}=" .env; then echo "${key}=present"; else echo "${key}=MISSING"; fi
done
```

Also verify the configured backup marker and the last encrypted off-host backup
through the existing backup runbook, without displaying archive contents or
credentials. Check API, worker, scheduler, PostgreSQL and Redis health with
`make prod-health`; verify Cloudflare/NetBird/Caddy routing and trusted CIDRs at
the operator boundary. Provider sign-in, Stripe webhook delivery, APNs/FCM
delivery, and restore readiness require controlled operator tests; they cannot be
proven by this checkout.

### Database, recovery, and rollback gates

The release includes migrations through Alembic head `0124_legal_evidence_provider_msg`.
Record the current revision and heads before applying anything, complete an
encrypted off-host backup and restore rehearsal, then use only the supported
tagged-release update command. Do not run ad-hoc production Alembic downgrades.
Rollback is code-only for compatible schema changes; otherwise stop writes and
restore the verified PostgreSQL backup before redeploying the prior tag. Existing
legal evidence, subscription, onboarding, and provider-link data must be included
in the restore rehearsal.

### Explicit release decision

PROD is **GO** only when the release tag/SHA, clean checkout, one Alembic head,
backup marker and restore evidence, provider callbacks, live Stripe mode, health
checks, trusted ingress, and every administrator's MFA enrollment are recorded.
It is **NO-GO** for any missing secret/configuration, callback mismatch, pending
unreviewed migration, unverified backup, password-only PCC access, failed health
check, or unaccepted native device.

For mobile BETA acceptance, separately verify the PROD iOS bundle/signing/App
Group/push configuration and TestFlight physical-device flow, and the Android
PROD application ID, Firebase project, upload signing identity, Play Internal
Testing artifact, FCM delivery, and physical-device flow. These are external
acceptance gates and are not implied by local shell tests or source inspection.

## Updates and rollback

Create `/var/lib/mykhaya/last-backup.ok` only after an encrypted off-host backup has
been verified. Then run `make prod-update RELEASE=vX.Y.Z` for the approved
GitHub release tag.

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
