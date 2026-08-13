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
"$script_dir/preflight.sh" "$1" "$2"
MY_PA_IMAGE_MANIFEST=$1
MY_PA_POSTGRES_RESOURCES=$3
MY_PA_LIFECYCLE_MODE=smoke
export MY_PA_IMAGE_MANIFEST MY_PA_POSTGRES_RESOURCES MY_PA_LIFECYCLE_MODE
. "$script_dir/lifecycle-common.sh"
container_id=$(nas_compose ps -a -q postgres)
[ -n "$container_id" ] || { echo "prepared canonical PostgreSQL container is absent" >&2; exit 1; }
"$NAS_PYTHON_BIN" "$script_dir/postgres_gate.py" "$3" --live --container-id "$container_id"

cleanup() {
  nas_compose stop --timeout 60 postgres >/dev/null 2>&1 || true
}
trap cleanup HUP INT TERM
if ! nas_compose start postgres; then
  cleanup
  echo "canonical PostgreSQL start failed" >&2
  exit 1
fi
attempt=0
while [ "$attempt" -lt 30 ]; do
  health=$(nas_docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_id")
  [ "$health" = healthy ] && break
  [ "$health" = unhealthy ] && { cleanup; echo "PostgreSQL became unhealthy" >&2; exit 1; }
  attempt=$((attempt + 1))
  sleep 2
done
[ "${health:-missing}" = healthy ] || { cleanup; echo "PostgreSQL health timeout" >&2; exit 1; }
"$NAS_PYTHON_BIN" "$script_dir/postgres_gate.py" "$3" --live --container-id "$container_id"
nas_docker exec -i "$container_id" sh -eu -c \
  'pg_isready -U my_pa -d my_pa >/dev/null && postgres --version | grep -Eq "PostgreSQL[)]? 17[.]10([[:space:]]|$)"'
trap - HUP INT TERM
echo "canonical PostgreSQL bootstrap running temporarily; migration remains explicit"
