#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/postgres-common.sh"
: "${MY_PA_EXPECTED_ALEMBIC_HEAD:?single expected Alembic head required}"
: "${MY_PA_VERIFIED_BACKUP_RECEIPT:?recent verified backup receipt required}"
"$script_dir/verify-backup-receipt.sh" "$MY_PA_VERIFIED_BACKUP_RECEIPT"
pg_exec pg_isready -U my_pa -d my_pa
heads=$(nas_compose run --rm --no-deps gateway python -m alembic heads | awk '{print $1}')
[ "$heads" = "$MY_PA_EXPECTED_ALEMBIC_HEAD" ] || { echo "Alembic head mismatch or multiple heads" >&2; exit 1; }
nas_compose run --rm --no-deps gateway python -m alembic upgrade head
current=$(nas_compose run --rm --no-deps gateway python -m alembic current | awk '{print $1}')
[ "$current" = "$MY_PA_EXPECTED_ALEMBIC_HEAD" ] || { echo "post-migration revision mismatch" >&2; exit 1; }
nas_compose run --rm --no-deps gateway python apps/cli/health.py
