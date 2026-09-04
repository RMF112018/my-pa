"""Revision `e7f3a9c2d514` narrows the idempotency domain and round-trips cleanly.

WP-03 (`PKL-MYPA-D-WP03-001`) makes the capture plane's owner an authorization
input, and this revision is its schema half: the idempotency key's collision
domain narrows from global to per-Principal, and the two hot partition columns
gain indexes. Four claims, separated because they fail for different reasons.

**The revision is in the chain.** Deliberately not "is the head", for the
reason `test_capture_schema_migration.py` records: that property is true only
until the next revision is written.

**At head, the constraint is the two-column one.** Asserted by reading the
constraint's own column list from the catalog rather than by provoking a
conflict, so a rename that kept the old single-column shape under the new name
fails here rather than in whichever isolation test happens to collide first.

**The narrowing is real.** Two Principals store the same key at head; that is
the behavioral difference between the two constraints, checked against the
server rather than inferred from the DDL.

**Downgrade restores the merged shape.** `c4a7e2d81b53` is what databases held
before this revision, and a downgrade that left the two-column constraint — or
the indexes — behind would strand them at a revision that has no idea they
exist. The old single-column constraint must also come back, or the downgraded
database would enforce nothing the merged chain says it enforces.

The database is disposable, created and dropped by its fixture, and never the
configured one. Every value is synthetic; no path is opened.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]

PARTITION_REVISION: Final = "e7f3a9c2d514"
PRIOR_REVISION: Final = "c4a7e2d81b53"

DISPOSABLE_DATABASE: Final = "my_pa_capture_partition_test"

OLD_CONSTRAINT: Final = "a_capture_key_admits_one_submission"
NEW_CONSTRAINT: Final = "a_capture_key_admits_one_submission_per_principal"
INDEXES: Final = ("captures_by_principal", "capture_versions_by_principal")

#: The catalog read the head-shape claim rests on: the unique constraints on
#: `capture_submissions`, each with its ordered column list.
_CONSTRAINTS: Final = """
    SELECT con.conname,
           array_agg(att.attname ORDER BY ord.n) AS columns
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
    CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS ord(attnum, n)
    JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ord.attnum
    WHERE nsp.nspname = 'knowledge'
      AND rel.relname = 'capture_submissions'
      AND con.contype = 'u'
    GROUP BY con.conname
"""

_INDEXES: Final = """
    SELECT indexname FROM pg_indexes
    WHERE schemaname = 'knowledge' AND indexname = ANY(:names)
"""


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


def _unique_constraints(engine: Engine) -> dict[str, tuple[str, ...]]:
    with engine.connect() as connection:
        rows = connection.execute(text(_CONSTRAINTS)).all()
    return {str(name): tuple(str(column) for column in columns) for name, columns in rows}


def _present_indexes(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(text(_INDEXES), {"names": list(INDEXES)}).scalars().all()
    return {str(name) for name in rows}


def test_the_partition_revision_is_in_the_chain() -> None:
    script = ScriptDirectory.from_config(_config())
    revisions = {revision.revision for revision in script.walk_revisions()}
    assert PARTITION_REVISION in revisions
    assert script.get_revision(PARTITION_REVISION).down_revision == PRIOR_REVISION


@pytest.mark.database
def test_the_key_domain_narrows_at_head_and_widens_back_on_downgrade(
    disposable_database: str,
) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        at_head = _unique_constraints(engine)
        assert OLD_CONSTRAINT not in at_head
        assert at_head[NEW_CONSTRAINT] == ("principal_id", "idempotency_key"), (
            "the constraint exists under the new name but not over the two "
            "columns the per-Principal domain requires"
        )
        assert _present_indexes(engine) == set(INDEXES)

        # The behavioral difference, against the server: one key, two
        # Principals, two stored submissions — and a third insert repeating an
        # existing pair is the conflict the constraint still refuses.
        with engine.begin() as connection:
            for suffix in ("a" * 28 + "0001", "b" * 28 + "0002"):
                connection.execute(
                    text(
                        "INSERT INTO knowledge.capture_submissions "
                        "(submission_id, idempotency_key, request_id, correlation_id,"
                        " principal_id, transport, capture_method, trust_state,"
                        " payload_sha256, server_received_at, admission_result,"
                        " version_id, receipt_id) "
                        "VALUES (:submission, 'shared-key', :request, :correlation,"
                        " :principal, 'local', 'typed_text', 'local_principal',"
                        " :digest, now(), 'accepted', :version, :receipt) "
                        "ON CONFLICT ON CONSTRAINT " + NEW_CONSTRAINT + " DO NOTHING"
                    ),
                    {
                        "submission": f"sub_{suffix}",
                        "request": f"req-{suffix}",
                        "correlation": f"corr_{suffix}",
                        "principal": f"prn_{suffix}",
                        "digest": "0" * 64,
                        "version": f"capver_{suffix}",
                        "receipt": f"rcpt_{suffix}",
                    },
                )
            stored = connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.capture_submissions "
                    "WHERE idempotency_key = 'shared-key'"
                )
            ).scalar_one()
            # Emptied before downgrade: the rows exist only to prove the
            # constraint, and the two-column data would violate the one-column
            # constraint the downgrade restores.
            connection.execute(text("DELETE FROM knowledge.capture_submissions"))
        assert stored == 2, (
            "two Principals could not store the same idempotency key, so the "
            "collision domain did not narrow"
        )

        command.downgrade(_config(), PRIOR_REVISION)

        downgraded = _unique_constraints(engine)
        assert NEW_CONSTRAINT not in downgraded
        assert downgraded[OLD_CONSTRAINT] == ("idempotency_key",)
        assert _present_indexes(engine) == set()

        # And forward again, so a database that took the downgrade is not
        # stranded off the chain.
        command.upgrade(_config(), "head")
        assert NEW_CONSTRAINT in _unique_constraints(engine)
    finally:
        engine.dispose()


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
