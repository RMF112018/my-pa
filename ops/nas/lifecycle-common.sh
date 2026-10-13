#!/bin/sh
set -eu

: "${MY_PA_NAS_COMPOSE_FILE:?exact NAS compose file required}"
: "${MY_PA_IMAGE_MANIFEST:?exact deployable image manifest required}"
: "${MY_PA_LIFECYCLE_MODE:=smoke}"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
pilot_overlay="$script_dir/compose.pilot.example.yml"
public_overlay=${MY_PA_NAS_PUBLIC_BROWSER_OVERLAY:-}
if [ -n "$public_overlay" ]; then
  [ "$MY_PA_LIFECYCLE_MODE" = smoke ] && \
    [ "$public_overlay" = "$script_dir/compose.public-browser.example.yml" ] && \
    [ -f "$public_overlay" ] && [ ! -L "$public_overlay" ] || {
    echo "public browser overlay must be the exact smoke source contract" >&2
    exit 1
  }
fi

case "$MY_PA_LIFECYCLE_MODE" in
  smoke)
    if [ -n "$public_overlay" ]; then
      "$NAS_PYTHON_BIN" "$script_dir/lifecycle_gate.py" "$MY_PA_NAS_COMPOSE_FILE" "$pilot_overlay" \
        --image-manifest "$MY_PA_IMAGE_MANIFEST" --live --public-browser-overlay "$public_overlay"
    else
      "$NAS_PYTHON_BIN" "$script_dir/lifecycle_gate.py" "$MY_PA_NAS_COMPOSE_FILE" "$pilot_overlay" \
      --image-manifest "$MY_PA_IMAGE_MANIFEST" --live
    fi
    ;;
  pilot)
    MY_PA_VERIFIED_PILOT_ORIGIN=$("$NAS_PYTHON_BIN" "$script_dir/lifecycle_gate.py" \
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
  "$NAS_PYTHON_BIN" "$script_dir/runtime_identity_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
    "$MY_PA_IMAGE_MANIFEST" --pilot-overlay "$pilot_overlay"
elif [ -n "$public_overlay" ]; then
  "$NAS_PYTHON_BIN" "$script_dir/runtime_identity_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
    "$MY_PA_IMAGE_MANIFEST" --public-browser-overlay "$public_overlay"
else
  "$NAS_PYTHON_BIN" "$script_dir/runtime_identity_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
    "$MY_PA_IMAGE_MANIFEST"
fi

nas_compose() {
  if [ "$MY_PA_LIFECYCLE_MODE" = pilot ]; then
    nas_docker compose --file "$MY_PA_NAS_COMPOSE_FILE" --file "$pilot_overlay" \
      --profile nas-01-contract-only "$@"
  elif [ -n "$public_overlay" ]; then
    nas_docker compose --file "$MY_PA_NAS_COMPOSE_FILE" --file "$public_overlay" \
      --profile nas-01-contract-only "$@"
  else
    nas_docker compose --file "$MY_PA_NAS_COMPOSE_FILE" \
      --profile nas-01-contract-only "$@"
  fi
}

verify_running_identity() {
  if [ "$MY_PA_LIFECYCLE_MODE" = pilot ]; then
    "$NAS_PYTHON_BIN" "$script_dir/runtime_identity_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
      "$MY_PA_IMAGE_MANIFEST" --pilot-overlay "$pilot_overlay" --running
  elif [ -n "$public_overlay" ]; then
    "$NAS_PYTHON_BIN" "$script_dir/runtime_identity_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
      "$MY_PA_IMAGE_MANIFEST" --public-browser-overlay "$public_overlay" --running
  else
    "$NAS_PYTHON_BIN" "$script_dir/runtime_identity_gate.py" "$MY_PA_NAS_COMPOSE_FILE" \
      "$MY_PA_IMAGE_MANIFEST" --running
  fi
}
