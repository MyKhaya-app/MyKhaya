#!/bin/sh
# Restore the persistent file stores (avatars, support attachments, vehicle
# photos, meal images) from a backup.sh files archive directly into their
# named volumes, via the same locked-down helper container backup.sh uses.
# The api container does NOT need to be running — on a rebuilt host, restore
# the file stores before starting the application. Requires the postgres
# service to be running (its image and Compose project are reused) and the
# volumes to exist (`docker compose create api` creates them without starting
# anything). See docs/operations/backup-and-restore.md.
#
#   MYKHAYA_BACKUP_AGE_IDENTITY=/offline/identity.txt \
#     restore-files.sh /absolute/path/mykhaya-<stamp>-files.tar.gz.age
#
# Restore into an isolated stack first. Existing files with the same name are
# overwritten; files not in the archive are left alone (storage keys are
# random UUIDs, so archives never collide with unrelated uploads).
set -eu
test "$#" -eq 1 || { echo "Usage: restore-files.sh /absolute/path/backup-files.tar.gz.age" >&2; exit 2; }
source_file="$1"
case "$source_file" in /*) ;; *) echo "Use an absolute backup path" >&2; exit 2;; esac
test -f "$source_file" || { echo "Backup does not exist" >&2; exit 2; }
case "$source_file" in
  *-files.tar.gz.age) ;;
  *) echo "Expected an encrypted *-files.tar.gz.age archive" >&2; exit 2 ;;
esac
identity="${MYKHAYA_BACKUP_AGE_IDENTITY:-}"
test -n "$identity" && test -f "$identity" ||
  { echo "Set MYKHAYA_BACKUP_AGE_IDENTITY to the offline age identity file." >&2; exit 2; }
command -v age >/dev/null 2>&1 || { echo "The age tool is not installed." >&2; exit 2; }

file_stores="avatars support-attachments vehicle-photos meal-images"
. "$(dirname "$0")/file-store-volumes.sh"
volume_mounts="$(file_store_volume_mounts rw)" || exit 1
helper_image="$(file_store_helper_image)" || { echo "Start the postgres service first." >&2; exit 1; }

age -d -i "$identity" "$source_file" | gzip -t ||
  { echo "Archive failed decryption or integrity verification." >&2; exit 1; }
# Only the known store directories are extracted; anything else in the
# archive (there should be nothing) is ignored rather than written to /data.
# Runs as the application's uid so restored files keep the ownership the api
# expects, with no network, no capabilities and no secrets.
# shellcheck disable=SC2086 # fixed, space-separated mount/store lists.
age -d -i "$identity" "$source_file" | gzip -dc |
  docker run --rm -i --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --user 10001:10001 $volume_mounts \
    --entrypoint tar "$helper_image" -C /data -xf - $file_stores
echo "File stores restored."
