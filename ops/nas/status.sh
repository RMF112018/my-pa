#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/lifecycle-common.sh"
verify_running_identity
nas_compose ps
