# Public Status Service

`status.mykhaya.app` is unauthenticated and uses `/api/v1/status`. It deliberately maps incidents to six public services: web application, authentication, API, email delivery, notifications and background processing.

The contract cannot contain database or Redis detail, queue depth, workers, scheduler, versions, commits, user counts, security events, backups, hostnames, addresses or topology. Without an active incident a service is shown as Operational; operators explicitly publish degraded, outage or maintenance state.

The first version reuses the stateless web/API deployment and database, so it may be unavailable during a whole-platform failure. Before public launch, deploy the status frontend at an independent static/edge origin with a cached public-status snapshot or external status provider. This is an availability blocker, not a data-separation blocker.
