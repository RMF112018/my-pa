#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
  echo "usage: $0 IMAGE_MANIFEST ARCHIVE_DIRECTORY POSTGRES_RESOURCES" >&2
  exit 64
fi
: "${MY_PA_NAS_COMPOSE_FILE:?exact NAS compose file required}"
[ "${MY_PA_LIFECYCLE_MODE:-smoke}" = smoke ] || {
  echo "PostgreSQL bootstrap is a temporary smoke-only state" >&2
  exit 1
}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
"$NAS_PYTHON_BIN" "$script_dir/image_gate.py" "$1" --archive-dir "$2" --live
MY_PA_IMAGE_MANIFEST=$1
MY_PA_POSTGRES_RESOURCES=$3
MY_PA_LIFECYCLE_MODE=smoke
export MY_PA_IMAGE_MANIFEST MY_PA_POSTGRES_RESOURCES MY_PA_LIFECYCLE_MODE
. "$script_dir/postgres-bootstrap-common.sh"
container_id=$(nas_postgres_compose ps -a -q postgres)
[ -n "$container_id" ] || { echo "prepared canonical PostgreSQL container is absent" >&2; exit 1; }
case "$container_id" in
  *[!0-9a-f]*|'') echo "prepared PostgreSQL container ID is not exact" >&2; exit 1 ;;
esac
[ "${#container_id}" -eq 64 ] || { echo "prepared PostgreSQL container ID is not full length" >&2; exit 1; }
"$NAS_PYTHON_BIN" "$script_dir/postgres_gate.py" "$3" --live --container-id "$container_id"

cleanup() {
  result=$1
  trap - EXIT HUP INT TERM
  if [ "${cleanup_needed:-false}" = true ]; then
    if ! nas_docker stop --time 60 "$container_id" >/dev/null; then
      echo "failed to stop exact PostgreSQL container during bootstrap cleanup" >&2
      result=1
    fi
    running_now=$(nas_docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null || true)
    if [ "$running_now" != false ]; then
      echo "exact PostgreSQL container remains running after bootstrap cleanup" >&2
      result=1
    fi
  fi
  exit "$result"
}
cleanup_needed=true
trap 'cleanup $?' EXIT
trap 'exit 1' HUP INT TERM
if ! nas_postgres_compose start postgres; then
  echo "canonical PostgreSQL start failed" >&2
  exit 1
fi
attempt=0
while [ "$attempt" -lt 30 ]; do
  health=$(nas_docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_id")
  [ "$health" = healthy ] && break
  [ "$health" = unhealthy ] && { echo "PostgreSQL became unhealthy" >&2; exit 1; }
  attempt=$((attempt + 1))
  sleep 2
done
[ "${health:-missing}" = healthy ] || { echo "PostgreSQL health timeout" >&2; exit 1; }
"$NAS_PYTHON_BIN" "$script_dir/postgres_gate.py" "$3" --live --container-id "$container_id"
nas_docker exec -i "$container_id" sh -eu -c \
  'pg_isready -U my_pa -d my_pa >/dev/null && postgres --version | grep -Eq "PostgreSQL[)]? 17[.]10([[:space:]]|$)"'
cleanup_needed=false
trap - EXIT HUP INT TERM
echo "canonical PostgreSQL bootstrap running temporarily; migration remains explicit"
