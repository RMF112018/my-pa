# Phase 01 — PostgreSQL Foundation

The database layer every later migration phase sits on: a connection contract, an
engine, and Alembic owning all target DDL. No table yet — the control plane and
the domain tables arrive in Phase 02 and later.

## What exists now

| Path | What it is |
|---|---|
| `src/my_pa/bootstrap/settings.py` | `database_url`, validated and fail-closed |
| `src/my_pa/infrastructure/database/engine.py` | engine factory, `session_scope`, `healthcheck` |
| `alembic.ini` | Alembic configuration; deliberately holds no URL |
| `migrations/env.py` | offline and online environments, URL from settings |
| `migrations/versions/` | revision home; one revision so far |
| `tests/unit/test_settings.py` | settings and URL validation, no database |
| `tests/schema/test_foundation_migration.py` | offline DDL plus the round trip |

The single revision, `5d75f23847c9`, creates nine schemas — `core`, `procore`,
`email`, `calendar`, `contacts`, `financial`, `schedule`, `construction`,
`migration_control` — and enables `pg_trgm` and `unaccent`. It is fully
reversible: `downgrade base` drops all eleven objects and leaves the database as
it was found.

`alembic_version` stays in the default schema. In `migration_control` the first
revision's own downgrade would drop the table Alembic was updating.

There is no `target_metadata` and autogenerate is not wired up. The target schema
follows the SQLite corpus being migrated, not an ORM model layer that does not
exist; revisions are written by hand.

## Connection contract

`MY_PA_DATABASE_URL` supplies the URL. It must use the `postgresql+psycopg`
scheme and name a host and a database; anything else fails at startup rather than
at first query. Pinning the scheme keeps a second driver from silently taking
over the connection.

The default is `postgresql+psycopg://my_pa@localhost:5433/my_pa`, which is the
local `my-pa-postgres` container. It carries **no password**. Supply the password
out of band:

```sh
export PGPASSWORD=...          # or use ~/.pgpass
```

No credential is committed, and no error message echoes a setting's value, so a
URL that does carry a password cannot leak through a failure.

Host port 5433, not 5432, so an accidental connection to some other local
PostgreSQL is not possible. The container is defined in `ops/compose/postgres.yml`;
`ops/postgres/README.md` is the runbook.

The pool is small and hard-bounded — five connections, no overflow — because the
workload is a single-user bulk load, not a request server. A connection leak
surfaces as a timeout instead of as an unbounded number of backends. Everything
is synchronous: the load is bounded by PostgreSQL's write path, not by waiting on
concurrent sockets, so async would buy nothing for its cost.

## Running migrations

```sh
.venv/bin/alembic current              # where the database stands
.venv/bin/alembic upgrade head         # apply every revision
.venv/bin/alembic downgrade base       # back to an empty database
.venv/bin/alembic upgrade head --sql   # emit SQL without connecting, for review
.venv/bin/alembic revision -m "..."    # start a new revision
```

Every revision must be reversible and must survive the empty-to-head-to-empty
round trip, which `AGENTS.md` section 6 requires and the schema tests enforce.
Downgrades drop with `RESTRICT`: reaching a downgrade with objects still in a
schema means a later revision failed to clean up after itself, and failing there
is better than silently deleting the contents.

## Running the tests

```sh
.venv/bin/pytest -q -m "not database"   # FAST tier, no server needed
PGPASSWORD=... .venv/bin/pytest -q -m database
```

The database tests create and drop a disposable `my_pa_foundation_test` database
for each test. They never run against the configured database: `downgrade base`
deletes schemas, and pointing that at `my_pa` would destroy a completed
migration. The fixture drops the disposable database on the way in as well as on
the way out, so an interrupted run cleans up on the next one. No test reads the
legacy SQLite source.

## Health check

```python
from my_pa.bootstrap.settings import load_settings
from my_pa.infrastructure.database import create_database_engine, healthcheck

engine = create_database_engine(load_settings().database_url)
print(healthcheck(engine))
```

Reports the server version and the installed extensions, and raises the driver's
own error when the server is unreachable.

## Deferred

- `pgvector` and any semantic index. `AGENTS.md` section 4 keeps it behind a
  benchmark gate; PostgreSQL full-text search plus `pg_trgm` is the search
  mechanism until there is evidence that is not enough.
- Migration roles and grants. The local instance has one role, which owns
  everything; splitting DDL from DML rights needs a second role to exist first.
- Async engines, read replicas, and connection proxies.
