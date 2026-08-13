#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/lifecycle-common.sh"
verify_running_identity
running=$(nas_compose ps --status running -q | wc -l | tr -d ' ')
[ "$running" -eq 6 ] || { echo "expected six running runtime services" >&2; exit 1; }
nas_compose exec -T postgres pg_isready -U my_pa -d my_pa >/dev/null
nas_compose exec -T gateway python apps/cli/health.py >/dev/null
echo "NAS process/database readiness converged; this is not full operational health"
echo "run diagnostics.sh for workers, web/proxy, filesystem, disk, backup, and Apple signals"
