"""Two synthetic Principals; neither can claim or count the other's queued work (WP-04).

Database tier, over a disposable database this module creates and drops.

`claim_job` was a **global FIFO**. It ordered `knowledge.jobs` — the whole table —
by `(created_at, operation_id)`, took the first claimable row under
`FOR UPDATE SKIP LOCKED`, and leased it to whichever worker asked. Ownership
existed only transitively (`jobs.enrollment_id -> enrollments.principal_id`,
`capture_jobs.version_id -> capture_versions.owner_principal_id`) and the claim
consulted none of it. One Principal's backlog therefore decided when another's
work ran, one Principal's failing job consumed a retry budget everyone shared,
and a worker acting for one Principal executed another's work under that
Principal's handler.

Revision `4f1a8b6d92e3` gives both queues their own `principal_id`, backfilled
from the transitive owner. What is asserted here is the behaviour that column
exists for, on both planes:

* a worker naming Principal B claims **nothing** while A's queue is full, and
  the answer is `None` — the same answer an empty queue gives, not a different
  refusal;
* the row A's worker claims is A's, and B's worker claims B's, when both queues
  hold work;
* the *count* of outstanding work is per-Principal, so B cannot learn how much
  work A has by asking how much work there is;
* `enqueue_job` takes the Principal from the subject's stored row, so a queue
  item cannot be filed into a partition its subject does not belong to, and a
  subject with no stored owner is refused rather than defaulted;
* the reap is partitioned too — B cannot make A's abandoned job terminal, which
  would be a write into A's partition dressed as maintenance;
* a *status read* is partitioned as well: `job_for` and `job_state` take the
  Principal as a required argument, so B asking about A's operation gets the
  same `None` B gets for an operation that does not exist. That one is defence
  in depth rather than a live leak — `application.authorization._status_scope`
  already resolves an operation only inside the caller's own enrollments — and
  it is here because the persistence layer must not depend on having been
  called through the layer that checks.

Every identity and every identifier here is synthetic. No path is opened and no
source is reached.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.jobs import (
    CAPTURE_JOBS,
    ENROLLMENT_JOBS,
    JobPlane,
    UnownedJobSubjectError,
    claim_job,
    enqueue_job,
    job_for,
    job_state,
    reap_abandoned_jobs,
)
from my_pa.infrastructure.persistence.tables import JobState

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_queue_isolation_test"

PRINCIPAL_A: Final = "prn_aaaa0004aaaaaaaaaaaaaaaa00000004"
PRINCIPAL_B: Final = "prn_bbbb0004bbbbbbbbbbbbbbbb00000004"

WHEN: Final = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)

pytestmark = pytest.mark.database


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes."""
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
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE knowledge.sources, knowledge.captures, knowledge.jobs, "
                    "knowledge.capture_jobs CASCADE"
                )
            )
            _seed(connection)
        yield engine
    finally:
        engine.dispose()


def _seed(connection: object) -> None:
    """One source, and one enrollment plus one capture version per Principal."""
    execute = connection.execute  # type: ignore[attr-defined]
    execute(
        text(
            "INSERT INTO knowledge.sources "
            "(source_id, provider_kind, label, classification, native_root) "
            "VALUES ('src_0000000000000001', 'fixture', 'Fixture corpus', "
            "'synthetic_test', '/synthetic/root')"
        )
    )
    for ordinal, principal in ((1, PRINCIPAL_A), (2, PRINCIPAL_B)):
        execute(
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
        execute(
            text(
                "INSERT INTO knowledge.captures (capture_id, owner_principal_id) "
                "VALUES (:capture_id, :principal)"
            ),
            {"capture_id": f"cap_{ordinal:016d}", "principal": principal},
        )
        content = f"synthetic capture {ordinal}"
        execute(
            text(
                "INSERT INTO knowledge.capture_versions "
                "(version_id, capture_id, version_number, content, content_sha256, "
                " owner_principal_id, classification, processing_policy, idempotency_key, "
                " correlation_id, audit_id, client_created_at, server_received_at, "
                " occurred_at, accepted_at, recorded_at) "
                "VALUES (:version_id, :capture_id, 1, :content, :digest, :principal, "
                "'private_local', 'local_only', :key, :correlation, :audit, "
                "now(), now(), now(), now(), now())"
            ),
            {
                "version_id": f"capver_{ordinal:016d}",
                "capture_id": f"cap_{ordinal:016d}",
                "content": content,
                "digest": sha256(content.encode()).hexdigest(),
                "principal": principal,
                "key": f"capture-{ordinal:010d}",
                "correlation": f"corr_{ordinal:016d}",
                "audit": f"audit_{ordinal:016d}",
            },
        )


#: The two planes and the subject each one queues work about, so every claim
#: below is made on both rather than on whichever one a test remembered.
PLANES: Final = (
    (ENROLLMENT_JOBS, "enr_{:016d}"),
    (CAPTURE_JOBS, "capver_{:016d}"),
)


def _queued(connection: object, principal_id: str, plane: JobPlane) -> int:
    """How much outstanding work one Principal has on one plane."""
    return int(
        connection.execute(  # type: ignore[attr-defined]
            text(
                f"SELECT count(*) FROM knowledge.{plane.table.name} "  # noqa: S608
                "WHERE principal_id = :principal AND state = 'queued'"
            ),
            {"principal": principal_id},
        ).scalar_one()
    )


@pytest.mark.parametrize("plane,subject", PLANES, ids=lambda value: getattr(value, "subject", ""))
def test_a_worker_for_one_principal_claims_nothing_from_another_s_queue(
    engine: Engine, plane: JobPlane, subject: str
) -> None:
    """`None`, and the same `None` an empty queue gives."""
    with engine.begin() as connection:
        for _ in range(3):
            enqueue_job(connection, subject.format(1), plane=plane)

    with engine.begin() as connection:
        # B has no work of its own and A has three units of it.
        foreign = claim_job(
            connection, owner="worker-bbbb", lease_seconds=60, principal_id=PRINCIPAL_B, plane=plane
        )
    assert foreign is None

    with engine.begin() as connection:
        # The control: the same call for A, against the same rows, takes one.
        held = claim_job(
            connection, owner="worker-aaaa", lease_seconds=60, principal_id=PRINCIPAL_A, plane=plane
        )
    assert held is not None
    assert held.subject_id == subject.format(1)


@pytest.mark.parametrize("plane,subject", PLANES, ids=lambda value: getattr(value, "subject", ""))
def test_each_worker_takes_its_own_principal_s_work_when_both_queues_hold_some(
    engine: Engine, plane: JobPlane, subject: str
) -> None:
    """A's oldest row is not B's oldest row, however the table is ordered.

    B's job is queued *first*, so under the global FIFO this replaces it would be
    the row A's worker took. The ordering is the point: a test that queued A's
    work first would pass against an unpartitioned claim.

    Two transactions, and that is not incidental. `created_at` defaults to
    `now()`, which in PostgreSQL is the *transaction's* start time — two enqueues
    in one transaction carry identical timestamps and the claim's tie-break falls
    to `operation_id`, which is random. A controlled violation of the claim's
    partition reddened this on one plane and not the other for exactly that
    reason. Separate transactions give B's row a genuinely earlier `created_at`,
    so "oldest first" is a fact about the rows rather than a coin toss.
    """
    with engine.begin() as connection:
        b_operation = enqueue_job(connection, subject.format(2), plane=plane)
    with engine.begin() as connection:
        a_operation = enqueue_job(connection, subject.format(1), plane=plane)

    with engine.begin() as connection:
        a_claim = claim_job(
            connection, owner="worker-aaaa", lease_seconds=60, principal_id=PRINCIPAL_A, plane=plane
        )
        b_claim = claim_job(
            connection, owner="worker-bbbb", lease_seconds=60, principal_id=PRINCIPAL_B, plane=plane
        )

    assert a_claim is not None
    assert b_claim is not None
    assert a_claim.operation_id == a_operation
    assert b_claim.operation_id == b_operation


@pytest.mark.parametrize("plane,subject", PLANES, ids=lambda value: getattr(value, "subject", ""))
def test_outstanding_work_is_counted_per_principal(
    engine: Engine, plane: JobPlane, subject: str
) -> None:
    """B cannot learn how much work A has by asking how much work there is."""
    with engine.begin() as connection:
        for _ in range(4):
            enqueue_job(connection, subject.format(1), plane=plane)
        enqueue_job(connection, subject.format(2), plane=plane)

    with engine.connect() as connection:
        assert _queued(connection, PRINCIPAL_A, plane) == 4
        assert _queued(connection, PRINCIPAL_B, plane) == 1
        total = int(
            connection.execute(
                text(f"SELECT count(*) FROM knowledge.{plane.table.name}")  # noqa: S608
            ).scalar_one()
        )
    # The control: the partitioned counts are not just the total repeated.
    assert total == 5


@pytest.mark.parametrize("plane,subject", PLANES, ids=lambda value: getattr(value, "subject", ""))
def test_the_queued_row_carries_the_subject_s_stored_owner_and_not_a_stated_one(
    engine: Engine, plane: JobPlane, subject: str
) -> None:
    """MU-AC-02 on the queue: the partition is read from the subject, never named."""
    with engine.begin() as connection:
        operation_id = enqueue_job(connection, subject.format(2), plane=plane)

    with engine.connect() as connection:
        stored = connection.execute(
            text(
                f"SELECT principal_id FROM knowledge.{plane.table.name} "  # noqa: S608
                "WHERE operation_id = :operation_id"
            ),
            {"operation_id": operation_id},
        ).scalar_one()
    assert stored == PRINCIPAL_B


@pytest.mark.parametrize("plane,subject", PLANES, ids=lambda value: getattr(value, "subject", ""))
def test_a_subject_with_no_stored_owner_is_refused_rather_than_defaulted(
    engine: Engine, plane: JobPlane, subject: str
) -> None:
    """Fails closed: no owner means no queue row, not a row in nobody's partition."""
    with engine.begin() as connection, pytest.raises(UnownedJobSubjectError):
        enqueue_job(connection, subject.format(99), plane=plane)

    with engine.connect() as connection:
        written = int(
            connection.execute(
                text(f"SELECT count(*) FROM knowledge.{plane.table.name}")  # noqa: S608
            ).scalar_one()
        )
    assert written == 0


@pytest.mark.parametrize("plane,subject", PLANES, ids=lambda value: getattr(value, "subject", ""))
def test_one_principal_cannot_reap_another_s_abandoned_job(
    engine: Engine, plane: JobPlane, subject: str
) -> None:
    """The reap writes, so it is partitioned like every other write.

    An abandoned job is one whose lease expired with its attempts spent, and
    making it terminal is a state change. B calling the reap must change nothing
    of A's — and A calling it must still work, or this would pass because the
    reap is broken rather than because it is scoped.
    """
    with engine.begin() as connection:
        operation_id = enqueue_job(connection, subject.format(1), plane=plane, max_attempts=1)
        claimed = claim_job(
            connection, owner="worker-aaaa", lease_seconds=1, principal_id=PRINCIPAL_A, plane=plane
        )
        assert claimed is not None

    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE knowledge.{plane.table.name} "  # noqa: S608
                "SET lease_expires_at = now() - interval '1 second' "
                "WHERE operation_id = :operation_id"
            ),
            {"operation_id": operation_id},
        )

    with engine.begin() as connection:
        assert reap_abandoned_jobs(connection, principal_id=PRINCIPAL_B, plane=plane) == 0
        state = connection.execute(
            text(
                f"SELECT state FROM knowledge.{plane.table.name} "  # noqa: S608
                "WHERE operation_id = :operation_id"
            ),
            {"operation_id": operation_id},
        ).scalar_one()
        assert state == "running", "B's reap changed A's job"

        # The control: the owner's reap does what B's could not.
        assert reap_abandoned_jobs(connection, principal_id=PRINCIPAL_A, plane=plane) == 1


@pytest.mark.parametrize("plane,subject", PLANES, ids=lambda value: getattr(value, "subject", ""))
def test_another_principal_s_operation_is_indistinguishable_from_an_absent_one(
    engine: Engine, plane: JobPlane, subject: str
) -> None:
    """A status read is a read, and it is partitioned like every other one.

    `job_for` and `job_state` took an operation identifier and nothing else, and
    returned the subject and the state of whatever row carried it. Nothing
    reachable exploited that — `application.authorization._status_scope` resolves
    an operation's enrollment only within the caller's own, so a request naming
    another Principal's operation is denied `scope_not_authorized` before this
    code runs — which is exactly why it is worth closing here as well: the
    persistence layer's answer should not depend on the application layer having
    been consulted.

    The assertion is *indistinguishability*, not refusal. B asking about A's
    operation and B asking about an identifier that names nothing must produce
    the same value, because a different answer would confirm that A's operation
    exists — and existence is the thing the identifier alone would otherwise
    reveal.

    Both controls matter: A's own read must still return the record, or this
    would pass because the read is broken; and B's `None` must not be the `None`
    of an empty table, so A's row is present throughout.
    """
    with engine.begin() as connection:
        operation_id = enqueue_job(connection, subject.format(1), plane=plane)
    absent = issue_identifier(IdKind.OPERATION)

    with engine.connect() as connection:
        assert job_for(connection, operation_id, principal_id=PRINCIPAL_B, plane=plane) is None
        assert job_for(connection, absent, principal_id=PRINCIPAL_B, plane=plane) is None
        assert job_state(connection, operation_id, principal_id=PRINCIPAL_B, plane=plane) is None
        assert job_state(connection, absent, principal_id=PRINCIPAL_B, plane=plane) is None

        # The control at both ends: the row is there, and its owner reads it.
        own = job_for(connection, operation_id, principal_id=PRINCIPAL_A, plane=plane)
        assert own is not None, "A cannot read its own job, so B's `None` proves nothing"
        assert own.operation_id == operation_id
        assert own.subject_id == subject.format(1)
        assert own.state is JobState.QUEUED
        assert job_state(connection, operation_id, principal_id=PRINCIPAL_A, plane=plane) is (
            JobState.QUEUED
        )


@pytest.mark.parametrize("plane,subject", PLANES, ids=lambda value: getattr(value, "subject", ""))
def test_a_status_read_will_not_run_without_a_principal(
    engine: Engine, plane: JobPlane, subject: str
) -> None:
    """The argument is required and unvalidated input does not become a partition.

    `principal_id` has no default on purpose: a default would restore the global
    read for every call site that had not been visited, and it would do it
    silently. A malformed one is refused before a statement is built, so a caller
    cannot reach the plane with a value the identifier vocabulary does not
    recognise.
    """
    with engine.begin() as connection:
        operation_id = enqueue_job(connection, subject.format(1), plane=plane)

    with engine.connect() as connection:
        with pytest.raises(TypeError):
            job_for(connection, operation_id, plane=plane)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            job_state(connection, operation_id, plane=plane)  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="identifier"):
            job_for(connection, operation_id, principal_id="not-a-principal", plane=plane)
