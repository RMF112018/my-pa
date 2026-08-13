#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/lifecycle-common.sh"
verify_running_identity
before=$(nas_compose ps -q postgres)
[ -n "$before" ] || { echo "postgres is not an existing Compose service instance" >&2; exit 1; }
nas_compose restart --timeout 60
after=$(nas_compose ps -q postgres)
[ "$before" = "$after" ] || { echo "postgres container identity changed during restart" >&2; exit 1; }
verify_running_identity
running=$(nas_compose ps --status running -q | wc -l | tr -d ' ')
if [ "$running" -ne 6 ]; then
  echo "expected six running runtime services; stopping the partial stack" >&2
  nas_compose stop --timeout 60
  exit 1
fi
echo "NAS runtime restarted without build or recreate"
