# Deployment configuration ownership

MyKhaya has one mutable deployment configuration per installation: the
untracked, permission-protected `.env` file at the repository root. Compose
files describe service topology, mounts, networks, health checks and security
invariants. They must not be edited on a server to change application policy.

## Sources and precedence

The effective configuration follows these rules:

1. **Security and topology invariants in Compose win.** Production always uses
   `MYKHAYA_ENVIRONMENT=production`, secure cookies and required administrator
   MFA. Only Caddy publishes the HTTP origin; data volumes and internal network
   boundaries remain Compose-owned.
2. **Installation-specific environment values come from `.env`.** Compose
   loads the same file into application services and uses it for Caddy domain
   and proxy substitutions. `.env` is not tracked, is not replaced by a tag
   checkout, and must be mode `600`.
3. **PCC operational settings win over their environment bootstrap defaults.**
   A stored `platform_settings` row is read on each request and is authoritative
   for signup, Beta/waitlist, registration limits, maintenance, DVLA enablement
   and other settings declared in `SETTINGS_SCHEMA`.
4. **Environment restrictions are deliberate hard ceilings.**
   `MYKHAYA_REGISTRATION_MODE=closed` disables registration; `invitation_only`
   narrows every open signup path to invitations; `open` leaves those choices to
   PCC. A PCC setting cannot make the application less restrictive than this
   deployment ceiling, and the PCC UI/API must not claim that a blocked value is
   effective.
5. **Protected secrets stay in `.env` or the approved secret store.** Database
   credentials, `MYKHAYA_SECRET_KEY`, SMTP/API keys, signing material and proxy
   trust CIDRs are never stored in PCC generic settings or tracked files.

The existing specialised precedence rules remain unchanged: enabled PCC SMTP
and stored Stripe settings use their documented ownership rules, while
environment-managed Push/Stripe/SMTP paths are explicit fallbacks or modes.
See `platform-control-centre.md` for those integration-specific rules.

## Configuration inventory

| Configuration | Owner/classification | Source | Notes |
| --- | --- | --- | --- |
| Compose services, networks, ports, volumes, health checks | Deployment structure | tracked Compose | Production overlay keeps only topology and security invariants. |
| `MYKHAYA_ENVIRONMENT`, secure cookies, admin MFA | Security invariant | production Compose | Cannot be relaxed by `.env`. |
| Domains, origins, trusted hosts/proxies, bind ports | Server-specific configuration | `.env` | Caddy and API consume the same installation values. |
| Database/Redis URLs and passwords, secret key, SMTP/API keys | Protected secret | `.env`/secret store | Never commit or place in PCC generic settings. |
| `MYKHAYA_REGISTRATION_MODE` | Bootstrap deployment ceiling | `.env` | `open` permits PCC control; `closed`/`invitation_only` intentionally restrict. |
| Signup, Beta, waitlist, maintenance and platform limits | Operational application setting | PCC database | PCC values are evaluated per request and survive image/tag updates. |
| Default locale/timezone/week start | Deployment default | `.env` | Locale/timezone PCC placeholders are not enforced today; no second source is introduced. |
| Release version, commit, build time/channel | Release process | `make prod-update RELEASE=...` | Exported from the exact tag before image build. |
| APNs/PCC-managed Push, SMTP and Stripe modes | Integration-specific | documented env/PCC precedence | Existing security and fallback behavior is retained. |

## Existing installation migration

Before checking out the first release containing this change, inspect the
currently effective production value. If the VPS has the local Compose edit
described in the incident, record that value (for example, `open`) and copy it
into the VPS `.env` before updating:

```sh
# Run this while the existing deployment checkout is still present.
docker compose -f compose.yml -f compose.production.yml config --format json \
  | grep -F 'MYKHAYA_REGISTRATION_MODE'
grep '^MYKHAYA_REGISTRATION_MODE=' .env || true
# Edit only the untracked .env if the intended value is missing or different.
chmod 600 .env
make prod-config
```

Do not copy the repository's example over an existing `.env`, and do not edit a
tracked Compose file. `make prod-config` must be run before the update so the
resolved startup configuration and signup ceiling are reviewed. The update
script still refuses a dirty tracked tree, checks the exact release tag and
keeps all persistent volumes. Git checkouts therefore leave the installation
configuration intact.

For the specific Beta-registration incident, `open` in `.env` allows PCC's
`registration_enabled`, `signup_mode` and `invite_only_mode` settings to govern
the flow. If a deployment-wide invitation requirement is intentionally wanted,
set `MYKHAYA_REGISTRATION_MODE=invitation_only` in `.env` and record that
decision; PCC cannot loosen it.

## Safe operational updates

1. Back up and verify the database before a production update.
2. Edit only the protected `.env` on the installation host; never edit tracked
   Compose files and never commit secrets.
3. Run `make prod-config` and review the resolved values without exposing
   secrets. For signup changes, verify `/public/signup-state` and the ordinary
   and Beta registration journeys before restarting application services.
4. Run `make prod-update RELEASE=vX.Y.Z`. The command checks a clean worktree,
   fetches and verifies the tag on `origin/main`, builds before migration, and
   never removes persistent volumes.
5. For rollback, use the previously approved release tag with the same `.env`.
   Restore the database backup first if the migration is not backward
   compatible; do not hand-edit Compose or improvise live Alembic downgrades.

