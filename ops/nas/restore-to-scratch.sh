#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/tooling-common.sh"
[ "$#" -eq 2 ] && [ -f "$1" ] && [ ! -L "$1" ] || { echo "usage: $0 REGULAR_CUSTOM_DUMP my_pa_scratch_NAME" >&2; exit 64; }
dump=$1
scratch=$2
: "${MY_PA_SCRATCH_DATABASE_URL:?secret scratch database URL required for application health}"
printf '%s\n' "$scratch" | grep -Eq '^my_pa_scratch_[A-Za-z0-9_]+$' || {
  echo "refusing non-scratch name" >&2; exit 1;
}
"$NAS_PYTHON_BIN" - "$MY_PA_SCRATCH_DATABASE_URL" "$scratch" <<'PY'
import sys
from urllib.parse import urlsplit
url = urlsplit(sys.argv[1])
if url.scheme != "postgresql+psycopg" or url.hostname != "postgres" or url.port != 5432 or url.username != "my_pa" or url.password is not None or url.query or url.fragment or url.path != "/" + sys.argv[2]:
    raise SystemExit("scratch URL authority does not match the verified Compose database")
PY
. "$script_dir/postgres-common.sh"
database_operator_with_url "$MY_PA_SCRATCH_DATABASE_URL" \
  python -c 'from my_pa.bootstrap.settings import load_settings; load_settings()'
heads=$(database_operator python -m alembic heads | awk '{print $1}')
printf '%s\n' "$heads" | grep -Eq '^[0-9a-f]{12}$' || { echo "repository Alembic head mismatch" >&2; exit 1; }
dump_dir=$(CDPATH= cd -- "$(dirname -- "$dump")" && pwd)
dump="$dump_dir/$(basename "$dump")"
umask 077
staged_dir=$(mktemp -d "${TMPDIR:-/tmp}/my-pa-restore.XXXXXX")
staged="$staged_dir/input.dump"
cleanup_stage() { rm -f "$staged"; rmdir "$staged_dir"; }
trap cleanup_stage EXIT HUP INT TERM
cp -p "$dump" "$staged"
chmod 0600 "$staged"
source_sha=$(sha256_file "$dump")
staged_sha=$(sha256_file "$staged")
[ "$source_sha" = "$staged_sha" ] || { echo "dump changed while staging" >&2; exit 1; }
pg_exec pg_restore --list < "$staged" >/dev/null
if pg_exec psql -U my_pa -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname = '$scratch'" | grep -q 1; then
  echo "scratch database already exists" >&2; exit 1
fi
pg_exec createdb -U my_pa -T template0 -E UTF8 \
  --locale=C.UTF-8 --owner=my_pa "$scratch"
if ! pg_exec pg_restore -U my_pa -d "$scratch" \
  --exit-on-error --no-owner --no-privileges < "$staged"; then
  echo "restore failed; scratch database retained for diagnosis" >&2; exit 1
fi
revision=$(pg_exec psql -U my_pa -d "$scratch" -tAc \
  'SELECT version_num FROM alembic_version')
[ "$revision" = "$heads" ] || { echo "scratch revision mismatch" >&2; exit 1; }
extensions=$(pg_exec psql -U my_pa -d "$scratch" -tAc \
  "SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension WHERE extname IN ('pg_trgm','plpgsql','unaccent')")
[ "$extensions" = "pg_trgm,plpgsql,unaccent" ] || { echo "scratch extensions mismatch" >&2; exit 1; }
database_operator_with_url "$MY_PA_SCRATCH_DATABASE_URL" python apps/cli/health.py
echo "scratch restore verified; database retained until explicit operator removal"
