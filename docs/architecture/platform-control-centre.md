# Platform Control Centre

## Decision

The Control Centre is a management plane within the FastAPI/Next.js modular monolith, isolated by the `admin.mykhaya.app` hostname, `/api/v1/platform` API namespace, platform-only identities and roles, and `mk_admin_*` cookies. It is never mounted at `mykhaya.app/admin`.

Platform roles are independent of Home membership: Platform Owner, Platform Administrator, Support Operator, Security Operator and Read-only Operator. Every route declares allowed roles server-side. Household Owner and Administrator roles have no effect.

## Privacy boundary

The API exposes operational account and Home metadata only. It does not query or return calendar, list, task, note, plan, meal, poll, message, child-profile, location or uploaded content. There is no impersonation or general “browse user data” route.

Exceptional future content access requires a separate design: record scope, elevated permission, reason, recent authentication, expiry, permanent audit, visible banner and appropriate owner notification.

## Control state

- Implemented: hostname/network gates, isolated sessions, role authorization, recent-auth checks, confirmation/reason schemas, immutable application audit API, bounded metadata lists, suspension/session revocation, notes, health, jobs, typed settings, global feature flags, security/audit views, incident management, and Platform-Admin-managed SMTP and Web Push (VAPID) configuration.
- Implemented feature controls: global and Home override management, role checks, recent authentication, explicit confirmation/reason and administrative audit events.
- Designed but incomplete: mandatory MFA ceremony, job manual retry and independent status hosting.
- Production blocker: no WebAuthn/passkey ceremony exists. Password-only production administration is not approved.

## SMTP configuration precedence

Outbound email transport can come from either deployment-level env vars or Platform-Admin
stored configuration, never both at once:

1. **Environment variables** (`MYKHAYA_SMTP_HOST` set to a non-empty value in `.env`) —
   always wins when present. The Platform Admin Email page shows the settings as
   read-only ("managed by deployment environment") and rejects writes with `409` rather
   than silently accepting a value it would then ignore.
2. **Platform Admin stored configuration** (`platform_smtp_settings` table, one row,
   password encrypted at rest — see `mykhaya.secrets_crypto`) — used only when no env var
   is set and the stored row has `enabled=true`.
3. **Unconfigured** — no env var and no enabled stored row. Email-dependent journeys are
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
