#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/postgres-common.sh"
: "${MY_PA_VERIFIED_BACKUP_RECEIPT:?recent verified backup receipt required}"
"$script_dir/verify-backup-receipt.sh" "$MY_PA_VERIFIED_BACKUP_RECEIPT"
pg_exec pg_isready -U my_pa -d my_pa
heads_output=$(nas_compose run --rm --no-deps gateway python -m alembic heads | awk '{print $1}')
[ "$(printf '%s\n' "$heads_output" | sed '/^$/d' | wc -l | tr -d ' ')" -eq 1 ] || {
  echo "Alembic head mismatch or multiple heads" >&2; exit 1;
}
heads=$heads_output
printf '%s\n' "$heads" | grep -Eq '^[0-9a-f]{12}$' || {
  echo "Alembic head mismatch or multiple heads" >&2; exit 1;
}
nas_compose run --rm --no-deps gateway python -m alembic upgrade head
current=$(nas_compose run --rm --no-deps gateway python -m alembic current | awk '{print $1}')
[ "$current" = "$heads" ] || { echo "post-migration revision mismatch" >&2; exit 1; }
nas_compose run --rm --no-deps gateway python apps/cli/health.py
