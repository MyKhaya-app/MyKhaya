# Automated Service Monitoring

MyKhaya continuously checks its own services and the external providers it
depends on, persists every observation and confirmed state change, feeds the
public status page, opens customer-safe incidents for confirmed failures and
alerts Platform Control Centre (PCC) administrators. Code:
`apps/api/mykhaya/monitoring/`. Operations and runbooks:
[`docs/operations/service-monitoring.md`](../operations/service-monitoring.md).

## Why it exists

Before this, the public status page derived every service's state solely from
manually declared incidents (`status_aggregation.service_states_from_impacts`),
and PCC Health ran its checks only when someone opened the page. Nothing was
persisted, nothing ran in the background, nothing alerted, and a service with
no declared incident was always shown as Operational, even if it was down or
nobody was checking. The model is now: automated observations, real
application failure signals, manual incidents, maintenance, overrides and
monitoring freshness combine into the public state.

## Components

```
scheduler process                 worker process                API process
┌──────────────────────────┐      ┌──────────────────────┐      ┌───────────────────────┐
│ notification scan loop   │      │ job loop (outbox)    │      │ request middleware     │
│ monitoring.run_forever ──┼─┐    │ watchdog_tick (60 s) │      │  → http_metrics (5xx,  │
│  (separate asyncio task) │ │    └──────────┬───────────┘      │    latency) → Redis    │
└──────────────────────────┘ │               │                  │ /status, /config/public│
                             ▼               ▼                  │ /platform/monitoring/* │
                  PostgreSQL (this environment only)            └───────────┬───────────┘
   monitor_components · monitor_observations · monitor_transitions          │
   monitor_alerts · monitor_overrides · public_incidents (source=automated) ◀┘
   operational_heartbeats("monitoring") · notification_deliveries / outbox
```

| Module | Responsibility |
| --- | --- |
| `results` | `CheckResult` and the sanitised failure categories |
| `catalogue` | Every monitored component: what it verifies, which public service(s) it feeds, default interval/thresholds/severity |
| `checks` | Read-only check implementations |
| `engine` | Runner, state machine application, stale sweep, retention, external dead-man ping |
| `state` | Pure rules: freshness, effective state, thresholds, public impact |
| `incidents` | Automatic public incidents |
| `alerts` | Administrator alerts, recipients, email via the Notification Engine |
| `http_metrics` | Request error-rate/latency counters for the API and Authentication monitors |
| `watchdog` | Worker-side check that the runner itself is alive |

## Health signals and confidence

A success does not always prove the same thing. Each component records a
confidence: **verified** (the check exercised the real dependency) or
**limited** (reachability only, observed from MyKhaya's own server, or no
traffic to judge). A service whose components are all fresh and verified is
published with confidence `verified`; otherwise `limited`; with no fresh
observation at all, the state is `unknown`.

| Public service | Component | Signal | Confidence |
| --- | --- | --- | --- |
| MyKhaya Web Application | `web.http` | GET `/` on the web container over the internal Docker network (`http://web:3000`, public Host header as Caddy sends it; redirects never followed): HTTP status, `text/html`, latency | verified (internal component health) |
| API | `api.database` | `SELECT 1` and latency | verified |
| API | `api.redis` | `PING` | verified |
| API | `api.ready` | GET `/api/v1/health/ready` on the API container over the internal Docker network (`http://api:8000`) | verified (internal component health) |
| API | `api.error_rate` | Share of real customer API requests answered 5xx over 5 minutes (≥5 % degraded, ≥25 % unavailable), average latency (>3 s degraded) | verified with ≥20 requests, otherwise limited |
| Authentication | `api.database`, `api.redis` | as above | verified |
| Authentication | `auth.endpoint` | GET `/api/v1/auth/providers` on the API container over the internal Docker network (read-only; no sign-in, no account) | verified (internal component health) |
| Authentication | `auth.error_rate` | 5xx share on `/api/v1/auth/*` | verified with ≥10 requests |
| Email Delivery | `email.smtp` | Connect, TLS, AUTH, NOOP, QUIT. Never MAIL/RCPT/DATA. Every 5 minutes. | limited |
| Email Delivery | `email.delivery` | Real delivery outcomes in 30 minutes; emails queued >15 minutes | verified when there is traffic |
| Notifications | `notifications.push_delivery` | Real production push outcomes (Web Push, Android, production APNs) in 60 minutes | verified when there is traffic |
| Notifications | `notifications.apns`, `notifications.fcm` | DNS/TLS to the push gateways (only when devices are registered) | limited |
| Background Processing | `api.database`, `api.redis` | as above | verified |
| Background Processing | `background.worker` | Worker heartbeat age (>90 s degraded, >300 s unavailable) | verified |
| Background Processing | `background.outbox` | Due work waiting while no job has finished for 5 / 15 minutes | verified |
| Background Processing | `background.failed_jobs` | Jobs currently failing and retrying (≥5 / ≥25) | verified |
| Billing & Subscriptions, Stripe Payments | `billing.stripe_api` | One authenticated `GET /v1/balance` with this environment's key, every 5 minutes. 401 = configuration error, 429 = rate limited, 5xx = provider error | verified (limited for a restricted key) |
| Billing & Subscriptions, Stripe Webhook Processing | `billing.stripe_webhooks` | Webhook processing failures in the last hour (≥3 / ≥10) | limited: cannot see Stripe silently not sending |
| DVSA MOT History | `provider.dvsa.connectivity` | DNS/TLS to the DVSA API and token hosts | limited |
| DVSA MOT History | `provider.dvsa.observed` | Outcomes of real customer MOT lookups (`driveway_mot.record_provider_health`): fails only on a *new* failure since the last check | verified when there are lookups |
| DVLA Vehicle Enquiry | `provider.dvla.connectivity` | DNS/TLS to the configured DVLA endpoint | limited |
| Apple Sign-In / Google Sign-In | `provider.apple.sign_in`, `provider.google.sign_in` | Fetch the public JWKS signing keys | limited (not a full sign-in) |
| (internal) | `monitoring.runner` | Runner heartbeat age, observed by the worker | verified |

Checks for integrations not configured or enabled in the environment report
`not_applicable`; the matching External Services row is then not published at
all. Billing background jobs are not separately monitored: no billing-specific
job topic exists today.

No check creates a payment, customer, sign-in, account, webhook delivery,
push, email, or DVSA/DVLA vehicle lookup. DVSA and DVLA quota is never spent
by monitoring.

## MyKhaya monitors itself from inside its own environment

MyKhaya's own components are checked from within the trusted application
environment: PostgreSQL and Redis directly, heartbeats, delivery and failure
records, request metrics, and the web and API containers over the internal
`app` Docker network, at the same addresses Caddy proxies to (`web:3000`,
`api:8000`; `MYKHAYA_MONITORING_WEB_URL` / `MYKHAYA_MONITORING_API_URL`,
identical in DEV and PROD). No self-check uses a public hostname, so
monitoring needs no NetBird service, DNS record, Cloudflare rule, firewall
opening or TLS exception. The web check sends the public Host header and
`X-Forwarded-Proto: https` exactly as Caddy does, so the web app routes it as
a customer request, and it never follows redirects, so nothing leaves the
internal network.

**Internal health is not internet reachability.** These checks prove that the
web, API and authentication services are running and answering. They do not
prove that customers can reach MyKhaya through DNS, Cloudflare, NetBird or
TLS, and results say so ("checked over the internal Docker network …").
Outside-in reachability needs a separate, externally hosted uptime monitor
(and the optional dead-man's switch catches a host that stops checking in);
MyKhaya does not open its infrastructure to measure it from inside.

Before migration `0126_monitoring_internal_checks`, these three checks used
public hostnames. That migration resets their history (which measured a
route a NetBird-protected deployment deliberately blocks) to Unknown, so the
first internal result sets the real state with no false recovery alert, and
returns them to public reporting unless an administrator configured them
explicitly.

## Live-validation gate (external providers only)

Seven checks leave MyKhaya for a third party (`requires_live_validation=True`):
the APNs and FCM gateways, the Stripe API, DVSA and DVLA connectivity, and the
Apple and Google key endpoints. They make outbound requests only, never need
inbound access, but whether this server's egress reaches each provider can
only be proven on the live environment. They therefore **start PCC-only**
(`public_visible = false`): they run, record and appear in PCC, but cannot
change the public page or open an incident, and their alerts are not emailed
(`awaiting_validation`). An Owner/Administrator enables public reporting per
check after validating it (Health → Configure → "Affects the public status
page"), audited as `monitoring.public_reporting_enabled`.

All internal checks, including web, API and authentication, are public from
the start.

### Cloudflare-fronted providers

`classify_public_route` (used by the probe for external endpoints) still
separates DNS, edge TLS, Cloudflare WAF challenges and blocks (reported as
"cannot verify", never an outage), origin unreachable (520–524, 530) and
origin TLS (525/526) when a provider is behind Cloudflare.

## Failure categories

`provider_outage`, `connectivity`, `dns`, `tls`, `timeout`, `auth_config`,
`rate_limited`, `unexpected_response`, `error_rate`, `latency`, `backlog`,
`heartbeat`, `delivery_failures`, `not_configured`, `monitor_error`, `stale`,
`simulated`, `egress`, and the Cloudflare categories above (`edge_origin_unreachable`, `edge_origin_tls`, `edge_error`, `waf_challenge`). **Egress**: when three or more *unrelated* external
providers fail at the network level in the same cycle, the failures are
relabelled as a probable MyKhaya-side outbound network or DNS problem rather
than three provider outages. Details are sanitised strings produced by the
checks: no exception text, credentials, tokens, response bodies or internal
addresses.

## State machine

States: `healthy`, `degraded`, `unavailable`, `unknown`, `not_applicable`
(plus `disabled` when a component is turned off in PCC).

- Unknown/Not applicable → Healthy on the first success.
- Any state → Degraded/Unavailable only after `failure_threshold` (default 3)
  consecutive failures; the check chooses which.
- Degraded/Unavailable → Healthy only after `recovery_threshold` (default 3,
  2 for slower external checks) consecutive successes.
- Unavailable never de-escalates to Degraded; it recovers to Healthy.
- `inconclusive` (nothing new to judge) and `monitor_error` (the check could
  not run) never move counters or state.
- **Freshness**: a component is stale once it has gone ~3 intervals (minimum
  interval + 2 minutes) without a conclusive result. Stale components are
  reported Unknown at read time immediately, and the runner's stale sweep
  records a `→ unknown` transition (category `stale`) and alerts.
- If the runner's own heartbeat is older than 3 minutes, every component is
  reported Unknown.

All of this is persisted in `monitor_components`, so restarts resume with the
same counters and states, and never falsely reset or reopen incidents.

## Public status aggregation

`status_aggregation.compute_status_snapshot` is the single source for the
public page, the Help & Support summary and the PCC incident list. Per
service, in order:

1. An active override: forced state, or "suppress" (ignore automated
   monitoring; manual incidents still apply).
2. Active incidents (manual or automated), including maintenance.
3. Automated monitoring: Degraded → Degraded Performance; Unavailable →
   Major Outage for a critical component, Partial Outage otherwise.
4. Highest severity wins between 2 and 3. With no fresh automated
   observation and no incident, the state is **Unknown**, never Operational.

Overall: the worst service state, with each external service's contribution
capped at Partial Outage (one provider failing never reads as "Major service
disruption"). If the worst known state is Operational but any core service
is Unknown, the overall is Unknown ("Some services could not be verified", or
"Live service monitoring is temporarily unavailable" when the runner has
stopped).

The public payload is additive. Existing fields are unchanged; new ones are
`services[].confidence`, `services[].last_checked`, `external_services`,
`monitoring.active` and `generated_at`. `state` gains the computed value
`unknown`. Nothing else reaches the public page: no component names,
categories, latency, failure detail or provider identifiers.

## Automatic incidents

On a confirmed transition affecting a public service, `incidents` opens,
escalates, eases or resolves that service's open automated incident
(`public_incidents.source = 'automated'`, `monitor_service_key`,
`created_by = NULL`). Wording is fixed and generic ("Our automated
monitoring has detected a problem affecting DVSA MOT History…"). Automated
incidents are ordinary incidents: administrators can update, resolve or
delete them through the existing endpoints. Monitoring acts again only on the
next confirmed transition, so a manual resolution is never immediately
undone. An active override on the service stops automated incidents.

## Alerts

Every alert-worthy transition creates a `monitor_alerts` row in the same
transaction (unique `dedupe_key`, so concurrent runners or retries can never
raise it twice):

| Transition | Alert |
| --- | --- |
| → Degraded | Service Degraded |
| → Unavailable (including escalation from Degraded) | Service Unavailable |
| Degraded/Unavailable → Healthy | Service Recovered |
| → Unknown because stale, or the runner stops | Monitoring Stopped |
| Unknown (stale) → Healthy, runner returns | Monitoring Resumed |

Alerts fire on transitions only, so a sustained failure produces one alert.
A per-component, per-kind **cooldown** (default 30 minutes) suppresses
flapping. Severity `info` and disabled alerting are recorded but not
emailed; the reason is stored and shown in PCC.

**Commissioning.** Alerts from a check still awaiting live validation
(`requires_live_validation` and public reporting not yet enabled) are
recorded and shown in PCC with reason `awaiting_validation`, but not emailed.
Validating the check (the audited "Affects the public status page" switch)
turns its emails on. The monitoring runner and every deterministic check
(database, Redis, worker, queue, error rates, real delivery outcomes) are
never gated, so monitoring-system and core-service failures always email.

### Alert channels

- **Email.** Through the Notification Engine (`notify()`, type
  `platform.monitoring_alert`, in `MANDATORY_EMAIL_TYPES`, sent with
  `recipient_email` because PCC administrators have no consumer account).
  Each recipient gets a `notification_deliveries` row (idempotency key
  `monitoring_alert:<alert>:<attempt>:<recipient>:email`) and an outbox
  event retried with backoff by the worker. Queued alerts survive restarts.
  Recipients: active administrators in the configured roles (default Owner
  and Administrator) minus individual opt-outs, plus configured additional
  addresses. Additional addresses are personal data: only Owners and
  Administrators can see or change them. Other roles see whether alerting is
  on, the recipient roles and counts.
- **PCC alert centre** (Health page). Every alert, its delivery records
  (sent, queued, failed or cancelled), the suppression reason,
  acknowledgement, and a resend action.
- **Push is not available.** PCC administrators are a separate identity
  (`platform_administrators`) with no push registration, so this is a known
  gap. The independent dead-man's switch below covers the "email itself is
  down" case.

## Monitoring the monitor

- The runner writes `operational_heartbeats('monitoring')` after each cycle;
  if it is older than 3 minutes, the public page shows Unknown.
- The worker's `watchdog_tick` (once a minute, advisory-locked) records the
  runner's liveness as component `monitoring.runner`. Two failing ticks
  raise **Monitoring Stopped**. While the scheduler heartbeat is stale, the
  watchdog pushes pending monitoring-alert emails onto the job queue itself,
  so an alert does not wait for the dead scheduler.
- Checks that keep erroring, or stop producing results, go stale and are
  swept to Unknown, with an alert.
- A failed cycle (including database write failures) writes no heartbeat,
  so it surfaces through the watchdog.
- **External dead-man's switch** (optional, recommended for PROD):
  `MYKHAYA_MONITORING_WATCHDOG_URL` (e.g. a healthchecks.io check). The
  runner pings it after each healthy cycle and pings `<url>/fail` while any
  critical component is Unavailable. A missed ping (host, Docker, network or
  the whole platform down) or a fail ping makes the external service alert on
  its own, independently of MyKhaya's email.

## Concurrency, performance and safety

- One runner at a time: a PostgreSQL session advisory lock per cycle;
  component rows updated under `SELECT … FOR UPDATE`; unique alert keys;
  idempotent delivery keys.
- The runner is a separate asyncio task in the scheduler: provider latency
  never delays reminder scans and never touches API requests. Checks run
  concurrently (at most 8), each with a timeout (default 10 s).
- Request metrics are a synchronous in-memory dict update per request,
  flushed to Redis at most every 10 s by a background task; Redis problems
  are swallowed.
- Retention: observations are purged after 90 days (hourly). Transitions,
  alerts and incidents follow the incident history retention.
- PCC endpoints: read for every role; configuration, on-demand runs,
  overrides, DEV fault injection, alert settings and resends require
  Owner/Administrator, recent authentication, a reason, and are audited.
  Acknowledgement is open to support operators. Fault injection is refused
  in production by both the API and the runner.

## DEV and PROD separation

Every monitoring table lives in the environment's own database; nothing is
keyed by or shared across environments. Provider checks use the
environment's own configuration and credentials (`resolve_stripe_config`,
`dvsa_*`, `dvla_environment`, Apple/Google settings). Alert subjects carry the
environment label (`[MyKhaya DEV]` / `[MyKhaya PROD]`), recipients are that
environment's PCC administrators, and the dead-man URL is per environment.
A DEV failure therefore cannot affect PROD status or alerts, and vice versa.

## Limitations

- Web, API and authentication health is internal component health. A
  failure only visible from outside (DNS, Cloudflare, NetBird, certificate
  expiry) is not detected by MyKhaya itself; it is caught by the external
  dead-man's switch only if it also stops the pings. Use an externally hosted
  uptime monitor for outside-in reachability.
- Provider status feeds (Stripe, Apple, Google) are not consumed: no feed
  format was verified for this release. Provider health comes from direct
  checks and real-traffic observations.
- Passive signals need traffic. With little traffic, components report
  limited confidence or stay inconclusive rather than claim health.
- PCC administrators cannot receive push.
- The public status frontend still shares the platform's deployment; see
  [public-status-service.md](public-status-service.md) for the
  independent-availability proposal.
