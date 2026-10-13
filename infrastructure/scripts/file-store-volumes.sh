# Shared by backup.sh and restore-files.sh (sourced, not executed).
#
# Resolves the persistent file-store named volumes from Compose's own labels
# on the running postgres container's project, so backups and restores reach
# the data directly instead of depending on the api container being up. The
# helper container reuses postgres's exact image (already present, pinned in
# compose.yml, and it ships tar) so no extra image is pulled.
#
# Requires: $file_stores (space-separated store names) and a running postgres
# service (pg_dump/pg_restore need it anyway).

_file_store_postgres_container() {
  docker compose ps -q postgres 2>/dev/null | head -n 1
}

file_store_helper_image() {
  container="$(_file_store_postgres_container)"
  [ -n "$container" ] || return 1
  docker inspect --format '{{.Config.Image}}' "$container"
}

# Prints "-v <volume>:/data/<store>[:ro] ..." for every store, or fails if a
# volume is missing. $1 = "ro" for read-only mounts (backup), "rw" for restore.
file_store_volume_mounts() {
  mode="$1"
  container="$(_file_store_postgres_container)"
  [ -n "$container" ] || { echo "The postgres service is not running." >&2; return 1; }
  project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container")"
  [ -n "$project" ] || { echo "Could not determine the Compose project." >&2; return 1; }
  mounts=""
  for store in $file_stores; do
    case "$store" in
      avatars) key=avatar_data ;;
      support-attachments) key=support_attachment_data ;;
      vehicle-photos) key=vehicle_photo_data ;;
      meal-images) key=meal_image_data ;;
      *) echo "Unknown file store: $store" >&2; return 1 ;;
    esac
    volume="$(docker volume ls -q \
      --filter "label=com.docker.compose.project=$project" \
      --filter "label=com.docker.compose.volume=$key" | head -n 1)"
    if [ -z "$volume" ]; then
      echo "Volume for $store ($key) not found in Compose project $project." >&2
      echo "Create the stack's volumes first (e.g. docker compose create api)." >&2
      return 1
    fi
    suffix=""
    [ "$mode" = ro ] && suffix=":ro"
    mounts="$mounts -v $volume:/data/$store$suffix"
  done
  printf '%s\n' "$mounts"
}
