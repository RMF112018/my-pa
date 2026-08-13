#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
  echo "usage: $0 IMAGE_MANIFEST ARCHIVE_DIRECTORY RESOURCE_OUTPUT MINIMUM_AVAILABLE_STORAGE_BYTES" >&2
  exit 64
fi
: "${MY_PA_NAS_COMPOSE_FILE:?exact NAS compose file required}"
: "${MY_PA_NAS_ROOT:?exact canonical NAS root required}"
[ "${MY_PA_LIFECYCLE_MODE:-smoke}" = smoke ] || {
  echo "PostgreSQL bootstrap is a temporary smoke-only state" >&2
  exit 1
}
[ "${MY_PA_DATA_NETWORK:-my-pa-nas-contract_data-plane}" != postgresql_default ] || {
  echo "postgresql_default is prohibited" >&2
  exit 1
}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
"$NAS_PYTHON_BIN" "$script_dir/image_gate.py" "$1" --archive-dir "$2" --live
MY_PA_IMAGE_MANIFEST=$1
MY_PA_LIFECYCLE_MODE=smoke
export MY_PA_IMAGE_MANIFEST MY_PA_LIFECYCLE_MODE
. "$script_dir/postgres-bootstrap-common.sh"

existing=$(nas_postgres_compose ps -a -q postgres)
[ -z "$existing" ] || {
  echo "canonical PostgreSQL container already exists; refusing identity replacement" >&2
  exit 1
}
nas_postgres_compose create postgres
container_id=$(nas_postgres_compose ps -a -q postgres)
[ -n "$container_id" ] || { echo "canonical PostgreSQL container was not created" >&2; exit 1; }
running=$(nas_docker inspect --format '{{.State.Running}}' "$container_id")
[ "$running" = false ] || { echo "prepare unexpectedly started PostgreSQL" >&2; exit 1; }
"$NAS_PYTHON_BIN" "$script_dir/generate-postgres-resources.py" \
  --container-id "$container_id" \
  --data-path "$MY_PA_NAS_ROOT/postgres/data" \
  --minimum-available-storage-bytes "$4" \
  --output "$3"
echo "canonical PostgreSQL bootstrap prepared but not started: $container_id"
