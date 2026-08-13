# Milestones

Durable record of MyKhaya's major product/architecture milestones — when a milestone is
closed, no further architectural redesign happens within it; only bug fixes,
performance improvements and (where applicable) new channel/module integrations.

## Communications Engine — Version 1 — COMPLETE

Closed 2026-08-07.

The single Notification Engine (`notify()`) that every user-facing communication in
MyKhaya flows through — email, push, in-app, and any future channel — with user
preferences, quiet hours, mandatory delivery for identity/security workflows,
admin-editable templates, and full operator visibility (Timeline, Diagnostics, Health
dashboard). See `docs/architecture/notification-engine.md` for the architecture and
`docs/engineering/engineering-standards.md#notification-architecture` for the
non-negotiable rule this milestone established: no module sends email or push
directly, creates in-app notifications directly, or enqueues outbox events for a
communication directly.

Delivered in ten stages: data model, engine core, push (VAPID), calendar reminders,
daily briefing, household routines, birthdays (treated as a first-class household
feature, not just another reminder type), migrating the three pre-existing hardcoded
email flows onto the single pipeline, admin-editable notification templates
(override-only storage — built-in defaults never copied into the database), and the
Communications Timeline/Diagnostics/Health dashboard in Platform Admin.

From this point, Communications is foundational infrastructure other modules integrate
with — Wish Lists, shopping, documents, and anything else that needs to notify someone
plugs into `notify()` rather than building its own delivery path.

## Calendar Experience — in progress

Started 2026-08-07. The next major product milestone: a TimeTree-inspired month view,
continuous multi-day event bars, overlapping-event layout, family member colours, and
mobile-first rendering. See `docs/design/` for the visual identity this must follow.

## Not yet started

Home Experience (a calm "what's happening today" dashboard built on top of the now-complete
Communications data — today's events, birthdays, routine reminders, the daily briefing),
Wish Lists, Shopping, Documents — all deliberately paused until Calendar and Home are in
a strong state, per `docs/product/product-vision.md`'s "does this make life together
simpler" test and the Home-screen-justification rule in
`docs/engineering/engineering-standards.md`.
