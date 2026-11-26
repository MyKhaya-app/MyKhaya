# Service-env cutover state file, shared by dev-deploy.sh and the production
# scripts (sourced, not executed). The caller defines die().
#
# The file lives outside the repository in the configuration root. Line 1 is
# the state; line 2 is non-secret provenance (time, commit, account):
#   absent | legacy    root .env deployments (before cutover, or after a rollback)
#   pending            a service-env cutover has started; legacy is refused
#   active             service-env deployed and verified; legacy is refused
#   rollback-pending   an explicit rollback to legacy has started
# The state never changes credentials, volumes or data.

# cutover_read_state FILE: prints the state, or dies on a linked or
# unrecognised file. An absent file means legacy.
cutover_read_state() {
  cutover_file=$1
  if [ -L "$cutover_file" ]; then
    die "cutover state $cutover_file must be a regular file, not a symbolic link"
  fi
  if [ ! -e "$cutover_file" ]; then
    printf 'legacy\n'
    return 0
  fi
  cutover_value=$(sed -n '1p' "$cutover_file" | tr -d '\r')
  case "$cutover_value" in
    legacy|pending|active|rollback-pending) printf '%s\n' "$cutover_value" ;;
    *) die "cutover state $cutover_file is unrecognised; refusing to deploy.\nInspect it, then restore the last known state (legacy, pending, active or rollback-pending)" ;;
  esac
}

# cutover_write_state FILE STATE: atomic replacement, so an interruption
# leaves either the old or the new state.
cutover_write_state() {
  cutover_file=$1
  cutover_new=$2
  cutover_dir=$(dirname -- "$cutover_file")
  [ -d "$cutover_dir" ] || die "cutover state directory $cutover_dir does not exist"
  cutover_tmp="$cutover_dir/.service-env-state.tmp.$$"
  (
    umask 027
    printf '%s\nupdated=%s commit=%s by=%s\n' "$cutover_new" \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" \
      "$(id -un 2>/dev/null || echo unknown)" >"$cutover_tmp"
  ) || die "could not write the cutover state"
  mv -f "$cutover_tmp" "$cutover_file" || { rm -f "$cutover_tmp"; die "could not record the cutover state"; }
  printf 'Cutover state: %s\n' "$cutover_new"
}
