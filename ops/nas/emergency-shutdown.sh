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

compose_services() {
  "$docker_bin" compose --project-name "$project" --file "$compose" \
    --profile nas-01-contract-only config --no-interpolate --services
}
actual_services=$(compose_services | LC_ALL=C sort) || {
  echo "NAS emergency stop refused: canonical_compose_unreadable" >&2
  exit 1
}
[ "$actual_services" = "$expected_services" ] || {
  echo "NAS emergency stop refused: canonical_compose_service_identity" >&2
  exit 1
}

# After validating the root-controlled Compose contract, resolve the running
# stack only through Docker's immutable project/service labels. A partial stack
# is expected during an incident. Three bounded passes contain replacements
# created concurrently with shutdown; success requires a fresh zero-running
# query, not merely the state of IDs captured before mutation.
identity_anomaly=false
stop_failure=false
pass=1
while [ "$pass" -le 3 ]; do
  project_ids=$(
    "$docker_bin" ps \
      --filter "label=com.docker.compose.project=$project" \
      --filter status=running \
      --format '{{.ID}}'
  ) || {
    echo "NAS emergency stop refused: emergency_container_discovery" >&2
    exit 1
  }
  [ -n "$project_ids" ] || break
  container_ids=""
  seen_services=""
  for short_id in $project_ids; do
    identity=$(
      "$docker_bin" inspect --format \
        '{{.Id}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "com.docker.compose.oneoff"}}' \
        "$short_id"
    ) || {
      echo "NAS emergency stop refused: emergency_container_identity" >&2
      exit 1
    }
    full_id=${identity%%|*}
    labels=${identity#*|}
    actual_project=${labels%%|*}
    labels=${labels#*|}
    service=${labels%%|*}
    oneoff=${labels#*|}
    case "$full_id" in
      *[!0-9a-f]*|'') valid_id=false ;;
      *) valid_id=true ;;
    esac
    if [ "$valid_id" != true ] || [ "${#full_id}" -ne 64 ] || \
       [ "$actual_project" != "$project" ]; then
      echo "NAS emergency stop refused: emergency_container_identity" >&2
      exit 1
    fi
    case "$service" in
      postgres|gateway|worker-enrollment|worker-capture|web|proxy) ;;
      *) identity_anomaly=true; continue ;;
    esac
    [ "$oneoff" = False ] || { identity_anomaly=true; continue; }
    case "|$seen_services|" in
      *"|$service|"*) identity_anomaly=true ;;
      *) seen_services="${seen_services}${seen_services:+|}${service}" ;;
    esac
    container_ids="${container_ids}${container_ids:+
}${full_id}"
  done
  for container_id in $container_ids; do
    "$docker_bin" stop --time 10 "$container_id" >/dev/null || stop_failure=true
  done
  pass=$((pass + 1))
done

remaining=$(
  "$docker_bin" ps \
    --filter "label=com.docker.compose.project=$project" \
    --filter status=running \
    --format '{{.ID}}'
) || {
  echo "NAS emergency stop refused: emergency_container_discovery" >&2
  exit 1
}
[ -z "$remaining" ] || {
  echo "NAS emergency stop refused: emergency_stop_incomplete" >&2
  exit 1
}
[ "$stop_failure" = false ] || {
  echo "NAS emergency stop refused: emergency_stop_command" >&2
  exit 1
}
[ "$identity_anomaly" = false ] || {
  echo "NAS emergency stop contained canonical services but found unexpected project identity" >&2
  exit 1
}
echo "NAS runtime stopped; no container, bind mount, volume, or data was removed"
