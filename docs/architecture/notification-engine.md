# Notification Engine

This is the single dispatch point for every outbound communication MyKhaya sends —
email, push, and in-app, and any future channel. It is a permanent, non-negotiable
project standard (see `docs/engineering/engineering-standards.md#notification-architecture`):
no module sends email or push directly, creates an in-app `Notification` row directly,
enqueues an `OutboxEvent` for a communication directly, or invents its own reminder
scheduling. Everything calls `notify()`. See `docs/architecture/background-jobs.md` for
the underlying transactional-outbox/worker/scheduler primitives this is built on.

## Flow diagram

```
Calendar / Household Routines / Birthdays / Invitations / Account security /
(future: Wish Lists, school reminders, shopping lists, ...)
        │
        │  notify(db, settings=..., recipient_user_id=..., notification_type=...,
        │         title=..., body=..., idempotency_key=..., deep_link=..., is_critical=...)
        ▼
mykhaya/notifications/engine.py :: notify()
        │
        ├─ mandatory? (MANDATORY_EMAIL_TYPES) ─── yes ──► skip preferences, always email
        │                                                  (identity/security workflows)
        ├─ no ─► load NotificationPreferences (get_or_create_preferences)
        │        check per-type category gate (PREFERENCE_GATES) + per-channel toggle
        │
        ├─ in_app_enabled?  ─► write Notification row synchronously (idempotency-checked)
        ├─ push_enabled?    ─► quiet-hours check ─► OutboxEvent(topic="notification.push")
        └─ email_enabled?   ─► OutboxEvent(topic="notification.email")
                │
                ▼
        mykhaya/scheduler.py — durable poll loop, moves due OutboxEvent rows to Redis
                │
                ▼
        mykhaya/worker.py :: process() — one handler per topic, bounded retry/backoff
                │
                ├─ notification.email  → mykhaya.mailer.send_email      (the only caller)
                ├─ notification.push   → mykhaya.notifications.push.send_push (the only caller)
                └─ notification.<reminder|briefing|routine|birthday> → deliver_*() re-validates
                   current data, then calls notify() again per recipient
```

Two dispatch shapes exist, both ending at the same `notify()` call:

- **Direct**: a request handler calls `notify()` synchronously (account verification,
  password reset, household invitations, admin resend actions).
- **Scanned**: a `scan_due_*()` function in `scheduler.py`'s poll loop finds work that
  has become due, enqueues a topic-specific `OutboxEvent` (e.g.
  `notification.event_reminder`), and the worker's handler for that topic re-validates
  the source record before calling `notify()` per recipient. See "Durable scans" below.

## `notify()`

Signature (`mykhaya/notifications/engine.py`):

```python
async def notify(
    db, *, settings,
    recipient_user_id: uuid.UUID | None = None,
    recipient_email: str | None = None,
    notification_type: str,
    title: str,
    body: str,
    idempotency_key: str,
    group_id: uuid.UUID | None = None,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
    deep_link: DeepLinkTarget | None = None,
    is_critical: bool = False,
    timezone_override: str | None = None,
) -> Notification | None
```

`recipient_user_id` is required for every notification type except the
`MANDATORY_EMAIL_TYPES` sent to someone with no MyKhaya account yet (a household
invitation to an email address that hasn't registered) — that case passes
`recipient_email` instead. Every other caller passes `recipient_user_id`; `notify()`
raises `ValueError` if a non-mandatory type is called without one.

Returns the created in-app `Notification` row, or `None` if nothing was written to
in-app (channel disabled, category disabled, or the type is a mandatory
email-only type that never touches in-app/push at all).

## Channel selection

Three channels exist today: `in_app`, `push`, `email` (`NotificationChannel`). Each is
gated independently:

- **in-app**: `NotificationPreferences.in_app_enabled` (default **on**) + category gate.
  Writes a `Notification` row synchronously — cheap, immediate, no queue.
- **push**: `NotificationPreferences.push_enabled` (default **on**) + category gate +
  quiet hours. Enqueues `notification.push` per active `PushSubscription` (fans out to
  every registered device).
- **email**: `NotificationPreferences.email_enabled` (default **off**) + category gate.
  Deliberately opt-in, unlike push/in-app — making it default-on would triple send
  volume for every optional reminder/briefing/routine/birthday. Enqueues
  `notification.email`.

A notification type not listed in `PREFERENCE_GATES` (e.g. a one-off test send) is
gated only by the channel toggles, with no category-specific opt-out.

## Preferences

One `NotificationPreferences` row per user (`get_or_create_preferences` creates it
lazily on first need — registration's verification email is usually what creates it).
Besides the three channel toggles: per-category toggles
(`event_reminders_enabled`, `event_invitations_enabled`, `event_changes_enabled`,
`household_reminders_enabled`, `daily_briefing_enabled`), daily briefing scheduling
(`briefing_time`, `briefing_days`, `empty_day_briefing_enabled`), lock-screen preview
level, and quiet hours (`quiet_hours_start`/`end`, `quiet_hours_critical_only`).
`PREFERENCE_GATES` in `engine.py` maps a `notification_type` string to the category
attribute that gates it; a type absent from that map is never category-gated.

## Quiet hours

`mykhaya/notifications/quiet_hours.py`. Applies to **push only** — in-app and (opted-in)
email are never suppressed by quiet hours, so nothing is silently lost, only push
timing is deferred to a more considerate hour. A notification flagged `is_critical=True`
(e.g. medication reminders) bypasses quiet hours entirely unless the user has also set
`quiet_hours_critical_only=False`, which flips the default and suppresses even critical
push during quiet hours. `effective_timezone()` resolves `User.timezone` →
`Settings.default_timezone`; `home_timezone()` resolves a household's primary calendar
timezone for scans that have no single recipient to anchor to (household routines, a
child's birthday).

## Mandatory delivery

`MANDATORY_EMAIL_TYPES = {"email_verification", "password_reset", "household_invitation"}`
in `engine.py`. These are identity/security workflows, not notifications — a user must
never be able to opt out of receiving them, so `notify()` skips preference/category
checks entirely for these types and always attempts email (skipping in-app/push, which
wouldn't make sense pre-account or pre-verification anyway). `docs/architecture/data-model.md`
and threat-model docs should treat these as the account-security surface, not the
optional-communications surface.

## Email

`mykhaya/mailer.py` holds the SMTP transport (`SmtpConfig`, `resolve_smtp_config`,
`send_email`) — see `docs/architecture/platform-control-centre.md` for the
environment-vs-Platform-Admin precedence rule. `send_email` is called from exactly one
place: `worker.py`'s `_process_email()`, handling the `notification.email` topic.
Content (subject/body) is rendered once, at `notify()`-call time, by the caller —
`mykhaya/notifications/default_templates.py` holds the trusted built-in copy for the
three mandatory types today. This is the file the (planned) Platform Admin template
override system reads its fallback from — see "Future: template overrides" below.

## Push

`mykhaya/notifications/push.py` — VAPID/Web Push (RFC 8291/8292) via `pywebpush`,
working uniformly across Android Chrome and installed iOS 16.4+ Safari PWAs. `send_push`
is called from exactly one place: `worker.py`'s `_process_push()`, handling the
`notification.push` topic. A dead/expired subscription (404/410 from the push service)
is marked `disabled_at` rather than retried forever; a malformed subscription (bad
stored keys) is treated the same way, since retrying it would fail identically forever.

## In-app

Written synchronously inside `notify()` — no queue, no worker round-trip, since it's a
cheap DB insert. `GET/PUT /notifications` (`routers/notifications.py`) serves the
in-app notification centre: list, mark-read, mark-all-read, deep-link resolution via
`mykhaya/notifications/deep_links.py` (a closed registry of logical targets, never a raw
URL a template could tamper with).

## Scheduler

`mykhaya/scheduler.py` — a 2-second poll loop with two responsibilities:

1. **Durable scans, not in-memory timers.** Once per cycle it calls each
   notification-producing module's `scan_due_*()` (currently `reminders.py`,
   `briefing.py`, `routines.py`, `birthdays.py`). Each scan computes fresh from current
   data — no persisted "reminder sent" flag, no pre-scheduled per-occurrence row — and
   inserts an idempotent `OutboxEvent` when something becomes due within a short
   look-ahead window (typically 2 minutes).
2. **Moving due outbox rows to Redis** for the worker to pick up (`FOR UPDATE SKIP
   LOCKED`, restart-safe, existing background-jobs machinery — see
   `docs/architecture/background-jobs.md`).

At delivery time, the worker re-fetches the source record and re-validates it (not
deleted, not rescheduled, still a valid occurrence) before calling `notify()` — so an
edit or delete that lands after the scan but before delivery is caught, not delivered
stale.

## Worker

`mykhaya/worker.py` :: `process()` — one topic per handler, bounded exponential-backoff
retry (`MAX_ATTEMPTS = 8`, capped backoff). A `WorkerJobRecord` row is the permanent
diagnostic record of every attempt, success or failure, independent of whether the
`OutboxEvent` itself is still pending or has given up.

## Idempotency is the actual safety net

Every notification carries a stable `idempotency_key` (e.g.
`f"reminder:{event_id}:{occurrence_start_iso}:{offset_minutes}"`,
`f"briefing:{user_id}:{date_iso}"`, `f"routine:{routine_id}:{occurrence_date_iso}:{timing}"`,
`f"email_verification:{token_id}"`). `notify()` checks for an existing
`NotificationDelivery` with that key (plus a `:in_app`/`:push:{subscription_id}`/`:email`
suffix per channel) before writing a new one; the unique DB constraint on
`notification_deliveries.idempotency_key` is the final backstop for a genuine race (e.g.
two scheduler instances), not the primary mechanism. This is what makes the system
correct under concurrent/duplicate scanning, independent of the documented
single-active-scheduler deployment convention.

## Future channels

Adding a channel (SMS, a native mobile push provider, etc.) means: add a
`NotificationChannel` value, add a preference toggle, add an `_enqueue_<channel>()`
helper in `engine.py` called from `notify()`, add one `worker.py` handler that's the
channel's only caller of its transport library. No caller of `notify()` changes.

## Future: template overrides (Stage 9)

Not built yet — noting the intended design so it isn't reinvented differently later.
`default_templates.py` remains the **authoritative source of truth**; a Platform Admin
customisation is stored as an **override only** (a row exists only when an admin has
actually changed that template/channel), never a copy of the built-in template. Deleting
the override row resets to the built-in default. When a built-in template's wording
changes in a future release, an admin with an active override should be able to see
"this template has changed since your override was created" and choose to compare, keep
their override, or adopt the new default — this comparison needs the override to record
which version of the built-in copy it was based on, decided at Stage 9 implementation
time, not before.

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
before wider household onboarding.

## Rebuilding after backend code changes

`api`, `worker`, `scheduler`, and `migrate` all build from the same
`apps/api/Dockerfile`, but are **four separate images** — rebuilding one does not
rebuild the others. Run `make backend-rebuild` (rebuilds and recreates all four
together; running any newly-added migrations is a separate, explicit step) rather than
rebuilding services individually — see
`docs/operations/dev-deployment.md#api-worker-scheduler-and-migrate-are-four-separate-images-built-from-one-dockerfile`
for the incidents this caused during Stages 5 and 8 before the single command existed.
