"""WP3P-S4 (S3 R2 carry-overs b, d): how a refused project-report write leaves the repository.

The `database` tier, on a disposable head-migrated clone. Proved here:

* a transaction-conflict victim of a repository write -- `40P01`
  (deadlock_detected) and `40001` (serialization_failure) -- leaves as the
  port's retryable `TransactionConflictError`, never as a
  `ProjectReportsWriteRefusedError` and never as the driver error. Each SQLSTATE
  is raised deterministically by a throwaway guard installed inside the test's
  own transaction (rolled back with it), and a real two-session deadlock over
  `get_or_create_record` shows the same answer for the server's own victim;
* a `StatementError` that is not a driver error (a bind value SQLAlchemy's
  column type refuses before the statement is sent, whose message quotes the
  bound parameters) leaves as `ProjectReportsWriteRefusedError` with no
  SQLSTATE, no constraint, and nothing on its chain.

Every identifier and text here is synthetic.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import Engine, insert, text
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import (
    IngestConsumer,
    IngestSnapshotRecord,
    IngestSourceRecord,
    ProjectReportBindingRevisionRecord,
    ProjectReportDerivationRecord,
    ProjectReportRecordEntry,
    ProjectReportRowRecord,
    ProjectReportSnapshotRecord,
    ProjectReportsWriteRefusedError,
    TransactionConflictError,
)
from my_pa.domain.project_reports.model import (
    BindingReason,
    BindingState,
    CompletenessClass,
    DerivationState,
    DerivationTrigger,
    FamilyView,
    IdentityBasis,
    RecordFamily,
)
from my_pa.infrastructure.persistence.ingestion import SqlIngestionRepository
from my_pa.infrastructure.persistence.project_reports import SqlProjectReportsRepository
from my_pa.infrastructure.persistence.tables import projects

pytestmark = pytest.mark.database

P: Final = "prn_prtrans0001aaa"
WHEN: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
SOURCE: Final = "isrc_prtrans0001"
PROJECT: Final = "prj_prtrans0001"
SNAP: Final = "isnp_prtrans0001"
DIGEST: Final = "a" * 64
R1: Final = "prbnd_prtrans0001"
D1: Final = "prdrv_prtrans0001"
#: A distinctive synthetic value, so any leak of the bound parameters is unmistakable.
_CANARY: Final = "SYNTHETIC-CANARY-s4-91d2"


def _revision(revision_id: str = R1) -> ProjectReportBindingRevisionRecord:
    return ProjectReportBindingRevisionRecord(
        binding_revision_id=revision_id,
        ingest_source_id=SOURCE,
        project_id=PROJECT,
        declared_project_number="SYN-0001",
        state=BindingState.ACTIVE,
        currency="USD",
        recorded_at=WHEN,
        change_set_sha256="a" * 64,
        reason_code=BindingReason.INITIAL,
    )


def _derivation(role_counts: dict[str, object]) -> ProjectReportDerivationRecord:
    return ProjectReportDerivationRecord(
        derivation_id=D1,
        snapshot_id=SNAP,
        ingest_source_id=SOURCE,
        binding_revision_id=R1,
        project_id=PROJECT,
        state=DerivationState.CLASSIFIED,
        identity_version="project_report_identity_v1",
        status_map_version="status_map_v1",
        role_counts=role_counts,  # type: ignore[arg-type]
        trigger=DerivationTrigger.INGEST,
        derived_at=WHEN,
        record_family=RecordFamily.RFIS,
        family_view=FamilyView.OPEN_OUTSTANDING,
        adapter_version="pulse_adapter_v1",
        completeness_class=CompletenessClass.VALID_EMPTY,
        reconciliation={},
    )


def _record(record_id: str, key: str) -> ProjectReportRecordEntry:
    return ProjectReportRecordEntry(
        record_id=record_id,
        project_id=PROJECT,
        record_family=RecordFamily.RFIS,
        identity_key=f"rfi:{key}",
        identity_version="project_report_identity_v1",
        identity_basis=IdentityBasis.EXPORTED_NUMBER,
        created_by_derivation_id=D1,
    )


def _parents(connection: Connection) -> SqlProjectReportsRepository:
    """A source, a lifecycle snapshot and a Project of `P`."""
    ingestion = SqlIngestionRepository(connection)
    ingestion.insert_source(
        P,
        IngestSourceRecord(
            ingest_source_id=SOURCE,
            consumer=IngestConsumer.PULSE_CSV_EXPORT,
            workspace_id="mcp",
            path_prefix="exports/one/",
            file_pattern="*.csv",
            enabled=True,
            admitted_at=WHEN,
        ),
    )
    ingestion.insert_snapshot(
        P,
        IngestSnapshotRecord(
            snapshot_id=SNAP,
            ingest_source_id=SOURCE,
            file_sha256=DIGEST,
            byte_count=10,
            observed_version_token=None,
            first_seen_at=WHEN,
        ),
    )
    connection.execute(
        insert(projects).values(
            project_id=PROJECT,
            principal_id=P,
            name="Synthetic project",
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return SqlProjectReportsRepository(connection)


def _with_derivation(repository: SqlProjectReportsRepository) -> None:
    repository.insert_binding_revision(P, _revision())
    repository.insert_snapshot(
        P,
        ProjectReportSnapshotRecord(
            snapshot_id=SNAP,
            ingest_source_id=SOURCE,
            file_sha256=DIGEST,
            bom_present=False,
            header_raw_record="A,B",
            header_terminator="lf",
            header_cells=("A", "B"),
            header_signature="e" * 64,
            signature_version="pulse_header_signature_v1",
            reader_version="pulse_csv_reader_v1",
            data_row_count=0,
            embedded_line_break_count=0,
            reconstruction_sha256=DIGEST,
        ),
        (),
    )
    repository.insert_derivation(P, _derivation({"detail": 0}))


@pytest.fixture
def connection(migrated_engine: Engine) -> Iterator[Connection]:
    """One transaction, rolled back after the test (with any guard it installed)."""
    with migrated_engine.connect() as opened:
        transaction = opened.begin()
        try:
            yield opened
        finally:
            transaction.rollback()


def _chain(error: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop()
        if any(current is known for known in seen):
            continue
        seen.append(current)
        pending.extend(e for e in (current.__cause__, current.__context__) if e is not None)
    return seen


@pytest.mark.parametrize("sqlstate", ["40P01", "40001"])
def test_a_conflict_victim_of_a_write_is_a_transaction_conflict(
    connection: Connection, sqlstate: str
) -> None:
    """Carry-over b: the retryable conflict SQLSTATEs are never a write refusal."""
    repository = _parents(connection)
    # A throwaway guard inside this transaction: rolled back by the fixture.
    connection.execute(
        text(
            "CREATE FUNCTION pg_temp.s4_conflict() RETURNS trigger LANGUAGE plpgsql AS "
            f"$$BEGIN RAISE EXCEPTION 'synthetic conflict' USING ERRCODE = '{sqlstate}'; END$$"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER s4_conflict BEFORE INSERT ON "
            "knowledge.project_report_binding_revisions "
            "FOR EACH ROW EXECUTE FUNCTION pg_temp.s4_conflict()"
        )
    )
    savepoint = connection.begin_nested()
    try:
        with pytest.raises(TransactionConflictError) as conflict:
            repository.insert_binding_revision(P, _revision())
    finally:
        savepoint.rollback()
    assert not isinstance(conflict.value, ProjectReportsWriteRefusedError)
    assert conflict.value.__cause__ is None
    assert conflict.value.__context__ is None


def test_a_real_deadlock_between_two_record_writes_is_a_transaction_conflict(
    migrated_engine: Engine,
) -> None:
    """Carry-over b, the server's own victim: two sessions insert two identities crosswise."""
    with migrated_engine.begin() as seed:
        _with_derivation(_parents(seed))
    barrier = threading.Barrier(2, timeout=20)
    outcomes: dict[str, BaseException | None] = {}

    def run(tag: str, first: tuple[str, str], second: tuple[str, str]) -> None:
        with migrated_engine.connect() as session:
            transaction = session.begin()
            repository = SqlProjectReportsRepository(session)
            try:
                repository.get_or_create_record(P, _record(*first))
                barrier.wait()
                time.sleep(0.3)
                repository.get_or_create_record(P, _record(*second))
                transaction.commit()
                outcomes[tag] = None
            except Exception as error:
                outcomes[tag] = error
                transaction.rollback()

    one = ("prrec_prtransdl01", "k1")
    two = ("prrec_prtransdl02", "k2")
    threads = [
        threading.Thread(target=run, args=("a", one, two)),
        threading.Thread(target=run, args=("b", two, one)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(outcomes) == ["a", "b"]
    failures = [error for error in outcomes.values() if error is not None]
    assert len(failures) == 1, outcomes
    assert type(failures[0]) is TransactionConflictError
    assert failures[0].__cause__ is None
    assert failures[0].__context__ is None


def test_a_non_driver_statement_error_is_a_refusal_with_no_parameters(
    connection: Connection,
) -> None:
    """Carry-over d: a Boolean bind value SQLAlchemy refuses before the statement is sent.

    SQLAlchemy's `Boolean` bind processor raises on a non-boolean value, wrapped
    as a `StatementError` (not a `DBAPIError`) whose text quotes the bound
    parameters -- here the raw record holding the canary.
    """
    repository = _parents(connection)
    head = ProjectReportSnapshotRecord(
        snapshot_id=SNAP,
        ingest_source_id=SOURCE,
        file_sha256=DIGEST,
        bom_present=False,
        header_raw_record="A,B",
        header_terminator="lf",
        header_cells=("A", "B"),
        header_signature="e" * 64,
        signature_version="pulse_header_signature_v1",
        reader_version="pulse_csv_reader_v1",
        data_row_count=1,
        embedded_line_break_count=0,
        reconstruction_sha256=DIGEST,
    )
    row = ProjectReportRowRecord(1, _CANARY, "none", (_CANARY,), _CANARY)  # type: ignore[arg-type]
    savepoint = connection.begin_nested()
    try:
        with pytest.raises(ProjectReportsWriteRefusedError) as refused:
            repository.insert_snapshot(P, head, (row,))
    finally:
        savepoint.rollback()
    assert (refused.value.sqlstate, refused.value.constraint) == (None, None)
    assert refused.value.__cause__ is None
    assert refused.value.__context__ is None
    for linked in _chain(refused.value):
        assert _CANARY not in str(linked)
        assert _CANARY not in repr(linked.args)
