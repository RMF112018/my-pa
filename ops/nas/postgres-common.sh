#!/bin/sh
set -eu
: "${MY_PA_NAS_COMPOSE_FILE:?exact NAS compose file required}"
: "${MY_PA_POSTGRES_RESOURCES:?verified PostgreSQL resource manifest required}"
: "${MY_PA_IMAGE_MANIFEST:?exact deployable image manifest required}"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
. "$script_dir/postgres-bootstrap-common.sh"
nas_compose() { nas_postgres_compose "$@"; }
postgres_container_id=$(nas_compose ps -q postgres)
[ -n "$postgres_container_id" ] || { echo "Compose postgres service is not running" >&2; exit 1; }
"$NAS_PYTHON_BIN" "$script_dir/postgres_gate.py" "$MY_PA_POSTGRES_RESOURCES" --live \
  --container-id "$postgres_container_id"
nas_docker exec -i "$postgres_container_id" sh -eu -c \
  'test -w /var/lib/postgresql/data && postgres --version | grep -Eq "PostgreSQL[)]? 17[.]10([[:space:]]|$)"'
pg_exec() {
  current=$(nas_compose ps -q postgres)
  [ "$current" = "$postgres_container_id" ] || { echo "Compose postgres identity drift" >&2; exit 1; }
  nas_docker exec -i "$postgres_container_id" "$@"
}

database_operator_image_id=$(sed -n \
  's/^database_operator_image_id = "\(sha256:[0-9a-f][0-9a-f]*\)"$/\1/p' \
  "$MY_PA_POSTGRES_BOOTSTRAP_ADMISSION")
[ "${#database_operator_image_id}" -eq 71 ] || {
  echo "database operator image identity is invalid" >&2
  exit 1
}
PGPASSWORD=$MY_PA_DB_PASSWORD
export PGPASSWORD
database_operator_with_url() {
  operator_database_url=$1
  shift
  nas_docker run --rm -i \
    --network my-pa-nas-contract_data-plane \
    --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=32m \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --user 10001:10001 \
    --env MY_PA_DATABASE_URL="$operator_database_url" \
    --env MY_PA_AUTH_MODE=local_operator \
    --env MY_PA_REMOTE_INGRESS_ENABLED=false \
    --env MY_PA_REDACTION_ENABLED=true \
    --env MY_PA_CONTRACT_STRICT_MODE=true \
    --env PGPASSWORD \
    "$database_operator_image_id" "$@"
}
database_operator() {
  database_operator_with_url postgresql+psycopg://my_pa@postgres:5432/my_pa "$@"
}
