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
cleanup_partial_prepare() {
  result=$1
  trap - EXIT HUP INT TERM
  candidate=${container_id:-}
  if [ -z "$candidate" ]; then
    discovered=$(nas_docker ps -a --no-trunc \
      --filter label=com.docker.compose.project=my-pa-nas-contract \
      --filter label=com.docker.compose.service=postgres \
      --filter label=com.docker.compose.oneoff=False \
      --format '{{.ID}}' 2>/dev/null || true)
    candidate=$discovered
  fi
  case "$candidate" in
    *[!0-9a-f]*)
      echo "partial prepare cleanup found ambiguous PostgreSQL identities" >&2
      result=1
      candidate=
      ;;
  esac
  if [ -n "$candidate" ] && [ "${#candidate}" -eq 64 ]; then
    project=$(nas_docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$candidate" 2>/dev/null || true)
    service=$(nas_docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$candidate" 2>/dev/null || true)
    oneoff=$(nas_docker inspect --format '{{index .Config.Labels "com.docker.compose.oneoff"}}' "$candidate" 2>/dev/null || true)
    number=$(nas_docker inspect --format '{{index .Config.Labels "com.docker.compose.container-number"}}' "$candidate" 2>/dev/null || true)
    running_now=$(nas_docker inspect --format '{{.State.Running}}' "$candidate" 2>/dev/null || true)
    image=$(nas_docker inspect --format '{{.Image}}' "$candidate" 2>/dev/null || true)
    if [ "$project" = my-pa-nas-contract ] && [ "$service" = postgres ] && \
      [ "$oneoff" = False ] && [ "$number" = 1 ] && \
      [ "$running_now" = false ] && [ "$image" = "$MY_PA_POSTGRES_IMAGE_ID" ]; then
      if ! nas_docker container rm "$candidate" >/dev/null; then
        echo "failed to remove exact partial PostgreSQL container" >&2
        result=1
      fi
    else
      echo "partial prepare cleanup refused unverified PostgreSQL identity" >&2
      result=1
    fi
  fi
  network_name=my-pa-nas-contract_data-plane
  network_id=$(nas_docker network inspect --format '{{.Id}}' "$network_name" 2>/dev/null || true)
  case "$network_id" in *[!0-9a-f]*|'') network_id= ;; esac
  if [ "${#network_id}" -eq 64 ]; then
    network_project=$(nas_docker network inspect --format '{{index .Labels "com.docker.compose.project"}}' "$network_id" 2>/dev/null || true)
    network_key=$(nas_docker network inspect --format '{{index .Labels "com.docker.compose.network"}}' "$network_id" 2>/dev/null || true)
    network_internal=$(nas_docker network inspect --format '{{.Internal}}' "$network_id" 2>/dev/null || true)
    network_containers=$(nas_docker network inspect --format '{{len .Containers}}' "$network_id" 2>/dev/null || true)
  else
    network_project= network_key= network_internal= network_containers=
  fi
  if [ "$network_project" = my-pa-nas-contract ] && [ "$network_key" = data-plane ] && \
    [ "$network_internal" = true ] && [ "$network_containers" = 0 ]; then
    if ! nas_docker network rm "$network_id" >/dev/null; then
      echo "failed to remove exact partial PostgreSQL network" >&2
      result=1
    fi
  elif [ -n "$network_id" ]; then
    echo "partial prepare cleanup refused unverified PostgreSQL network" >&2
    result=1
  fi
  exit "$result"
}
container_id=
trap 'cleanup_partial_prepare $?' EXIT
trap 'exit 1' HUP INT TERM
nas_postgres_compose create postgres
container_id=$(nas_postgres_compose ps -a -q postgres)
[ -n "$container_id" ] || { echo "canonical PostgreSQL container was not created" >&2; exit 1; }
case "$container_id" in
  *[!0-9a-f]*|'') echo "canonical PostgreSQL container ID is not exact" >&2; exit 1 ;;
esac
[ "${#container_id}" -eq 64 ] || { echo "canonical PostgreSQL container ID is not full length" >&2; exit 1; }
running=$(nas_docker inspect --format '{{.State.Running}}' "$container_id")
[ "$running" = false ] || { echo "prepare unexpectedly started PostgreSQL" >&2; exit 1; }
"$NAS_PYTHON_BIN" "$script_dir/generate-postgres-resources.py" \
  --container-id "$container_id" \
  --data-path "$MY_PA_NAS_ROOT/postgres/data" \
  --minimum-available-storage-bytes "$4" \
  --output "$3"
trap - EXIT HUP INT TERM
echo "canonical PostgreSQL bootstrap prepared but not started: $container_id"
