#!/bin/sh
set -eu

: "${MY_PA_NAS_COMPOSE_FILE:?exact NAS compose file required}"
: "${MY_PA_IMAGE_MANIFEST:?exact deployable image manifest required}"
: "${MY_PA_POSTGRES_BOOTSTRAP_ADMISSION:=/etc/my-pa/postgres-bootstrap-admission.toml}"
: "${MY_PA_POSTGRES_IMAGE_ID:?exact loaded PostgreSQL image ID required}"
: "${MY_PA_DB_PASSWORD:?database password required}"
: "${MY_PA_NAS_ROOT:?exact canonical NAS root required}"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"

# Compose interpolates the complete canonical file before selecting one service.
# These fixed invalid values satisfy that parser only; the bootstrap generator
# proves none reaches the selected PostgreSQL service or its data-plane network.
MY_PA_APP_IMAGE_ID=sha256:0000000000000000000000000000000000000000000000000000000000000000
MY_PA_WEB_IMAGE_ID=$MY_PA_APP_IMAGE_ID
MY_PA_PROXY_IMAGE=invalid.example/my-pa-bootstrap-sentinel
MY_PA_PROXY_IMAGE_DIGEST=$MY_PA_APP_IMAGE_ID
MY_PA_UID=1
MY_PA_GID=1
MY_PA_NAS_ENV_FILE=/dev/null
MY_PA_WEB_ENV_FILE=/dev/null
MY_PA_PROXY_UID=1
MY_PA_PROXY_GID=1
MY_PA_PROXY_PORT=1
MY_PA_TAILNET_HOST=invalid.example
MYPA_CANONICAL_ORIGIN=https://invalid.example
MYPA_ENTRA_REDIRECT_URI=https://invalid.example/callback
export MY_PA_APP_IMAGE_ID MY_PA_WEB_IMAGE_ID MY_PA_PROXY_IMAGE MY_PA_PROXY_IMAGE_DIGEST
export MY_PA_UID MY_PA_GID MY_PA_NAS_ENV_FILE MY_PA_WEB_ENV_FILE
export MY_PA_PROXY_UID MY_PA_PROXY_GID MY_PA_PROXY_PORT MY_PA_TAILNET_HOST
export MYPA_CANONICAL_ORIGIN MYPA_ENTRA_REDIRECT_URI

"$NAS_PYTHON_BIN" "$script_dir/lifecycle_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
  "$script_dir/compose.pilot.example.yml" --image-manifest "$MY_PA_IMAGE_MANIFEST" --live
"$NAS_PYTHON_BIN" "$script_dir/postgres-bootstrap-identity-gate.py" \
  "$MY_PA_NAS_COMPOSE_FILE" "$MY_PA_IMAGE_MANIFEST" \
  --admission "$MY_PA_POSTGRES_BOOTSTRAP_ADMISSION"

nas_postgres_compose() {
  nas_docker compose --file "$MY_PA_NAS_COMPOSE_FILE" \
    --profile nas-01-contract-only "$@"
}
