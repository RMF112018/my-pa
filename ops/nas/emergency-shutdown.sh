#!/bin/sh
set -eu

: "${MY_PA_NAS_DOCKER:=/usr/local/bin/docker}"
: "${MY_PA_EMERGENCY_COMPOSE:=/etc/my-pa/compose.yml}"
project=my-pa-nas-contract
expected_services='gateway
postgres
proxy
web
worker-capture
worker-enrollment'

case "$MY_PA_NAS_DOCKER" in
  /*) docker_bin=$MY_PA_NAS_DOCKER ;;
  *) docker_bin=$(command -v "$MY_PA_NAS_DOCKER") ;;
esac
[ -x "$docker_bin" ] || { echo "NAS emergency stop refused: docker_unavailable" >&2; exit 1; }

compose=$MY_PA_EMERGENCY_COMPOSE
[ "$compose" = /etc/my-pa/compose.yml ] || {
  echo "NAS emergency stop refused: canonical_compose_path" >&2
  exit 1
}
[ -f "$compose" ] && [ ! -L "$compose" ] || {
  echo "NAS emergency stop refused: canonical_compose_metadata" >&2
  exit 1
}
[ "$(stat -c '%u:%a:%h' "$compose")" = "0:400:1" ] || {
  echo "NAS emergency stop refused: canonical_compose_metadata" >&2
  exit 1
}
[ "$(awk '$0 ~ /^name:[[:space:]]/ {count += 1; value = $2} END {if (count == 1) print value}' "$compose")" = "$project" ] || {
  echo "NAS emergency stop refused: canonical_compose_project_identity" >&2
  exit 1
}

nas_compose() {
  "$docker_bin" compose --project-name "$project" --file "$compose" \
    --profile nas-01-contract-only "$@"
}
actual_services=$(nas_compose config --no-interpolate --services | LC_ALL=C sort) || {
  echo "NAS emergency stop refused: canonical_compose_unreadable" >&2
  exit 1
}
[ "$actual_services" = "$expected_services" ] || {
  echo "NAS emergency stop refused: canonical_compose_service_identity" >&2
  exit 1
}

nas_compose stop --timeout 10 || {
  echo "NAS emergency stop refused: emergency_stop_command" >&2
  exit 1
}
running=$(nas_compose ps --status running -q) || {
  echo "NAS emergency stop refused: emergency_stop_command" >&2
  exit 1
}
[ -z "$running" ] || {
  echo "NAS emergency stop refused: emergency_stop_incomplete" >&2
  exit 1
}
echo "NAS runtime stopped; no container, bind mount, volume, or data was removed"
