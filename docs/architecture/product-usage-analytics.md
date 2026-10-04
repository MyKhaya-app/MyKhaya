# Product usage analytics

Product usage analytics is separate from authentication timestamps, the
heartbeat/Last Active signal, security audit records, and notification
delivery records.

## Events

`ProductUsageEvent` stores only stable semantic events: `app_open`, module view
events, and confirmed calendar, list, and meal mutations. The controlled module
taxonomy is `app`, `calendar`, `nudges`, `lists`, `meals`, `notifications`,
`family`, `home`, and `settings`. Platforms are `web`, `ios`, and `android`.
The server derives the user from authentication and timestamps events in UTC.
The client platform is attribution only, never an authorisation decision.

Payloads deliberately have no free-form metadata, request body, route, title,
search text, item text, or other user-generated content. Client events use a
bounded opaque usage-session identifier in session storage. It is unrelated to
authentication sessions and rotates after 30 minutes without product events.
Event keys provide idempotency across remounts and retries.

The initial client instrumentation is app-open and one module-view signal per
usage session. Confirmed calendar-event, list, list-item-completion, and meal
creation mutations are recorded server-side after their domain transaction
succeeds. Analytics failures are logged and swallowed; they cannot roll back
or fail a user action.

## Aggregation and definitions

Raw events are stored in PostgreSQL for 90 days. A scheduler recomputes the
previous UTC day into normalized `ProductUsageDailyAggregate` rows and can be
rerun safely. Aggregates contain counts only, not user identifiers. Managed
demo Homes and their fixture owners are excluded using the canonical
`ManagedDemoHome` records, never email addresses.

- DAU: unique users with qualifying activity in a UTC reporting day.
- WAU: unique users with qualifying activity in the preceding seven UTC days.
- MAU: unique users with qualifying activity in the preceding thirty UTC days.
- Active Home: a Home with at least one qualifying user event in the period.
- Returning user: active in the period and active before its start.
- New user: account creation, not first activity.

These counts must not be inferred from raw event totals. Per-user local-day
reporting is deferred; aggregate boundaries are UTC.

## Adding an event

Add a stable event and, where needed, its module to the enums and migration.
Use the shared client helper only for a genuine screen/product entry, or call
`record_usage_event` after a successful server mutation. Never include free-form
metadata or identifiers in event payloads, and add idempotency and privacy tests.

## PCC reporting

Privileged operators can read `GET /api/v1/platform/usage/report`. The report
defaults to the production classification and a 30-day UTC period. Operators
may select 7, 30, or 90 days, one of the explicit audience classifications
(`production`, `all`, `demo`, `test`, or `apple_review`), and an optional
platform (`web`, `ios`, or `android`). This endpoint is PCC-only and requires
the existing recent-auth platform role policy.

The report uses bounded raw events for the selected trend, module, platform,
and event breakdowns. DAU is the final UTC day in the period; WAU and MAU use
their full trailing seven- and thirty-day windows even when the selected trend
period is shorter. Returning users are active in the selected period and have
retained activity before its start. Because raw events are retained for 90
days, returning-user history is necessarily limited to that retention window.
Managed demo homes and their fixture owners are excluded from the default
production view with NULL-safe predicates. The endpoint does not add a second
telemetry pipeline or expose event payload data.
