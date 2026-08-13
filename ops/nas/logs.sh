#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
  echo "usage: $0 SERVICE" >&2
  exit 64
fi
case "$1" in
  postgres|gateway|worker-enrollment|worker-capture|web|proxy) ;;
  *) echo "unknown runtime service" >&2; exit 64 ;;
esac
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/lifecycle-common.sh"
verify_running_identity
nas_compose logs --no-color --tail 200 "$1"
