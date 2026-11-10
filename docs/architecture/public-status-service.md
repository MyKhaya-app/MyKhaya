# Public Status Service

`status.mykhaya.app` (PROD) and `status.dev.mykhaya.app` (DEV) are
unauthenticated and read `/api/v1/status` from their own environment. Each
shows seven MyKhaya services (MyKhaya Web Application, Authentication, API,
Email Delivery, Notifications, Background Processing, Billing &
Subscriptions) and a separate **External services** section for
customer-relevant providers in use in that environment (DVSA MOT History,
DVLA Vehicle Enquiry, Stripe Payments, Stripe Webhook Processing, Apple
Sign-In, Google Sign-In).

## Where the state comes from

Service state combines automated monitoring observations, active incidents
(manual or opened automatically by monitoring), scheduled maintenance,
administrator overrides and monitoring freshness. See
[service-monitoring.md](service-monitoring.md) for the full rules. In short:

- A confirmed automated failure changes the affected service and opens a
  generic, customer-safe incident without anyone declaring it.
- A declared incident still applies even when monitoring says healthy
  (highest severity wins).
- With no fresh automated observation, a service is **Unknown**, never
  Operational. If monitoring has stopped, the banner says "Live service
  monitoring is temporarily unavailable".
- A single external provider failing contributes at most "Partial service
  disruption" to the overall banner.
- Each service carries a `confidence` (`verified`, `limited`, `none` or
  `override`); the page notes "Limited monitoring" or "Not currently
  verified" where relevant.

## Public contract

The response is additive over the original contract: `overall`,
`overall_message`, `services[{key,name,state}]`, `current_incidents`,
`recent_incidents` and `last_updated` are unchanged in shape. Additions:
`services[].confidence`, `services[].last_checked`, `external_services`,
`monitoring.active`, `generated_at`. `state`/`overall` may be the computed
value `unknown`.

The contract never contains database, Redis or queue detail, worker or
scheduler names, component names, failure categories, latency, provider
error text, versions, commits, user counts, security events, backups,
hostnames, addresses or topology. Automated incidents use fixed generic
wording; their internal notes stay in PCC.

## Independent availability (proposal; not yet deployed)

The status frontend is served by the same web/API deployment and database as
the platform, so a whole-platform outage also takes the status page down.
That is exactly when customers need it. This is an availability gap, not a
data-separation one.

Built in this release:

- `GET /api/v1/status/snapshot` returns the same payload with `Cache-Control:
  public, max-age=30, stale-if-error=86400` and a `generated_at` timestamp,
  so an edge cache or an external poller can keep serving the last good copy
  and show its age honestly.
- An optional external dead-man's switch (`MYKHAYA_MONITORING_WATCHDOG_URL`)
  alerts operators independently when the platform stops checking in.

Proposed next step (needs an infrastructure decision and approval):

1. Host a small static status page (the same markup and CSS as
   `apps/web/app/service-status`) on an independent origin, e.g. a static
   host or object storage + CDN in a different provider/region from the
   application server. Point `status.mykhaya.app` at it.
2. A scheduled job outside the application host (CI schedule or a small
   serverless function) fetches `/api/v1/status/snapshot` every minute and
   publishes `status.json` next to the page.
3. The page renders `status.json`. If `generated_at` is older than about
   3 minutes, it shows "We can't reach MyKhaya right now; last confirmed
   status at HH:MM" over the last good data, instead of an empty error.
4. Operators can publish a manual `status.json` override directly to the
   static origin during a total outage.

This keeps the existing visual design, adds no new monitoring platform and
removes the shared failure domain. Until it is deployed, the documented
limitation stands.
