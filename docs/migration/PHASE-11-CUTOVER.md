# Phase 11 — Cutover

PostgreSQL `my_pa` is now the canonical store for this repository. This document
records what that means concretely, how an application component obtains a
session, why there is nothing to coexist with, and how to roll the target back.

Every figure below was read from the live database or from
`migration_control` on 2026-08-01. Nothing here is copied from a plan or a
report.

## What "cutover" means here

The `OP-CUTOVER-001` operator gate was resolved **PROCEED**, with a scope narrow
enough that the word "cutover" is misleading unless it is spelled out. The
narrowness is the whole point:

- `my-pa` had no datastore before this migration. There was no live system to
  cut over from, no downtime, and no read switch to flip.
- Cutover is therefore a **statement of record**, not an operation: PostgreSQL
  `my_pa` holds the canonical data, and every future `my-pa` component reads and
  writes it.
- Nothing was deployed, exposed, or activated in production. The container
  publishes on `127.0.0.1:5433` only.
- The legacy `hb-personal-assistant` application keeps running on its own SQLite
  file, untouched and unaffected by anything in this repository.

## Verified state

Read from the live server on 2026-08-01.

| Property | Value | Source |
| --- | --- | --- |
| Server | PostgreSQL 17.10 (Debian 17.10-1.pgdg13+1), aarch64 | `SELECT version()` |
| Container / image | `my-pa-postgres` / `postgres:17.10` | `docker compose ps` |
| Endpoint | `127.0.0.1:5433` → container `5432` | `docker compose ps` |
| Data volume | `my_pa_pgdata` | `docker volume ls` |
| Alembic revision | `3a8e2cb16d59` (head) | `public.alembic_version` |
| Schemas | `core`, `procore`, `email`, `calendar`, `contacts`, `financial`, `schedule`, `construction`, `migration_control` | `pg_namespace` |
| Extensions | `pg_trgm` 1.6, `unaccent` 1.1, `plpgsql` 1.0 | `pg_extension` |
| Base tables | 494 = 484 domain + 9 `migration_control` + `public.alembic_version` | `information_schema.tables` |
| Rows in domain schemas | **3,263,870** | `count(*)` over all 484 domain tables |
| Foreign keys | 277, of which 0 are `NOT VALID` | `pg_constraint` |
| Indexes | 1,511 | `pg_indexes` |
| Views | 0 | `information_schema.views` |
| Database size | 4,412 MB | `pg_database_size('my_pa')` |
| Collation / encoding | `C.UTF-8` / `UTF8`, data checksums on | `pg_database` |

Per schema:

| Schema | Tables | Rows |
| --- | ---: | ---: |
| `procore` | 150 | 2,102,327 |
| `schedule` | 43 | 452,609 |
| `email` | 26 | 391,432 |
| `financial` | 67 | 144,429 |
| `core` | 161 | 119,910 |
| `calendar` | 11 | 50,874 |
| `construction` | 26 | 2,289 |
| `contacts` | 0 | 0 |
| **Total** | **484** | **3,263,870** |

`contacts` is empty and has no tables because every object the plan assigned to
that domain is one of the fifteen absent from the source at schema 128
(`OD-001`; see [`PHASE-12-RETENTION.md`](PHASE-12-RETENTION.md)). It is an
expected, named gap, not a load failure.

The view count of 0 is **not** expected. `OD-018` requires the two SQLite read
models — `v_procore_inspection_unanswered_items` and
`v_procore_open_action_signals` — to be hand-ported as PostgreSQL views over the
migrated base tables, and they have not been. Phase 10 records this as an open
failure (`P10-16`). It does not affect the data above, which is base-table
content, but the cutover state is not complete until those two views exist.

Two loads produced this state, both `COMPLETED` in
`migration_control.migration_runs`:

| Run | Bound revision | Tables | Source rows | Loaded | Quarantined |
| --- | --- | ---: | ---: | ---: | ---: |
| `9c36cf05-b5f1-4382-94b0-0328679a3373` | `4b9f0d27ac31` | 393 | 3,258,490 | 3,258,482 | 8 |
| `ed06aadf-c1de-42f4-bc32-a2ce33c5975a` | `3a8e2cb16d59` | 5 | 5,388 | 5,388 | 0 |
| **Total** | | **398** | **3,263,878** | **3,263,870** | **8** |

The second run is the `OD-028` correction: five `*_runs` provenance tables that
the original operational-state exclusion had wrongly withheld from their derived
children. All 277 foreign keys validate with zero orphans, which is the outcome
`OD-028` predicted.

Control-plane volumes: `source_key_map` 3,228,581 rows, `identifier_map` 764
rows, `audit_events` 860 rows, `quarantine_records` 8 rows.

## What "canonical" means concretely

- **`my-pa` reads and writes PostgreSQL.** `MY_PA_DATABASE_URL` is the only
  database configuration the package has, and it must name a PostgreSQL server.
  No application, domain, or repository code path reads SQLite, and none may be
  added.
- **The legacy SQLite file is an immutable archive of record.** It is not a
  runtime dependency, not a fallback, and not a read replica. The only code in
  this repository that opens it is the migration tooling under
  `src/my_pa/infrastructure/migration/`, which reads it through an
  `immutable=1` URI and has finished its work. Nothing in the application path
  reaches it.
- **The archive is permanent.** `OP-RETIRE-001` was resolved **DO NOT PROCEED**
  (`OD-003`). It is retained indefinitely and never mutated. See
  [`PHASE-12-RETENTION.md`](PHASE-12-RETENTION.md).
- **Provenance travels with the data.** Every one of the 484 domain tables
  carries `migration_run_id`, `migration_source_table`,
  `migration_source_schema_version`, and `migration_natural_key_hash`, so any row
  can be traced to the run and the source table it came from without consulting
  the archive.

## Connection contract

The contract itself is documented in
[`PHASE-01-FOUNDATION.md`](PHASE-01-FOUNDATION.md); this section says only how a
component obtains a session against the now-populated database.

`MY_PA_DATABASE_URL` supplies the URL. It must use the `postgresql+psycopg`
scheme and name a host and a database, or startup fails. The default is
`postgresql+psycopg://my_pa@localhost:5433/my_pa` and carries **no password**;
supply it out of band with `PGPASSWORD` or `~/.pgpass`.

`src/my_pa/infrastructure/database/` exports exactly three names — there is no
other supported way in:

```python
from my_pa.bootstrap.settings import load_settings
from my_pa.infrastructure.database import (
    DatabaseHealth,
    create_database_engine,
    healthcheck,
)

engine = create_database_engine(load_settings().database_url)
try:
    with engine.begin() as connection:
        ...  # one transaction: commits on a clean exit, rolls back on any error
finally:
    engine.dispose()
```

Three properties of that module worth knowing before you use it:

- **Nothing in it reads process settings.** `create_database_engine` takes a URL
  argument. Configuration stays in bootstrap, and a disposable test database is
  an ordinary argument rather than a special case — which is what makes the
  rollback rehearsal below safe to run.
- **The caller owns the engine's lifetime** and must `dispose()` it.
- **The pool is small and hard-bounded**: five connections, no overflow, 30 s
  checkout timeout, with pre-ping. A leak surfaces as a timeout rather than as
  an unbounded number of backends.

`healthcheck(engine)` returns a `DatabaseHealth` carrying the server version and
the installed extensions, and raises the driver's own error when the server is
unreachable. It carries no row content. Verified against the live database:

```
DatabaseHealth(server_version='17.10 (Debian 17.10-1.pgdg13+1)',
               extensions=('pg_trgm', 'plpgsql', 'unaccent'))
```

## Coexistence

**The two systems share nothing.** They are separate stores, on separate
technologies, with no connection between them:

| | `my-pa` | legacy `hb-personal-assistant` |
| --- | --- | --- |
| Store | PostgreSQL `my_pa`, `127.0.0.1:5433` | its own SQLite file |
| Written by | `my-pa` only | the legacy application only |
| Reads the other | never | never |

There is **no dual-write**, by default and by decision. The cutover strategy
prohibits it unless an operator records an explicit exception, and no exception
exists. Nothing propagates from PostgreSQL back to SQLite, and nothing
propagates forward from SQLite to PostgreSQL after the migration runs recorded
above.

The practical consequence: the two stores drift apart from the moment the load
finished, and that is intended. PostgreSQL is canonical for `my-pa`; the SQLite
file is a frozen snapshot of what the legacy application held at schema 128 on
the day it was captured. Neither is a mirror of the other, and reconciling them
is not a goal.

## Rollback runbook

Rollback here is **target-side only**. It is not a cutover reversal — there is
no application to switch back — it is how you return the PostgreSQL side to a
known state when a load needs redoing.

### Rehearse against a disposable database, never against `my_pa`

`my_pa` now holds 3,263,870 real rows that took two runs to produce.
`alembic downgrade base` against it drops every schema and destroys all of them.
Rehearse on a disposable database instead:

```sh
docker exec my-pa-postgres psql -U my_pa -d postgres \
  -c 'DROP DATABASE IF EXISTS my_pa_rollback_rehearsal;' \
  -c 'CREATE DATABASE my_pa_rollback_rehearsal OWNER my_pa;'

export MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@localhost:5433/my_pa_rollback_rehearsal'
export PGPASSWORD=...
```

**Export `MY_PA_DATABASE_URL` in the same shell before every Alembic command
below.** Alembic reads its URL from that variable through
`my_pa.bootstrap.settings`; `alembic.ini` deliberately has no `sqlalchemy.url`
key. An unset variable falls back to the default, which is canonical `my_pa`.
That fallback is the single most likely way to destroy this database by
accident. See the
[operations runbook](/ops/runbooks/postgres-operations.md#never-downgrade-canonical-my_pa)
for the check to run first.

Everything in this section was executed against
`my_pa_rollback_rehearsal` on 2026-08-01 and the database was dropped afterwards.
Canonical `my_pa` was never a target.

### 1. Roll the database back to empty

```sh
.venv/bin/alembic downgrade base
```

Verified on the rehearsal database: the five revisions reverse in order and the
database returns to empty — 0 of the 9 migration-owned schemas remain, the only
relation left is `public.alembic_version` (empty, Alembic's own bookkeeping),
and `pg_extension` falls back to `plpgsql` alone. `alembic current` prints
nothing, which is how base reports itself. It took under two seconds on an empty
schema; against a populated database it also has to drop the data.

Downgrades drop with `RESTRICT`. Reaching one with objects still in a schema
means a revision failed to clean up after itself, and failing there is better
than silently deleting the contents.

### 2. Re-run a migration from scratch

```sh
export MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@localhost:5433/<disposable-db>'
export PGPASSWORD=...

.venv/bin/alembic downgrade base
.venv/bin/alembic upgrade head
.venv/bin/alembic current            # must print 3a8e2cb16d59 (head)

.venv/bin/python apps/cli/migration.py init-run --source <path-to-legacy-sqlite>
# note the run_id it prints, then:
.venv/bin/python apps/cli/migration.py load --run-id <run-id> --source <path-to-legacy-sqlite>
.venv/bin/python apps/cli/migration.py validate-foreign-keys
.venv/bin/python apps/cli/migration.py status --run-id <run-id>
```

`upgrade head` and `downgrade base` were both verified on the rehearsal
database. At head it reproduced canonical `my_pa` exactly: 494 base tables, 277
foreign keys, 1,511 indexes, extensions `pg_trgm`, `plpgsql`, `unaccent`. The
`init-run`/`load` half of the sequence was **not** re-executed — a second full
load is a two-and-a-half-minute write of 3.26M rows and the completed runs are
already recorded — so treat those four lines as the documented procedure rather
than as a rehearsed one. `status` was run against canonical `my_pa`, which it
only reads. `validate-foreign-keys` was **not** run; the same fact was confirmed
by reading `pg_constraint` directly (277 foreign keys, 0 `NOT VALID`).

`init-run` re-reads the source and binds the new run to its sha256, byte count,
and schema version, so a source that has drifted stops the run rather than
loading silently. Use `resume` instead of `load` to continue a run that was
interrupted; use `dry-run` to transform and count without committing.

### 3. Roll back a single run by `migration_run_id`

Every domain table carries `migration_run_id`, so one run's rows can be removed
without disturbing another's. There is no CLI subcommand for this — it is the
SQL below.

Two facts that shape the procedure, both verified against the live database:

- **Order matters.** `migration_run_id` carries no foreign key of its own, but
  the loaded rows do: deleting a parent table before its children fails with a
  foreign-key violation. This was reproduced deliberately on the rehearsal
  database.
- **The foreign-key graph is a DAG of depth 3**, with no cycles and no
  self-references, so a reverse-topological delete order always exists and is
  cheap to compute.

Save as `rollback_run.sql`:

```sql
-- Roll back one migration run, target side only.
--   psql -v run_id='<uuid>' -f rollback_run.sql
\set ON_ERROR_STOP on

BEGIN;

SELECT format('DELETE FROM %s WHERE migration_run_id = %L;', ident, :'run_id')
FROM (
    WITH RECURSIVE owned AS (
        SELECT c.oid
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid
        WHERE c.relkind = 'r'
          AND n.nspname IN ('core', 'procore', 'email', 'calendar',
                            'contacts', 'financial', 'schedule', 'construction')
          AND a.attname = 'migration_run_id'
          AND NOT a.attisdropped
    ),
    edge AS (
        SELECT conrelid AS child, confrelid AS parent
        FROM pg_constraint
        WHERE contype = 'f' AND conrelid <> confrelid
    ),
    depth AS (
        SELECT oid AS rel, 0 AS d FROM owned
        UNION ALL
        SELECT e.parent, d.d + 1
        FROM depth d JOIN edge e ON e.child = d.rel
        WHERE d.d < 50
    )
    SELECT rel::regclass AS ident, max(d) AS level
    FROM depth GROUP BY rel
) t
ORDER BY level ASC, ident::text ASC;
\gexec

DELETE FROM migration_control.source_key_map     WHERE run_id = :'run_id';
DELETE FROM migration_control.quarantine_records WHERE run_id = :'run_id';
DELETE FROM migration_control.batch_checkpoints  WHERE run_id = :'run_id';
DELETE FROM migration_control.table_progress     WHERE run_id = :'run_id';
DELETE FROM migration_control.phase_status       WHERE run_id = :'run_id';
DELETE FROM migration_control.leases             WHERE run_id = :'run_id';

UPDATE migration_control.migration_runs
   SET status = 'ROLLED_BACK'
 WHERE run_id = :'run_id';

COMMIT;
```

Run it against a **disposable** database:

```sh
docker exec -i my-pa-postgres psql -U my_pa -d <disposable-db> \
  -v run_id='<uuid>' -f - < rollback_run.sql
```

The `SELECT`/`\gexec` pair generates one `DELETE` per table ordered
children-before-parents and then executes them. Run the `SELECT` on its own
first to read the statements before they run — that preview is the reason this
is written as `\gexec` rather than as a `DO` block. (It is also the reason it
cannot be a `DO` block: psql does not interpolate `:'run_id'` inside a
dollar-quoted body, which fails at parse time.)

The whole script is one transaction, so a foreign-key violation anywhere aborts
the entire rollback rather than leaving a half-removed run.

The run row is kept and marked `ROLLED_BACK` rather than deleted. The status is
part of the record: a deleted run row would make the rollback invisible, and the
`ON DELETE CASCADE` on its children would take the evidence with it.

Verified on `my_pa_rollback_rehearsal` with a synthetic parent/child pair tagged
to a synthetic run: the naive parent-first delete failed with the expected
foreign-key violation; the ordered script removed both rows, cleared the
control-plane rows, and left the run at `ROLLED_BACK`.

**Per-run rollback is not always possible, and that is correct.** Run
`ed06aadf-…` loaded five parent tables whose children were loaded by run
`9c36cf05-…`. Rolling back `ed06aadf-…` alone would orphan those children, so
the script aborts. Roll back the dependent run first, or roll the database back
to empty and reload.

### What rollback must never touch

**The legacy SQLite source, under any circumstance.** Not to "restore" it, not
to re-sync it, not to reset a flag in it, not to `VACUUM` it, not to rename or
move it. `OD-003` makes this absolute for every phase, and no rollback path
above reads it at all except `init-run`, which opens it with `immutable=1` so
that not even a journal or WAL file can appear beside it.

If a rollback procedure ever appears to require writing to the source, that is a
defect in the procedure. Stop and report it.

Also out of scope for rollback: the container, the `my_pa_pgdata` volume, and
the role. Rolling a *schema* back is Alembic's job. Destroying the *cluster* is
a different and much larger operation — see
[`ops/postgres/README.md`](/ops/postgres/README.md).

## Where this contradicts the plan

Five parts of the planning package's Phase 11 text are superseded. They are
listed rather than quietly dropped.

| Plan text | Superseded by | Why |
| --- | --- | --- |
| Cutover sequence steps 3–7: source freeze, final delta window, delta migration, application read switch, watch period | `OP-CUTOVER-001`, with `OD-002` | All presuppose a live system being moved. The target was created fresh by this campaign and `my-pa` had no datastore before it, so there is nothing to freeze, no delta, and no switch. |
| Rollback window "retained until PHASE-12 eligibility" | `OD-003` / `OP-RETIRE-001` | There is no Phase 12 eligibility date. Retention is indefinite, so the window never closes. |
| §7 "legacy remains RO fallback until retirement auth" | `OD-003` | The legacy store is not a fallback. It is an archive that no `my-pa` component opens, retained permanently rather than pending authorization. |
| P11-AC-02 read-switch rehearsal, P11-AC-08 operator cutover authorization ID, P11-AC-09 communications checklist, P11-AC-10 independent review | `OD-005`, and `OP-CUTOVER-001` | No read switch exists to rehearse. `OD-005` sets aside authorization artifacts and mandatory external review for this campaign. A single-user local database has no one to notify. |
| §9 and §14: source bound by sha256 `fa3631f7…` at schema 135; §17 stop condition "schema version ≠ 135" | `OD-001` | That snapshot does not exist on this machine. The bound source is sha256 `9b8c8d8b…` at schema 128. A stop condition on 135 would halt the completed migration. |

`P11-AC-01` (freeze/delta assumptions), `P11-AC-04` (rollback triggers),
`P11-AC-06` (no dual-write), and `P11-AC-07` (legacy still read-only and
present) are satisfied by this document and by `OD-003`. `P11-AC-03` and
`P11-AC-05` are satisfied for the parts that exist: the health check is defined
and green, and the rollback rehearsal above passed.
