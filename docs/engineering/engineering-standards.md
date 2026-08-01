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
- `main` is stable and release-only; do not push direct feature work to `main`.
- Stable releases require semantic versioning and stable tags (`vMAJOR.MINOR.PATCH`).
- Development versions must be clearly marked with `-dev`.
- Version, commit and build metadata must be safe to expose internally and must not include secrets.
- Public status endpoints must not expose internal build identifiers.

## Architecture

MyKhaya begins as a modular monolith. Do not introduce microservices or Kubernetes without measured need and an approved architectural decision record.

PostgreSQL is authoritative. API and web processes are stateless. Redis is used only for cache, coordination, rate limiting and durable worker infrastructure where configured appropriately.

Privileged platform administration is a separate management-plane boundary. Household roles, sessions, routes and layouts must never be reused as platform authorization. Public status contracts must be constructed independently of internal diagnostic contracts.

## Definition of quality

A change is complete only when it is secure, tested, documented, observable, reversible and consistent with the approved MyKhaya visual identity.
