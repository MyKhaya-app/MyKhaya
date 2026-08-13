#!/bin/sh
# Runs the backend test/lint/typecheck/format container against an isolated,
# disposable postgres-test/redis-test pair (compose.test.yml) instead of the
# persistent postgres/redis the dev stack uses — so test runs can never wipe
# platform settings, exhaust rate limits, or leave scheduler-visible junk data
# behind in the long-lived development database. See
# docs/operations/dev-deployment.md#automated-tests-use-an-isolated-database.
#
# Usage: run-tests.sh [COMMAND ARGS...]
#   run-tests.sh                              # full pytest suite (default CMD)
#   run-tests.sh ruff check mykhaya tests
#   run-tests.sh mypy mykhaya
#   run-tests.sh pytest tests/test_x.py -v
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

compose() {
  docker compose -f compose.yml -f compose.test.yml --profile tools "$@"
}

cleanup() {
  compose down -v --remove-orphans postgres-test redis-test migrate-test test >/dev/null 2>&1 || true
}
trap cleanup EXIT

compose build migrate-test test
compose up -d --wait postgres-test redis-test
compose run --rm --no-deps migrate-test
compose run --rm --no-deps test "$@"
