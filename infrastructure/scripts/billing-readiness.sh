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

# DEV after a cutover uses its own overlays; everywhere else this is unchanged.
die() { printf '%b\n' "ERROR: $*" >&2; exit 1; }
DEV_TOOL_MODE=legacy
if [ "${MYKHAYA_PRODUCTION:-}" = 1 ]; then
  ROOT=$REPO_ROOT
  . "$SCRIPT_DIR/prod-config-mode.sh"
  prod_select_mode readonly
  if [ "$PROD_CONFIG_MODE" != legacy ]; then
    prod_compose run --rm --no-deps api python -m mykhaya.billing_readiness "$@"
    exit
  fi
fi
if [ "${MYKHAYA_PRODUCTION:-}" != 1 ]; then
  . "$SCRIPT_DIR/dev-config-mode.sh"
  dev_select_mode "$SCRIPT_DIR"
fi
if [ "$DEV_TOOL_MODE" = legacy ]; then
  docker compose run --rm --no-deps api python -m mykhaya.billing_readiness "$@"
else
  dev_tool_compose run --rm --no-deps api python -m mykhaya.billing_readiness "$@"
fi
