#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: $0 IMAGE_MANIFEST ARCHIVE_DIRECTORY" >&2
  exit 64
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
"$NAS_PYTHON_BIN" "$script_dir/image_gate.py" "$1" --archive-dir "$2" --live
MY_PA_IMAGE_MANIFEST=$1
export MY_PA_IMAGE_MANIFEST
. "$script_dir/lifecycle-common.sh"
"$script_dir/synology-data-plane-firewall.sh" check
nas_compose config --quiet
if ! nas_compose up --detach --no-build --pull never; then
  echo "Compose start failed; stopping any partial stack" >&2
  "$script_dir/cleanup-partial-start.sh" || true
  exit 1
fi
if ! running_output=$(nas_compose ps --status running -q); then
  echo "could not verify services after start; stopping the partial stack" >&2
  "$script_dir/cleanup-partial-start.sh" || true
  exit 1
fi
running=$(printf '%s\n' "$running_output" | sed '/^$/d' | wc -l | tr -d ' ')
if [ "$running" -ne 6 ]; then
  echo "expected six running runtime services; stopping the partial stack" >&2
  "$script_dir/cleanup-partial-start.sh" || true
  exit 1
fi
if ! verify_running_identity; then
  echo "running service identity mismatch; stopping the partial stack" >&2
  "$script_dir/cleanup-partial-start.sh" || true
  exit 1
fi

echo "NAS runtime started in $MY_PA_LIFECYCLE_MODE mode; run health.sh and permission gates"
