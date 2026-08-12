"""Revision `4f1a8b6d92e3` partitions both queues, backfills them, and round-trips.

WP-04. `knowledge.jobs` and `knowledge.capture_jobs` carried no principal column.
Ownership existed transitively — `jobs.enrollment_id -> enrollments.principal_id`
and `capture_jobs.version_id -> capture_versions.owner_principal_id` — and
`persistence.jobs.claim_job` used none of it: it ordered the whole table by
`(created_at, operation_id)` and took the first claimable row, which is a global
FIFO across every Principal.

Four claims, separated because they fail for different reasons:

**The revision is in the chain.** Deliberately not "is the head", for the reason
`test_capture_schema_migration.py` records: that property is true only until the
next revision is written.

**At head, both queues carry the partition, with its CHECK and its index.** Read
from the catalog rather than inferred from the DDL, so a rename that kept the old
shape under a new name fails here rather than somewhere downstream.

**The backfill is the transitive owner, and it is total.** This is the claim the
migration exists for and the one an empty-database test cannot make. The
disposable database is taken to the *previous* revision, real queue rows are
written while no principal column exists, and the revision is then applied: each
row must come out carrying the principal of the enrollment or capture version it
is about. A row that matched no owner must abort the upgrade rather than be
dropped or defaulted — asserted separately, because "the backfill worked" and
"the backfill refused to guess" are two different properties and a migration can
have the first without the second.

**Downgrade removes the partition and leaves the work.** A queue that lost its
rows on downgrade would be a destructive migration wearing a reversible one's
clothes.

The database is disposable, created and dropped by this module's own fixture, and
is never the configured one. Every identity and every identifier is synthetic.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]

QUEUE_REVISION: Final = "4f1a8b6d92e3"
PRIOR_REVISION: Final = "9d4e7a3b1c62"

DISPOSABLE_DATABASE: Final = "my_pa_queue_partition_test"

PRINCIPAL_A: Final = "prn_aaaa0004aaaaaaaaaaaaaaaa00000004"
PRINCIPAL_B: Final = "prn_bbbb0004bbbbbbbbbbbbbbbb00000004"

CHECK_NAME: Final = "principal_id_is_an_opaque_identifier"
INDEXES: Final = {
    "jobs": "jobs_by_principal_claim_order",
    "capture_jobs": "capture_jobs_by_principal_claim_order",
}

pytestmark = pytest.mark.database


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture
def disposable_database() -> Iterator[str]:
    """An empty database at `base`, dropped when the test finishes."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


def _seed_owners(engine: Engine) -> None:
    """One source, two enrollments, and two capture versions — one per Principal."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.sources "
                "(source_id, provider_kind, label, classification, native_root) "
                "VALUES ('src_0000000000000001', 'fixture', 'Fixture corpus', "
                "'synthetic_test', '/synthetic/root')"
            )
        )
        for ordinal, principal in ((1, PRINCIPAL_A), (2, PRINCIPAL_B)):
            connection.execute(
                text(
                    "INSERT INTO knowledge.enrollments "
                    "(enrollment_id, source_id, principal_id, purpose, policy_version, "
                    " idempotency_key, request_fingerprint, root_object_id, media_types, "
                    " max_items, max_bytes) "
                    "VALUES (:enrollment_id, 'src_0000000000000001', :principal, "
                    "'bounded_enrollment', 'mcv-1', :key, :key, :root, "
                    "ARRAY['text/plain'], 10, 1024)"
                ),
                {
                    "enrollment_id": f"enr_{ordinal:016d}",
                    "principal": principal,
                    "key": f"enroll-{ordinal:010d}",
                    "root": f"obj_{ordinal:016d}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge.captures (capture_id, owner_principal_id) "
                    "VALUES (:capture_id, :principal)"
                ),
                {"capture_id": f"cap_{ordinal:016d}", "principal": principal},
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge.capture_versions "
                    "(version_id, capture_id, version_number, content, content_sha256, "
                    " owner_principal_id, classification, processing_policy, "
                    " idempotency_key, correlation_id, audit_id, client_created_at, "
                    " server_received_at, occurred_at, accepted_at, recorded_at) "
                    "VALUES (:version_id, :capture_id, 1, :content, "
                    ":digest, :principal, "
                    "'private_local', 'local_only', :key, :correlation, :audit, now(), "
                    "now(), now(), now(), now())"
                ),
                {
                    "version_id": f"capver_{ordinal:016d}",
                    "capture_id": f"cap_{ordinal:016d}",
                    "content": f"synthetic capture {ordinal}",
                    "digest": sha256(f"synthetic capture {ordinal}".encode()).hexdigest(),
                    "principal": principal,
                    "key": f"capture-{ordinal:010d}",
                    "correlation": f"corr_{ordinal:016d}",
                    "audit": f"audit_{ordinal:016d}",
                },
            )


def _queue_rows_without_a_partition(engine: Engine) -> None:
    """Two jobs and two capture jobs, written while no principal column exists."""
    with engine.begin() as connection:
        for ordinal in (1, 2):
            connection.execute(
                text(
                    "INSERT INTO knowledge.jobs (operation_id, enrollment_id, state) "
                    "VALUES (:operation_id, :enrollment_id, 'queued')"
                ),
                {
                    "operation_id": f"op_{ordinal:016d}",
                    "enrollment_id": f"enr_{ordinal:016d}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge.capture_jobs (operation_id, version_id, state) "
                    "VALUES (:operation_id, :version_id, 'queued')"
                ),
                {
                    "operation_id": f"op_{ordinal + 10:016d}",
                    "version_id": f"capver_{ordinal:016d}",
                },
            )


def test_the_revision_is_in_the_chain_below_its_predecessor() -> None:
    """Chain membership, not headship: the latter stops being true by design."""
    script = ScriptDirectory.from_config(_config())
    revision = script.get_revision(QUEUE_REVISION)
    assert revision is not None
    assert revision.down_revision == PRIOR_REVISION
    assert len(script.get_heads()) == 1, "the chain has forked"


def test_both_queues_carry_the_partition_its_check_and_its_index_at_head(
    disposable_database: str,
) -> None:
    """Read from the catalog, so a rename that kept the old shape fails here."""
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            for table, index in INDEXES.items():
                nullable = connection.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_schema = 'knowledge' AND table_name = :table "
                        "AND column_name = 'principal_id'"
                    ),
                    {"table": table},
                ).scalar_one_or_none()
                assert nullable == "NO", f"{table}.principal_id is {nullable!r}, not NOT NULL"

                checks = set(
                    connection.execute(
                        text(
                            "SELECT conname FROM pg_constraint "
                            "WHERE conrelid = ('knowledge.' || :table)::regclass "
                            "AND contype = 'c' AND convalidated"
                        ),
                        {"table": table},
                    ).scalars()
                )
                assert CHECK_NAME in checks, (
                    f"{table} carries no validated {CHECK_NAME}; the migration adds it "
                    "NOT VALID and validates it, and skipping the validation would "
                    "leave a malformed backfilled identifier storable"
                )

                indexes = set(
                    connection.execute(
                        text("SELECT indexname FROM pg_indexes WHERE schemaname = 'knowledge'")
                    ).scalars()
                )
                assert index in indexes, f"{table} has no principal-first claim-order index"
    finally:
        engine.dispose()


def test_the_backfill_takes_each_queue_row_s_owner_from_the_row_it_is_about(
    disposable_database: str,
) -> None:
    """The claim an empty-database migration test cannot make.

    Real queue rows are written at the previous revision, while the column does
    not exist, and the revision is then applied to them.
    """
    command.upgrade(_config(), PRIOR_REVISION)
    engine = create_database_engine(disposable_database)
    try:
        _seed_owners(engine)
        _queue_rows_without_a_partition(engine)

        # The control: before the revision, neither queue has a partition at all,
        # so what follows is a migration rather than a re-read.
        with engine.connect() as connection:
            columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'knowledge' AND table_name = 'jobs'"
                    )
                ).scalars()
            )
        assert "principal_id" not in columns

        command.upgrade(_config(), QUEUE_REVISION)

        with engine.connect() as connection:
            enrollment_owners = dict(
                connection.execute(
                    text("SELECT operation_id, principal_id FROM knowledge.jobs")
                ).all()  # type: ignore[arg-type]
            )
            capture_owners = dict(
                connection.execute(
                    text("SELECT operation_id, principal_id FROM knowledge.capture_jobs")
                ).all()  # type: ignore[arg-type]
            )
        assert enrollment_owners == {
            "op_0000000000000001": PRINCIPAL_A,
            "op_0000000000000002": PRINCIPAL_B,
        }
        assert capture_owners == {
            "op_0000000000000011": PRINCIPAL_A,
            "op_0000000000000012": PRINCIPAL_B,
        }
    finally:
        engine.dispose()


def test_the_upgrade_refuses_rather_than_guessing_when_a_row_has_no_owner(
    disposable_database: str,
) -> None:
    """The other half: a row that matched no owner aborts, it is not defaulted.

    Produced by dropping the foreign key at the previous revision and inserting a
    job about an enrollment that does not exist. Without this, a migration that
    silently wrote a placeholder — or deleted the unmatched row — would satisfy
    the backfill test above perfectly.
    """
    command.upgrade(_config(), PRIOR_REVISION)
    engine = create_database_engine(disposable_database)
    try:
        _seed_owners(engine)
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE knowledge.jobs DROP CONSTRAINT jobs_enrollment_id_fkey")
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge.jobs (operation_id, enrollment_id, state) "
                    "VALUES ('op_0000000000000099', 'enr_0000000000000099', 'queued')"
                )
            )

        with pytest.raises(Exception) as raised:  # the class is the driver's
            command.upgrade(_config(), QUEUE_REVISION)
        assert "principal_id" in str(raised.value)

        # And nothing was destroyed on the way to refusing: the orphan is still
        # there, still unmatched, for an operator to resolve.
        with engine.connect() as connection:
            orphans = connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.jobs WHERE operation_id = 'op_0000000000000099'"
                )
            ).scalar_one()
        assert orphans == 1
    finally:
        engine.dispose()


def test_the_downgrade_removes_the_partition_and_leaves_the_work(
    disposable_database: str,
) -> None:
    """Reversible means the column goes and the queued rows stay."""
    command.upgrade(_config(), PRIOR_REVISION)
    engine = create_database_engine(disposable_database)
    try:
        _seed_owners(engine)
        _queue_rows_without_a_partition(engine)
        command.upgrade(_config(), QUEUE_REVISION)
        command.downgrade(_config(), PRIOR_REVISION)

        with engine.connect() as connection:
            for table in INDEXES:
                columns = set(
                    connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'knowledge' AND table_name = :table"
                        ),
                        {"table": table},
                    ).scalars()
                )
                assert "principal_id" not in columns, f"{table} kept the partition column"
                remaining = connection.execute(
                    text(f"SELECT count(*) FROM knowledge.{table}")  # noqa: S608
                ).scalar_one()
                assert remaining == 2, f"{table} lost queued work on downgrade"
    finally:
        engine.dispose()
