# Notification Engine

This is the single dispatch point for every outbound communication MyKhaya sends —
email, push, and in-app. It is a permanent project standard: no module sends email or
push directly, creates its own scheduling, or implements its own reminder logic. See
`docs/architecture/background-jobs.md` for the underlying outbox/worker/scheduler
primitives this is built on.

```
Calendar / Household Routines / Birthdays / Invitations / (future modules)
        │  outbox(topic, payload) — transactional outbox
        ▼
mykhaya/notifications/engine.py :: notify()
        │
        ├─ loads NotificationPreferences, checks per-type + channel toggles
        ├─ writes an in-app Notification row synchronously
        ├─ enqueues OutboxEvent(topic="notification.push", idempotency_key=...)
        └─ enqueues OutboxEvent(topic="notification.email", idempotency_key=...) (Stage 8+)
                │
                ▼
        worker.py process() — existing scheduler/Redis/backoff machinery
```

## Durable scans, not in-memory timers

`scheduler.py`'s poll loop calls a `scan_due_*()` function per notification-producing
module every cycle (currently `reminders.py`, `briefing.py`, `routines.py`). Each scan:

- Computes fresh from current data — no persisted "reminder sent" flag, no
  pre-scheduled per-occurrence row.
- Inserts an idempotent `OutboxEvent` when something becomes due within a short
  look-ahead window (typically 2 minutes).
- At delivery time, the worker re-fetches the source record and re-validates it
  (not deleted, not rescheduled, still a valid occurrence) before sending — so an
  edit or delete that lands after the scan but before delivery is caught, not
  delivered stale.

## Idempotency is the actual safety net

Every notification carries a stable `idempotency_key` (e.g.
`f"reminder:{event_id}:{occurrence_start_iso}:{offset_minutes}"`,
`f"briefing:{user_id}:{date_iso}"`, `f"routine:{routine_id}:{occurrence_date_iso}:{timing}"`).
`notify()` checks for an existing `NotificationDelivery` with that key before writing a
new one; the unique DB constraint on `notification_deliveries.idempotency_key` is the
final backstop for a genuine race (e.g. two scheduler instances), not the primary
mechanism. This is what makes the system correct under concurrent/duplicate scanning,
independent of the documented single-active-scheduler deployment convention.

## Known limitation: repeated enqueueing of already-pending work

Found during Stage 6 (household routines) live verification, 2026-08-06.

Because a scan's "already queued" check only looks at *currently pending*
(`processed_at IS NULL`) `OutboxEvent` rows for its topic, a reminder that becomes due
gets re-enqueued on every scheduler tick (currently every 2s) for as long as its
look-ahead window stays open — observed as 58 outbox rows generated to deliver a single
routine reminder in one test run. Idempotency in `notify()` means this produces exactly
one actual notification, so it is not a correctness bug, but it is wasted database and
worker throughput that will not scale to hundreds or thousands of households.

**Backlog: optimise scan enqueue behaviour** — normal operation should enqueue a given
piece of due work once, not repeatedly across every tick until it's processed. Idempotency
must remain as the final safety net regardless of the fix chosen. Candidate approaches:
narrowing each scan's look-ahead window to roughly the scheduler's own tick interval so
there's only ever one tick's worth of overlap, or checking recently-*processed* outbox
rows (not just pending ones) within the look-ahead window before inserting. Not
addressed yet — deliberately deferred rather than fixed reactively mid-stage; revisit
before wider household onboarding, and before Stage 6's `routines.py` scan pattern is
copied into any future module.

## Rebuilding after backend code changes

`api`, `worker`, and `scheduler` build from the same `apps/api/Dockerfile` via a
YAML anchor in `compose.yml`, but are three separate images — rebuilding one does not
rebuild the others. See `docs/operations/dev-deployment.md#api-worker-and-scheduler-are-three-separate-images-built-from-one-dockerfile`
for the incident this caused during Stage 5 and the documented fix (`make
backend-rebuild`, or `make dev-up`/`dev-update` for the persistent server). Treat
"rebuild and recreate all three together" as the standard for any backend change, not
just Communications work.
