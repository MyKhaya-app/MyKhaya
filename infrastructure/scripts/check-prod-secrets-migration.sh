#!/usr/bin/env bash
# PROD security migration rehearsal (CI and local), MK-SEC-001 v1.2.
#
# Runs the real PROD scripts, Compose files and images through legacy -> F-03 ->
# file-backed secrets -> rollback, plus an isolated restore, with synthetic
# credentials, in the same disposable nested Docker daemon as the DEV rehearsal.
# It proves the tooling, never the production host.
REHEARSAL=prod exec bash infrastructure/scripts/check-dev-secrets-migration.sh
