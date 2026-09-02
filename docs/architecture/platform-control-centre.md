# Platform Control Centre

## Decision

The Control Centre is a management plane within the FastAPI/Next.js modular monolith, isolated by the `admin.mykhaya.app` hostname, `/api/v1/platform` API namespace, platform-only identities and roles, and `mk_admin_*` cookies. It is never mounted at `mykhaya.app/admin`.

Platform roles are independent of Home membership: Platform Owner, Platform Administrator, Support Operator, Security Operator and Read-only Operator. Every route declares allowed roles server-side. Household Owner and Administrator roles have no effect.

## Privacy boundary

The API exposes operational account and Home metadata only. It does not query or return calendar, list, task, note, plan, meal, poll, message, child-profile, location or uploaded content. There is no impersonation or general “browse user data” route.

Exceptional future content access requires a separate design: record scope, elevated permission, reason, recent authentication, expiry, permanent audit, visible banner and appropriate owner notification.

## Control state

- Implemented: hostname/network gates, isolated sessions, role authorization, recent-auth checks, confirmation/reason schemas, immutable application audit API, bounded metadata lists, suspension/session revocation, notes, health, jobs, a schema-driven administrator-facing operational settings UI (see "Platform settings" below) with a consumer-safe allow-listed config endpoint, global feature flags, security/audit views, incident management, and Platform-Admin-managed SMTP and Web Push (VAPID) configuration.
- Implemented feature controls: global and Home override management, role checks, recent authentication, explicit confirmation/reason and administrative audit events.
- Designed but incomplete: mandatory MFA ceremony, job manual retry and independent status hosting.
- Production blocker: no WebAuthn/passkey ceremony exists. Password-only production administration is not approved.

## SMTP configuration precedence

Outbound email transport has one authoritative operational source: the enabled
Platform-Admin stored configuration. Environment SMTP is retained only as an explicit
development/test fallback for isolated local runs:

1. **Platform Admin stored configuration** (`platform_smtp_settings` table, one row,
   password encrypted at rest — see `mykhaya.secrets_crypto`) — used when the stored row
   has `enabled=true` and always wins over environment SMTP.
2. **Development/test fallback** — when no enabled stored row exists and
   `MYKHAYA_EMAIL_DELIVERY_CONFIGURED=true`, environment settings may be used only when
   `MYKHAYA_ENVIRONMENT` is `development` or `test` (for example, Mailpit).
3. **Unconfigured** — neither an enabled stored row nor an allowed local fallback exists.
   Email-dependent journeys are
   blocked with a clear "email not configured" condition rather than failing silently.

The environment path supports the same three connection-security options as the stored
path (`MYKHAYA_SMTP_CONNECTION_SECURITY=none|starttls|tls`, `tls` being implicit TLS —
typically port 465), plus `MYKHAYA_SMTP_TIMEOUT_SECONDS` and `MYKHAYA_SMTP_REPLY_TO`. In
production, once `MYKHAYA_EMAIL_DELIVERY_CONFIGURED=true`, `Settings` refuses to start
with `MYKHAYA_SMTP_HOST`/`MYKHAYA_EMAIL_FROM` still pointed at this repo's
development-only defaults (Mailpit, `*.local`) — see
`docs/architecture/notification-engine.md` "Email".

The SMTP password is encrypted at rest with a Fernet key derived (HKDF-SHA256) from
`MYKHAYA_SECRET_KEY`; rotating that secret invalidates stored SMTP passwords the same way
it invalidates sessions, so it must be re-entered after a `SECRET_KEY` rotation. The
password is never returned by any API response; leaving the password field blank on
update retains the existing credential, and a separate "clear stored password" action
exists for explicit removal. Every settings change, credential replacement, disable, and
test-email attempt is written to the platform audit log without secret values.

## Push (VAPID) configuration precedence

Identical model to SMTP, using `MYKHAYA_PUSH_DELIVERY_CONFIGURED` as the explicit
env-managed switch (mirroring `MYKHAYA_EMAIL_DELIVERY_CONFIGURED`) rather than inferring
it from whether the VAPID key vars happen to be set:

1. **Environment variables** (`MYKHAYA_PUSH_DELIVERY_CONFIGURED=true`, with
   `MYKHAYA_VAPID_PUBLIC_KEY`/`MYKHAYA_VAPID_PRIVATE_KEY`/`MYKHAYA_VAPID_SUBJECT`) —
   always wins when set. The Platform Admin Push page shows read-only fields and rejects
   writes with `409`.
2. **Platform Admin stored configuration** (`platform_push_settings` table, one row,
   private key encrypted at rest via `mykhaya.secrets_crypto`) — used only when the
   environment switch is off and the stored row has `enabled=true`.
3. **Unconfigured** — push-dependent delivery is skipped (not queued, not failed) rather
   than erroring.

Keys are generated in-app (`POST /platform/push/vapid-settings/generate-keys`) using
`py_vapid`; the public key is safe to expose (it's sent to browsers as the
`applicationServerKey`), the private key is encrypted the same way the SMTP password is
and is never returned by any API response. **Rotating keys immediately invalidates every
currently registered device** — there is no way to re-derive a subscription's usability
against a new key pair, so every device must re-subscribe (a fresh `enableNotifications()`
call on the household side). The admin UI requires explicit rotation confirmation and
states this consequence before proceeding; it is not a silent operation.

## Stripe configuration precedence

Configured through the Platform Control Centre's Payments page
(`GET/PUT /platform/payments/stripe...`). Structurally similar to SMTP/push
(`PlatformStripeSettings`, single row, secrets encrypted at rest via
`mykhaya.secrets_crypto`, never returned by any API response) but with two
deliberate differences:

1. **Test and Live credentials are stored in entirely separate columns**, since a
   payment provider must never let one mode's key be mistaken for the other's — see
   `mykhaya.models.PlatformStripeSettings` and `mykhaya.billing.config.StripeConfig`.
2. **The stored row, once `enabled`, takes precedence *over* the
   `MYKHAYA_STRIPE_*` environment variables** — the reverse of SMTP/push's
   environment-wins precedence. Precedence order:
   1. **Platform Admin stored configuration** (`platform_stripe_settings`, `enabled=true`)
      — authoritative once enabled. If the active mode's stored configuration is
      incomplete (a required field missing, or a key that doesn't match the selected
      mode's `sk_test_`/`sk_live_` prefix), `resolve_stripe_config` returns
      `configured=False` with an `incomplete_reason` and does **not** fall through to
      the environment or to the other mode — mixing sources, or silently running Live
      on Test credentials, is exactly what this precedence exists to prevent.
   2. **Environment variables** (`MYKHAYA_STRIPE_BILLING_CONFIGURED=true`) — the
      original bootstrap/fallback path, unchanged in behaviour, used only when the
      stored row is absent or disabled. The Payments page shows these fields
      read-only ("managed by deployment environment") and rejects writes with `409`.
   3. **Unconfigured** — no stored row and no environment configuration. Billing
      operations fail cleanly (`StripeNotConfiguredError` → `503`); MyKhaya still
      boots and the Control Centre remains reachable to repair the configuration.

Every consumer of Stripe configuration (checkout/portal session creation, webhook
verification, price resolution, billing health, reconciliation, the readiness CLI)
calls `mykhaya.billing.config.resolve_stripe_config(settings, db)` — there is exactly
one resolution path; nothing reads `Settings.stripe_*` directly outside that function.
A **Test Stripe connection** action (`POST /platform/payments/stripe/test-connection`)
makes one safe, read-only Stripe API call (account retrieval) against the currently
active mode — never a charge, customer, or subscription — and is rate-limited,
audited, and requires recent re-authentication, matching the SMTP test-email action's
security posture. Every settings change, secret replacement/removal, mode change, and
connection test is written to the platform audit log without secret values.

## Platform settings (generic key/value)

Ordinary administrator-managed operational configuration — the things a Platform Owner
should be able to change during normal operation without editing `.env`, touching the
database directly, or redeploying — lives in one generic table (`platform_settings`,
one row per key, added in migration `0002_platform_control_centre`) with its schema
defined centrally in `mykhaya.platform_settings.SETTINGS_SCHEMA`
(`SettingDefinition`: key, label, description, section, value type, python type, risk,
runtime effect, and whether it may be exposed to consumer clients). `GET`/`PUT
/platform/settings/{key}` (`mykhaya.routers.platform`) are the only way to read or
write it; both require an authenticated Platform Owner and `PUT` additionally requires
recent re-authentication (`require_recent_auth`) — identical to every other sensitive
PCC mutation. This is deliberately a much simpler model than SMTP/Push/Stripe above:
there is exactly one generic table, not a bespoke one per integration, because these
settings have no secret material and no complex per-integration resolution logic.

**Precedence** (same "stored row wins, environment is only a fallback" shape as
SMTP/Push):
1. **Platform-Admin stored row** — once an Owner saves a value via PCC, it is
   canonical and always wins.
2. **Environment default** — used only when no stored row exists yet, and only for
   the small number of keys that have one defined (see
   `mykhaya.platform_settings.resolve_environment_fallback`; today only
   `service_status_url`, which falls back to `Settings.status_url`).
3. **Unset** — no stored row and no environment default. The PCC Settings page
   (`apps/web/app/control-centre/settings/page.tsx`) renders this as a genuinely
   empty control ("Not yet set") — never the word "Unavailable", which was a UI bug
   in the previous generic-table rendering of this endpoint, not a real state.

**`service_status_url`** — the page Help & Support sends consumers to for MyKhaya's
status. Bootstraps from `Settings.status_url` (the same env var that also names the
hardened `/status` host, `MYKHAYA_STATUS_URL` — e.g. `https://status.dev.mykhaya.app`
in development) purely as a *default*; once a Platform Owner saves an explicit value
via PCC, that stored value is canonical and fully independent of the env var from then
on. **`Settings.status_url` itself is not, and must never become, live-editable** — it
also gates `mykhaya.routers.status.enforce_status_host`'s Host-header check for the
hardened status-hosting subdomain and is validated at startup
(`validate_admin_and_status_url_configuration`) against `trusted_hosts`/`cors_origins`;
changing it at runtime without redeploying would desynchronise it from those checks and
break the hardened status host. `service_status_url` and `status_url` are two
deliberately separate concepts: one is an administrator-facing informational link,
the other is infrastructure/security configuration.

**Consumer-safe exposure** — `GET /api/v1/config/public`
(`mykhaya.routers.public_config`, unauthenticated) is the *only* window consumer
clients have into `platform_settings`. It builds a brand-new response containing
exclusively the keys `SETTINGS_SCHEMA` marks `consumer_visible=True` (today just
`service_status_url`) — it never accepts a caller-supplied key list and never returns
the full schema for a client to filter. Every `/api/v1/*` response already gets
`Cache-Control: no-store` from `mykhaya.main`'s `security_and_limits` middleware, so a
PCC change to a consumer-visible setting is effective on the very next request — no
cache to invalidate, no restart required. The consumer Help & Support page
(`apps/web/app/help-support/page.tsx`) fetches this endpoint and opens the URL via
`openExternalUrl` (native `Browser.open`/browser `window.open`) — it never links to a
hardcoded environment-specific URL.

**Runtime enforcement is tracked explicitly, not assumed** — `SettingDefinition`'s
`runtime_effect` field records whether a setting is actually consumed by running code
today (`"effective"`), purely informational with no behavioural claim
(`"informational"`), or a placeholder nothing reads yet (`"not_enforced"`). As of this
writing: `registration_enabled`/`invite_only_mode` (the real gate is the env-only
`Settings.registration_mode`), `email_verification_required` (the real gate is the
similarly-but-confusingly-named env `Settings.email_verification_enabled`),
`maintenance_mode` (no maintenance-mode mechanism exists at all), `maximum_homes_per_user`
(nothing enforces it), `maximum_members_per_home` (the real per-plan limit is
`entitlements.py`'s `home.max_members`), and `invitation_expiry_days` (invitations use a
hardcoded `timedelta(days=7)` in `routers/invitations.py`) are all `"not_enforced"`. PCC
renders this as an honest "Not yet enforced by the application" caption, and a
sensitive+not-enforced setting's confirmation dialog says exactly that rather than
describing an operational effect that doesn't currently exist. Wiring any of these up to
real enforcement — and resolving the `registration_mode`/`registration_enabled`
duplication in particular — is future work, not done here; when it happens, flip that
key's `runtime_effect` to `"effective"` and the PCC confirmation copy for sensitive
settings automatically switches to the stronger operational warning.

**What stays environment/secret-only and must never become a PCC-editable
`platform_settings` row**: database URL, Redis URL, `secret_key`, SMTP
password/host/port (`platform_smtp_settings` already exists as the correct
Platform-Admin-managed path for the *non-secret* SMTP fields — see above), VAPID/APNs
private keys, Stripe secret/webhook keys, and any future OAuth client secret. Secrets
never touch `platform_settings`, and no endpoint here returns one even read-only.
