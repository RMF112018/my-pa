#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/postgres-common.sh"
nas_compose config --quiet
echo "NAS PostgreSQL storage and resource evidence passed"
