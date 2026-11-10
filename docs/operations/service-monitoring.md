# Service Monitoring Operations

How to configure, operate, troubleshoot and verify automated service
monitoring. Design: [`docs/architecture/service-monitoring.md`](../architecture/service-monitoring.md).

## Configuration

Environment (per deployment; DEV and PROD each have their own values):

| Variable | Default | Purpose |
| --- | --- | --- |
| `MYKHAYA_MONITORING_ENABLED` | `true` | Runs the monitoring runner in the scheduler and the watchdog in the worker. Off means the public page shows Unknown, never a fabricated Operational. |
| `MYKHAYA_MONITORING_WEB_URL` | `http://web:3000` | Internal address of the web container (the one Caddy proxies to). Blank = default. Never a public hostname. |
| `MYKHAYA_MONITORING_API_URL` | `http://api:8000` | Internal address of the API container, for readiness and authentication checks. Blank = default. |
| `MYKHAYA_MONITORING_WATCHDOG_URL` | unset | External dead-man's switch URL (secret; it contains the check token). |
| `MYKHAYA_MONITORING_WATCHDOG_FAIL_SUFFIX` | `/fail` | Appended while a critical component is Unavailable. |

In PCC (**Health → Automated monitoring**), per component: enabled, interval
(30–3600 s), timeout (1–30 s), failure threshold, recovery threshold (1–10),
whether it affects the public page, and severity (critical / warning / info).
Every change is audited and needs recent authentication and a reason.

Alert recipients (**Health → Alert recipients**): alert emails on/off,
recipient roles (default Owner and Administrator), additional addresses (up
to 10), cooldown (default 30 minutes), whether warning-severity alerts are
emailed, and each administrator's own opt-out. Only Owners and
Administrators see or edit the additional addresses.

During commissioning, unvalidated network/provider checks raise alerts in the
PCC alert centre only ("Not emailed: check awaiting live validation"). They
start emailing once validated (see below). Core and monitoring-system alerts
always email.

## Day-to-day

- **An alert arrives.** Open the link (the automated incident, or Health).
  Acknowledge it in the alert centre. The automated incident's public text
  is generic; add a specific customer update through the incident page if
  useful.
- **False positive.** Add a *Suppress* override for the public service with
  a reason and an expiry, then fix or retune the check (threshold, interval,
  or disable it). Overrides expire on their own.
- **Planned maintenance.** Create a maintenance incident as before, or a
  *Publish Maintenance* override. Platform maintenance mode also makes HTTP
  checks inconclusive, so expected 503s don't raise alerts.
- **Email alerts failing.** The alert centre shows failed deliveries. Fix the
  mail configuration, then use *Resend email*. Meanwhile the external
  dead-man's switch (if configured) is the out-of-band channel.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Public page shows "Live service monitoring is temporarily unavailable" | Scheduler running? `docker compose logs scheduler`; look for `monitoring.cycle_failed` / `monitoring.task_stopped_restarting`. PCC Health shows *Monitoring stopped* with the last cycle time. |
| One service Unknown | That service's components are stale: their checks error (`monitor_error` in History) or are disabled. Open History for the component. |
| External service row missing publicly | The integration is not configured or enabled in this environment (`not_applicable`), which is expected. |
| Several providers failing with "MyKhaya outbound connectivity failure" | Host DNS or egress problem, not the providers. Check the server's DNS, firewall and the `edge` Docker network. |
| No alert emails | Alert recipients: emails enabled? Recipients > 0? Alert shows a suppression reason (cooldown, info severity, no recipients)? Deliveries failed? |
| Alert email delayed while the scheduler is down | Expected: the worker watchdog dispatches monitoring alert emails itself within about a minute. If the worker is also down, only the external dead-man's switch can alert. |

## Monitoring failure recovery

1. Restart the scheduler (and the worker if needed):
   `docker compose up -d scheduler worker`.
2. State resumes from the database. Expect a **Monitoring Resumed** alert,
   and components that went stale move back to Healthy on their first good
   check.
3. If a cycle keeps failing (`monitoring.cycle_failed` in the logs),
   suspect the database or a migration mismatch: `/api/v1/health/ready`
   reports schema drift.

## Adding a new external dependency

1. Write a read-only check in `apps/api/mykhaya/monitoring/checks.py`. Prefer
   DNS/TLS (`_probe_hosts`), a public endpoint, a cheap authenticated read,
   or a passive signal from records the integration already writes. Never
   spend quota or create anything. Return `not_applicable` when the
   integration is not enabled. Return only sanitised details.
2. If it is customer-relevant, add a key and name to `EXTERNAL_SERVICES` in
   `status_aggregation.py`, and to `PublicServiceKey` in `platform_schemas.py`
   and `apps/web/components/platform-types.ts`.
3. Add a `ComponentDefinition` in `catalogue.py` with `category="external"`,
   `provider`, `service_keys`, `verifies`, `customer_impact`, and a polite
   interval (≥300 s for third parties).
4. Add tests to `apps/api/tests/test_service_monitoring.py` that prove it
   makes no side-effecting or quota-consuming requests.
5. The row is created automatically on the next cycle. No migration is needed.

## Testing

- Backend: `sh infrastructure/scripts/run-tests.sh pytest
  tests/test_service_monitoring.py`. Failures are driven through DEV fault
  injection, the same path a real failure takes; recovery uses checks that
  genuinely pass against the test PostgreSQL/Redis. Provider checks run
  against `httpx.MockTransport` and fakes that assert no side-effecting call
  is made.
- Frontend: `apps/web/app/service-status/page.test.tsx`,
  `apps/web/app/control-centre/health/monitoring-panel.test.tsx`,
  `apps/web/components/monitoring-logic.test.ts`.
- A passing mocked test is **not** evidence that live DEV or PROD monitoring
  works. Use the runbook below.

## Verifying internal checks and validating provider checks

MyKhaya's own web, API and authentication checks run over the internal Docker
network and need no validation or infrastructure change. To see exactly what
they see, run the read-only probe from the scheduler container (one GET, no
authentication, redirects not followed with `--host`):

```sh
docker compose exec scheduler python -m mykhaya.monitoring.probe http://api:8000/api/v1/health/ready --expect-json status=ready
docker compose exec scheduler python -m mykhaya.monitoring.probe http://api:8000/api/v1/auth/providers
docker compose exec scheduler python -m mykhaya.monitoring.probe http://web:3000/ --host dev.mykhaya.app
docker compose exec scheduler python -m mykhaya.monitoring.probe http://api:8000/api/v1/health/ready --timeout 0.05
```

Use the hostname of `MYKHAYA_PUBLIC_WEB_URL` for `--host`. Expected verdicts:
`SUCCESS` (a 3xx from the web container is also a healthy answer), and a
timeout for the last command. No public hostname, NetBird route, Cloudflare
rule or firewall change is involved. A failure here is a genuine internal
problem with that container.

These checks prove internal component health only, not internet
reachability (see the architecture doc).

**External provider checks** (APNs, FCM, Stripe API, DVSA, DVLA, Apple,
Google) start as *PCC only: awaiting live validation*. They make outbound
requests only. Probe each provider from the scheduler container, for example:

```sh
docker compose exec scheduler python -m mykhaya.monitoring.probe https://appleid.apple.com/auth/keys
docker compose exec scheduler python -m mykhaya.monitoring.probe https://www.googleapis.com/oauth2/v3/certs
docker compose exec scheduler python -m mykhaya.monitoring.probe https://history.mot.api.gov.uk/
```

(For DVSA, an HTTP 4xx without credentials is expected; only DNS and TLS
matter. Never probe a vehicle endpoint.) Once the component shows Healthy for
3 consecutive scheduled checks in PCC → Health, choose Configure → tick
**Affects the public status page**, with the probe evidence as the reason.
If a provider is unreachable because of this server's egress policy, leave it
PCC-only; never open inbound access for it.

## Live DEV acceptance runbook

Run on DEV only, by an operator with DEV PCC Owner/Administrator access.
Never inject faults in PROD (the API and runner both refuse), and never
disrupt a real provider or account.

1. **Deploy and migrate.** After the approved DEV deployment, run
   `docker compose exec api alembic heads` and
   `docker compose exec api alembic current`. `current` must print the same
   single revision as `heads`, marked `(head)`. Monitoring needs
   `0126_monitoring_internal_checks` or later; any later head includes it.
   The internal probes above must also return `SUCCESS`.
2. **Scheduler active.** In `docker compose logs scheduler`, look for
   `monitoring.transition` lines on first start (`unknown → healthy`).
   PCC **Health → Automated monitoring** shows *Monitoring running* and
   *Last cycle* within 30 s.
3. **Checks run at their intervals.** Open *History* for `Database`: about
   one observation per minute. `Stripe API` / `DVSA` connectivity: about one
   every 5 minutes.
4. **Results persisted.** Against the DEV database (read-only query):
   `select key, state, last_checked_at from monitor_components order by key;`
   and `select count(*) from monitor_observations where observed_at > now() -
   interval '10 minutes';` (should grow every minute).
5. **Public page reflects observations.** `https://status.dev.mykhaya.app`:
   services show Operational (or Unknown where DEV has no traffic or the
   integration is off, which is correct). External services appear only for
   integrations enabled in DEV.
6. **Validation gate.** Web, API and authentication show Healthy without
   any validation step. Every external provider check marked *PCC only:
   awaiting live validation* has been validated with the probes above, or
   deliberately left PCC-only. Confirm none of them opened a public incident
   or sent an email while unvalidated.
7. **Controlled failure (core service).** Pick a component that is public by
   default and has no live-validation gate: **Job queue progress**
   (`background.outbox`, Background Processing, critical, 60 s). Choose
   **Simulate failure** for 15 minutes, severity Unavailable, with a reason.
   Fault injection replaces only that check's *result*; the real queue is
   untouched. The simulated failure is applied **immediately** as an
   already-confirmed failure. There is no wait for the failure threshold,
   and the threshold itself is not changed. If PCC answers "A monitoring
   cycle is in progress", nothing was applied; try again a few seconds
   later. Straight away:
   - the component shows Unavailable in PCC, with category "Simulated failure
     (DEV fault injection)" and *DEV fault injection active until …*;
     *History* shows one transition whose detail says it was confirmed
     immediately by DEV fault injection;
   - `status.dev.mykhaya.app` shows Background Processing as **Major
     Outage**, an automated incident "Background Processing: outage" with the
     generic message, and the overall banner "Major service disruption";
   - every other service is unchanged.

   *Optional, external service:* only if DVSA is enabled in DEV **and**
   `provider.dvsa.connectivity` has been validated and set to public in step
   6, repeat with it. Expect DVSA MOT History Major Outage, the overall banner
   capped at "Partial service disruption", and core services unchanged.
8. **Real alert received.** DEV PCC Owners/Administrators receive
   `[MyKhaya DEV] Service Unavailable: …` with environment, detection time,
   failure category "Simulated failure (DEV fault injection)", its detail,
   consecutive failures (1), last success and a PCC link. The alert centre
   shows the delivery as *sent*. Email follows the existing controls: no
   email for a component that is not public and awaits live validation, for
   *info* severity, for warning severity when that is switched off, or when
   the same kind of alert was emailed for the component within the cooldown
   (default 30 minutes). Repeating the drill within the cooldown records the
   alert in PCC without a second email.
9. **No duplicates.** Leave the simulation active for 10+ minutes: scheduled
   checks keep recording *simulated* observations, but there is no further
   alert email, still one transition and one incident.
10. **Recovery.** Choose **Stop simulation** once. It ends the simulation and
   runs the component's real check at once. If that check succeeds, expect
   right away: Healthy in PCC, a recovery transition whose detail says DEV
   fault injection stopped, the incident auto-resolved on the public page,
   and a `[MyKhaya DEV] Service Recovered: …` email. There is no wait for
   the recovery threshold. If the real check fails, PCC says so and the
   failure is reported and recovers under the normal thresholds. If PCC
   says a monitoring cycle was in progress, the row still shows *Held by
   DEV fault injection*; choose **Stop simulation** again. If a simulation
   simply expires, the component stays *Held by DEV fault injection* until
   **Stop simulation** is chosen, or until it recovers through the normal
   recovery threshold.
11. **Audit.** PCC Audit shows `monitoring.fault_injection_started` and
    `monitoring.fault_injection_cleared` (a *failed* `cleared` entry means
    the start was withdrawn because a cycle was in progress), plus any
    `monitoring.check_run`, override or acknowledgement actions.
12. **Restart behaviour.** During a simulated failure, run `docker compose
    restart scheduler worker`. Afterwards the component is still Unavailable
    (counters persisted), with no second incident and no duplicate alert.
13. **Monitoring stops.** `docker compose stop scheduler` for 6 minutes.
    The public page shows "Live service monitoring is temporarily
    unavailable", PCC shows *Monitoring stopped*, and administrators receive
    **Monitoring Stopped** (sent by the worker watchdog). `docker compose
    start scheduler` → **Monitoring Resumed**.
14. **DEV/PROD independence.** While steps 7–13 run, PROD's
    `status.mykhaya.app` and PROD PCC show none of it, and no PROD
    administrator receives a DEV-tagged alert (unless they are also a DEV
    administrator).
15. **Dead-man's switch** (if configured for DEV): its dashboard shows
    regular pings; during step 7 it receives `/fail` pings; during step 13
    it alerts on missed pings.

Record the results (timestamps, screenshots of PCC and the status page, and
the alert emails) before recommending the PROD rollout.
