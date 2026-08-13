#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/lifecycle-common.sh"
verify_running_identity
nas_compose stop --timeout 60
[ -z "$(nas_compose ps --status running -q)" ] || { echo "services remain running" >&2; exit 1; }
echo "NAS runtime stopped; bind-mounted data was not removed"
