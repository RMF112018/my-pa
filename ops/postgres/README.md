# PostgreSQL — the canonical `my_pa` store

This directory documents the local PostgreSQL instance that holds the `my_pa`
database. The instance itself is defined by
[`../compose/postgres.yml`](../compose/postgres.yml).

| Property | Value |
| --- | --- |
| Image | `postgres:17.10` |
| Container | `my-pa-postgres` |
| Database | `my_pa` |
| Role | `my_pa` |
| Host port | `5433` (container `5432`) |
| Data volume | `my_pa_pgdata` |
| Extensions | `pg_trgm`, `unaccent` |
| Encoding / locale | `UTF8` / `C.UTF-8` (see [Collation contract](#collation-contract)) |
| Data checksums | enabled |

## Do not connect to the legacy SQLite database

**PostgreSQL `my_pa` is the canonical store.** The legacy SQLite file that this
migration reads from is a **read-only source snapshot**. It must never be
written to, renamed, moved, deleted, or opened by application code. Migration
tooling opens it only through an immutable URI:

```python
sqlite3.connect(f"file:{path}?immutable=1", uri=True)
```

`immutable=1` is required — it prevents journal, WAL, and lock-file creation
alongside the source. Anything that would mutate the snapshot is a defect, not a
configuration choice.

## Start and stop

All commands run from the repository root.

```sh
# Start (detached) and wait for the healthcheck to pass
docker compose -f ops/compose/postgres.yml up -d

# Status and health
docker compose -f ops/compose/postgres.yml ps

# Server logs
docker compose -f ops/compose/postgres.yml logs -f postgres

# Stop the container, keep all data
docker compose -f ops/compose/postgres.yml down
```

`down` removes the container but not the `my_pa_pgdata` volume, so data survives
a stop/start cycle and a machine reboot (`restart: unless-stopped` brings the
container back with Docker).

## Password

The password comes from the `MY_PA_DB_PASSWORD` environment variable, with the
local-development fallback `my_pa_local_dev` baked into the compose file:

```yaml
POSTGRES_PASSWORD: ${MY_PA_DB_PASSWORD:-my_pa_local_dev}
```

**No real secret is stored in this repository.** `my_pa_local_dev` is a publicly
known placeholder, and it is only acceptable because the container publishes on
`127.0.0.1:5433` — the loopback interface alone, not `0.0.0.0`. That binding is
what keeps a committed password harmless, so the two go together: if you ever
widen the port binding, the password stops being a placeholder and must move to
`MY_PA_DB_PASSWORD` with a real value. To use a different password, export it
before starting:

```sh
export MY_PA_DB_PASSWORD='...'
docker compose -f ops/compose/postgres.yml up -d
```

Changing the variable after the volume exists has **no effect** — the password
is written into the data directory by `initdb` on first start only. To change it
afterwards, either alter the role in SQL or reset the database (below).

Do not add `MY_PA_DB_PASSWORD` to the application `.env.example`: that file is
non-secret configuration only, and unknown `MY_PA_` names are rejected at
startup.

## Connection URL

```
postgresql://my_pa:<password>@localhost:5433/my_pa
```

Port `5433` is deliberate — it leaves the conventional `5432` free for any other
local PostgreSQL, so an unqualified connection cannot land here by accident.

Keep the password out of source and out of shell history; build the URL from the
environment at runtime.

## psql shell

```sh
docker exec -it my-pa-postgres psql -U my_pa -d my_pa
```

No password is needed for this form — connections over the container's Unix
socket are trusted locally. A one-off statement:

```sh
docker exec my-pa-postgres psql -U my_pa -d my_pa -c 'SELECT version();'
```

## Reset the database from scratch

This **destroys every row** in the `my_pa` database. It is safe with respect to
the legacy SQLite snapshot, which is never touched, but it discards all migrated
data and every schema Alembic has applied.

```sh
docker compose -f ops/compose/postgres.yml down --volumes
docker compose -f ops/compose/postgres.yml up -d
```

`--volumes` deletes `my_pa_pgdata`. Confirm it is actually gone before starting
again — if the volume survives, `initdb` is skipped and the cluster comes back
with its old settings:

```sh
docker volume ls --format '{{.Name}}' | grep -x my_pa_pgdata   # must print nothing
```

The next start runs `initdb` again and produces an empty `my_pa` database owned
by `my_pa`. Re-create the extensions and re-run the Alembic migrations
afterwards:

```sh
docker exec my-pa-postgres psql -U my_pa -d my_pa \
  -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;' \
  -c 'CREATE EXTENSION IF NOT EXISTS unaccent;'
```

## Verified server properties

Recorded on first stand-up of `postgres:17.10`:

| Setting | Value |
| --- | --- |
| `version()` | PostgreSQL 17.10 (Debian 17.10-1.pgdg13+1), aarch64-unknown-linux-gnu |
| `server_encoding` | `UTF8` |
| `lc_collate` (`pg_database.datcollate`) | `C.UTF-8` |
| `lc_ctype` (`pg_database.datctype`) | `C.UTF-8` |
| locale provider (`datlocprovider`) | `c` (libc) |
| `TimeZone` | `Etc/UTC` |
| `max_connections` | `100` |
| `data_checksums` | `on` |

PostgreSQL 16 removed `lc_collate` and `lc_ctype` as server settings, so they do
not appear in `pg_settings`. Read them per database:

```sh
docker exec my-pa-postgres psql -U my_pa -d my_pa \
  -c "SELECT datcollate, datctype, datlocprovider FROM pg_database WHERE datname='my_pa';"
```

## Cluster-creation-only settings

`server_encoding`, the collation/ctype locale, and `data_checksums` are written
by `initdb` when the data directory is first created. They are passed via
`POSTGRES_INITDB_ARGS` in the compose file:

```
--data-checksums --locale=C.UTF-8 --encoding=UTF8
```

**None of them can be changed on a live cluster.** Changing any one means
destroying `my_pa_pgdata` and reloading every row from the legacy source. Note
also that `POSTGRES_INITDB_ARGS` is ignored whenever the volume already exists —
a surviving volume silently skips `initdb`, so a changed flag appears to apply
while the old cluster keeps its original settings. Always confirm by reading the
values back rather than assuming the restart took effect.

`--data-checksums` costs a few percent on writes and buys detection of silent
page corruption. This database is a long-lived personal knowledge store, so bit
rot surfacing as a wrong answer is the failure worth spending that on.

## Collation contract

**The cluster default is `C.UTF-8`: byte ordering, not linguistic ordering.**

Two reasons:

- It sorts identically to SQLite, so source-vs-target reconciliation compares
  directly without `COLLATE` clauses scattered through verification queries, and
  it builds indexes measurably faster on a bulk load.
- It is version-stable. `en_US.utf8` resolves through the container's glibc, so
  a base-image bump can change collation underneath existing text indexes and
  silently corrupt them. `C.UTF-8` is immune to that.

The consequence: `ORDER BY` on text is case- and accent-sensitive in byte order
(`'Apple' < 'Zebra' < 'apple'`). That is correct for storage and comparison, and
wrong for a human-facing list.

**So apply a linguistic collation explicitly at the query site whenever text is
being presented to a person:**

```sql
SELECT display_name FROM contacts.contact
ORDER BY display_name COLLATE "en_US.utf8";
```

Presentation ordering is a query-site decision, not a cluster default. Do not
"fix" a sort order by changing the cluster locale.

## Tuning

Tuning flags live in the compose file's `command:` block, each with the reason
it was chosen. They are sized for this machine — a 14-CPU / 8 GB Docker VM
running a single-user bulk load — and are not server settings:

| Flag | Value |
| --- | --- |
| `shared_buffers` | `1GB` |
| `effective_cache_size` | `3GB` |
| `work_mem` | `32MB` |
| `maintenance_work_mem` | `512MB` |
| `max_wal_size` | `4GB` |
| `min_wal_size` | `1GB` |

`shm_size: 1gb` raises the container's `/dev/shm` above Docker's 64 MB default
so parallel scans and hash joins have room. `stop_grace_period: 60s` gives the
server time to shut down cleanly instead of being killed mid-checkpoint.
