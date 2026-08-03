"""The port adapters return what WP-3 actually persisted.

`tests/contract/test_application_capabilities.py` proves that the application
assembles a disclosure from whatever the coverage port returns. That is only half
the claim: it says nothing about whether the port returns the rows the extraction
writer wrote. This file is the other half, and neither is sufficient alone —
between them they say that a change to a stored outcome reaches the envelope.

So the tests here write through WP-2's and WP-3's own writers — `register_source`,
`observe_object`, `accept_enrollment`, `record_outcome`, `quarantine_object`,
`record_limitation` — and then read through the *ports*, not through the free
functions, because the port is what the application holds.

The database is disposable, created and dropped by its fixture, and never the
configured one: this suite writes, and pointing it at `my_pa` would put synthetic
rows into the schema that holds the migrated corpus. Every value inserted is
synthetic; no path here exists and none is opened.
"""

from __future__ import annotations

import io
import os
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from tests.conftest import DEFAULT_LIMITS, RecordingAudit

from my_pa.application.commands import ListSources
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import RepositoryFailureError, UnitOfWork
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.extraction.coverage import LimitationReason
from my_pa.domain.extraction.quarantine import QuarantineReason
from my_pa.domain.extraction.text import ExtractionStatus, extract_text
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.enrollment import EnrollmentRequest, EnrollmentScope
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.enrollment import accept_enrollment, record_scope
from my_pa.infrastructure.persistence.extraction import (
    quarantine_object,
    record_limitation,
    record_outcome,
)
from my_pa.infrastructure.persistence.jobs import enqueue_job
from my_pa.infrastructure.persistence.registry import observe_object, register_source
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

ROOT = Path(__file__).resolve().parents[2]

#: Fixed name, so a run interrupted before teardown is cleaned up by the next.
DISPOSABLE_DATABASE = "my_pa_application_ports_test"

WHEN = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: Synthetic throughout. No such path exists and none is opened.
NATIVE_ROOT = "/synthetic/application/corpus"

READABLE = ("text/markdown", "text/plain")


def administer(maintenance: Engine, *statements: object) -> None:
    """Run statements that cannot be inside a transaction, such as CREATE DATABASE."""
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
        administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture(scope="module")
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        yield built
    finally:
        built.dispose()


class Corpus:
    """One source, three observed objects, and one enrollment naming them.

    `native_root` is a parameter because the source lookup is now driven by the
    stored row: a request that reaches a provider builds one over exactly this
    path, so a test that needs the provider to work has to register a directory
    that exists. The default stays the synthetic locator, which is right for
    every test here that never leaves persistence.
    """

    def __init__(self, engine: Engine, key: str, native_root: str | None = None) -> None:
        self.engine = engine
        self.principal_id = issue_identifier(IdKind.PRINCIPAL)
        with engine.begin() as connection:
            source = register_source(
                connection,
                provider_kind=SourceProviderKind.FIXTURE,
                label="Synthetic corpus",
                classification=Classification.SYNTHETIC_TEST,
                native_root=f"{NATIVE_ROOT}/{key}" if native_root is None else native_root,
            )
            self.source_id = source.source_id
            self.objects = {
                name: observe_object(
                    connection,
                    source_id=source.source_id,
                    native_locator=f"{NATIVE_ROOT}/{key}/{name}",
                    kind=ObjectKind.FILE,
                    fingerprint=f"fingerprint-{key}-{name}",
                    modified_at=WHEN,
                    media_type=media_type,
                    size_bytes=32,
                )
                for name, media_type in (
                    ("notes", "text/markdown"),
                    ("list", "text/plain"),
                    ("statement", "application/pdf"),
                )
            }
            self.enrollment = accept_enrollment(
                connection,
                EnrollmentRequest(
                    source_id=source.source_id,
                    principal_id=self.principal_id,
                    purpose=Purpose.BOUNDED_ENROLLMENT,
                    scope=EnrollmentScope(
                        object_ids=tuple(o.source_object_id for o in self.objects.values())
                    ),
                    media_types=READABLE,
                    policy_version="mcv-1",
                    idempotency_key=f"ports-{key}-{secrets.token_hex(4)}",
                    max_items=100,
                    max_bytes=1_000_000,
                ),
            ).enrollment
            # The enumerated object set: what every read restricts to, and the
            # eligible total the coverage port reads for itself. `sources.enroll`
            # writes it inside the accepting transaction, so a fixture that
            # skipped it would build an enrollment authorizing nothing.
            record_scope(
                connection,
                self.enrollment.enrollment_id,
                [o.source_object_id for o in self.objects.values()],
            )

    def object_id(self, name: str) -> str:
        return self.objects[name].source_object_id

    def extract(self, name: str, body: bytes, media_type: str) -> str:
        with self.engine.begin() as connection:
            return record_outcome(
                connection,
                enrollment_id=self.enrollment.enrollment_id,
                outcome=extract_text(
                    source_id=self.source_id,
                    source_object_id=self.object_id(name),
                    observed_version_id=self.objects[name].version_id,
                    content_version_id=self.objects[name].version_id,
                    media_type=media_type,
                    content=body,
                    observed_at=WHEN,
                ),
            )


def unit_of_work(engine: Engine) -> tuple[UnitOfWork, RecordingAudit]:
    audit = RecordingAudit()
    return SqlAlchemyUnitOfWork(engine, audit=audit), audit


def test_the_enrollment_port_returns_the_principals_own_grants(engine: Engine) -> None:
    corpus = Corpus(engine, "grants")
    work, _ = unit_of_work(engine)
    with work as opened:
        held = opened.enrollments.for_principal(corpus.principal_id)
        stranger = opened.enrollments.for_principal(issue_identifier(IdKind.PRINCIPAL))
    assert [e.enrollment_id for e in held] == [corpus.enrollment.enrollment_id]
    assert stranger == ()


def test_the_source_port_answers_none_for_an_identifier_that_names_no_row(
    engine: Engine,
) -> None:
    """Absence is `None`, so the caller reports `not_found` rather than crashing."""
    corpus = Corpus(engine, "absent")
    work, _ = unit_of_work(engine)
    with work as opened:
        assert opened.sources.source(corpus.source_id) is not None
        assert opened.sources.source(issue_identifier(IdKind.SOURCE)) is None
        assert opened.sources.source_of_object(corpus.object_id("notes")) == corpus.source_id
        assert opened.sources.source_of_object(issue_identifier(IdKind.SOURCE_OBJECT)) is None


def test_the_source_port_returns_no_locator(engine: Engine) -> None:
    """The one column that holds a path stays behind this boundary."""
    corpus = Corpus(engine, "locator")
    work, _ = unit_of_work(engine)
    with work as opened:
        source = opened.sources.source(corpus.source_id)
    assert source is not None
    assert NATIVE_ROOT not in repr(source)


def test_the_operation_port_returns_the_grant_and_the_state_together(
    engine: Engine,
) -> None:
    corpus = Corpus(engine, "operation")
    work, _ = unit_of_work(engine)
    with work as opened:
        operation_id = opened.operations.enqueue(corpus.enrollment.enrollment_id)
    work, _ = unit_of_work(engine)
    with work as opened:
        found = opened.operations.operation(operation_id)
        missing = opened.operations.operation(issue_identifier(IdKind.OPERATION))
    assert found is not None
    assert found.enrollment_id == corpus.enrollment.enrollment_id
    assert found.state is SourceStatusState.QUEUED
    assert missing is None


def test_the_coverage_port_counts_what_the_extraction_writer_wrote(
    engine: Engine,
) -> None:
    """The other half of criterion 4: the port reads persisted rows."""
    corpus = Corpus(engine, "coverage")
    work, _ = unit_of_work(engine)
    with work as opened:
        before = opened.knowledge.coverage(corpus.enrollment.enrollment_id, observed_at=WHEN)
    assert before.processed == 0
    assert before.state() is CoverageState.ELIGIBLE

    corpus.extract("notes", b"# Notes\n\nquarterly revenue\n", "text/markdown")
    corpus.extract("statement", b"%PDF-1.4\n", "application/pdf")

    work, _ = unit_of_work(engine)
    with work as opened:
        after = opened.knowledge.coverage(corpus.enrollment.enrollment_id, observed_at=WHEN)
    # Three objects were enumerated, so the denominator is three whichever
    # outcomes exist. No caller states it and none can: the port has no
    # `eligible` parameter to state it with.
    assert after.eligible == 3
    assert after.processed == 1
    assert after.unsupported == 1
    assert after.state() is CoverageState.PARTIALLY_PROCESSED


def test_the_limitation_port_reads_the_newest_snapshot(engine: Engine) -> None:
    corpus = Corpus(engine, "limitation")
    with engine.begin() as connection:
        record_limitation(
            connection,
            enrollment_id=corpus.enrollment.enrollment_id,
            observed_at=WHEN,
            reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
            affected_count=2,
        )
        record_limitation(
            connection,
            enrollment_id=corpus.enrollment.enrollment_id,
            observed_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
            reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
            affected_count=5,
        )
    work, _ = unit_of_work(engine)
    with work as opened:
        limitations = opened.knowledge.limitations(corpus.enrollment.enrollment_id)
    assert [limitation.affected_count for limitation in limitations] == [5]


def test_the_object_outcome_port_applies_the_precedence_the_counts_apply(
    engine: Engine,
) -> None:
    """A quarantine outranks a later success (`INV-PKL-007`)."""
    corpus = Corpus(engine, "precedence")
    corpus.extract("notes", b"# Notes\n\nreadable\n", "text/markdown")
    work, _ = unit_of_work(engine)
    with work as opened:
        assert (
            opened.knowledge.outcome_for_object(
                enrollment_id=corpus.enrollment.enrollment_id,
                source_object_id=corpus.object_id("notes"),
            )
            is ExtractionStatus.EXTRACTED
        )
        assert (
            opened.knowledge.outcome_for_object(
                enrollment_id=corpus.enrollment.enrollment_id,
                source_object_id=corpus.object_id("list"),
            )
            is None
        )
    with engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=corpus.enrollment.enrollment_id,
            source_object_id=corpus.object_id("notes"),
            version_id=corpus.objects["notes"].version_id,
            reason=QuarantineReason.MALFORMED_INPUT,
        )
    work, _ = unit_of_work(engine)
    with work as opened:
        assert (
            opened.knowledge.outcome_for_object(
                enrollment_id=corpus.enrollment.enrollment_id,
                source_object_id=corpus.object_id("notes"),
            )
            is ExtractionStatus.QUARANTINED
        )


def test_the_read_port_returns_a_record_inside_its_grant_and_nothing_outside(
    engine: Engine,
) -> None:
    corpus = Corpus(engine, "read")
    knowledge_id = corpus.extract("notes", b"# Notes\n\nquarterly revenue\n", "text/markdown")
    other = Corpus(engine, "read-other")

    work, _ = unit_of_work(engine)
    with work as opened:
        record = opened.knowledge.read(knowledge_id, enrollment_id=corpus.enrollment.enrollment_id)
        foreign = opened.knowledge.read(knowledge_id, enrollment_id=other.enrollment.enrollment_id)
    assert record is not None
    assert "quarterly revenue" in record.text
    assert record.provenance.source_id == corpus.source_id
    assert record.provenance.version_id == corpus.objects["notes"].version_id
    assert foreign is None, "a record read through another grant"


def test_an_unsupported_row_is_not_a_readable_record(engine: Engine) -> None:
    """It has no text, so `knowledge.read` finds nothing rather than empty text."""
    corpus = Corpus(engine, "unsupported")
    knowledge_id = corpus.extract("statement", b"%PDF-1.4\n", "application/pdf")
    work, _ = unit_of_work(engine)
    with work as opened:
        assert (
            opened.knowledge.read(knowledge_id, enrollment_id=corpus.enrollment.enrollment_id)
            is None
        )


def test_the_unit_of_work_commits_on_a_normal_exit(engine: Engine) -> None:
    corpus = Corpus(engine, "commit")
    work, _ = unit_of_work(engine)
    with work as opened:
        operation_id = opened.operations.enqueue(corpus.enrollment.enrollment_id)
    work, _ = unit_of_work(engine)
    with work as opened:
        assert opened.operations.operation(operation_id) is not None


def test_the_unit_of_work_rolls_back_when_the_block_raises(engine: Engine) -> None:
    corpus = Corpus(engine, "rollback")
    work, _ = unit_of_work(engine)
    captured: str | None = None
    with pytest.raises(RuntimeError), work as opened:
        captured = opened.operations.enqueue(corpus.enrollment.enrollment_id)
        raise RuntimeError("the handler failed after queueing")
    assert captured is not None
    work, _ = unit_of_work(engine)
    with work as opened:
        assert opened.operations.operation(captured) is None


def test_a_repository_is_unavailable_outside_a_transaction(engine: Engine) -> None:
    """A statement outside the unit of work would autocommit; it raises instead."""
    work, _ = unit_of_work(engine)
    with pytest.raises(RuntimeError, match="not inside a transaction"):
        _ = work.sources


def test_a_broken_read_becomes_a_port_failure_and_carries_no_statement(
    engine: Engine,
) -> None:
    """An inconsistency is classified, and nothing of the statement escapes.

    The failure induced here is the one `coverage_for` can still raise now that
    it reads its own denominator: `queued` is the caller's, and work claimed
    against a scope smaller than it is a number that cannot be true. Three
    objects are enumerated and four are declared queued. It is
    `RepositoryFailureError` rather than an unavailability, because retrying
    reads the same rows and fails the same way, and its message carries neither
    the schema nor the statement.

    The control is the same call without the impossible declaration, in the same
    test: it returns counts rather than raising, so the refusal is about the
    arithmetic and not about the fixture being unreadable.
    """
    corpus = Corpus(engine, "broken")
    corpus.extract("notes", b"# Notes\n\ntext\n", "text/markdown")
    work, _ = unit_of_work(engine)
    with work as opened:
        honest = opened.knowledge.coverage(corpus.enrollment.enrollment_id, observed_at=WHEN)
    assert honest.eligible == 3
    assert honest.processed == 1

    work, _ = unit_of_work(engine)
    with work as opened, pytest.raises(RepositoryFailureError) as caught:
        opened.knowledge.coverage(corpus.enrollment.enrollment_id, observed_at=WHEN, queued=4)
    assert "knowledge" not in str(caught.value)
    assert "SELECT" not in str(caught.value)


def test_the_application_discloses_coverage_read_from_the_database(
    engine: Engine, tmp_path: Path
) -> None:
    """The two halves joined: a stored outcome changes the disclosed envelope.

    The service runs over the real unit of work and the real fixture provider,
    so the counts in the envelope came out of `knowledge.extractions` rather than
    out of a fake that agrees with the test.
    """
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "notes.md").write_bytes(b"# Notes\n\nquarterly revenue\n")

    corpus = Corpus(engine, "envelope", native_root=str(root))
    principal = Principal(
        principal_id=corpus.principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
    )
    audit = RecordingAudit()
    service = ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
    )
    from tests.conftest import metadata_for

    def disclose() -> tuple[int, CoverageState]:
        envelope = service.invoke(
            metadata_for(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, principal),
            ListSources(source_id=corpus.source_id),
            principal=principal,
        )
        assert envelope.error is None, envelope.error
        assert envelope.disclosure is not None
        return envelope.disclosure.coverage.processed, envelope.disclosure.coverage.state

    assert disclose() == (0, CoverageState.ELIGIBLE)
    corpus.extract("notes", b"# Notes\n\nquarterly revenue\n", "text/markdown")
    assert disclose() == (1, CoverageState.PARTIALLY_PROCESSED)
    assert audit.events, "the run recorded no audit event"


def test_the_enqueue_writer_and_the_operation_port_agree(engine: Engine) -> None:
    """The port is a read of the same row `enqueue_job` writes."""
    corpus = Corpus(engine, "agree")
    with engine.begin() as connection:
        operation_id = enqueue_job(connection, corpus.enrollment.enrollment_id)
    work, _ = unit_of_work(engine)
    with work as opened:
        found = opened.operations.operation(operation_id)
    assert found is not None
    assert found.operation_id == operation_id
