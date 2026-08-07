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

Every new module must justify its existence on the Home screen. If a feature never surfaces useful, glanceable information on Home, it likely isn't important enough to exist as a first-class module — fold it into an existing surface, or reconsider it. This is a deliberate check against feature bloat, not a UI-placement suggestion: a module that has nothing to say on Home is a signal to revisit the proposal, not to add a Home widget for its own sake.

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
