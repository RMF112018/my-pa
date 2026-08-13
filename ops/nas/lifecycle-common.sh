#!/bin/sh
set -eu

: "${MY_PA_NAS_COMPOSE_FILE:?exact NAS compose file required}"
: "${MY_PA_IMAGE_MANIFEST:?exact deployable image manifest required}"
: "${MY_PA_LIFECYCLE_MODE:=smoke}"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
pilot_overlay="$script_dir/compose.pilot.example.yml"

case "$MY_PA_LIFECYCLE_MODE" in
  smoke)
    python3 "$script_dir/lifecycle_gate.py" "$MY_PA_NAS_COMPOSE_FILE" "$pilot_overlay" \
      --image-manifest "$MY_PA_IMAGE_MANIFEST" --live
    ;;
  pilot)
    MY_PA_VERIFIED_PILOT_ORIGIN=$(python3 "$script_dir/lifecycle_gate.py" \
      "$MY_PA_NAS_COMPOSE_FILE" "$pilot_overlay" \
      --image-manifest "$MY_PA_IMAGE_MANIFEST" --pilot --live --print-verified-origin)
    export MY_PA_VERIFIED_PILOT_ORIGIN
    ;;
  *)
    echo "MY_PA_LIFECYCLE_MODE must be smoke or pilot" >&2
    exit 64
    ;;
esac

if [ "$MY_PA_LIFECYCLE_MODE" = pilot ]; then
  python3 "$script_dir/runtime_identity_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
    "$MY_PA_IMAGE_MANIFEST" --pilot-overlay "$pilot_overlay"
else
  python3 "$script_dir/runtime_identity_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
    "$MY_PA_IMAGE_MANIFEST"
fi

nas_compose() {
  if [ "$MY_PA_LIFECYCLE_MODE" = pilot ]; then
    docker compose --file "$MY_PA_NAS_COMPOSE_FILE" --file "$pilot_overlay" \
      --profile nas-01-contract-only "$@"
  else
    docker compose --file "$MY_PA_NAS_COMPOSE_FILE" \
      --profile nas-01-contract-only "$@"
  fi
}

verify_running_identity() {
  if [ "$MY_PA_LIFECYCLE_MODE" = pilot ]; then
    python3 "$script_dir/runtime_identity_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
      "$MY_PA_IMAGE_MANIFEST" --pilot-overlay "$pilot_overlay" --running
  else
    python3 "$script_dir/runtime_identity_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
      "$MY_PA_IMAGE_MANIFEST" --running
  fi
}
