# Operator CLI

`migration.py` drives the legacy-SQLite to PostgreSQL migration.

```text
python apps/cli/migration.py init-run --source <path>
python apps/cli/migration.py status   --run-id <id>
python apps/cli/migration.py load     --run-id <id> --source <path> --phase PHASE-03
python apps/cli/migration.py resume   --run-id <id> --source <path>
python apps/cli/migration.py dry-run  --run-id <id> --source <path> --phase PHASE-03
```

Targets are always explicit: `--source` is required wherever the legacy database
is read, and the target comes from `MY_PA_DATABASE_URL`. The source is opened
read-only and is never written to. Output carries counts, table names, states,
and error codes — never a row value.

The engine behind it lives in `src/my_pa/infrastructure/migration/`; the load's
place in the Alembic sequence is documented in
[`migrations/README.md`](/migrations/README.md).

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.
