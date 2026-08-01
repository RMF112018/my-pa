# Runbook — PostgreSQL operations for `my_pa`

Day-to-day operation of the canonical `my_pa` database: start, stop, health
check, connect, back up, restore.

The instance itself — image, tuning, locale, cluster-creation settings, and why
each was chosen — is documented in [`../postgres/README.md`](../postgres/README.md)
and defined by [`../compose/postgres.yml`](../compose/postgres.yml). This runbook
does not repeat that; it covers the operations.

All commands run from the repository root. Every command below was executed on
2026-08-01 except where marked otherwise.

| | |
| --- | --- |
| Container | `my-pa-postgres` (`postgres:17.10`) |
| Database / role | `my_pa` / `my_pa` |
| Endpoint | `127.0.0.1:5433` → container `5432` |
| Data volume | `my_pa_pgdata` |
| Compose file | `ops/compose/postgres.yml` |

## Never downgrade canonical `my_pa`

**`alembic downgrade base` against `my_pa` drops all nine migration-owned
schemas and destroys 3,263,870 migrated rows.** They took two loads of the 4.4 GB
legacy source to produce. There is no undo.

The way this happens by accident is that Alembic takes its URL from
`MY_PA_DATABASE_URL` through `my_pa.bootstrap.settings` — `alembic.ini`
deliberately has no `sqlalchemy.url` key — and an **unset** variable falls back
to the default, which is canonical `my_pa`. So a `downgrade` intended for a
disposable database silently hits the real one when the export is missing from
the shell you are actually in.

Check before every destructive Alembic command, in the same shell:

```sh
echo "${MY_PA_DATABASE_URL:?MY_PA_DATABASE_URL is unset - refusing}"
```

It must print a URL ending in your disposable database name, not `/my_pa`.

The `:?` form fails the shell with that message when the variable is unset,
rather than printing an empty line you might miss.

Then confirm what Alembic itself resolved — `current -v` names the URL it
connected to:

```sh
.venv/bin/alembic current -v
```

```
Current revision(s) for postgresql+psycopg://my_pa@localhost:5433/my_pa:
Rev: 3a8e2cb16d59 (head)
```

If that line ends in `/my_pa`, you are pointed at the canonical database. Stop.

Two habits that make the mistake harder:

- Do the destructive work on a **separate database in the same container**, not
  on `my_pa` with a mental note. Creating one is two seconds:

  ```sh
  docker exec my-pa-postgres psql -U my_pa -d postgres \
    -c 'CREATE DATABASE my_pa_scratch OWNER my_pa;'
  ```

- **Take a dump first** (below). A 10-second `pg_dump` is cheaper than a
  three-minute reload, and much cheaper than discovering the reload needs a
  source file you no longer have.

Rollback procedures themselves are in
[`docs/migration/PHASE-11-CUTOVER.md`](/docs/migration/PHASE-11-CUTOVER.md#rollback-runbook).

## Start and stop

```sh
docker compose -f ops/compose/postgres.yml up -d      # start, detached
docker compose -f ops/compose/postgres.yml ps         # status and health
docker compose -f ops/compose/postgres.yml logs -f postgres
docker compose -f ops/compose/postgres.yml down       # stop; keeps the volume
```

`down` removes the container but not `my_pa_pgdata`, so data survives a
stop/start cycle and a reboot. `restart: unless-stopped` brings the container
back with Docker.

`stop_grace_period: 60s` in the compose file gives the server an unhurried
shutdown; do not shorten it, and do not `docker kill` the container — an
interrupted checkpoint means crash recovery on the next start.

**`down --volumes` deletes `my_pa_pgdata` and every row in it.** That is the
reset procedure in [`../postgres/README.md`](../postgres/README.md#reset-the-database-from-scratch),
not an operation to reach for casually.

`up -d`, `down`, and `down --volumes` were **not** executed while writing this
runbook: the container was serving a live database at the time and stopping it
would have interrupted work in progress. They are transcribed from the compose
file and from `../postgres/README.md`. `ps` was run.

## Health check

Three levels, cheapest first.

```sh
docker compose -f ops/compose/postgres.yml ps
```

```
NAME             IMAGE            STATUS                    PORTS
my-pa-postgres   postgres:17.10   Up 29 minutes (healthy)   127.0.0.1:5433->5432/tcp
```

`(healthy)` comes from the compose healthcheck, which runs
`pg_isready -U my_pa -d my_pa` every 10 s. Run it directly to see why:

```sh
docker exec my-pa-postgres pg_isready -U my_pa -d my_pa
# /var/run/postgresql:5432 - accepting connections   (exit 0)
```

Through the application's own connection path, which additionally proves the
URL, the driver, and the extensions:

```sh
MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@localhost:5433/my_pa' \
PGPASSWORD=... \
.venv/bin/python -c "
from my_pa.bootstrap.settings import load_settings
from my_pa.infrastructure.database import create_database_engine, healthcheck
engine = create_database_engine(load_settings().database_url)
print(healthcheck(engine))
engine.dispose()"
```

```
DatabaseHealth(server_version='17.10 (Debian 17.10-1.pgdg13+1)',
               extensions=('pg_trgm', 'plpgsql', 'unaccent'))
```

It reports the server version and installed extensions, carries no row content,
and raises the driver's own error when the server is unreachable.

A one-line content check — expect the migration head and the database size:

```sh
docker exec my-pa-postgres psql -U my_pa -d my_pa -c "
SELECT (SELECT version_num FROM public.alembic_version) AS head,
       pg_size_pretty(pg_database_size('my_pa')) AS size;"
```

```
     head     |  size
--------------+---------
 3a8e2cb16d59 | 4412 MB
```

## Connect

Interactive shell over the container's Unix socket — no password needed, because
local socket connections are trusted:

```sh
docker exec -it my-pa-postgres psql -U my_pa -d my_pa
```

One-off statement:

```sh
docker exec my-pa-postgres psql -U my_pa -d my_pa -c 'SELECT version();'
```

Over TCP from the host, which is what the application does:

```
postgresql://my_pa:<password>@localhost:5433/my_pa
```

Port 5433 rather than 5432 is deliberate — an unqualified connection to some
other local PostgreSQL cannot land here by accident. Keep the password out of
source and out of shell history; supply it with `PGPASSWORD` or `~/.pgpass` and
build the URL from the environment at runtime.

## Back up

```sh
mkdir -p ~/local-sensitive/my-pa-backups

docker exec my-pa-postgres pg_dump \
  -U my_pa -d my_pa \
  --format=custom --compress=zstd --no-owner --no-privileges \
  > ~/local-sensitive/my-pa-backups/my_pa-$(date -u +%Y%m%dT%H%M%SZ).dump
```

**The output lands on the host**, at the path after `>`. `pg_dump` writes to its
stdout inside the container and `docker exec` streams that to your shell, so no
file is created inside the container and no volume mount is needed.

Measured on 2026-08-01 against the live database: **10.7 seconds, 583,375,401
bytes** (556 MB) for 3,263,870 rows and a 4,412 MB database. `pg_dump` takes only
a shared lock, so it is safe to run while the database is in use.

Choices worth knowing:

- `--format=custom` is required for selective and parallel restore, and is what
  `pg_restore` consumes. A plain SQL dump cannot do either.
- `--compress=zstd` gets 4.4 GB down to 556 MB. It needs PostgreSQL 16 or newer
  at both ends; this is 17.10.
- `--no-owner --no-privileges` lets the dump restore under any role, so a
  restore does not depend on `my_pa` existing with the same name.

**Where the file goes matters.** The dump contains personal data — email,
calendar, and project records. Do not write it inside the repository: nothing in
`.gitignore` covers it and a 556 MB dump of personal data is one `git add -A`
away from being committed. `~/local-sensitive/` is outside the repository and is
where this machine already keeps such material. Do not write it into the legacy
source's directory.

A dump is **not** a substitute for retaining the legacy SQLite file. It contains
none of the 59,572 rows deliberately excluded from the migration — see
[`docs/migration/PHASE-12-RETENTION.md`](/docs/migration/PHASE-12-RETENTION.md).

Verify the dump is readable without restoring it. There is no `pg_restore` on
this host — the PostgreSQL client tools live only in the container — so this,
like the restore below, goes through `docker exec -i` with the file on stdin:

```sh
docker exec -i my-pa-postgres pg_restore --list \
  < ~/local-sensitive/my-pa-backups/<file>.dump | head
```

The header reports the archive format, compression, TOC entry count, and the
server version it came from:

```
; Archive created at 2026-08-01 15:34:51 UTC
;     dbname: my_pa
;     TOC Entries: 2348
;     Compression: zstd
;     Format: CUSTOM
;     Dumped from database version: 17.10 (Debian 17.10-1.pgdg13+1)
```

(Those figures are from a `--schema-only` dump used to verify this command; a
full dump has the same header with a larger TOC.)

## Restore

Restore into a **new, empty database**. `pg_restore` does not empty an existing
one, and restoring over a populated database produces duplicate-key errors, not
a clean replacement.

```sh
# 1. Create an empty target with the same locale as the original.
docker exec my-pa-postgres psql -U my_pa -d postgres \
  -c "CREATE DATABASE my_pa_restored OWNER my_pa
      TEMPLATE template0 ENCODING UTF8 LOCALE 'C.UTF-8';"

# 2. Restore into it.
docker exec -i my-pa-postgres pg_restore \
  -U my_pa -d my_pa_restored \
  --no-owner --no-privileges --exit-on-error \
  < ~/local-sensitive/my-pa-backups/<file>.dump
```

Verified end to end on 2026-08-01: a full dump of `my_pa` restored into a fresh
`my_pa_restored` in **44.8 seconds**, exit 0, no errors. The restored database
matched the original on every dimension checked — 494 base tables, 277 foreign
keys with 0 `NOT VALID`, 1,511 indexes, extensions `pg_trgm`/`plpgsql`/`unaccent`,
Alembic head `3a8e2cb16d59`, 3,263,870 domain rows, 2 migration runs, 398
`table_progress` rows, 8 `quarantine_records`, 3,228,581 `source_key_map` rows,
collation `C.UTF-8`. The rehearsal database was dropped afterwards.

Three things that must not be dropped from step 1:

- **`TEMPLATE template0`.** `template1` may carry local additions that collide
  with the dump's own objects.
- **`LOCALE 'C.UTF-8'`.** The collation is a cluster-creation property that
  cannot be changed later, and `C.UTF-8` is what every text index in this
  database was built under. Restoring into a database with a different collation
  produces indexes that disagree with their data.
- **`--exit-on-error`.** Without it `pg_restore` reports errors and continues,
  and a restore that "succeeded" with 200 skipped objects is worse than one that
  stopped.

Verify before promoting the restored database to anything:

```sh
docker exec my-pa-postgres psql -U my_pa -d my_pa_restored -c "
SELECT (SELECT version_num FROM public.alembic_version) AS head,
       (SELECT count(*) FROM pg_constraint WHERE contype='f') AS fks,
       (SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated) AS not_valid,
       (SELECT count(*) FROM migration_control.migration_runs) AS runs;"
```

### Replacing `my_pa` itself

Not documented here as a command sequence, deliberately. It means dropping the
canonical database, which requires every session to disconnect first and is
irreversible if the dump turns out to be bad. Restore to a differently named
database, verify it with the query above, and only then decide. That decision is
the operator's, and `AGENTS.md` §5 keeps destructive data operations there.

## Clean up rehearsal databases

A restore rehearsal costs as much disk as the original — the one above occupied
4,172 MB. A schema-only rollback rehearsal is cheap by comparison, at 41 MB.
Either way, drop them when finished:

```sh
# Review what exists first.
docker exec my-pa-postgres psql -U my_pa -d postgres -c "
SELECT datname, pg_size_pretty(pg_database_size(datname))
FROM pg_database WHERE datname LIKE 'my_pa%' ORDER BY 1;"

# Then drop by exact name.
docker exec my-pa-postgres psql -U my_pa -d postgres \
  -c 'DROP DATABASE IF EXISTS my_pa_restored;'
```

List before you drop. `DROP DATABASE` names its target explicitly and cannot be
undone; never pass `my_pa`.

## Related

- [`../postgres/README.md`](../postgres/README.md) — the instance: image, tuning,
  locale, collation contract, cluster-creation settings, reset procedure.
- [`../compose/postgres.yml`](../compose/postgres.yml) — the definition.
- [`/docs/migration/PHASE-01-FOUNDATION.md`](/docs/migration/PHASE-01-FOUNDATION.md)
  — connection contract and Alembic usage.
- [`/docs/migration/PHASE-11-CUTOVER.md`](/docs/migration/PHASE-11-CUTOVER.md)
  — what is in the database now, and the rollback runbook.
- [`/docs/migration/PHASE-12-RETENTION.md`](/docs/migration/PHASE-12-RETENTION.md)
  — the legacy source, what it uniquely holds, and its backup risk.
