#!/bin/sh
# Production backup preflight. Run by prod-deploy.sh (validate, and first
# thing in update) so a release can never be deployed onto a host that would
# then be unable to take the encrypted backup the release requires. Read-only
# apart from a throwaway probe file in the backup directory. Never weakens
# backup.sh's refusal to write plaintext in production.
#
# Checks:
#   1. `age` is installed
#   2. the recipients file exists and is readable
#   3. it contains age PUBLIC recipients only (no private key, no other lines)
#   4. it is not writable by group/others
#   5. the backup destination exists (or can be created) and is writable
#   6. no private identity is exposed to the backup process
#      (MYKHAYA_BACKUP_AGE_IDENTITY unset in the environment and absent from
#      .env, and no AGE-SECRET-KEY text file inside the backup directory)
#
# Values come from the environment first, then the production .env, then the
# documented defaults — the same resolution backup.sh uses.
set -eu

# MYKHAYA_ROOT lets an operator run a copy of this script extracted from a
# release tag (before that release's prod-deploy.sh exists on the host).
ROOT="${MYKHAYA_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}"
env_file="${MYKHAYA_ENV_FILE:-$ROOT/.env}"

env_value() {
  [ -f "$env_file" ] || return 0
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

problems=""
problem() { problems="$problems
  - $1"; }

recipients_file="${MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE:-$(env_value MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE)}"
recipients_file="${recipients_file:-/etc/mykhaya/backup-recipients.txt}"
backup_dir="${MYKHAYA_BACKUP_DIR:-$(env_value MYKHAYA_BACKUP_DIR)}"
backup_dir="${backup_dir:-$ROOT/backups}"

# 1. age
command -v age >/dev/null 2>&1 || problem "age is not installed (Debian/Ubuntu: apt install age)"

# 2-4. recipients file
if [ ! -f "$recipients_file" ]; then
  problem "backup recipients file not found: $recipients_file"
elif [ ! -r "$recipients_file" ]; then
  problem "backup recipients file is not readable: $recipients_file"
else
  if grep -q "AGE-SECRET-KEY" "$recipients_file"; then
    problem "recipients file contains a PRIVATE key; it must hold age public keys (age1...) only"
  fi
  public_count=$(grep -c '^age1[0-9a-z]\{58\}$' "$recipients_file" || true)
  [ "${public_count:-0}" -ge 1 ] || problem "recipients file has no valid age public key (age1...)"
  # Every non-blank, non-comment line must be a public recipient.
  if grep -v '^[[:space:]]*$' "$recipients_file" | grep -v '^#' |
    grep -v '^age1[0-9a-z]\{58\}$' >/dev/null; then
    problem "recipients file contains lines that are not age public keys"
  fi
  perms=$(ls -l "$recipients_file" | cut -c1-10)
  case "$perms" in
    ?????w????|????????w?) problem "recipients file is writable by group/others ($perms)" ;;
  esac
fi

# 5. backup destination
if mkdir -p "$backup_dir" 2>/dev/null; then
  probe="$backup_dir/.preflight-$$"
  if ( umask 077 && : > "$probe" ) 2>/dev/null; then
    rm -f "$probe"
  else
    problem "backup directory is not writable: $backup_dir"
  fi
else
  problem "backup directory cannot be created: $backup_dir"
fi

# 6. no private identity exposed to the backup process
[ -z "${MYKHAYA_BACKUP_AGE_IDENTITY:-}" ] ||
  problem "MYKHAYA_BACKUP_AGE_IDENTITY is set in the deployment environment; supply it only at restore time"
[ -z "$(env_value MYKHAYA_BACKUP_AGE_IDENTITY)" ] ||
  problem "MYKHAYA_BACKUP_AGE_IDENTITY is set in .env; supply it only at restore time"
if [ -d "$backup_dir" ] && grep -rlI "AGE-SECRET-KEY" "$backup_dir" >/dev/null 2>&1; then
  problem "a file containing an age PRIVATE key is inside the backup directory"
fi

if [ -n "$problems" ]; then
  printf 'ERROR: backup preflight failed:%s\n' "$problems" >&2
  printf 'See docs/operations/backup-and-restore.md (One-time setup).\n' >&2
  exit 1
fi
printf 'Backup preflight passed: age present, public-only recipients, writable %s.\n' "$backup_dir"
