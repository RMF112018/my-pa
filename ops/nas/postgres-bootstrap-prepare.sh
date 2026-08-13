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

cleanup_partial_prepare() {
  result=$1
  trap - EXIT HUP INT TERM
  current=$(nas_postgres_compose ps -a -q postgres 2>/dev/null || true)
  if [ -n "${container_id:-}" ] && [ "$current" = "$container_id" ]; then
    project=$(nas_docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container_id" 2>/dev/null || true)
    service=$(nas_docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$container_id" 2>/dev/null || true)
    running_now=$(nas_docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null || true)
    image=$(nas_docker inspect --format '{{.Image}}' "$container_id" 2>/dev/null || true)
    if [ "$project" = my-pa-nas-contract ] && [ "$service" = postgres ] && \
      [ "$running_now" = false ] && [ "$image" = "$MY_PA_POSTGRES_IMAGE_ID" ]; then
      nas_postgres_compose rm --force --stop postgres >/dev/null 2>&1 || true
    else
      echo "partial prepare cleanup refused unverified PostgreSQL identity" >&2
    fi
  fi
  network=my-pa-nas-contract_data-plane
  network_project=$(nas_docker network inspect --format '{{index .Labels "com.docker.compose.project"}}' "$network" 2>/dev/null || true)
  network_name=$(nas_docker network inspect --format '{{index .Labels "com.docker.compose.network"}}' "$network" 2>/dev/null || true)
  network_internal=$(nas_docker network inspect --format '{{.Internal}}' "$network" 2>/dev/null || true)
  network_containers=$(nas_docker network inspect --format '{{len .Containers}}' "$network" 2>/dev/null || true)
  if [ "$network_project" = my-pa-nas-contract ] && [ "$network_name" = data-plane ] && \
    [ "$network_internal" = true ] && [ "$network_containers" = 0 ]; then
    nas_docker network rm "$network" >/dev/null 2>&1 || true
  fi
  exit "$result"
}
trap 'cleanup_partial_prepare $?' EXIT HUP INT TERM
running=$(nas_docker inspect --format '{{.State.Running}}' "$container_id")
[ "$running" = false ] || { echo "prepare unexpectedly started PostgreSQL" >&2; exit 1; }
"$NAS_PYTHON_BIN" "$script_dir/generate-postgres-resources.py" \
  --container-id "$container_id" \
  --data-path "$MY_PA_NAS_ROOT/postgres/data" \
  --minimum-available-storage-bytes "$4" \
  --output "$3"
trap - EXIT HUP INT TERM
echo "canonical PostgreSQL bootstrap prepared but not started: $container_id"
