#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/postgres-common.sh"
[ "$#" -eq 1 ] && [ -d "$1" ] || { echo "usage: $0 EXISTING_BACKUP_DIRECTORY" >&2; exit 64; }
repo_root=$(git rev-parse --show-toplevel)
destination=$(CDPATH= cd -- "$1" && pwd)
case "$destination/" in "$repo_root/"*) echo "backup destination must be outside repository" >&2; exit 1;; esac
umask 077
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
final="$destination/my-pa-$timestamp.dump"
partial="$final.partial.$$"
receipt="$final.sha256"
[ ! -e "$final" ] && [ ! -e "$receipt" ] || { echo "backup collision" >&2; exit 1; }
trap 'rm -f "$partial"' EXIT HUP INT TERM
pg_exec pg_dump --username my_pa --dbname my_pa \
  --format custom --compress=zstd:9 --no-owner --no-privileges > "$partial"
pg_exec pg_restore --list < "$partial" >/dev/null
mv "$partial" "$final"
(CDPATH= cd -- "$destination" && shasum -a 256 "$(basename "$final")" > "$(basename "$receipt")")
trap - EXIT HUP INT TERM
echo "$receipt"
