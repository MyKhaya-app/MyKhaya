#!/bin/sh
# Runs mykhaya.billing_readiness (Phase 7) against this deployment's actual
# configuration — the real compose.yml `api` service, not the isolated test
# stack, since the whole point is checking real environment configuration.
# See docs/operations/billing-production-readiness.md#readiness-command.
#
# Usage:
#   infrastructure/scripts/billing-readiness.sh                # config-only checks
#   infrastructure/scripts/billing-readiness.sh --check-stripe  # also calls the live Stripe API (test mode only — refuses a live key)
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

docker compose run --rm --no-deps api python -m mykhaya.billing_readiness "$@"
