#!/bin/sh
set -eu
: "${MY_PA_RUNTIME_SERVICES:?verified runtime service manifest required}"
: "${MY_PA_NAS_COMPOSE_FILE:?exact NAS compose file required}"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
"$NAS_PYTHON_BIN" "$script_dir/runtime_gate.py" "$MY_PA_RUNTIME_SERVICES" --live \
  --compose-file "$MY_PA_NAS_COMPOSE_FILE" --permissions
