#!/bin/sh
set -u
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
: "${MY_PA_NAS_COMPOSE_FILE:?exact NAS compose file required}"
: "${MY_PA_LIFECYCLE_MODE:=smoke}"
nas_compose() {
  if [ "$MY_PA_LIFECYCLE_MODE" = pilot ]; then
    nas_docker compose --file "$MY_PA_NAS_COMPOSE_FILE" \
      --file "$script_dir/compose.pilot.example.yml" \
      --profile nas-01-contract-only "$@"
  else
    nas_docker compose --file "$MY_PA_NAS_COMPOSE_FILE" \
      --profile nas-01-contract-only "$@"
  fi
}
stop_failed=0
nas_compose stop --timeout 60 || stop_failed=1
if ! remaining=$(nas_compose ps --status running -q); then
  echo "failed to verify partial-stack cleanup" >&2
  exit 1
fi
if [ -n "$remaining" ]; then
  echo "partial stack remains running after cleanup" >&2
  exit 1
fi
if [ "$stop_failed" -ne 0 ]; then
  echo "Compose stop failed but zero running services were verified" >&2
fi
exit 0
