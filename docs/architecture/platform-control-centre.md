# Platform Control Centre

## Decision

The Control Centre is a management plane within the FastAPI/Next.js modular monolith, isolated by the `admin.mykhaya.app` hostname, `/api/v1/platform` API namespace, platform-only identities and roles, and `mk_admin_*` cookies. It is never mounted at `mykhaya.app/admin`.

Platform roles are independent of Home membership: Platform Owner, Platform Administrator, Support Operator, Security Operator and Read-only Operator. Every route declares allowed roles server-side. Household Owner and Administrator roles have no effect.

## Privacy boundary

The API exposes operational account and Home metadata only. It does not query or return calendar, list, task, note, plan, meal, poll, message, child-profile, location or uploaded content. There is no impersonation or general “browse user data” route.

Exceptional future content access requires a separate design: record scope, elevated permission, reason, recent authentication, expiry, permanent audit, visible banner and appropriate owner notification.

## Control state

- Implemented: hostname/network gates, isolated sessions, role authorization, recent-auth checks, confirmation/reason schemas, immutable application audit API, bounded metadata lists, suspension/session revocation, notes, health, jobs, typed settings, global feature flags, security/audit views and incident management.
- Designed but incomplete: mandatory MFA state and enforcement boundary, Home flag override management, mail delivery event persistence, job manual retry and independent status hosting.
- Production blocker: no WebAuthn/passkey ceremony exists. Password-only production administration is not approved.
