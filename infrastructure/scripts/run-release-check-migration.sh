#!/usr/bin/env sh
set -eu

project="${RELEASE_COMPOSE_PROJECT:-mykhaya-release-check}"
case "$project" in
  ''|*[!a-z0-9_-]*)
    echo "RELEASE_COMPOSE_PROJECT must contain only lowercase letters, digits, '_' or '-'" >&2
    exit 2
    ;;
esac

cleanup() {
  docker compose -p "$project" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

# The explicit project name is mandatory: this probe must never resolve to the
# persistent `mykhaya` project or any caller's unrelated Compose project.
docker compose -p "$project" run --rm migrate alembic heads
