"""The extraction executor, against a real server and a real fixture tree.

`infrastructure.jobs.extraction.extract_enrollment` is the first thing in this
product that turns an accepted enrollment into stored knowledge, and every claim
it makes is about a transaction, a constraint, or a lease. None of them can be
shown against an in-memory double, which would agree with whatever the executor
did.

**Every assertion here is on a non-empty result.** The failure mode this package
is built around is silent: a mismatched identifier yields an empty work list, an
empty coverage report, and no exception anywhere. So a test that only proved
"nothing raised" would pass on an executor that did nothing at all, and the three
tests below whose subject genuinely is a zero each carry a control in the same
test that is non-zero.

**The corpora are synthetic and built in `tmp_path`.** No live source is reached
and `fixtures/mcv/root` is not touched, so a test that needed a file to disappear
or to conflict with its own media type can have one.

The stage each test builds is the production path in miniature and not a
shortcut: `register_source`, then a provider bound to a `RegistryIdentity` that
issues durable identifiers as it lists, then `accept_enrollment`, `record_scope`,
and `enqueue_job`. Nothing here inserts a row the product would not have written.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.extraction.coverage import CoverageCounts, CoverageState
from my_pa.domain.extraction.quarantine import QuarantineReason
from my_pa.domain.extraction.text import ExtractionOutcome
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.enrollment import EnrollmentRequest, EnrollmentScope
from my_pa.domain.source.provider import ObjectKind, SourceObjectContent
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs import extraction
from my_pa.infrastructure.jobs.extraction import extract_enrollment
from my_pa.infrastructure.jobs.worker import issue_worker_owner, run_worker
from my_pa.infrastructure.persistence.enrollment import accept_enrollment, record_scope
from my_pa.infrastructure.persistence.extraction import coverage_for
from my_pa.infrastructure.persistence.jobs import claim_job, enqueue_job
from my_pa.infrastructure.persistence.registry import register_source
from my_pa.infrastructure.providers.fixture import FixtureSourceProvider
from my_pa.infrastructure.providers.identity import RegistryIdentity

import threading  # isort: skip

ROOT = Path(__file__).resolve().parents[2]

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE = "my_pa_extraction_executor_test"

WHEN = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

#: The markers a text file carries, so that a search or a read that returns it is
#: returning *this* file rather than something with the same shape.
NOTES = "quarterly revenue review, prepared for the operator"
README = "the corpus this worker was pointed at"


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
    built = create_database_engine(disposable_database)
    try:
        with built.begin() as connection:
            connection.execute(text("TRUNCATE knowledge.sources CASCADE"))
        yield built
    finally:
        built.dispose()


@dataclass(frozen=True, slots=True)
class Staged:
    """One enrollment over one corpus, with its job queued and its objects known."""

    source_id: str
    enrollment_id: str
    operation_id: str
    root: Path
    objects: tuple[str, ...]


def _corpus(root: Path, files: Sequence[tuple[str, bytes]]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files:
        (root / name).write_bytes(content)
    return root


def _stage(
    engine: Engine,
    root: Path,
    key: str,
    *,
    media_types: tuple[str, ...] = ("text/markdown", "text/plain"),
    max_bytes: int = 1 << 16,
) -> Staged:
    """Register, enumerate, enrol, record the scope, and queue the job.

    The enumeration is the provider's own listing under a `RegistryIdentity`,
    which is what `sources.enroll` does: the identifiers recorded in
    `enrollment_objects` are therefore the identifiers the worker's provider will
    resolve, and a mismatch between the two is the silent failure this whole file
    exists to make loud.
    """
    with engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label=f"Corpus {key}",
            classification=Classification.SYNTHETIC_TEST,
            native_root=str(root),
        )
        provider = FixtureSourceProvider(
            root, source.source_id, RegistryIdentity(connection, source.source_id)
        )
        objects = tuple(
            child.source_object_id
            for child in provider.list_children()
            if child.kind is ObjectKind.FILE
        )
        assert objects, f"the {key} corpus enumerated nothing"
        accepted = accept_enrollment(
            connection,
            EnrollmentRequest(
                source_id=source.source_id,
                principal_id=issue_identifier(IdKind.PRINCIPAL),
                purpose=Purpose.BOUNDED_ENROLLMENT,
                scope=EnrollmentScope(object_ids=objects),
                media_types=media_types,
                policy_version="policy-v1",
                idempotency_key=f"enroll-{key}",
                max_items=100,
                max_bytes=max_bytes,
            ),
        )
        enrollment_id = accepted.enrollment.enrollment_id
        recorded = record_scope(connection, enrollment_id, objects)
        assert recorded == len(objects)
        operation_id = enqueue_job(connection, enrollment_id)
    return Staged(
        source_id=source.source_id,
        enrollment_id=enrollment_id,
        operation_id=operation_id,
        root=root,
        objects=objects,
    )


def _run(engine: Engine, *, iterations: int = 1, owner: str | None = None) -> object:
    return run_worker(
        engine,
        owner=owner or issue_worker_owner(),
        handler=extract_enrollment,
        stop=threading.Event(),
        max_iterations=iterations,
    )


def _coverage(engine: Engine, enrollment_id: str) -> CoverageCounts:
    with engine.connect() as connection:
        return coverage_for(connection, enrollment_id, observed_at=WHEN)


def _count(engine: Engine, table: str, enrollment_id: str | None = None) -> int:
    where = "" if enrollment_id is None else " WHERE enrollment_id = :id"
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(f"SELECT count(*) FROM knowledge.{table}{where}"),  # noqa: S608
                {} if enrollment_id is None else {"id": enrollment_id},
            ).scalar_one()
        )


def _stored_text(engine: Engine, enrollment_id: str) -> list[str]:
    with engine.connect() as connection:
        return [
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT text FROM knowledge.extractions "
                    "WHERE enrollment_id = :id AND text IS NOT NULL ORDER BY text"
                ),
                {"id": enrollment_id},
            )
        ]


def _quarantine_reasons(engine: Engine, enrollment_id: str) -> list[str]:
    with engine.connect() as connection:
        return [
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT reason FROM knowledge.quarantine_records "
                    "WHERE enrollment_id = :id ORDER BY reason"
                ),
                {"id": enrollment_id},
            )
        ]


def _job_row(engine: Engine, operation_id: str) -> tuple[str, int, str | None]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT state, attempt_count, last_error_code FROM knowledge.jobs "
                "WHERE operation_id = :id"
            ),
            {"id": operation_id},
        ).one()
    return (str(row[0]), int(row[1]), row[2])


#: The four-file shape `fixtures/mcv/root` has: two readable, two this extractor
#: does not read. Built here rather than pointed at, because two of the tests
#: below have to change a file after the enrollment was accepted.
FOUR_FILES: tuple[tuple[str, bytes], ...] = (
    ("notes.md", NOTES.encode()),
    ("readme.txt", README.encode()),
    ("handbook.pdf", b"%PDF-1.7\nnot a library this repository depends on\n"),
    ("opaque.bin", bytes(range(32))),
)


# ---- what one pass records ----------------------------------------------------


@pytest.mark.database
def test_the_executor_records_an_outcome_for_every_object_it_can_and_counts_the_rest(
    engine: Engine, tmp_path: Path
) -> None:
    """The whole of one pass over the four-file shape.

    Two files are read and their text stored; the PDF and the unidentifiable
    binary reach an `unsupported` row and are **counted**, which is the change
    this executor makes to the PDF story — before it existed, a PDF in scope was
    absent from every count rather than reported in one. `P00-OD-003` is still
    open and nothing here opens it.

    The assertions are on the stored text and on four positive counts, not on the
    absence of an exception. An executor that recorded nothing would leave
    `eligible == 4` with everything else zero, and every line below would fail.
    """
    staged = _stage(engine, _corpus(tmp_path / "four", FOUR_FILES), "four")

    run = _run(engine)

    assert (run.claimed, run.completed) == (1, 1)  # type: ignore[attr-defined]
    counts = _coverage(engine, staged.enrollment_id)
    assert counts.eligible == 4
    assert counts.processed == 2
    assert counts.unsupported == 2
    assert counts.quarantined == 0
    assert counts.state() is CoverageState.PARTIALLY_PROCESSED
    assert sorted(_stored_text(engine, staged.enrollment_id)) == sorted([NOTES, README])
    assert _job_row(engine, staged.operation_id)[0] == "succeeded"


@pytest.mark.database
def test_a_media_type_the_enrollment_never_allowed_leaves_its_object_uncovered(
    engine: Engine, tmp_path: Path
) -> None:
    """The content dimension refuses, the loop continues, and nothing is invented.

    The enrollment allows Markdown and nothing else, so `record_outcome` refuses
    the plain-text file's extracted text. That refusal is about the enrollment's
    allowlist rather than about the object, so it is caught: no row is written,
    the object stays uncovered, and the result is honestly partial.

    The Markdown file is the control that makes the zero mean something. Without
    it, an executor that refused everything would pass.
    """
    corpus = _corpus(
        tmp_path / "allowlist",
        (("notes.md", NOTES.encode()), ("readme.txt", README.encode())),
    )
    staged = _stage(engine, corpus, "allowlist", media_types=("text/markdown",))

    _run(engine)

    counts = _coverage(engine, staged.enrollment_id)
    assert counts.eligible == 2
    assert counts.processed == 1, "the allowed content type was not stored"
    assert _stored_text(engine, staged.enrollment_id) == [NOTES]
    assert counts.unsupported == 0 and counts.quarantined == 0
    assert counts.state() is CoverageState.PARTIALLY_PROCESSED


# ---- criterion 4: idempotency --------------------------------------------------


@pytest.mark.database
def test_running_the_handler_twice_adds_no_row(engine: Engine, tmp_path: Path) -> None:
    """A second pass over the same enrollment writes nothing at all.

    Four counts, all equal before and after, and all of the ones that can be
    non-zero are. The quarantine is the one that matters: `quarantine_records` is
    append-only by design and has no unique key to conflict against, so its
    idempotency is a *predicate* — `pending_objects` refuses to offer an object
    that already has a quarantine — rather than a constraint. That is the one
    idempotency in this design that a database cannot enforce, so it is the one a
    test has to.
    """
    corpus = _corpus(
        tmp_path / "twice",
        (
            ("notes.md", NOTES.encode()),
            ("readme.txt", README.encode()),
            ("handbook.pdf", b"%PDF-1.7\nreported, not read\n"),
            ("mislabelled.md", b"%PDF-1.7\ncalling itself markdown\n"),
        ),
    )
    staged = _stage(engine, corpus, "twice")

    _run(engine)
    first = {
        table: _count(engine, table, staged.enrollment_id)
        for table in ("extractions", "quarantine_records", "coverage_limitations")
    }
    first["enrollment_objects"] = _count(engine, "enrollment_objects", staged.enrollment_id)
    assert first["extractions"] == 3, first
    assert first["quarantine_records"] == 1, first
    assert first["enrollment_objects"] == 4, first

    # A second job over the same enrollment, exactly as a re-queued operation
    # would be. The handler is run again rather than the loop being tricked.
    with engine.begin() as connection:
        second_operation = enqueue_job(connection, staged.enrollment_id)
    run = _run(engine)
    assert run.completed == 1  # type: ignore[attr-defined]
    assert _job_row(engine, second_operation)[0] == "succeeded"

    second = {
        table: _count(engine, table, staged.enrollment_id)
        for table in ("extractions", "quarantine_records", "coverage_limitations")
    }
    second["enrollment_objects"] = _count(engine, "enrollment_objects", staged.enrollment_id)
    assert second == first, "the second pass changed what the first had recorded"


# ---- criterion 6: one stopped object does not stop the others -------------------


@pytest.mark.database
def test_a_quarantined_object_does_not_stop_the_others(engine: Engine, tmp_path: Path) -> None:
    """A file whose bytes contradict its media type is quarantined, and the pass goes on.

    `quarantined == 1` is the quarantine test. `processed == 2` is what makes it a
    *non-blocking* test: an executor that let the quarantine escape its per-object
    loop would leave the two readable files unprocessed and only the first
    assertion would notice.
    """
    corpus = _corpus(
        tmp_path / "quarantine",
        (
            ("notes.md", NOTES.encode()),
            ("readme.txt", README.encode()),
            ("mislabelled.md", b"%PDF-1.7\ncalling itself markdown\n"),
        ),
    )
    staged = _stage(engine, corpus, "quarantine")

    _run(engine)

    counts = _coverage(engine, staged.enrollment_id)
    assert counts.quarantined == 1
    assert counts.processed == 2, "one quarantine stopped the objects around it"
    assert _quarantine_reasons(engine, staged.enrollment_id) == [
        QuarantineReason.MEDIA_TYPE_CONFLICTS_WITH_SIGNATURE.value
    ]
    assert sorted(_stored_text(engine, staged.enrollment_id)) == sorted([NOTES, README])


@pytest.mark.database
def test_a_denied_object_does_not_stop_the_others(engine: Engine, tmp_path: Path) -> None:
    """An object the provider will not serve is quarantined, and the pass goes on.

    The file is removed after the enrollment was accepted, which is the state a
    corpus reaches on its own between an enrolment and a worker run. The provider
    cannot prove containment of something that is not there and denies without
    saying which of the two it was — so the recorded reason is
    `containment_unproven`, which is the honest one.
    """
    corpus = _corpus(
        tmp_path / "denied",
        (
            ("notes.md", NOTES.encode()),
            ("readme.txt", README.encode()),
            ("vanishes.md", b"here at enrolment\n"),
        ),
    )
    staged = _stage(engine, corpus, "denied")
    (corpus / "vanishes.md").unlink()

    _run(engine)

    counts = _coverage(engine, staged.enrollment_id)
    assert counts.quarantined == 1
    assert counts.processed == 2, "one denial stopped the objects around it"
    assert _quarantine_reasons(engine, staged.enrollment_id) == [
        QuarantineReason.CONTAINMENT_UNPROVEN.value
    ]


# ---- the store contradicting itself is not laundered ---------------------------


@pytest.mark.database
def test_an_object_the_enrollment_does_not_authorize_fails_the_attempt(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`enrollment_objects` and `authorized_object` disagreeing is a broken store.

    The plan is made to offer an object of the same source that the enrollment
    never enumerated — which is exactly what a hand-written or corrupted
    `enrollment_objects` would do. `record_outcome` refuses it on the object
    dimension, and that refusal is *not* caught: it means two reads of the same
    rows disagree, and skipping the object would launder that into a partial
    result.

    The two legitimate objects come first, so the attempt's failure sits beside
    work that did commit: `internal_error` on the job **and** a stored extraction
    are both asserted. A test that only checked the error code would pass on an
    executor that failed before doing anything.
    """
    corpus = _corpus(
        tmp_path / "broken",
        (("notes.md", NOTES.encode()), ("readme.txt", README.encode()), ("stray.md", b"stray\n")),
    )
    staged = _stage(engine, corpus, "broken")
    # The stray object exists under the source and is not in the enrolled set.
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM knowledge.enrollment_objects "
                "WHERE enrollment_id = :id AND source_object_id = ("
                "  SELECT source_object_id FROM knowledge.source_objects "
                "  WHERE source_id = :source AND native_locator LIKE '%stray.md')"
            ),
            {"id": staged.enrollment_id, "source": staged.source_id},
        )
        stray = connection.execute(
            text(
                "SELECT source_object_id FROM knowledge.source_objects "
                "WHERE source_id = :source AND native_locator LIKE '%stray.md'"
            ),
            {"source": staged.source_id},
        ).scalar_one()

    real_pending = extraction.pending_objects

    def pending_with_the_stray(connection: object, enrollment_id: str) -> tuple[str, ...]:
        return (*real_pending(connection, enrollment_id), str(stray))  # type: ignore[arg-type]

    monkeypatch.setattr(extraction, "pending_objects", pending_with_the_stray)

    run = _run(engine)

    assert run.released == 1 and run.completed == 0  # type: ignore[attr-defined]
    state, _, code = _job_row(engine, staged.operation_id)
    assert (state, code) == ("queued", ErrorCode.INTERNAL_ERROR.value)
    assert _count(engine, "extractions", staged.enrollment_id) == 2, (
        "the attempt failed before it recorded the objects it was entitled to"
    )


# ---- criterion 5: recovery -----------------------------------------------------


@pytest.mark.database
@pytest.mark.recovery
def test_a_worker_killed_mid_extraction_loses_no_object(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker that dies after three of four objects loses neither and duplicates neither.

    The failure is planted at the fourth `record_outcome`, which is after three
    have committed and before the last one does — the place where "commits per
    object" and "all or nothing" give different answers. The attempt is released,
    the job returns to `queued`, and the next worker picks up exactly the object
    with no outcome yet.

    **The corpus holds two quarantine triggers, and that is the whole of why this
    test can fail.** `pending_objects` is offered in identifier order, which is
    random, so which object is left over is not decidable here — but with two
    triggers and one object left, *at least one quarantine is always committed by
    the first run*. That matters because `extractions` is idempotent by
    constraint and `quarantine_records` is not: a re-offered extraction writes no
    row whatever the planner does, so a corpus without a committed quarantine
    would let a `pending_objects` that returned everything pass this test
    unnoticed. It did, before the plant was tried.

    The final assertion is per object across both tables, because that is where a
    duplicate would land.
    """
    corpus = _corpus(
        tmp_path / "killed",
        (
            ("notes.md", NOTES.encode()),
            ("readme.txt", README.encode()),
            ("bad-one.md", b"%PDF-1.7\nfirst mislabelled file\n"),
            ("bad-two.md", b"%PDF-1.7\nsecond mislabelled file\n"),
        ),
    )
    staged = _stage(engine, corpus, "killed")

    real_record = extraction.record_outcome
    calls = {"count": 0}

    def die_on_the_fourth(connection: object, *, enrollment_id: str, outcome: object) -> str:
        calls["count"] += 1
        if calls["count"] == 4:
            raise RuntimeError("as if the process went here")
        return real_record(  # type: ignore[arg-type]
            connection,  # type: ignore[arg-type]
            enrollment_id=enrollment_id,
            outcome=outcome,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(extraction, "record_outcome", die_on_the_fourth)
    first = _run(engine)
    assert first.released == 1  # type: ignore[attr-defined]
    committed = _count(engine, "extractions", staged.enrollment_id) + _count(
        engine, "quarantine_records", staged.enrollment_id
    )
    assert committed == 3, "the objects committed before the failure did not survive it"
    assert _count(engine, "quarantine_records", staged.enrollment_id) >= 1, (
        "no quarantine was committed, so a re-offered object could not be detected"
    )

    monkeypatch.setattr(extraction, "record_outcome", real_record)
    second = _run(engine)

    assert second.completed == 1  # type: ignore[attr-defined]
    counts = _coverage(engine, staged.enrollment_id)
    assert counts.eligible == 4
    assert counts.processed == 2
    assert counts.quarantined == 2
    assert _count(engine, "extractions", staged.enrollment_id) == 2
    assert _count(engine, "quarantine_records", staged.enrollment_id) == 2, (
        "the recovered pass quarantined an object it had already quarantined"
    )
    with engine.connect() as connection:
        duplicated = connection.execute(
            text(
                "SELECT count(*) FROM ("
                "  SELECT source_object_id FROM knowledge.extractions WHERE enrollment_id = :id"
                "  UNION ALL"
                "  SELECT source_object_id FROM knowledge.quarantine_records"
                "  WHERE enrollment_id = :id"
                ") AS outcomes GROUP BY source_object_id HAVING count(*) > 1"
            ),
            {"id": staged.enrollment_id},
        ).all()
    assert duplicated == [], "an object reached two outcomes across the two passes"


@pytest.mark.database
@pytest.mark.recovery
def test_a_lost_lease_commits_no_outcome(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The narrow property, at the object the lease was taken at.

    The lease is stolen from a second connection between the first object's write
    and the second object's read — the window in which no transaction of this
    worker's is open, which is where a lease actually expires. Every write
    transaction takes `hold_lease` as its first statement, so the second object's
    transaction finds the lease gone and rolls back having written nothing.

    The steal is deliberately *not* made from inside a write transaction. That
    transaction holds the job row `FOR UPDATE`, so a second session updating the
    same row would block until it committed — and the worker would be waiting on
    the session waiting on it. `hold_lease` locking the row is what makes that
    true, and it is the same property that makes the check race-free.

    **The zero is meaningful only beside the control**, and the control is in this
    same test: the first object's row is there, and it is asserted before the
    absence of the rest is. Without it, an executor that wrote nothing at all
    would satisfy "no outcome after the lease was lost" perfectly.
    """
    corpus = _corpus(
        tmp_path / "stolen",
        (
            ("a-notes.md", NOTES.encode()),
            ("b-readme.txt", README.encode()),
            ("c-more.md", b"a third object nobody should reach\n"),
        ),
    )
    staged = _stage(engine, corpus, "stolen")
    thief = issue_worker_owner()

    real_read = extraction._read
    reads = {"count": 0}

    def steal_before_the_second(*args: object, **keywords: object) -> object:
        reads["count"] += 1
        if reads["count"] == 2:
            with engine.begin() as other:
                other.execute(
                    text(
                        "UPDATE knowledge.jobs SET lease_owner = :owner, "
                        "lease_expires_at = now() + interval '60 seconds' "
                        "WHERE operation_id = :id"
                    ),
                    {"owner": thief, "id": staged.operation_id},
                )
        return real_read(*args, **keywords)  # type: ignore[arg-type]

    monkeypatch.setattr(extraction, "_read", steal_before_the_second)

    run = _run(engine)

    assert run.lost == 1 and run.completed == 0  # type: ignore[attr-defined]
    assert _count(engine, "extractions", staged.enrollment_id) == 1, (
        "the object recorded while the lease was held was not kept"
    )
    assert _count(engine, "quarantine_records", staged.enrollment_id) == 0
    state, _, _ = _job_row(engine, staged.operation_id)
    assert state == "running", "a worker without the lease reported the job finished"
    assert state != "succeeded"


@pytest.mark.database
@pytest.mark.recovery
def test_an_expired_lease_lets_another_worker_finish_the_job(
    engine: Engine, tmp_path: Path
) -> None:
    """A crashed worker's job is finished by the next one, with nothing lost.

    The first worker claims and then does nothing at all, which is what a killed
    process leaves behind; its lease is expired rather than waited out. The
    second worker claims the same job — that is `claim_job`'s recovery
    predicate — and drives it to `succeeded`.
    """
    corpus = _corpus(
        tmp_path / "expired",
        (
            ("one.md", b"first\n"),
            ("two.md", b"second\n"),
            ("three.md", b"third\n"),
            ("four.md", b"fourth\n"),
        ),
    )
    staged = _stage(engine, corpus, "expired")
    dead = issue_worker_owner()
    with engine.begin() as connection:
        assert claim_job(connection, owner=dead, lease_seconds=1) is not None
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE knowledge.jobs SET lease_expires_at = now() - interval '1 second'")
        )

    run = _run(engine)

    assert run.completed == 1  # type: ignore[attr-defined]
    counts = _coverage(engine, staged.enrollment_id)
    assert counts.eligible == 4
    assert counts.processed == 4
    assert counts.state() is CoverageState.PROCESSED
    state, attempts, _ = _job_row(engine, staged.operation_id)
    assert state == "succeeded"
    assert attempts == 2, "the dead worker's attempt was not counted against the bound"


# ---- the boundary the handler signature changed for ----------------------------


@pytest.mark.database
def test_no_database_transaction_is_open_while_the_bytes_are_read(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`module-boundaries.md` section 10, asked of the server rather than asserted.

    The whole reason `JobHandler` stopped receiving an open connection is that
    source bytes may not be read inside a database transaction. That is a claim
    about what the server sees, so it is measured there: while `fetch` is running,
    every backend of this database is asked for its state, and none of them may be
    `idle in transaction`.

    The control is in the same measurement. The connection the read phase holds
    *is* live — it is `active` or `idle` — so the assertion cannot be satisfied by
    a run in which the executor never connected at all, and the number of samples
    is asserted to be non-zero for the same reason.
    """
    corpus = _corpus(tmp_path / "boundary", (("notes.md", NOTES.encode()),))
    staged = _stage(engine, corpus, "boundary")
    real_fetch = FixtureSourceProvider.fetch
    samples: list[list[str]] = []

    def watched_fetch(
        self: FixtureSourceProvider, source_object_id: str, *, max_bytes: int
    ) -> SourceObjectContent:
        with engine.connect() as watcher:
            samples.append(
                [
                    str(row[0])
                    for row in watcher.execute(
                        text(
                            "SELECT state FROM pg_stat_activity "
                            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                        )
                    )
                ]
            )
        return real_fetch(self, source_object_id, max_bytes=max_bytes)

    monkeypatch.setattr(FixtureSourceProvider, "fetch", watched_fetch)

    _run(engine)

    assert samples, "the fetch never ran, so nothing was measured"
    assert all(samples), "no other backend was connected; the sample proves nothing"
    for sample in samples:
        assert "idle in transaction" not in sample, (
            f"a transaction was open while the bytes were read: {sample}"
        )
    assert _coverage(engine, staged.enrollment_id).processed == 1


# ---- guards on this file itself -------------------------------------------------


def test_the_executor_is_the_handler_the_worker_process_wires() -> None:
    """The tests above drive the same callable `apps/worker.py` does.

    Runs in every tier, because it needs no server. Without it, this file could
    prove a great deal about a function nothing calls.
    """
    import apps.worker as worker_process

    assert worker_process.extract_enrollment is extract_enrollment
    assert "extract_enrollment" in worker_process._run.__code__.co_names


def test_the_outcome_types_this_file_relies_on_are_the_ones_that_exist() -> None:
    """Guard the imports: a renamed outcome would make several tests vacuous."""
    assert ExtractionOutcome.__name__ == "ExtractionOutcome"
    assert QuarantineReason.CONTAINMENT_UNPROVEN.value == "containment_unproven"
