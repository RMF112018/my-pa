#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
  echo "usage: $0 CANDIDATE_MANIFEST ARCHIVE_DIRECTORY OUTPUT_MANIFEST" >&2
  exit 64
fi
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
candidate=$1
archive_dir=$2
output=$3
[ -f "$candidate" ] && [ -d "$archive_dir" ] || {
  echo "candidate manifest and archive directory must exist" >&2
  exit 64
}
[ ! -e "$output" ] || { echo "output manifest already exists" >&2; exit 1; }

# Admission verifies the candidate checksums before any engine mutation.
"$NAS_PYTHON_BIN" - "$candidate" "$archive_dir" <<'PY'
import hashlib, sys, tomllib
from pathlib import Path
manifest = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if manifest.get("status") != "candidate_not_deployable":
    raise SystemExit("candidate manifest is not loadable")
def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            value.update(chunk)
    return value.hexdigest()
for name in ("app", "postgres", "proxy", "web"):
    section = manifest.get("images", {}).get(name, {})
    for suffix, key in (("tar", "archive_sha256"), ("metadata.json", "build_metadata_sha256")):
        path = Path(sys.argv[2]) / f"{name}.{suffix}"
        if digest(path) != section.get(key):
            raise SystemExit(f"{name} {suffix} checksum mismatch")
PY

for name in app web postgres proxy; do
  nas_docker load --input "$archive_dir/$name.tar" >/dev/null
done
"$NAS_PYTHON_BIN" "$script_dir/admit-image-manifest.py" "$candidate" "$archive_dir" "$output"
"$NAS_PYTHON_BIN" "$script_dir/image_gate.py" "$output" --archive-dir "$archive_dir" --live
