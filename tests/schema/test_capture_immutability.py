"""`QC-AC-010`, against the server: a stored version cannot be changed under concurrent write.

This is the **second** of the criterion's two independent halves. The first is
`tests/architecture/test_capture_has_no_update_path.py`, which reads the source
and says no writer under `src/` builds an `UPDATE` or a `DELETE` against
`capture_versions`. Neither half implies the other:

* a build that dropped the trigger passes the **static** half, because no writer
  would have gained a statement;
* a build that grew an `update()` on `capture_versions` passes **this** half,
  because the server refuses whatever the code that never ran contains.

`D-55` is why this matters and why the two halves live in two modules: one plant
proves only the half it reached first, so each plant is required to leave the
other **green**, and both runs are recorded in the implementation evidence.

**Why a trigger and not a CHECK.** A CHECK is evaluated against the row that
results, and an update to a row that still satisfies every column rule is
exactly the write that has to be refused. `BEFORE UPDATE OR DELETE` is the only
server-side mechanism that expresses "no UPDATE", and expressing it in the
server rather than in the writer is the whole point: immutability as a property
of the code that happens to be running is not inherited by a repair script, a
later revision, or a second writer.

**The concurrency is real and the assertion is not a clock.** Two connections
sit on a barrier and issue the same `UPDATE` against the same row at the same
moment; both are collected and both must have been refused. There is deliberately
**no wall-clock assertion** anywhere here — `tests/concurrency/` already carries
one that flakes on a loaded machine, and a criterion about immutability has no
business depending on how fast a laptop is.

**The control is the whole point of the module.** A build in which *every*
`UPDATE` failed — a read-only connection, a broken engine, a wrong database —
would satisfy every refusal below. So the same connection, in the same test,
updates `knowledge.capture_jobs`, which is a table this plane deliberately does
mutate, and that update has to **succeed**.

The database is disposable, created and dropped by its fixture, and never the
configured one. Every value is synthetic; no path is opened.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.contracts.ports import CaptureAdmissionRequest
from my_pa.domain.capture.version import CaptureContent, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.capture import admit_capture
from my_pa.infrastructure.persistence.principal_scope import capture_context

ROOT: Final = Path(__file__).resolve().parents[2]

#: Fixed name so a run interrupted before teardown is cleaned up by the next
#: one, and distinct from every other suite's — these names are server-global.
DISPOSABLE_DATABASE: Final = "my_pa_capture_immutability_test"

WHEN: Final = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

#: The text a stored version was written with. Read back after every refused
#: statement, because "the update was refused" and "the row still says what it
#: said" are two claims and only the second is the criterion.
ORIGINAL: Final = "the original text of a stored capture version"

#: How many connections contend for the row at once.
WRITERS: Final = 2


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture
def stored(disposable_database: str) -> Iterator[tuple[Engine, str, str]]:
    """One capture version, written by the production writer. Yields its identifiers.

    Written through `admit_capture` rather than by a hand-built `INSERT`, so the
    row under test is one the product can actually produce.
    """
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE knowledge.captures, knowledge.capture_versions, "
                    "knowledge.capture_receipts, knowledge.capture_submissions, "
                    "knowledge.capture_jobs CASCADE"
                )
            )
            principal_id = issue_identifier(IdKind.PRINCIPAL)
            admission = admit_capture(
                connection,
                CaptureAdmissionRequest(
                    capture_id=None,
                    content=CaptureContent(ORIGINAL),
                    idempotency_key="immutability-1",
                    request_id="req-immutability",
                    correlation_id=issue_identifier(IdKind.CORRELATION),
                    principal_id=principal_id,
                    audit_id=issue_identifier(IdKind.AUDIT),
                    classification=Classification.PRIVATE_LOCAL,
                    processing_policy=ProcessingPolicy.LOCAL_ONLY,
                    server_received_at=WHEN,
                    accepted_at=WHEN,
                ),
                context=capture_context(principal_id),
            )
        with engine.connect() as connection:
            operation_id = str(
                connection.execute(
                    text("SELECT operation_id FROM knowledge.capture_jobs")
                ).scalar_one()
            )
        yield engine, admission.receipt.version_id, operation_id
    finally:
        engine.dispose()


def _content(engine: Engine, version_id: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT content FROM knowledge.capture_versions WHERE version_id = :id"),
                {"id": version_id},
            ).scalar_one()
        )


def _attempt(engine: Engine, statement: str, version_id: str) -> BaseException | None:
    """Run one statement in its own transaction. Returns what it raised, or `None`."""
    try:
        with engine.begin() as connection:
            connection.execute(text(statement), {"id": version_id})
    except DBAPIError as refused:
        return refused
    return None


@pytest.mark.database
def test_two_concurrent_connections_are_both_refused_an_update_of_one_version(
    stored: tuple[Engine, str, str],
) -> None:
    """`QC-AC-010` under concurrent write, and the row unchanged afterwards.

    Both writers are released by a barrier, so neither has finished before the
    other starts. The claim is on the *outcome* of both attempts and on the
    stored text after them — not on how long anything took.
    """
    engine, version_id, _ = stored
    barrier = threading.Barrier(WRITERS)
    outcomes: list[BaseException | None] = [None] * WRITERS

    def contend(index: int) -> None:
        barrier.wait()
        outcomes[index] = _attempt(
            engine,
            "UPDATE knowledge.capture_versions SET content = 'rewritten' WHERE version_id = :id",
            version_id,
        )

    writers = [threading.Thread(target=contend, args=(index,)) for index in range(WRITERS)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=30)
    assert not any(writer.is_alive() for writer in writers), "a contending writer never returned"

    assert all(outcome is not None for outcome in outcomes), (
        f"an UPDATE of a stored capture version succeeded: {outcomes}. The "
        "trigger is what makes immutability a property of the schema rather than "
        "of whichever writer happens to be running"
    )
    for outcome in outcomes:
        assert "append only" in str(outcome), (
            f"the statement was refused for some other reason: {outcome}. A "
            "refusal by a lock, a permission, or a missing table would satisfy "
            "this test without the trigger existing"
        )

    assert _content(engine, version_id) == ORIGINAL, (
        "the stored text changed even though both statements were refused"
    )


@pytest.mark.database
def test_a_delete_of_a_stored_version_is_refused_and_the_row_survives(
    stored: tuple[Engine, str, str],
) -> None:
    """The other half of the trigger: append-only means no removal either.

    `QC-AC-010` is about the original text remaining retrievable, and a row that
    can be deleted is not retrievable however immutable it was while it existed.
    """
    engine, version_id, _ = stored

    refused = _attempt(
        engine,
        "DELETE FROM knowledge.capture_versions WHERE version_id = :id",
        version_id,
    )
    assert refused is not None, "a stored capture version was deleted"
    assert "append only" in str(refused)
    assert _content(engine, version_id) == ORIGINAL


@pytest.mark.database
def test_the_same_connection_updates_a_table_this_plane_does_mutate(
    stored: tuple[Engine, str, str],
) -> None:
    """The control, without which every refusal above would prove nothing.

    A read-only connection, a broken engine, or a database with no capture plane
    at all would refuse an `UPDATE` just as thoroughly as the trigger does. This
    is the same engine, in the same module, updating `capture_jobs` — a table
    the outbox deliberately does mutate, because a lease has to be claimable —
    and the update has to succeed and to be visible afterwards.
    """
    engine, _, operation_id = stored

    with engine.begin() as connection:
        changed = connection.execute(
            text(
                "UPDATE knowledge.capture_jobs SET attempt_count = attempt_count + 1 "
                "WHERE operation_id = :id"
            ),
            {"id": operation_id},
        ).rowcount
    assert changed == 1, (
        "the control update changed no row, so the refusals in this module are "
        "not distinguishable from a connection that cannot write at all"
    )

    with engine.connect() as connection:
        assert (
            int(
                connection.execute(
                    text(
                        "SELECT attempt_count FROM knowledge.capture_jobs WHERE operation_id = :id"
                    ),
                    {"id": operation_id},
                ).scalar_one()
            )
            == 1
        )
