#!/bin/sh
# Dry-run rollback planner. Does not talk to production, does not docker build,
# and does not start, stop, or tag images.
set -eu

usage() {
  echo "usage: $0 --dry-run PREVIOUS_MANIFEST" >&2
  exit 64
}

dry_run=false
manifest=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=true ;;
    --build|build)
      echo "rollback refused: docker build is forbidden" >&2
      exit 1
      ;;
    -h|--help) usage ;;
    --*)
      echo "rollback refused: unknown option $arg" >&2
      exit 64
      ;;
    *)
      if [ -n "$manifest" ]; then
        echo "rollback refused: extra argument $arg" >&2
        exit 64
      fi
      manifest=$arg
      ;;
  esac
done

[ -n "$manifest" ] || usage
[ -f "$manifest" ] || {
  echo "rollback refused: previous manifest missing: $manifest" >&2
  exit 1
}

if command -v python3 >/dev/null 2>&1; then
  python_bin=python3
elif command -v python >/dev/null 2>&1; then
  python_bin=python
else
  echo "rollback refused: python is required to read the manifest" >&2
  exit 1
fi

identities=$("$python_bin" - "$manifest" <<'PY'
import sys
import tomllib
from pathlib import Path

path = Path(sys.argv[1])
data = tomllib.loads(path.read_text(encoding="utf-8"))
if data.get("schema") != "my-pa.nas-deployment-manifest.v1":
    raise SystemExit("rollback refused: unsupported manifest schema")
fields = (
    "app_image_id",
    "web_image_id",
    "proxy_image_digest",
    "cloudflared_image",
)
for name in fields:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"rollback refused: missing {name}")
    lowered = value.lower()
    if (
        lowered.endswith(":latest")
        or ":latest@" in lowered
        or lowered == "latest"
        or "/latest@" in lowered
    ):
        raise SystemExit(f"rollback refused: latest tag forbidden in {name}")
    print(f"{name}={value}")
PY
) || exit 1

echo "rollback dry-run: previous manifest $manifest"
printf '%s\n' "$identities"
echo "rollback does not talk to production and will not docker build"

if [ "$dry_run" != true ]; then
  echo "rollback refused: live rollback is operator-gated; pass --dry-run" >&2
  exit 1
fi

echo "PRODUCTION_ACTIVATION_NOT_PERFORMED"
exit 0
