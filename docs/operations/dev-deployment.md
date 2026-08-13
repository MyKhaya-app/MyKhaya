# Persistent Development Deployment

This is the supported deployment path for the long-running, shared `dev` server — not
your own machine; see [`local-development.md`](local-development.md) for that. It uses
`compose.yml` as the shared base and the tracked `compose.dev.yml` overlay. It does not
use `compose.override.yml`. PostgreSQL and Redis remain on Docker-internal networks,
Mailpit binds only to loopback, and Caddy exposes one configurable HTTP origin for an
external HTTPS reverse proxy.

## First installation

Requirements are Git, GNU Make, Docker Engine with Docker Compose v2, Python 3, and
either `curl` or `wget`.

```sh
git clone --branch dev https://github.com/MyKhaya-app/MyKhaya.git
cd MyKhaya
cp .env.dev.example .env
nano .env
make dev-up
```

Replace every `CHANGE_ME` value with an independently generated secret. Restrict
`MYKHAYA_ADMIN_ALLOWED_NETWORKS` to the operator NetBird addresses that may use the
Control Centre, preferably explicit `/32` entries. Set
`MYKHAYA_DEV_PROXY_TRUSTED_CIDRS` to the exact NetBird Proxy peer `/32` where possible.
The broader `100.64.0.0/10` examples are functional defaults, not the preferred final
allow-list.

`make dev-up` validates the host, builds all images without stopping a running stack,
starts and checks the private data services, runs Alembic migrations, replaces the app
services, prints container status, and verifies liveness and readiness. The public URLs
are HTTPS, so secure cookies remain enabled even though NetBird Proxy connects to Caddy
over HTTP.

## DNS and NetBird Proxy

Create or delegate these names to NetBird Proxy:

- `dev.mykhaya.app`
- `admin.dev.mykhaya.app`
- `status.dev.mykhaya.app`

Configure three HTTPS proxy routes and preserve the incoming `Host` header:

```text
dev.mykhaya.app        -> http://SERVER_NETBIRD_IP:8089
admin.dev.mykhaya.app  -> http://SERVER_NETBIRD_IP:8089
status.dev.mykhaya.app -> http://SERVER_NETBIRD_IP:8089
```

The host port defaults to `8089` (`MYKHAYA_DEV_HOST_PORT`, set in `compose.dev.yml`) —
changed from Caddy's usual `8080` because another app already uses `8080` on this
machine. Change `MYKHAYA_DEV_HOST_PORT` again (and update the NetBird routes above to
match) if `8089` is ever unavailable too.
Keep `MYKHAYA_DEV_BIND_ADDRESS=0.0.0.0`, or bind to the server's specific NetBird IP.
Do not expose this HTTP port to the public internet; allow it only over NetBird or the
host firewall.

The tracked development Caddyfile accepts only the three development hosts plus
`localhost`/`127.0.0.1`. Caddy trusts incoming forwarded client information only from
`MYKHAYA_DEV_PROXY_TRUSTED_CIDRS`, replaces rather than blindly passes the upstream
forwarding headers, preserves `Host`, and tells the application that public requests
used HTTPS. The API independently trusts forwarding only from its private Docker proxy
network.

## Updating

Maintain a current, verified backup as described below. The complete update command is:

```sh
make dev-update
```

The command requires the local `dev` branch and a clean working tree, apart from ignored
local `.env` secret files. It fetches `origin/dev`, fast-forwards only, reports settings
that were added to `.env.dev.example`, builds images, runs migrations, starts the updated
services, and performs health checks. It never invokes `docker compose down -v`, deletes
a volume, or requires local edits to tracked deployment files.

If a newly required setting is reported, compare `.env.dev.example` with `.env`, add the
setting, and rerun `make dev-update`. A non-fast-forward update stops before deployment
and must be investigated rather than merged on the server.

## Logs and health checks

```sh
make dev-logs
make dev-health
docker compose -f compose.yml -f compose.dev.yml ps
```

Direct server checks intentionally use the `localhost` Caddy site:

```sh
curl -fsS http://127.0.0.1:8089/api/v1/health/live
curl -fsS http://127.0.0.1:8089/api/v1/health/ready
curl -fsS http://127.0.0.1:8089/api/v1/health/build
```

Mailpit is available only on the server at `http://127.0.0.1:8025` by default. Use an
SSH or NetBird tunnel if remote operator access is necessary; do not bind it publicly.

## Backups

Run `make backup`, verify the resulting gzip file, and copy it off-host using encrypted
transport and storage. A backup is only dependable after a documented restore test; see
`docs/operations/backup-and-restore.md`. PostgreSQL is authoritative. Redis is disposable
coordination state and is not a database backup.

## Failure behavior and rollback

Image builds complete before any currently running container is replaced. If a build
fails, the old stack continues to run. Migrations run before new API, worker, scheduler,
or web containers are started. If a migration fails, rollout stops and the previous app
containers remain in place. Alembic and PostgreSQL normally make each migration
transactional, but an unsuccessful migration still requires inspection: check the
`migrate` output, the Alembic revision, and database health before retrying.

The update command prints the previous commit as its rollback reference. For a
code-only rollback where the migrated schema is backward-compatible:

```sh
git switch --detach PREVIOUS_COMMIT
MYKHAYA_DEV_ALLOW_NON_DEV_BRANCH=1 make dev-up
```

After the incident, return the checkout to the supported update path with `git switch
dev`. Do not run an Alembic downgrade against live data merely to force old code to work.
If the new schema is not backward-compatible, stop writes and restore the verified
pre-update PostgreSQL backup, then deploy the previous commit. This is why backups must
precede schema-changing updates.

`make dev-down` uses `docker compose stop`; it does not remove containers, networks, or
persistent volumes.

## Troubleshooting

- **Missing `.env` or variables:** copy `.env.dev.example`, preserve existing secrets,
  and add the reported keys. Never commit `.env`.
- **Invalid JSON:** JSON list settings must use double-quoted strings, for example
  `["100.64.0.10/32"]`.
- **Occupied port:** change `MYKHAYA_DEV_HOST_PORT` or
  `MYKHAYA_DEV_MAILPIT_PORT`, or stop the unrelated listener. Preflight recognises ports
  already owned by this Compose project.
- **Docker unavailable:** start Docker Engine and confirm `docker info` and `docker
  compose version` work for the deployment account.
- **Wrong branch or dirty deployment files:** return to `dev` and restore tracked files
  from Git. Keep server-specific changes only in `.env`.
- **502 or failed readiness:** run `make dev-logs`, then inspect `api`, `web`, `postgres`,
  `redis`, and `caddy` health. Readiness requires both PostgreSQL and Redis.
- **Wrong site routing:** confirm NetBird preserves the original `Host` value and uses
  the exact domain-to-origin mappings above.
- **Control Centre returns 404:** confirm the client address forwarded through NetBird
  is included in `MYKHAYA_ADMIN_ALLOWED_NETWORKS`. A 404 is the deliberate network
  boundary response.

## Creating the initial Platform Admin account

`MYKHAYA_ADMIN_BOOTSTRAP_ENABLED` gates a one-shot CLI that creates the first
`platform_owner` account. Leave it unset (or `false`) once the account exists — the flag
is a bootstrap door, not a standing config value. Run it against the running `api`
service after migrations have completed:

```sh
docker compose -f compose.yml -f compose.dev.yml run --rm --no-deps \
  -e MYKHAYA_ADMIN_BOOTSTRAP_ENABLED=true \
  api python -m mykhaya.bootstrap_platform_owner \
  --email you@example.com \
  --display-name "Your Name"
```

The command prints a one-time credential/enrolment step for MFA, which is required
before the account can sign in (`MYKHAYA_ADMIN_MFA_REQUIRED` is enforced). Complete MFA
enrolment at `https://admin.dev.mykhaya.app/login` immediately afterwards.

## Confirming the deployed version

`GET /api/v1/health/build` (unauthenticated, `include_in_schema=False`) returns
`version`, `commit`, `build_time`, `environment`, and `channel` sourced from
`MYKHAYA_VERSION`, `MYKHAYA_COMMIT_SHA`, `MYKHAYA_BUILD_TIME`, and
`MYKHAYA_BUILD_CHANNEL` (or the `VERSION` file baked into the image if unset):

```sh
curl -fsS http://127.0.0.1:8089/api/v1/health/build
```

The same version/channel (plus commit and build time outside production) is already
surfaced without any extra tooling on the Control Centre Overview page
(`https://admin.dev.mykhaya.app/`) — that is the fastest way to confirm what an update
actually deployed.

## Email delivery

The Control Centre **Email** page (`https://admin.dev.mykhaya.app/mail`) reports whether
SMTP is configured, its source (`environment` or `platform_admin`), outbound queue depth,
last successful delivery, and recent failures, and offers a rate-limited "send a test
email" action. See `docs/architecture/platform-control-centre.md` for how Platform Admin
SMTP settings relate to `MYKHAYA_SMTP_*` env vars (env vars always win when set). In dev,
Mailpit (`http://127.0.0.1:8025`, tunnel over SSH/NetBird — do not expose publicly) is the
usual way to see mail land without a real external provider.

## Worker and scheduler health

`make dev-health` / `infrastructure/scripts/dev-deploy.sh health` already checks the
`worker` and `scheduler` containers are running (via `wait_healthy`, falling back to
container status since these services have no Docker `HEALTHCHECK` of their own) in
addition to the `/health/live` and `/health/ready` HTTP checks — there is no separate
worker/scheduler check to remember to run.

## api, worker, scheduler and migrate are four separate images built from one Dockerfile

`compose.yml` defines `worker` and `scheduler` as YAML-anchor copies of the `api`
service (`<<: *api`), and `migrate` builds from the same `apps/api/Dockerfile` with a
different command. All four always build from the exact same source, but are four
**separate** Docker images (`mykhaya-api`, `mykhaya-worker`, `mykhaya-scheduler`,
`mykhaya-migrate`) with independent build caches — rebuilding one does not rebuild the
others. A manual `docker compose build api` (or `docker build ... --target builder`)
only refreshes `mykhaya-api`; the other three silently keep running the old code/schema
expectations with no error. This has caused two separate incidents: a new
`mykhaya/notifications/*.py` module briefly missing from a running scheduler
(Communications Stage 5), and a scheduler crash-looping against a schema `migrate`
hadn't actually been rebuilt to apply (Communications Stage 8, where `migrate` was the
one forgotten out of four).

**Always use `make backend-rebuild`** for any backend code change — it rebuilds and
recreates `api`, `worker`, `scheduler`, and `migrate` together in one command, so
nobody has to remember which services share images. It does not run migrations itself
(whether a new migration needs applying is a separate, explicit decision — run `make
migrate` after, or use `make dev-up`/`make dev-update` for the persistent server, which
build all four *and* run migrations *and* do a full health-check sequence). Never
rebuild `api` — or any subset of the four — individually when backend code changed.

## Automated tests use an isolated database

The automated backend test suite (`make test`/`lint`/`typecheck`/`format`, via
`infrastructure/scripts/run-tests.sh`) runs against `postgres-test`/`redis-test` —
dedicated, tmpfs-backed, disposable services defined in `compose.test.yml` — never
against the persistent `postgres`/`redis` the dev stack uses. Each run brings the
isolated pair up, applies migrations to it, runs the requested command with
`--no-deps` (so the persistent `postgres`/`redis`/`migrate` are never touched or even
started), and tears the isolated pair back down on exit, success or failure.

This replaced an earlier setup where `test` shared the dev stack's `postgres`/`redis`
directly. That caused repeated live contamination: rate-limit keys exhausted mid-run,
`platform_smtp_settings`/`platform_push_settings` wiped by test cleanup fixtures,
and — most seriously — thousands of test-generated user accounts accumulating in the
dev database, some with real preferences (e.g. `daily_briefing_enabled=true`) that
caused the live scheduler to generate real notifications for accounts nobody would
ever read. Isolating the test database at the infrastructure level closes all of
these at once, permanently, rather than requiring every new test file to remember to
clean up after itself. Do not point `MYKHAYA_DATABASE_URL`/`MYKHAYA_REDIS_URL` for the
`test` service back at `postgres`/`redis`, and do not add application-code cleanup
(e.g. deleting `@example.com` users) as a substitute for this isolation.

The automated suite's own login/register volume grew with Phase 3's Stripe billing
tests (each does a full register/verify/login/create-Home round trip); `MYKHAYA_RATE_LIMIT_LOGIN`/
`MYKHAYA_RATE_LIMIT_REGISTER` for the `test` service were raised from 100/300 to
1000/1000 accordingly — see the field comments on `rate_limit_login`/`rate_limit_register`
in `mykhaya/config.py`, which already anticipated this. If the full suite starts
returning 429s from `/auth/login` again, this is the first thing to check.

## Stripe sandbox (Phase 3)

Stripe billing is entirely optional and off by default (`MYKHAYA_STRIPE_BILLING_CONFIGURED=false`)
— Free and Complimentary Homes need no Stripe setup at all. This section is only for
actually exercising Checkout/Portal/webhooks locally.

### One-time setup (Stripe test-mode account)

1. Create or use an existing Stripe account, switch to **test mode** (toggle in the
   Stripe Dashboard).
2. Create one Product ("MyKhaya Family") with two recurring Prices: monthly and
   annual, in GBP. Copy both Price IDs (`price_...`).
3. Copy the test-mode secret key (`sk_test_...`) from
   `dashboard.stripe.com/test/apikeys`. Never copy the live-mode key for local
   development — `Settings.validate_stripe_configuration` rejects a live key
   outside `MYKHAYA_ENVIRONMENT=production` anyway, but don't rely on that as the
   only safeguard.
4. Set in `.env` (never commit real values — `.env` is gitignored):
   ```
   MYKHAYA_STRIPE_BILLING_CONFIGURED=true
   MYKHAYA_STRIPE_SECRET_KEY=sk_test_...
   MYKHAYA_STRIPE_FAMILY_MONTHLY_PRICE_ID=price_...
   MYKHAYA_STRIPE_FAMILY_ANNUAL_PRICE_ID=price_...
   MYKHAYA_STRIPE_PUBLISHABLE_KEY=pk_test_...   # only if a future phase needs it client-side
   ```
5. `MYKHAYA_STRIPE_WEBHOOK_SECRET` comes from the Stripe CLI, not the Dashboard, for
   local development — see below.

### Local webhook forwarding (Stripe CLI)

Stripe cannot reach a developer's machine directly, so local verification uses the
[Stripe CLI](https://stripe.com/docs/stripe-cli) to forward test-mode events:

```
stripe login
stripe listen --forward-to localhost:8089/api/v1/billing/stripe/webhook
```

The CLI prints a webhook signing secret (`whsec_...`) each time it starts — put that
in `MYKHAYA_STRIPE_WEBHOOK_SECRET` and restart `api`. This secret is ephemeral to the
CLI session; do not treat it as a stable value, and never commit it. A production
deployment instead registers a webhook endpoint in the Stripe Dashboard and uses
*that* endpoint's own permanent signing secret.

With `stripe listen` running, trigger individual test events without a real Checkout:

```
stripe trigger customer.subscription.created
stripe trigger invoice.payment_failed
```

or drive the full flow through the actual UI — `/settings/billing` on the household
app starts a real test-mode Checkout Session; Stripe's documented test card
`4242 4242 4242 4242` (any future expiry, any CVC) completes it.

Do not assume every deployment runs the Stripe CLI — it's a local-development
convenience only; production uses a registered webhook endpoint as above.

### Going live (not performed in Phase 3)

Phase 3 is test-mode only; do not switch to live mode as part of this phase. When a
later phase does:

1. Create the equivalent live-mode Product/Prices in the Stripe Dashboard (live and
   test mode have entirely separate catalogues — a test Price ID is never valid in
   live mode and vice versa).
2. Register a permanent webhook endpoint in the live Dashboard pointing at the
   production `/api/v1/billing/stripe/webhook` URL, and copy its signing secret.
3. Set `MYKHAYA_ENVIRONMENT=production`, `MYKHAYA_STRIPE_SECRET_KEY=sk_live_...`, the
   live Price IDs, and the live webhook secret — all as real deployment secrets, never
   committed. `Settings.validate_stripe_configuration` requires a live key when
   `MYKHAYA_ENVIRONMENT=production` and rejects a test key there, so a stale test key
   left in production configuration fails startup rather than silently taking no
   payments.
4. Rotate the webhook secret by registering a second endpoint alongside the first,
   confirming events arrive successfully, then removing the old endpoint — Stripe
   supports multiple simultaneous webhook endpoints for exactly this overlap.
5. Verify the full lifecycle (Checkout → activation → renewal → cancellation) against
   a real card in live mode before announcing billing is live — none of Phase 3's
   verification substitutes for this.
