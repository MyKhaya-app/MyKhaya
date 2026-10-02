# PCC Usage Analytics — Phase 4 Manual Acceptance

This is the manual runtime and visual acceptance procedure for the PCC Usage
Analytics page. It intentionally does not add telemetry, dashboard features,
or consumer/mobile presentation changes.

## Supported local startup

Run from the repository root on a development machine with Docker Compose v2:

```sh
pnpm install --frozen-lockfile
make init
make up
make migrate
```

`make init` supplies `.env` and the local `compose.override.yml` when absent;
it uses the repository examples. `make up` starts PostgreSQL, Redis, the
migration service, API, worker, scheduler, Web, Caddy, and Mailpit. The
explicit migration check is:

```sh
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic heads
curl -fsS http://localhost:8080/api/v1/health/live
curl -fsS http://localhost:8080/api/v1/health/ready
```

Use `http://admin.localhost:8080` for PCC. The normal PCC login and MFA flow
must be used; do not bypass authorization. `make logs` and
`docker compose ps` are the supported diagnostics. Do not use `make reset`
unless intentionally destroying disposable local volumes.

## Acceptance checks

### Startup and PCC access

- PostgreSQL and Redis are healthy.
- API liveness/readiness succeeds.
- Web responds.
- Alembic current/head includes `0076_product_usage_analytics`.
- Sign into PCC normally.
- `Operations → Usage` exists and opens `/control-centre/usage`.
- Direct refresh of that route succeeds without an authorization error.

### Default and overview

Confirm the default filters are Production, 30 days, and All platforms.
Confirm numeric values render for Active Users, Active Homes, Usage Sessions,
Product Events, DAU, WAU, MAU, Returning Users, and New Users. There must be
no `NaN`, `Infinity`, `undefined`, malformed percentages, or misleading
zero-percent output when there are no active users.

### Filters and isolation

Exercise 7, 30, and 90 days; Production, All, Demo, Test, and Apple Review;
and All, Web, iOS, and Android. Confirm requests and values update without
unexpected filter resets. Production must exclude managed Demo, Test, and
Apple Review activity; those categories must appear only when explicitly
selected.

### Modules, platforms, and trend

- Module rows may include Calendar, Nudges, Lists, Meals, Home, Family, and
  Notifications only when data exists.
- Confirm module unique-user counts, event counts, and percentages use the
  selected active-user denominator.
- Confirm global active users count a multi-platform person once, while a
  person may appear in multiple platform buckets.
- Confirm daily trend rows remain readable for zero, sparse, and empty days.
- Confirm trend values are available as text without hover.

### Empty, error, and accessibility checks

- Select a known empty classification/filter and confirm a meaningful empty
  state with valid zero-safe metrics and no empty table chrome.
- If safe, stop/block the API, confirm the error and Retry behavior, then
  restore the API and confirm PCC navigation remains usable.
- Tab through navigation and filters; confirm visible focus, associated labels,
  table captions, readable trend values, and operation without a mouse.
- Confirm colour is not the only meaning conveyed.

### Viewports and consistency

Inspect at 1440–1600px, 1280–1366px, and 768–1024px. At each width confirm
there is no uncontrolled page overflow, awkward wrapping, clipping, overlap,
or cramped table. Compare spacing, cards, tables, headings, and controls with
Users, Homes, Health, Timeline, and Payments. PCC remains desktop-first; do
not assess or alter consumer phone layout as part of this check.

### Safe analytics smoke test and privacy

Using only a development/test account, generate semantic activity by opening
MyKhaya, Calendar, Lists, Meals, and Nudges where available. Create or mutate
the supported records, allow the normal aggregation/reporting path to run,
and confirm semantic event counts in PCC. Do not inspect or expect content
values. Network responses and database rows must contain no calendar titles,
descriptions, reminders, list names/items, meal text, notes, arbitrary URLs,
or authentication/session tokens.

## Acceptance record

Record the result and notes for each check before changing the phase status.

| Check | Result | Notes |
|---|---|---|
| PCC login | Pass/Fail | |
| Usage route | Pass/Fail | |
| Production default | Pass/Fail | |
| 7/30/90 filters | Pass/Fail | |
| Classification isolation | Pass/Fail | |
| Platform filters | Pass/Fail | |
| Overview metrics | Pass/Fail | |
| DAU/WAU/MAU | Pass/Fail | |
| Module usage | Pass/Fail | |
| Platform usage | Pass/Fail | |
| Trend | Pass/Fail | |
| Empty state | Pass/Fail | |
| Error/retry | Pass/Fail | |
| Desktop visual QA | Pass/Fail | |
| Laptop visual QA | Pass/Fail | |
| Tablet visual QA | Pass/Fail | |
| Keyboard accessibility | Pass/Fail | |
| Privacy check | Pass/Fail | |

Phase 4 may be marked `PHASE 4 READY` only after the critical checks pass:
route load, production isolation, date/platform filters, metrics, privacy,
desktop/laptop layout, runtime stability, and error handling. Otherwise use
`PHASE 4 AWAITING MANUAL ACCEPTANCE`.
