#!/bin/sh
set -eu
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
(CDPATH= cd -- "$(dirname -- "$receipt")" && shasum -a 256 --check "$(basename "$receipt")") >/dev/null
now=$(date +%s)
stamp=$(printf '%s' "$dump_name" | sed -E 's/^my-pa-([0-9]{8}T[0-9]{6})Z[.]dump$/\1/')
created=$(date -u -d "${stamp%T*} ${stamp#*T}" +%s)
[ "$created" -le "$now" ] && [ $((now - created)) -le 86400 ] || {
  echo "backup receipt is not recent" >&2; exit 1;
}
