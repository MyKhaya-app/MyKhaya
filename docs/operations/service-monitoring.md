# Service Monitoring Operations

How to configure, operate, troubleshoot and verify automated service
monitoring. Design: [`docs/architecture/service-monitoring.md`](../architecture/service-monitoring.md).

## Configuration

Environment (per deployment; DEV and PROD each have their own values):

| Variable | Default | Purpose |
| --- | --- | --- |
| `MYKHAYA_MONITORING_ENABLED` | `true` | Runs the monitoring runner in the scheduler and the watchdog in the worker. Off means the public page shows Unknown, never a fabricated Operational. |
| `MYKHAYA_MONITORING_WEB_URL` | `public_web_url` | Target for the web application check, when the public URL is not reachable from inside the container (local Docker). |
| `MYKHAYA_MONITORING_API_URL` | `native_api_url` | Target for the API readiness and authentication checks. |
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

## Validating public-hostname and provider checks (before public reporting)

Vantage-dependent checks start **PCC only: awaiting live validation**. For
each one, run the probe **from the scheduler container**, which uses the same
DNS resolver, egress and User-Agent as the monitor. It is read-only: one GET,
no authentication.

First print the hostnames this deployment actually uses:

```sh
docker compose exec scheduler python -c "from mykhaya.config import get_settings as g; s = g(); print(s.public_web_url, s.native_api_url, s.monitoring_web_url, s.monitoring_api_url)"
```

Then probe each (substitute the printed hostnames; DEV examples shown):

```sh
# Web application (the check expects an HTML page)
docker compose exec scheduler python -m mykhaya.monitoring.probe https://dev.mykhaya.app/

# API readiness (the check expects {"status": "ready"})
docker compose exec scheduler python -m mykhaya.monitoring.probe https://api.dev.mykhaya.app/api/v1/health/ready --expect-json status=ready

# Authentication route (read-only provider status; no sign-in)
docker compose exec scheduler python -m mykhaya.monitoring.probe https://api.dev.mykhaya.app/api/v1/auth/providers

# Timeout behaviour: an impossible budget must end promptly as a classified
# failure, never hang
docker compose exec scheduler python -m mykhaya.monitoring.probe https://dev.mykhaya.app/ --timeout 0.05
```

Each run prints one line per layer, then the verdict the monitor would record:

| Line | What it proves | If it fails |
| --- | --- | --- |
| `DNS` | The container's resolver returns addresses (normally Cloudflare anycast) | Container/host DNS: check `/etc/resolv.conf` in the container and the host resolver |
| `TLS` | TCP to the edge, and full certificate validation for the hostname (protocol, CN, issuer, expiry) | Egress firewall (connect error) or edge certificate problem (`certificate validation failed`) |
| `HTTP` | Status, latency, `server`, `cf-ray`, `cf-cache-status`, `cf-mitigated`, content type | See the verdict |
| `body` | The first 300 characters | Wrong content, or a challenge/error page |
| `Monitor verdict` | Exactly what the check records | — |

Verdicts:

- `SUCCESS`: the check is valid from this server.
- `CANNOT VERIFY (monitor error) / Blocked by a Cloudflare security challenge`:
  Cloudflare WAF/bot protection is challenging the monitor. Add a Cloudflare
  WAF *skip* rule matching `ip.src` = the server's egress IP **and**
  User-Agent `MyKhaya-Monitoring/1.0` (the User-Agent alone is spoofable),
  then probe again. Until then the check records Unknown, never an outage.
- `FAILURE / Cloudflare could not reach the origin server` (HTTP 520–524/530,
  with the Cloudflare error code, e.g. 1016 = origin DNS): the edge works but
  the origin did not answer. Look for the origin being down, the origin
  firewall not allowing Cloudflare's ranges, or a wrong origin record.
- `FAILURE / Cloudflare could not establish TLS to the origin` (525/526): the
  origin certificate, or the Cloudflare SSL mode.
- `FAILURE / DNS …` or a TLS failure: the container's own path to Cloudflare.
- `FAILURE / Request timed out` (in the `--timeout 0.05` run): the expected
  behaviour. The monitor bounds every check the same way (default 10 s).

Provider connectivity (DNS/TLS only, matching what those checks do):

```sh
docker compose exec scheduler python -m mykhaya.monitoring.probe https://history.mot.api.gov.uk/
docker compose exec scheduler python -m mykhaya.monitoring.probe https://appleid.apple.com/auth/keys
docker compose exec scheduler python -m mykhaya.monitoring.probe https://www.googleapis.com/oauth2/v3/certs
```

For DVSA, an HTTP 4xx without credentials is expected. Only the `DNS` and
`TLS` lines matter, because that is all the DVSA connectivity check uses.
Never probe a vehicle endpoint or supply a registration.

Then in PCC → Health → Automated monitoring, confirm the component itself
shows Healthy for at least 3 consecutive scheduled checks. Only then choose
Configure → tick **Affects the public status page**, with a reason that
records the probe evidence (audited as `monitoring.public_reporting_enabled`).

**If a public hostname cannot be checked reliably** (e.g. a challenge you
cannot allow-list), leave public reporting off. MyKhaya Web Application then
stays Unknown publicly, which is accurate. Optionally set
`MYKHAYA_MONITORING_WEB_URL` / `MYKHAYA_MONITORING_API_URL` to an internal
address. Those results are labelled "does not prove public availability",
stay limited-confidence, and must not be presented or enabled as an external
availability check. Use an external uptime monitor for genuine outside-in
coverage.

## Live DEV acceptance runbook

Run on DEV only, by an operator with DEV PCC Owner/Administrator access.
Never inject faults in PROD (the API and runner both refuse), and never
disrupt a real provider or account.

1. **Deploy and migrate.** After the approved DEV deployment, confirm
   migration `0125_service_monitoring` is applied (`docker compose exec api
   alembic current` shows `0125_service_monitoring (head)`) and the API
   readiness endpoint on the DEV API host returns `{"status":"ready"}`.
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
6. **Validation gate.** Every check marked *PCC only: awaiting live
   validation* has been validated with the probe procedure above, or
   deliberately left PCC-only. Confirm that none of them has opened a public
   incident while unvalidated.
7. **Controlled failure (core service).** Pick a component that is public by
   default and has no live-validation gate: **Job queue progress**
   (`background.outbox`, Background Processing, critical, 60 s). Choose
   **Simulate failure** for 15 minutes, severity Unavailable, with a reason.
   Fault injection replaces only that check's *result*; the real queue is
   untouched. Within about 3 minutes (or press **Run now** three times, at
   least 30 s apart):
   - the component shows Unavailable in PCC, with category "Simulated failure
     (DEV fault injection)";
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
   failure category, consecutive failures, last success and a PCC link. The
   alert centre shows the delivery as *sent*.
9. **No duplicates.** Leave it failing for 10+ minutes: no further alert
   email, one transition, one incident.
10. **Recovery.** **Stop simulation**. After the recovery threshold, expect
   Healthy in PCC, the incident auto-resolved on the public page, and a
   `[MyKhaya DEV] Service Recovered: …` email.
11. **Audit.** PCC Audit shows `monitoring.fault_injection_started`,
    `monitoring.check_run`, `monitoring.fault_injection_cleared`, and any
    override or acknowledgement actions.
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
