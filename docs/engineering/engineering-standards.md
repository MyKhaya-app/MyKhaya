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

## Architecture

MyKhaya begins as a modular monolith. Do not introduce microservices or Kubernetes without measured need and an approved architectural decision record.

PostgreSQL is authoritative. API and web processes are stateless. Redis is used only for cache, coordination, rate limiting and durable worker infrastructure where configured appropriately.

## Definition of quality

A change is complete only when it is secure, tested, documented, observable, reversible and consistent with the approved MyKhaya visual identity.
