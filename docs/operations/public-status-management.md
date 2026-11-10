# Public Status Management

Public service state is driven by automated monitoring and by incidents
together (see [service-monitoring](../architecture/service-monitoring.md)).
Operators no longer need to declare an incident for the page to reflect a
detected failure, but manual incidents remain fully supported.

## Manual incidents

Operators create an incident with one or more affected public services
(including External services), a customer-safe title/message, an impact, an
explicit confirmation and an internal audit reason. Updates and resolution
are permanently audited. Do not paste stack traces, provider identifiers,
ticket secrets, internal hosts or security investigation detail into customer
messages.

Use Operational, Degraded Performance, Partial Outage, Major Outage or
Maintenance according to customer impact. Update during material changes and
resolve only after customer-facing recovery is confirmed. A declared incident
applies even while monitoring reports the service healthy: highest severity
wins.

## Automated incidents

When monitoring confirms a failure on a public service, it opens an incident
marked **Automated** in PCC (author "Automated monitoring") with generic
wording, updates its impact as the failure worsens or eases, and resolves it
on confirmed recovery. Treat it as your own incident: post specific customer
updates, change the lifecycle, or resolve it. Monitoring only acts again on
the next confirmed state change, so it will not immediately undo a manual
resolution.

## Overrides

Use **Health → Public reporting overrides** to:

- **Suppress** automated reporting for a service (e.g. a confirmed false
  positive while a check is being fixed). Manual incidents still apply, and
  no automated incident is opened.
- **Publish a fixed state** (e.g. Maintenance during a planned window).

Every override needs a reason and an expiry (5 minutes to 7 days), can be
revoked, and is audited.

## Retention

The public page shows a 90-day recent-history view. Incident records follow
the retention standard. Detailed monitoring observations are kept about 90
days; transitions and alerts are kept with incident history.
