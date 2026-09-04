# MyKhaya Engineering Standards

## Authority

This document and the linked architecture, security and design standards are the repository source of truth. Codex, AI agents and human contributors must read them before making changes.

Where implementation and documentation conflict, stop, identify the correct intended behaviour and update both. Do not allow silent divergence.

## Core rules inherited from Kaya

- Inspect before changing.
- Preserve working behaviour unless a change is explicitly required.
- Prefer clear, minimal and reviewable changes.
- Enforce security and permissions server-side.
- Use migrations for every schema change.
- Never commit secrets or production data.
- Do not expose debug behaviour in production.
- Add tests for happy paths, failure paths and regressions.
- Update documentation whenever architecture, security, data models or UI conventions change.
- Do not present mocked, partial or simulated behaviour as complete.
- Keep errors useful to users without exposing internals.
- Avoid unnecessary dependencies and abstractions.
- Treat rollback and operational impact as part of implementation.

## Branching and release gates

- `dev` is the default target for normal development pull requests.
- Codex performs all normal work directly on `dev` unless Anthony asks for a short-lived branch.
- `main` is stable; only Anthony merges, tags and deploys it.
- Do not create release or hotfix branches, automate promotion, force-push or rewrite history.
- Stable releases require semantic versioning and stable tags (`vMAJOR.MINOR.PATCH`).
- `VERSION` is branch-independent and every component must use the same value.
- Version, commit and build metadata must be safe to expose internally and must not include secrets.
- Public status endpoints must not expose internal build identifiers.

## Architecture

MyKhaya begins as a modular monolith. Do not introduce microservices or Kubernetes without measured need and an approved architectural decision record.

PostgreSQL is authoritative. API and web processes are stateless. Redis is used only for cache, coordination, rate limiting and durable worker infrastructure where configured appropriately.

Privileged platform administration is a separate management-plane boundary. Household roles, sessions, routes and layouts must never be reused as platform authorization. Public status contracts must be constructed independently of internal diagnostic contracts.

Every unfinished module must be enforced through the central server-side feature evaluator. Hiding a navigation link is not authorization or feature enforcement.

Every commercial (plan-based) restriction must go through the central entitlement service (`mykhaya.entitlements` — `has_entitlement`/`require_entitlement` for booleans, `get_limit`/`require_within_limit` for numeric limits, `classify_ordered_resources` for deriving which of several existing resources stay usable after a downgrade). Never write `if subscription.plan == ...` or `if subscription.provider == ...` in a router or domain module — those checks belong exclusively inside `mykhaya.entitlements`, which resolves *effective* plan once, in one place, fail-safe to Free. A numeric limit enforced on resource creation must acquire a per-Home `pg_advisory_xact_lock` (or an equivalent row lock) around the count-then-insert, in the same transaction — see `routers.calendar.create_calendar` and `routers.billing.checkout_session` for the pattern. Raise commercial restrictions through `mykhaya.entitlements.commercial_restriction_error` with one of its stable codes (`plan_feature_unavailable`, `plan_limit_reached`, `resource_restricted_by_plan`) rather than a bespoke error shape. A downgrade must never delete Home data — see "Safe downgrade principle" in `docs/architecture/commercial-entitlements.md`.

Every new module must justify its existence on the Home screen. If a feature never surfaces useful, glanceable information on Home, it likely isn't important enough to exist as a first-class module — fold it into an existing surface, or reconsider it. This is a deliberate check against feature bloat, not a UI-placement suggestion: a module that has nothing to say on Home is a signal to revisit the proposal, not to add a Home widget for its own sake.

## Security and privacy engineering

Security, privacy, tenant isolation, resilience and scale are first-class requirements. They are design and implementation concerns, not a final hardening phase. The detailed references are [Security Baseline](../security/security-baseline.md), [Secure Development Lifecycle](../security/secure-development-lifecycle.md), [API Security](../security/api-security.md), [Multi-Tenancy](../architecture/multi-tenancy.md) and [Definition of Done](definition-of-done.md).

### Security by design

Before implementing a meaningful feature, identify its trust boundaries, data flows, authentication and authorization rules, abuse cases, tenant impact, privacy implications, rate limits, operational impact, audit requirements, failure modes and dependency/supply-chain impact. Security review happens before implementation and is revisited when the design changes.

Security-relevant decisions must fail closed:

- deny by default when authority, role, capability, tenant or host state is missing, unknown or malformed;
- do not make a new capability delegatable without an explicit allow-list decision;
- require explicit authority for privileged operations;
- return predictable errors without revealing whether another tenant's data exists; and
- never turn a dependency failure, timeout or degraded mode into an authorization bypass.

Apply least privilege to household users, child accounts, Platform Control Centre operators, service accounts, database users, workers, queues, API scopes, CI/CD and infrastructure credentials. The UI may improve usability, but it is never the security boundary; all client identifiers and requested actions are untrusted and must be checked server-side.

### Home isolation and child safety

A Home is the primary tenant and privacy boundary. Every tenant-owned read, write, search, notification, cache entry, background job and external reference must be scoped to an authorized Home. One Home must not enumerate, infer, cache, search, share or receive data belonging to another Home. Prefer Home-scoped queries and repositories over unconstrained object lookup, and add cross-Home tests for new access paths.

Child accounts are a distinct, lower-trust account type. Child permissions and restrictions are server-enforced and fail closed; children cannot self-elevate; child session state cannot become adult authority; adult-only and child-related data are disclosed only when necessary; PINs and remembered access do not become reusable credentials; and child-to-adult transitions require explicit secure handling.

External calendar, wishlist and other sharing features create a separate trust boundary. Access must be narrowly scoped, with explicit read/write authority, expiry or single-use semantics where appropriate, revocation, no tenant enumeration and server-side checks on every shared resource. Notifications and briefings must apply the same visibility rules.

### Privileged administration and secure defaults

The Platform Control Centre is a separate high-trust management plane. It requires separate privileged authorization, MFA, strong session controls, recent authentication for sensitive actions, audit logging and appropriate host/network restrictions. Consumer sessions must never inherit platform privilege, and missing administrative state must not fail open.

Shared development, staging and production environments default securely: Secure cookies, HTTPS, strict host validation, security headers, CSRF protection, explicit CORS allow-lists, rate limits, no debug bypasses and no development backdoors. Local-only exceptions must be explicit, isolated, documented and impossible to silently carry into shared environments.

Critical controls use defence in depth across application authorization, database constraints, tenant-scoped queries, reverse-proxy limits, host validation, rate limiting, CSP and security headers, request-size limits, queue/task validation, audit logging and infrastructure controls. No single layer is sufficient on its own.

Authentication and session designs must use strong password hashing, secure token generation, passkeys where available, no plaintext session tokens at rest, CSRF protection for cookie mutations, strict CORS, safe reset flows, rotation/revocation where appropriate, secure native bearer storage and separation of trusted-device credentials from ordinary active sessions. Persistent mobile UX must not require weakening authentication.

### Privacy, data minimisation and observability

Collect only the personal and household data needed for the feature, minimise retention, protect child and household information, and provide appropriate export and deletion mechanisms. Review diagnostics, caches, search, analytics and notifications for unintended disclosure before release. Do not make legal or compliance claims beyond established project policy.

Security-relevant actions should be auditable without recording credentials: login and session events, privilege and membership changes, Home Admin changes, child-permission changes, external shares, billing administration, Platform Control Centre changes and security configuration changes. Logs must not contain passwords, reset/session tokens, API keys, CSRF secrets, payment secrets, APNs/private keys or other credentials. Diagnostics must be useful without exposing private image, household or child data.

Malformed or unexpected input must produce a safe, predictable 4xx response where appropriate. Do not expose sensitive stack traces, swallow security errors, buffer unbounded request bodies, retry without limits or let degraded dependencies bypass controls.

### Scale, resilience and abuse resistance

Design for eventual operation at 100,000+ Homes and global public-Internet exposure. Treat credential stuffing, enumeration, brute force, invitation and sharing abuse, spam, notification abuse, scraping, oversized or decompression-heavy files, queue flooding, webhook abuse, rate-limit bypass, denial of service and authenticated-user abuse as normal threat cases. Prefer horizontally scalable controls and bounded work.

Performance and scalability are security concerns. New paths should consider bounded queries, pagination, indexes, tenant-scoped filters, queue backpressure, retry limits, idempotency, rate limiting, circuit breakers where appropriate, storage growth, notification fan-out, cache isolation, connection-pool exhaustion, worker concurrency and expensive endpoints. An endpoint safe for 10 Homes may be unsafe for 100,000 Homes; resilience, backup/restore and rollback impact belong in the design.

### Software supply chain and secrets

Protect branches, require pull-request review and required CI checks, and use dependency, secret, SAST, container and IaC scanning. Keep lockfiles current, produce SBOMs, prefer reproducible immutable builds and provenance/signing where practical, minimize CI permissions, store secrets in controlled secret stores and review dependency updates deliberately.

Never commit secrets or real keys in source, fixtures, logs or documentation. Clearly mark placeholders as fake. Credentials exposed in Git history must be rotated, not merely deleted. Local environment files, disposable test credentials, generated payloads and one-off databases remain local.

### Engineering change checklist

Before implementation:

- identify data and trust boundaries, including Home and child-account boundaries;
- define server-side authentication, authorization and failure behavior;
- consider abuse cases, privacy, retention, notifications, sharing and cache isolation;
- assess scale, resilience, operational impact and rollback; and
- identify dependency, secret-handling and supply-chain implications.

During implementation:

- preserve secure defaults and existing controls;
- validate all inputs and enforce authorization server-side;
- bound requests, queries, files, retries and queue work;
- avoid exposing secrets or sensitive data in responses and logs; and
- add focused happy-path, denial-path, tenant-isolation and regression tests.

Before completion:

- run relevant tests, type checks, lint, build and security checks;
- update architecture, threat-model or operational documentation when needed;
- remove temporary diagnostics, test data, files and generated output;
- review untracked files and `git status`;
- review the final diff and rollback implications; and
- confirm no unresolved high or critical security issue remains without an approved risk record.

### Repository hygiene

Do not commit local IDE or tool settings, temporary diagnostics, generated test payloads, investigation screenshots, scratch scripts, ad-hoc audit output, local credentials, one-off test databases, downloaded scanner binaries or temporary logs. Use normal engineering names based on the feature, defect, component, security control or release. Remove task-created temporary artifacts before completion; preserve unrelated local files rather than deleting them.

### Assurance target

MyKhaya is designed and reviewed against OWASP ASVS Level 2 as the practical application-security verification target, with the OWASP Top 10 used for awareness and risk classification and relevant UK NCSC secure development and software-security guidance used for engineering practice. These are assurance targets and review references, not claims of certification.

## Notification architecture

All user-facing communications must originate from `notify()`
(`apps/api/mykhaya/notifications/engine.py`). This is a non-negotiable rule, not a
convention to follow when convenient — see `docs/architecture/notification-engine.md`
for the full design.

Modules must never:

- send email directly (call `mykhaya.mailer.send_email` from anywhere other than
  `worker.py`'s single `notification.email` handler),
- send push notifications directly (call `mykhaya.notifications.push.send_push` from
  anywhere other than `worker.py`'s single `notification.push` handler),
- create in-app notifications directly (insert a `Notification` row outside `notify()`),
- enqueue `OutboxEvent` rows for communications directly, bypassing `notify()`.

The Notification Engine is the sole communication pipeline and is responsible for
channel selection, user preferences, quiet hours, mandatory delivery (identity/security
workflows — email verification, password reset, household invitations — that must
never depend on user preferences), retries, and delivery auditing. Every future
delivery channel (SMS, a future mobile push provider, etc.) is added inside `notify()`,
not as a parallel path a module calls instead.

## Definition of quality

A change is complete only when it is secure, tested, documented, observable, reversible and consistent with the approved MyKhaya visual identity.
