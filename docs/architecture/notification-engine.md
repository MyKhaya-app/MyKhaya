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
`household_reminders_enabled`, `list_assignments_enabled`,
`wishlist_sharing_enabled`, `daily_briefing_enabled`), daily briefing scheduling
(`briefing_time`, `briefing_days`, `empty_day_briefing_enabled`), lock-screen preview
level, and quiet hours (`quiet_hours_start`/`end`, `quiet_hours_critical_only`).
`PREFERENCE_GATES` in `engine.py` maps a `notification_type` string to the category
attribute that gates it; a type absent from that map is never category-gated.

Lists and Wishlists use those two explicit categories for actionable access changes:
assigning a shared list item notifies only the new assignee, while granting or
revoking an authenticated Wishlist share notifies only the affected recipient.
Ordinary list/wishlist CRUD, completion, reservation, release, purchase, and guest
share actions remain silent. Wishlist owner responses and notifications never contain
reservation or purchase state.

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
`send_email`) — the enabled Platform Control Centre SMTP row is authoritative; Mailpit
environment settings are only an explicit development/test fallback. `send_email` is called from exactly one
place: `worker.py`'s `_process_email()`, handling the `notification.email` topic.
Content (subject/body) is rendered once, at `notify()`-call time, by the caller, via
`mykhaya/notifications/templates.render_notification_email` — `default_templates.py`
holds the trusted built-in copy per type, overridable by a Platform Admin
(`NotificationTemplate`, text only) via `templates.render_notification`.

Every send is `multipart/alternative` (`text/plain` + `text/html`), never HTML-only.
The HTML half is built by `mykhaya/email_branding.py` from the *same* resolved
subject/body — one conservative, inline-styled, table-based layout (no external CSS, no
web fonts, no JavaScript, no tracking pixels) reused by every email type, so an admin's
text override is reflected in both without a second content-authoring path. The logo is
a static PNG at `apps/web/public/mykhaya-email-logo.png`, served over HTTPS on
`MYKHAYA_PUBLIC_WEB_URL` — reachable by an unauthenticated external mail client, unlike
anything on the admin/API hosts — and reproduces `apps/web/components/logo.tsx`'s
existing mark exactly.

`send_email` raises a specific `EmailSendError` subclass
(`EmailConnectionError`/`EmailAuthenticationError`/`EmailTlsError`/`EmailPermanentError`/
`EmailTemporaryError`) rather than a bare `Exception`, so `worker.py` can tell a
permanent rejection (5xx — never retried) from a transient one (4xx/connectivity/TLS —
retried with the existing backoff) without inspecting `smtplib`-specific exception
types itself. `NotificationDelivery.sanitised_failure_reason` stores only the category,
never the raw exception text (which some SMTP servers echo the recipient address or
other detail into).

In production (`MYKHAYA_ENVIRONMENT=production`), once
`MYKHAYA_EMAIL_DELIVERY_CONFIGURED=true`, `Settings` refuses to start with
`MYKHAYA_SMTP_HOST`/`MYKHAYA_EMAIL_FROM` still pointed at the development-only
defaults this repo ships (Mailpit's service name, `*.local`) — see
`Settings.reject_placeholder_production_email_configuration` in `mykhaya/config.py`.
This does not, on its own, make mail land in the inbox — see the deliverability
report from the branding/deliverability work for SPF/DKIM/DMARC and sending-IP
reputation, which are DNS/provider configuration outside this repository.

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

## Notification template registry and PCC overrides (Stage 9)

This is the layer that owns notification **wording**. It has no say in who receives a
notification, whether it fires at all, or which channel it goes over — that stays with
the producer modules (Calendar, Routines, Daily Briefing, Invitations, account security,
...) and with the preference/channel gating in `notify()` described above. Concretely:
recipient selection, visibility rules, and the decision to call `notify()` all happen
**before** this layer is ever consulted; this layer only answers "given this template
key and these variables, what text should go in `title`/`body`?".

```
producer module (Calendar / Routines / Daily Briefing / Invitations / account security / ...)
        │  decides: who receives it, whether it fires, which channel — unchanged by this layer
        ▼
render_notification(db, template_type, variables, channel=None)   [templates.py]
        │
        ├─ look up TemplateDefault in TEMPLATES (default_templates.py) — 404 if unknown key
        ├─ look up a matching NotificationTemplate override row (template_type, channel)
        │
        ├─ override exists, enabled, keeps every required placeholder, substitutes
        │  cleanly ──► use override's subject/body
        │
        └─ no override / disabled / drops a required placeholder / references an
           unknown placeholder ──► log a warning, fall back to the built-in default
        ▼
notify(..., title=<resolved subject>, body=<resolved body>, ...)   [engine.py, unchanged]
```

### Registry (`mykhaya/notifications/default_templates.py`)

`TEMPLATES: dict[str, TemplateDefault]` is the **authoritative, code-owned** source of
every notification's default wording — not a cache of something in the database. Each
entry is a `TemplateDefault`:

- `template_type` (the dict key) — a stable internal key, e.g. `email_verification` or
  `calendar.event.reminder`. Dotted `module.entity.event` keys are used for newer,
  more granular templates; the eight pre-Stage-9 types keep their original flat names
  (`email_verification`, `household_invitation`, ...) rather than being renamed, since
  renaming would silently orphan any admin override already saved against the old key.
- `module` — a coarse grouping (`account_security`, `calendar`, `calendar_sharing`,
  `daily_briefing`, `platform`, ...) used for filtering in the PCC Templates browser.
- `channel` (`NotificationChannel`) — which channel this template's row lives on. Every
  template that existed before this field was added defaults to `email`, preserving
  exact prior behaviour; newer, in-app-only templates (the calendar/routine/briefing
  fragments) are registered under `in_app`.
- `subject` / `body` — the built-in default wording, using `{{variable}}` placeholders.
- `allowed_variables` (`frozenset[str]`) — the closed set of placeholders this template
  may reference. This is enforced in both directions: a saved override may not reference
  a variable outside this set, and every variable in this set must be supplied by the
  producer's call to `render_notification()` for the default itself to render cleanly.
- `required_variables` (`frozenset[str]`) — the subset of `allowed_variables` that must
  remain present (in the subject, the body, or both — checked as one combined set, not
  per-field, since no current template needs a variable pinned to one specific field)
  for a save to be accepted. Always a subset of `allowed_variables`; a module-level
  check at the bottom of `default_templates.py` raises `AssertionError` at import time
  if any template violates this, so a bad registry entry fails at process startup, not
  silently at render time. Only the five security/mandatory-invitation templates
  (`email_verification`, `password_reset`, `household_invitation`,
  `calendar_share_invitation`, `platform_administrator_invitation`) require anything —
  each requires `{{link}}`, since dropping the secure link makes the notification
  actively broken (the recipient has no way to complete the flow it exists for).
  Ordinary product notifications (calendar, routines, briefing, birthdays,
  informational calendar-sharing notices) require nothing: removing a variable there
  changes the wording, it doesn't break or mislead.
- `disableable` — whether a Platform Admin may turn this notification type off at all.
  `False` for account-security and other mandatory workflows; enforced server-side in
  `routers/platform.py::update_notification_template` (not just hidden in the UI), so a
  request that bypasses a stale or tampered frontend is still rejected with 422.
- `security_critical` — a display-only flag (badge in the PCC UI) for account-security /
  authentication notifications; distinct from, but currently identical in coverage to,
  `disableable is False`.

`SAMPLE_VARIABLES` holds one realistic example value set per template, used by the PCC
preview panel and Test Centre so every registered template can be rendered without a
real event/invitation/user to source variables from.

Saving an override that drops a `required_variables` placeholder is rejected at write
time (`PUT /notification-templates/{type}` → 422, "Template must include required
placeholder(s): {{link}}.") — checked with the exact same subject+body-combined logic
described above, alongside (not instead of) the existing unknown-placeholder check.
Nothing is auto-inserted on the administrator's behalf; they must fix the wording
themselves before it can save. The PCC Templates editor's variable list marks each
required placeholder distinctly ("`{{link}}` — Required") so this isn't a surprise at
save time.

### Overrides (`NotificationTemplate` / `NotificationTemplateRevision`, `platform.py`)

A `NotificationTemplate` row is created **only when an admin actually customises** a
template/channel pair (unique on `(template_type, channel)`) — the registry is never
copied into the database, so a brand-new notification type added in code appears in PCC
immediately with zero migration or seeding step. Deleting the row (`DELETE
/notification-templates/{type}`) resets that template to the built-in default; there is
also a bulk `POST /notification-templates/reset-all` (requires `reason` +
`confirmed: true` — a `SensitiveActionRequest` — plus the frontend's own confirmation
dialog) that deletes every override row in one action.

Saving a second override over an existing one first copies the row's *previous*
subject/body into a `NotificationTemplateRevision` (undo history) before overwriting it.
`NotificationTemplate.based_on_default_version` records `DEFAULT_TEMPLATE_VERSION` (a
single package-wide integer bumped whenever a *default's wording* changes) at save time;
the API exposes this as `is_stale` — true when the built-in default has moved on since
the override was last saved — so PCC can flag "the built-in wording changed since you
customised this" without guessing from text diffs.

`NotificationChannel` on the override row means a template registered on multiple
channels (none are, today, but the schema supports it) can carry independent overrides
per channel.

### Failure handling — a malformed override can never block delivery

`render_notification()`'s override branch is wrapped in a `try/except
(UnknownTemplateVariable, MissingRequiredTemplateVariable)`: if a saved override
references a placeholder outside the template's `allowed_variables`, **or** drops one of
its `required_variables` — because it was hand-edited, or because a since-changed
registry now requires or allows something different than when it was saved — the
exception is caught, a `notification_template_render_fallback` warning is logged (via
`structlog`, not raised to the caller), and the trusted built-in default is substituted
and returned instead. The producer module and `notify()` never see the failure; a
notification is never dropped or delivered half-rendered because of a bad PCC
customisation. Both checks are also enforced up front at write time
(`validate_override_text` / `validate_required_variables`, both 422) — the render-time
fallback exists for overrides that were valid when saved but have since drifted out of
sync with a registry change (including an older override saved before
`required_variables` gained an entry it doesn't satisfy), not as the primary defence.

A **disabled** override (`NotificationTemplate.enabled = False`) is treated the same as
"no override" for rendering purposes — `render_notification()` falls through to the
default text. (Whether the notification is sent *at all* when its type is disabled is a
`notify()`/producer-level concern, not something this layer decides.)

Upgrading past a registry change (a template's default wording, or its allowed variable
set, changes in a later release) is safe by construction: existing overrides for
*other* templates are untouched, and an override that becomes invalid under the new
registry is not deleted — it simply stops applying (falls back to the new default, per
the failure handling above) until an admin revisits it, which the `is_stale` flag
surfaces.

### Security

- Rendering is plain-text `{{variable}}` substitution (`templates.py::substitute`, a
  single regex + closed allowlist lookup) — never Jinja, `str.format`, `eval`, or any
  templating engine capable of arbitrary expression evaluation, attribute access, or
  control flow. A template body is data, never code.
- The allowlist is closed per template: a variable not in `TemplateDefault.allowed_variables`
  cannot be referenced, in either the built-in default or an override, full stop —
  there is no way for a PCC-authored string to read an arbitrary field off a model, a
  settings value, or an environment variable.
- HTML email output is built by `email_branding.py` from the *resolved* subject/body and
  HTML-escapes interpolated variables before they reach markup — an override cannot
  inject markup or scripts into the branded email template.
- Editing, resetting, enabling/disabling, reset-all, previewing, and test-sending
  templates all require an authenticated `PlatformContext` via `require_roles(*OPERATORS)`
  (owner/administrator), the same platform-admin auth model as the rest of PCC — entirely
  separate from household `User` sessions. A household user (including a Home Admin) has
  no path to these endpoints regardless of their in-household role. Save/reset/reset-all
  additionally require `require_recent_auth` (a recent MFA step-up).
- Secrets — SMTP credentials, VAPID keys, API tokens — are never read, stored, or
  rendered by this layer. The Channels screen links to the existing Email/Push
  configuration pages rather than re-displaying provider settings.
- Test Centre sends go through the real delivery pipeline (real SMTP send, real
  `notify()` call for in-app) so a test is representative, but every test is prefixed
  `[Test]`, uses a freshly generated idempotency key, and performs no genuine business
  or security side effect — sending a test of `password_reset`'s wording does not reset
  anyone's password, create a session, or generate a real reset link.

### Localisation

There is exactly one locale today — UK English — and `render_notification()` takes no
locale parameter. The registry/override schema does not assume this remains true forever
(template keys are stable identifiers independent of any particular wording, and nothing
about the resolution flow is English-specific), but no locale-selection, per-locale
override storage, or translation-management UI exists yet. Adding a locale would be a
new stage of work, not a flag flip.

### Audit and delivery visibility

Template mutations reuse the **existing** platform audit trail
(`platform_audit()` → `AdministrativeAuditEvent`), not a parallel logging system:
`notification_template.updated` (covers both a wording change and an enable/disable
toggle — recorded as an `enabled: bool` field, not a separate action), `.reset`,
`.reset_all`, `.test_sent`, and `.test_failed` each record the acting administrator,
timestamp, reason, and outcome. The audited `new`/`previous` payloads intentionally carry
only structural facts (`template_type`, `enabled`, `reset_count`) — never the customised
subject/body text itself — so browsing the audit log cannot leak what an override's
wording says.

Delivery-level visibility (did a specific notification actually send, and if not, why)
is **not** a new store built for this stage — it reuses the existing
`NotificationDelivery`/`OutboxEvent` data already exposed by
`routers/communications_admin.py` (`GET /communications/health`,
`GET /communications/diagnostics`). The PCC Notifications module's Channels and Delivery
Logs screens call these same endpoints rather than duplicating the underlying storage or
retention behaviour; there is currently no separate retention policy layered on for
this stage beyond whatever `communications_admin.py` already implements.

### Platform Control Centre screens

`/control-centre/notifications/*` — Overview, Templates, Channels, Daily Briefing, Test
Centre, Delivery Logs — implemented as ordinary PCC pages (`PlatformShell` +
`NotificationsSubNav`), calling the endpoints above. The Templates screen is the
CRUD/browse/preview/reset surface; Daily Briefing is the same CRUD narrowed to the two
`briefing.title`/`briefing.intro` fragments (the daily briefing's actual content
selection — which events/meals appear, ordering, empty-day rotation — is not exposed
here and is not affected by this stage). The previous `/control-centre/notification-templates`
page now redirects to `/control-centre/notifications/templates` rather than being
deleted outright, so any existing bookmark or link keeps working.

### Birthdays (`mykhaya/notifications/birthdays.py`)

`notifications.birthdays` sends exactly two wording variants, never a third, regardless
of whether the birthday belongs to an adult user or a child: `birthday.reminder.self`
(shown to the birthday person themself) and `birthday.reminder.other` (shown to every
other household member, with `{{display_name}}`). The **external** `notify()`
`notification_type` stays the single, unchanged string `"birthday_reminder"` for both —
this is deliberately different from the internal template key, so existing
`NotificationPreferences`/idempotency-key/delivery-log rows keyed on
`notification_type` are entirely unaffected by the split; only the wording lookup
changed, from two hard-coded f-strings to two registry entries. Trigger timing,
recipient selection (co-members of the birthday person's household, or of a child's
guardian's household), the `birthday_visible` visibility gate, and deep links are all
unchanged.

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
