#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
exec "$NAS_PYTHON_BIN" "$script_dir/emergency_stop.py"
