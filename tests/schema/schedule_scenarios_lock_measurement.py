"""Schedule Scenarios S6-2: measure revision A's live-table lock windows (section 14.6.3).

A by-hand measurement, never a CI test (R9-F10): on a disposable catalog of a
scratch PostgreSQL cluster it seeds synthetic `record_links` rows (10^5 and
10^6, inserted under `session_replication_role = replica` so no endpoint row is
needed, then `ANALYZE`d) and 10^4 synthetic `schedule_publications` rows at
`621ef6786c64`, runs revision `2a90f91dd786`'s own `upgrade()` once per size, and
prints, per size: the wall time of live phase C (the one `record_links`
`ALTER TABLE`) and of live phase A (the one `schedule_publications` `ALTER
TABLE`), each read with `clock_timestamp()` immediately around the statement in
a measurement-only wrapper of `op` (the revision text is not changed), the wall
time of the whole upgrade and each table's `pg_relation_size`.

Run from the worktree root, against an admin URL of a scratch cluster only::

    PYTHONPATH=src python -m tests.schema.schedule_scenarios_lock_measurement \
        postgresql+psycopg://USER@127.0.0.1:PORT/postgres

It creates and drops its own `my_pa_p_measure_*` catalogs. Every value is
synthetic; nothing persistent or real is touched.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
MIGRATION: Final = (
    ROOT / "migrations" / "versions" / "20261103_2a90f91dd786_schedule_scenarios_persistence.py"
)
PREVIOUS: Final = "621ef6786c64"
LINK_SIZES: Final = (100_000, 1_000_000)
PUBLICATIONS: Final = 10_000

_SEED_LINKS: Final = """
    INSERT INTO knowledge.record_links (principal_id, link_id, kind, from_family, from_id,
      to_family, to_id, relation_type, normalized_identity, authority_class, decision_channel,
      source_capability, created_at)
    SELECT 'prn_measure' || lpad((g % 97)::text, 8, '0'),
           'irl_measure' || lpad(g::text, 10, '0'), 'semantic', 'meeting',
           'mtg_measure' || lpad(g::text, 10, '0'), 'task', 'tsk_measure' || lpad(g::text, 10, '0'),
           'discusses', 'synthetic-identity-' || g, 'local_operator', 'local_cli',
           'records.associations.assert', now()
      FROM generate_series(1, :n) AS g
"""
_SEED_SERIES: Final = """
    INSERT INTO knowledge.schedule_series (series_id, principal_id, project_id, name, name_key)
    VALUES ('sser_measure0001', 'prn_measure00000001', 'prj_measure0001', 'Master', 'master')
"""
_SEED_PUBLICATIONS: Final = """
    INSERT INTO knowledge.schedule_publications (publication_id, principal_id, project_id,
      series_id, enrollment_id, source_object_id, source_version_id, idempotency_key,
      request_digest, publication_role)
    SELECT 'spub_measure' || lpad(g::text, 10, '0'), 'prn_measure00000001', 'prj_measure0001',
           'sser_measure0001', 'enr_measure0001', 'obj_measure0001',
           'ver_measure' || lpad(g::text, 10, '0'), 'measure-key-' || g, repeat('d', 64), 'update'
      FROM generate_series(1, :n) AS g
"""


class _Timed:
    """`op` for one in-process upgrade: time the two live `ALTER TABLE`s on the server."""

    def __init__(self, real: object, connection: object) -> None:
        self._real = real
        self._connection = connection
        self.timings: dict[str, float] = {}

    def execute(self, statement: str) -> None:
        live = next(
            (
                table
                for table in ("record_links", "schedule_publications")
                if statement.startswith(f"ALTER TABLE knowledge.{table} DROP CONSTRAINT")
            ),
            None,
        )
        if live is None:
            self._real.execute(statement)  # type: ignore[attr-defined]
            return
        clock = "SELECT extract(epoch FROM clock_timestamp())"
        before = self._connection.execute(text(clock)).scalar_one()  # type: ignore[attr-defined]
        self._real.execute(statement)  # type: ignore[attr-defined]
        after = self._connection.execute(text(clock)).scalar_one()  # type: ignore[attr-defined]
        self.timings[live] = float(after - before)


def _upgrade_timed(engine: Engine) -> tuple[dict[str, float], float]:
    namespace: dict[str, object] = {}
    exec(compile(MIGRATION.read_text(encoding="utf-8"), str(MIGRATION), "exec"), namespace)  # noqa: S102
    with engine.connect() as connection:
        timed = _Timed(namespace["op"], connection)
        namespace["op"] = timed
        started = time.monotonic()
        with connection.begin(), Operations.context(MigrationContext.configure(connection)):
            namespace["upgrade"]()  # type: ignore[operator]
        elapsed = time.monotonic() - started
    return timed.timings, elapsed


def _measure(admin_url: str, links: int) -> dict[str, object]:
    name = f"my_pa_p_measure_{links}"
    admin = create_database_engine(admin_url, statement_timeout_ms=None)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        c.execute(text(f"CREATE DATABASE {name}"))
    url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    previous = {
        k: os.environ.get(k) for k in ("MY_PA_DATABASE_URL", "MY_PA_MIGRATION_DATABASE_URL")
    }
    os.environ["MY_PA_DATABASE_URL"] = os.environ["MY_PA_MIGRATION_DATABASE_URL"] = url
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), PREVIOUS)
        engine = create_database_engine(url, statement_timeout_ms=None)
        with engine.begin() as c:
            c.execute(text("SET LOCAL session_replication_role = replica"))
            c.execute(text(_SEED_LINKS), {"n": links})
            c.execute(text(_SEED_SERIES))
            c.execute(text(_SEED_PUBLICATIONS), {"n": PUBLICATIONS})
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text("ANALYZE knowledge.record_links"))
            c.execute(text("ANALYZE knowledge.schedule_publications"))
            sizes = {
                table: int(
                    c.execute(
                        text("SELECT pg_relation_size(CAST(:t AS regclass))"),
                        {"t": f"knowledge.{table}"},
                    ).scalar_one()
                )
                for table in ("record_links", "schedule_publications")
            }
        timings, whole = _upgrade_timed(engine)
        engine.dispose()
        return {"record_links_rows": links, "sizes": sizes, "timings": timings, "upgrade": whole}
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin.dispose()


def main(admin_url: str) -> None:
    for links in LINK_SIZES:
        result = _measure(admin_url, links)
        print(result)


if __name__ == "__main__":
    main(sys.argv[1])
