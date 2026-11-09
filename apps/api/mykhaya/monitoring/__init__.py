"""Automated service monitoring.

Continuously checks MyKhaya's own services and the external providers it
depends on, persists every observation and confirmed state change, feeds the
public status page (mykhaya.status_aggregation) and alerts Platform Control
Centre administrators. See docs/architecture/service-monitoring.md.

Modules:

- ``results``: check result type and failure categories.
- ``catalogue``: every monitored component and what it maps to publicly.
- ``checks``: the check implementations (read-only, side-effect free).
- ``engine``: the runner, state machine, freshness and retention.
- ``incidents``: automatic public incidents for confirmed failures.
- ``alerts``: administrator alerts and their email delivery.
- ``http_metrics``: API request error-rate and latency counters.
- ``watchdog``: the worker's independent check that monitoring is running.
"""
