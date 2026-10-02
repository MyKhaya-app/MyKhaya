# Local container log retention

MyKhaya keeps local Docker stdout/stderr logs as a bounded, independent copy of
the application logs. Central Syslog is an additional remote destination; Graylog
availability is not required for local logging or application operation.

## Policy

The Compose stack uses Docker's `json-file` driver for each service with:

```yaml
logging:
  driver: json-file
  options:
    max-size: "20m"
    max-file: "5"
```

This retains approximately 100 MB per container, including the active file and
up to four rotated files. The persistent long-running stack contains eight
logging services (Caddy, web, API, worker, scheduler, PostgreSQL, Redis and
Mailpit), so the configured container-log ceiling is approximately 800 MB,
excluding Docker metadata and filesystem overhead. One-shot migration/test
containers use the same bound when they are created, so a full stack including
those transient containers is approximately 1 GB at most.

Caddy access logs are configured for stdout. PostgreSQL has no separate
configured persistent log destination; its server logs go to container
stderr/stdout. Redis's `/data` volume stores Redis data/AOF, not service logs.
The application, web runtime, worker and scheduler do not write log files to
their persistent application volumes.

The per-service Compose setting takes precedence over the Docker daemon's
default logging driver/options for containers created from this stack. It does
not change application log levels or add forwarding to Caddy, PostgreSQL or
Redis.

## Inspecting usage

To see the configured Compose logging policy:

```bash
docker compose config
```

To see Docker's aggregate disk usage:

```bash
docker system df -v
```

To identify container log files that are unexpectedly large on a Linux Docker
host:

```bash
sudo du -ah /var/lib/docker/containers --include='*-json.log' | sort -h | tail -20
```

The exact Docker root directory can differ; check `docker info` before relying
on `/var/lib/docker`. `docker inspect <container>` shows the active logging
driver and its configured options.

Changing Compose logging options normally requires container recreation before
the new settings take effect. For example:

```bash
docker compose up -d --force-recreate
```

Do not delete existing logs as part of changing the policy. Existing container
log files retain their previous settings until their containers are recreated.
