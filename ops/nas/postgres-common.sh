#!/bin/sh
set -eu
: "${MY_PA_NAS_COMPOSE_FILE:?exact NAS compose file required}"
: "${MY_PA_POSTGRES_RESOURCES:?verified PostgreSQL resource manifest required}"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
nas_compose() {
  docker compose --file "$MY_PA_NAS_COMPOSE_FILE" --profile nas-01-contract-only "$@"
}
postgres_container_id=$(nas_compose ps -q postgres)
[ -n "$postgres_container_id" ] || { echo "Compose postgres service is not running" >&2; exit 1; }
python3 "$script_dir/postgres_gate.py" "$MY_PA_POSTGRES_RESOURCES" --live \
  --container-id "$postgres_container_id"
docker exec -i "$postgres_container_id" sh -eu -c \
  'test -w /var/lib/postgresql/data && postgres --version | grep -Eq "PostgreSQL[)]? 17[.]10([[:space:]]|$)"'
pg_exec() {
  current=$(nas_compose ps -q postgres)
  [ "$current" = "$postgres_container_id" ] || { echo "Compose postgres identity drift" >&2; exit 1; }
  docker exec -i "$postgres_container_id" "$@"
}
