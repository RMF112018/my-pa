#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
[ "$#" -eq 1 ] && [ -f "$1" ] && [ ! -L "$1" ] || { echo "verified backup receipt missing or linked" >&2; exit 1; }
receipt=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)/$(basename "$1")
case "$receipt" in *.dump.sha256) ;; *) echo "invalid backup receipt name" >&2; exit 1;; esac
line_count=$(wc -l < "$receipt" | tr -d ' ')
[ "$line_count" -eq 1 ] || { echo "receipt must name exactly one dump" >&2; exit 1; }
grep -Eq '^[0-9a-f]{64}  my-pa-[0-9]{8}T[0-9]{6}Z[.]dump$' "$receipt" || {
  echo "invalid backup receipt grammar" >&2; exit 1;
}
dump_name=$(awk '{print $2}' "$receipt")
[ "$dump_name" = "$(basename "${receipt%.sha256}")" ] || { echo "receipt names wrong dump" >&2; exit 1; }
dump=$(dirname "$receipt")/$dump_name
[ -f "$dump" ] && [ ! -L "$dump" ] || { echo "backup dump missing or linked" >&2; exit 1; }
(CDPATH= cd -- "$(dirname -- "$receipt")" && sha256_check_receipt "$(basename "$receipt")") >/dev/null
"$NAS_PYTHON_BIN" - "$dump_name" <<'PY'
from datetime import UTC, datetime
import sys

try:
    created = datetime.strptime(sys.argv[1], "my-pa-%Y%m%dT%H%M%SZ.dump").replace(tzinfo=UTC)
except ValueError:
    raise SystemExit("backup receipt timestamp is invalid") from None
age = (datetime.now(UTC) - created).total_seconds()
if age < 0 or age > 86_400:
    raise SystemExit("backup receipt is not recent")
PY
