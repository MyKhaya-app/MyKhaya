# Platform Health

PCC **Health** has two parts.

**Live diagnostics** (the cards at the top) run when the page is opened or
*Run checks* is pressed. They use Healthy, Degraded, Unavailable and Unknown;
each observation has an explanation, check time, last success where known
and a safe operator action. Unknown is the correct state when no
authoritative observation exists. PostgreSQL and Redis are actively checked;
worker and scheduler use database heartbeats; email and push are computed
from real delivery records; file storage is probed; backups use recorded
backup runs. The **External dependencies** card summarises the persisted
automated monitoring of Stripe, DVSA, DVLA, Apple/Google sign-in and the push
gateways. It never runs a second live probe and never claims Healthy without
observations behind it.

**Automated monitoring** (below the cards) is continuous and persisted: every
monitored component and external dependency with its state, confidence, last
check, latency and sanitised last failure; check history; on-demand runs;
configuration; DEV-only fault injection; the alert centre with delivery
status; public reporting overrides; and alert recipients. It also shows when
monitoring itself has stopped. See
[service-monitoring.md](service-monitoring.md) and
[the architecture](../architecture/service-monitoring.md).

Restore-test results, migration drift beyond the readiness check, disk
capacity beyond the storage probe, and response time from outside the
server's own network still need deployment integrations, and remain Unknown
or unavailable.

Never expose internal health through the public status API.
