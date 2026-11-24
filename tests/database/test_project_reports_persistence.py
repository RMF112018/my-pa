"""WP3P-S3: `SqlProjectReportsRepository` and `list_paths_of_snapshot`, on a live server.

The `database` tier, on a disposable head-migrated clone. Proved here: each
repository operation writes and reads back exactly what it was given (Decimal,
date, boolean and text values each in their own column); every read is
partitioned, so another Principal's row answers as an absent one; the binding
pointer moves to the superseding revision and the guard refuses any other move;
the record identity is get-or-create; current derivations are read through the
view, so a superseded derivation is never returned; the guards surface
unabsorbed, as `ProjectReportsWriteRefusedError` carrying no cell text (S2);
a supersedes cycle, a new pointer on a superseded revision and a cross-check
in reversed roles are refused (B1, N2, N1); the lifecycle lists a snapshot's paths in first-seen order; and the
general unit of work exposes the repository on its connection.

Every identifier and text here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Final

import pytest
from sqlalchemy import Engine, insert
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import (
    IngestConsumer,
    IngestSnapshotPathRecord,
    IngestSnapshotRecord,
    IngestSourceRecord,
    ProjectReportBindingRecord,
    ProjectReportBindingRevisionRecord,
    ProjectReportCrossCheckRecord,
    ProjectReportDerivationRecord,
    ProjectReportFilterDeclarationRecord,
    ProjectReportLineRecord,
    ProjectReportLineValueRecord,
    ProjectReportRecordEntry,
    ProjectReportRowRecord,
    ProjectReportRowRoleRecord,
    ProjectReportSnapshotRecord,
    ProjectReportStatedTotalRecord,
    ProjectReportsWriteRefusedError,
    RepositoryFailureError,
)
from my_pa.domain.project_reports.model import (
    Additivity,
    BindingReason,
    BindingState,
    CompletenessClass,
    DerivationState,
    DerivationTrigger,
    FamilyView,
    IdentityBasis,
    IdentityState,
    LineKind,
    ObservationState,
    QuarantineReason,
    ReconciliationOutcome,
    RecordFamily,
    RowReason,
    RowRole,
    StatusClass,
    TotalScope,
    ValueKind,
)
from my_pa.domain.project_reports.reconciliation import CROSS_CHECK_KIND
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.ingestion import SqlIngestionRepository
from my_pa.infrastructure.persistence.project_reports import SqlProjectReportsRepository
from my_pa.infrastructure.persistence.tables import projects
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

P: Final = "prn_prrepo0001aaaa"
OTHER: Final = "prn_prrepo0002bbbb"
WHEN: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)
RESTRICT_VIOLATION: Final = "23001"
UNIQUE_VIOLATION: Final = "23505"
CHECK_VIOLATION: Final = "23514"

SOURCE: Final = "isrc_prrepo0001"
SOURCE_2: Final = "isrc_prrepo0002"
PROJECT: Final = "prj_prrepo0001"
PROJECT_2: Final = "prj_prrepo0002"
SNAP: Final = "isnp_prrepo0001"
SNAP_2: Final = "isnp_prrepo0002"
SNAP_3: Final = "isnp_prrepo0003"
R1: Final = "prbnd_prrepo0001"
R2: Final = "prbnd_prrepo0002"
R3: Final = "prbnd_prrepo0003"
D1: Final = "prdrv_prrepo0001"
D2: Final = "prdrv_prrepo0002"
D3: Final = "prdrv_prrepo0003"
D_BUY: Final = "prdrv_prrepobuy1"
D_REC: Final = "prdrv_prreporec1"
REC: Final = "prrec_prrepo0001"


def _revision(revision_id: str, **overrides: object) -> ProjectReportBindingRevisionRecord:
    values: dict[str, object] = {
        "binding_revision_id": revision_id,
        "ingest_source_id": SOURCE,
        "project_id": PROJECT,
        "declared_project_number": "SYN-0001",
        "state": BindingState.ACTIVE,
        "currency": "USD",
        "recorded_at": WHEN,
        "change_set_sha256": "a" * 64,
        "reason_code": BindingReason.INITIAL,
    }
    values.update(overrides)
    return ProjectReportBindingRevisionRecord(**values)  # type: ignore[arg-type]


def _snapshot(snapshot_id: str, digest: str, rows: int) -> ProjectReportSnapshotRecord:
    return ProjectReportSnapshotRecord(
        snapshot_id=snapshot_id,
        ingest_source_id=SOURCE,
        file_sha256=digest,
        bom_present=True,
        header_raw_record='"Number",Subject,Amount',
        header_terminator="crlf",
        header_cells=("Number", "Subject", "Amount"),
        header_signature="e" * 64,
        signature_version="pulse_header_signature_v1",
        reader_version="pulse_csv_reader_v1",
        data_row_count=rows,
        embedded_line_break_count=1,
        reconstruction_sha256=digest,
    )


def _rows() -> tuple[ProjectReportRowRecord, ...]:
    return (
        ProjectReportRowRecord(1, "Group A,,", "crlf", ("Group A", "", ""), True),
        ProjectReportRowRecord(
            2, '7,"Line\r\nbreak",1.50', "crlf", ("7", "Line\r\nbreak", "1.50"), True
        ),
        ProjectReportRowRecord(3, "Grand Totals,,1.50", "none", ("Grand Totals", "", "1.50"), True),
    )


def _derivation(derivation_id: str, **overrides: object) -> ProjectReportDerivationRecord:
    values: dict[str, object] = {
        "derivation_id": derivation_id,
        "snapshot_id": SNAP,
        "ingest_source_id": SOURCE,
        "binding_revision_id": R1,
        "project_id": PROJECT,
        "state": DerivationState.CLASSIFIED,
        "identity_version": "project_report_identity_v1",
        "status_map_version": "status_map_v1",
        "role_counts": {"detail": 1, "group_header": 1, "grand_total": 1},
        "trigger": DerivationTrigger.INGEST,
        "derived_at": WHEN,
        "record_family": RecordFamily.RFIS,
        "family_view": FamilyView.OPEN_OUTSTANDING,
        "adapter_version": "pulse_adapter_v1",
        "completeness_class": CompletenessClass.POPULATED,
        "reconciliation": {"group_columns": {"match": 1}, "groups_checked": 1},
    }
    values.update(overrides)
    return ProjectReportDerivationRecord(**values)  # type: ignore[arg-type]


def _roles(derivation_id: str) -> tuple[ProjectReportRowRoleRecord, ...]:
    path = ((1, "Group A", 1),)
    return (
        ProjectReportRowRoleRecord(
            derivation_id, 1, SNAP, RowRole.GROUP_HEADER, path, group_level=1, group_key="Group A"
        ),
        ProjectReportRowRoleRecord(
            derivation_id, 2, SNAP, RowRole.DETAIL, path, parent_header_ordinal=1
        ),
        ProjectReportRowRoleRecord(derivation_id, 3, SNAP, RowRole.GRAND_TOTAL),
    )


def _line(derivation_id: str, record_id: str | None) -> ProjectReportLineRecord:
    return ProjectReportLineRecord(
        derivation_id=derivation_id,
        row_ordinal=2,
        project_id=PROJECT,
        record_family=RecordFamily.RFIS,
        family_view=FamilyView.OPEN_OUTSTANDING,
        line_kind=LineKind.RFI_ROW,
        identity_state=IdentityState.IDENTIFIED if record_id else IdentityState.IDENTITY_MISSING,
        observation_state=ObservationState.DEGRADED,
        record_id=record_id,
        identity_reason=None if record_id else RowReason.IDENTITY_MISSING,
        degraded_reasons=(RowReason.TYPE_ERROR,),
        status_raw="Open",
        status_class=StatusClass.OPEN,
        identifier_prefix="RFI",
        identifier_numeric_suffix=7,
        values=(
            ProjectReportLineValueRecord("rfi.amount", ValueKind.MONEY, "1.50", Decimal("1.5000")),
            ProjectReportLineValueRecord("rfi.closed", ValueKind.BOOLEAN, "Yes", True),
            ProjectReportLineValueRecord(
                "rfi.due_date", ValueKind.DATE, "1/2/2026", date(2026, 1, 2)
            ),
            ProjectReportLineValueRecord("rfi.number", ValueKind.IDENTIFIER, "7", "7"),
            ProjectReportLineValueRecord(
                "rfi.opened", ValueKind.DATE, "not a date", None, RowReason.TYPE_ERROR
            ),
            ProjectReportLineValueRecord(
                "rfi.subject", ValueKind.TEXT, "Line\r\nbreak", "Line\r\nbreak"
            ),
            ProjectReportLineValueRecord("rfi.variance", ValueKind.NUMBER, "", None),
        ),
    )


def _totals(derivation_id: str) -> tuple[ProjectReportStatedTotalRecord, ...]:
    return (
        ProjectReportStatedTotalRecord(
            derivation_id,
            1,
            2,
            RowRole.GROUP_HEADER,
            TotalScope.GROUP,
            "rfi.amount",
            "",
            Additivity.ADDITIVE,
            ReconciliationOutcome.MISMATCH,
            group_level=1,
            group_key="Group A",
            computed_value=Decimal("1.5000"),
        ),
        ProjectReportStatedTotalRecord(
            derivation_id,
            3,
            2,
            RowRole.GRAND_TOTAL,
            TotalScope.GRAND,
            "rfi.amount",
            "1.50",
            Additivity.ADDITIVE,
            ReconciliationOutcome.MATCH,
            value=Decimal("1.5000"),
            computed_value=Decimal("1.5000"),
        ),
    )


def _record(record_id: str, key: str = "rfi:7") -> ProjectReportRecordEntry:
    return ProjectReportRecordEntry(
        record_id=record_id,
        project_id=PROJECT,
        record_family=RecordFamily.RFIS,
        identity_key=key,
        identity_version="project_report_identity_v1",
        identity_basis=IdentityBasis.EXPORTED_NUMBER,
        created_by_derivation_id=D1,
    )


@pytest.fixture
def connection(migrated_engine: Engine) -> Iterator[Connection]:
    """One transaction, rolled back after the test."""
    with migrated_engine.connect() as opened:
        transaction = opened.begin()
        try:
            yield opened
        finally:
            transaction.rollback()


@pytest.fixture
def repository(connection: Connection) -> SqlProjectReportsRepository:
    """Two sources and two Projects of `P`, and two lifecycle snapshots of the first."""
    ingestion = SqlIngestionRepository(connection)
    for source in (SOURCE, SOURCE_2):
        ingestion.insert_source(
            P,
            IngestSourceRecord(
                ingest_source_id=source,
                consumer=IngestConsumer.PULSE_CSV_EXPORT,
                workspace_id="mcp",
                path_prefix=f"exports/{source[-4:]}/",
                file_pattern="*.csv",
                enabled=True,
                admitted_at=WHEN,
            ),
        )
    for snapshot_id, digest in ((SNAP, "a" * 64), (SNAP_2, "b" * 64), (SNAP_3, "c" * 64)):
        ingestion.insert_snapshot(
            P,
            IngestSnapshotRecord(
                snapshot_id=snapshot_id,
                ingest_source_id=SOURCE,
                file_sha256=digest,
                byte_count=10,
                observed_version_token=None,
                first_seen_at=WHEN,
            ),
        )
    for project in (PROJECT, PROJECT_2):
        connection.execute(
            insert(projects).values(
                project_id=project,
                principal_id=P,
                name="Synthetic project",
                opened_at=WHEN,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
    return SqlProjectReportsRepository(connection)


def _refusal(
    connection: Connection, call: Callable[[], object]
) -> ProjectReportsWriteRefusedError | None:
    """Run `call` under a savepoint; return its refusal (and undo the failure)."""
    savepoint = connection.begin_nested()
    try:
        call()
    except ProjectReportsWriteRefusedError as error:
        savepoint.rollback()
        return error
    savepoint.commit()
    return None


def _refused(connection: Connection, call: Callable[[], object]) -> str | None:
    """The SQLSTATE `call` is refused with, or `None`."""
    refusal = _refusal(connection, call)
    return None if refusal is None else refusal.sqlstate


def _bound(repository: SqlProjectReportsRepository) -> None:
    repository.insert_binding_revision(P, _revision(R1))
    repository.insert_binding(
        P, ProjectReportBindingRecord(SOURCE, R1, PROJECT, BindingState.ACTIVE)
    )


def _layer_a(repository: SqlProjectReportsRepository) -> None:
    repository.insert_snapshot(P, _snapshot(SNAP, "a" * 64, 3), _rows())


def _classified(repository: SqlProjectReportsRepository) -> None:
    """`D1` (roles only), then `D2` superseding it with roles, a line and totals."""
    _bound(repository)
    _layer_a(repository)
    repository.insert_derivation(P, _derivation(D1), row_roles=_roles(D1))
    record_id = repository.get_or_create_record(P, _record(REC))
    repository.insert_derivation(
        P,
        _derivation(D2, trigger=DerivationTrigger.REDERIVE_ADAPTER, supersedes_derivation_id=D1),
        row_roles=_roles(D2),
        lines=(_line(D2, record_id),),
        stated_totals=_totals(D2),
    )


# ---- bindings ---------------------------------------------------------------------


def test_a_binding_revision_and_its_declarations_round_trip(
    repository: SqlProjectReportsRepository,
) -> None:
    first = _revision(R1)
    second = _revision(
        R2,
        project_id=PROJECT_2,
        declared_project_number="SYN-0002",
        currency="CAD",
        recorded_at=LATER,
        reason_code=BindingReason.CORRECTION,
        supersedes_revision_id=R1,
    )
    repository.insert_binding_revision(P, first)
    repository.insert_binding_revision(P, second)
    assert repository.get_binding_revision(P, R1) == first
    assert repository.get_binding_revision(P, R2) == second
    assert repository.list_binding_revisions(P, SOURCE) == (first, second)
    assert repository.get_binding_revision(OTHER, R1) is None
    assert repository.list_binding_revisions(OTHER, SOURCE) == ()
    declarations = (
        ProjectReportFilterDeclarationRecord(R2, "open-rfis", "Open items only\nfor the job", WHEN),
        ProjectReportFilterDeclarationRecord(R2, "closed-rfis", "Closed items only", WHEN),
    )
    repository.insert_filter_declarations(P, declarations)
    assert repository.list_filter_declarations(P, R2) == (declarations[1], declarations[0])
    assert repository.list_filter_declarations(OTHER, R2) == ()


def test_the_binding_pointer_moves_forward_only(
    repository: SqlProjectReportsRepository, connection: Connection
) -> None:
    _bound(repository)
    pointer = ProjectReportBindingRecord(SOURCE, R1, PROJECT, BindingState.ACTIVE)
    assert repository.get_binding(P, SOURCE) == pointer
    assert repository.get_binding(OTHER, SOURCE) is None
    repository.insert_binding_revision(
        P,
        _revision(
            R2,
            state=BindingState.RETIRED,
            supersedes_revision_id=R1,
            reason_code=BindingReason.RETIRE,
        ),
    )
    retired = ProjectReportBindingRecord(SOURCE, R2, PROJECT, BindingState.RETIRED)
    repository.move_binding(P, retired)
    assert repository.get_binding(P, SOURCE) == retired
    assert repository.list_bindings(P) == (retired,)
    assert repository.list_bindings(P, active_only=True) == ()
    # Back to a superseded revision: the guard refuses, unabsorbed.
    assert _refused(connection, lambda: repository.move_binding(P, pointer)) == RESTRICT_VIOLATION
    # Another Principal's pointer does not exist.
    with pytest.raises(RepositoryFailureError):
        repository.move_binding(OTHER, retired)


def test_a_second_active_binding_for_one_project_is_refused(
    repository: SqlProjectReportsRepository, connection: Connection
) -> None:
    _bound(repository)
    repository.insert_binding_revision(P, _revision(R3, ingest_source_id=SOURCE_2))
    second = ProjectReportBindingRecord(SOURCE_2, R3, PROJECT, BindingState.ACTIVE)
    assert _refused(connection, lambda: repository.insert_binding(P, second)) == UNIQUE_VIOLATION


# ---- Layer A ----------------------------------------------------------------------


def test_a_snapshot_and_its_raw_rows_round_trip_byte_exact(
    repository: SqlProjectReportsRepository,
) -> None:
    _layer_a(repository)
    assert repository.get_snapshot(P, SNAP) == _snapshot(SNAP, "a" * 64, 3)
    assert repository.list_rows(P, SNAP) == _rows()
    assert repository.get_snapshot(OTHER, SNAP) is None
    assert repository.list_rows(OTHER, SNAP) == ()


def test_a_snapshot_of_another_digest_is_refused(
    repository: SqlProjectReportsRepository, connection: Connection
) -> None:
    wrong = _snapshot(SNAP, "b" * 64, 0)
    assert _refused(connection, lambda: repository.insert_snapshot(P, wrong, ())) == "23503"
    unreconstructed = replace(_snapshot(SNAP, "a" * 64, 0), reconstruction_sha256="c" * 64)
    assert (
        _refused(connection, lambda: repository.insert_snapshot(P, unreconstructed, ()))
        == CHECK_VIOLATION
    )


# ---- derivations ------------------------------------------------------------------


def test_a_classified_derivation_and_its_children_round_trip(
    repository: SqlProjectReportsRepository,
) -> None:
    _classified(repository)
    assert repository.get_derivation(P, D1) == _derivation(D1)
    assert repository.list_row_roles(P, D2) == _roles(D2)
    lines = repository.list_lines(P, D2)
    assert len(lines) == 1
    line = lines[0]
    expected = replace(
        _line(D2, REC), values=tuple(sorted(_line(D2, REC).values, key=lambda v: v.field_key))
    )
    assert line == expected
    by_key = {value.field_key: value.value for value in line.values}
    assert by_key["rfi.amount"] == Decimal("1.5000")
    assert by_key["rfi.closed"] is True
    assert by_key["rfi.due_date"] == date(2026, 1, 2)
    assert by_key["rfi.opened"] is None
    assert by_key["rfi.variance"] is None
    assert repository.list_stated_totals(P, D2) == _totals(D2)
    assert repository.list_lines(OTHER, D2) == ()
    assert repository.get_derivation(OTHER, D1) is None


def test_current_derivations_exclude_every_superseded_one(
    repository: SqlProjectReportsRepository,
) -> None:
    _classified(repository)
    assert repository.current_derivation(P, SNAP) == repository.get_derivation(P, D2)
    quarantined = _derivation(
        D3,
        state=DerivationState.QUARANTINED,
        quarantine_reason=QuarantineReason.UNKNOWN_HEADER_SIGNATURE,
        record_family=None,
        family_view=None,
        adapter_version=None,
        completeness_class=None,
        reconciliation=None,
        role_counts={"unclassified": 3},
        trigger=DerivationTrigger.REDERIVE_VERSION,
        supersedes_derivation_id=D2,
    )
    repository.insert_derivation(P, quarantined)
    assert repository.current_derivation(P, SNAP) == quarantined
    assert repository.list_current_derivations(P) == (quarantined,)
    assert repository.list_current_derivations(P, state=DerivationState.CLASSIFIED) == ()
    assert repository.list_current_derivations(P, ingest_source_id=SOURCE_2) == ()
    assert repository.list_current_derivations(OTHER) == ()
    # Superseded rows are kept, append-only, and still readable by id.
    assert repository.get_derivation(P, D1) is not None
    assert repository.list_row_roles(P, D3) == ()


def test_a_record_identity_is_get_or_create(repository: SqlProjectReportsRepository) -> None:
    _bound(repository)
    _layer_a(repository)
    repository.insert_derivation(P, _derivation(D1))
    first = repository.get_or_create_record(P, _record(REC))
    again = repository.get_or_create_record(P, _record("prrec_prrepo0009"))
    assert first == again == REC
    assert repository.get_record(P, REC) == _record(REC)
    assert repository.get_record(P, "prrec_prrepo0009") is None
    assert repository.get_record(OTHER, REC) is None
    other = repository.get_or_create_record(P, _record("prrec_prrepo0010", key="rfi:8"))
    assert other == "prrec_prrepo0010"


def _cross_check_sides(repository: SqlProjectReportsRepository) -> None:
    """`D_BUY` (buyout summary) and `D_REC` (reconciliation), each on its own snapshot."""
    for snapshot_id, digest in ((SNAP_2, "b" * 64), (SNAP_3, "c" * 64)):
        repository.insert_snapshot(P, _snapshot(snapshot_id, digest, 0), ())
    repository.insert_derivation(
        P,
        _derivation(
            D_BUY,
            snapshot_id=SNAP_2,
            record_family=RecordFamily.BUYOUT,
            family_view=FamilyView.BUYOUT_SUMMARY,
        ),
    )
    repository.insert_derivation(
        P,
        _derivation(
            D_REC,
            snapshot_id=SNAP_3,
            record_family=RecordFamily.CHANGE_ORDER_RECONCILIATION,
            family_view=FamilyView.RECONCILIATION,
        ),
    )


def test_a_cross_check_round_trips(repository: SqlProjectReportsRepository) -> None:
    _classified(repository)
    _cross_check_sides(repository)
    check = ProjectReportCrossCheckRecord(
        check_kind=CROSS_CHECK_KIND,
        left_derivation_id=D_BUY,
        right_derivation_id=D_REC,
        project_id=PROJECT,
        outcome=ReconciliationOutcome.MATCH,
        checked_at=WHEN,
        date_label="20261124",
        left_value=Decimal("12.3400"),
        right_value=Decimal("12.3400"),
    )
    repository.insert_cross_check(P, check)
    assert repository.list_cross_checks(P, PROJECT) == (check,)
    assert repository.list_cross_checks(OTHER, PROJECT) == ()


def test_a_cross_check_in_the_other_role_order_is_refused(
    repository: SqlProjectReportsRepository, connection: Connection
) -> None:
    """N1: `(A, B)` and `(B, A)` cannot both be recorded; the sides keep their roles."""
    _classified(repository)
    _cross_check_sides(repository)
    reversed_check = ProjectReportCrossCheckRecord(
        check_kind=CROSS_CHECK_KIND,
        left_derivation_id=D_REC,
        right_derivation_id=D_BUY,
        project_id=PROJECT,
        outcome=ReconciliationOutcome.NOT_CHECKED,
        checked_at=WHEN,
    )
    refusal = _refusal(connection, lambda: repository.insert_cross_check(P, reversed_check))
    assert refusal is not None
    assert (refusal.sqlstate, refusal.constraint) == (
        RESTRICT_VIOLATION,
        "project_report_cross_checks_keep_their_roles",
    )


def test_append_only_rows_refuse_a_second_write(
    repository: SqlProjectReportsRepository, connection: Connection
) -> None:
    _classified(repository)
    assert (
        _refused(connection, lambda: repository.insert_derivation(P, _derivation(D1)))
        == UNIQUE_VIOLATION
    )


# ---- refusals carry no cell text (S2) and the insert guards (B1, N2) ------------------

#: A distinctive synthetic cell, so any leak of the refused row is unmistakable.
_CANARY: Final = "SYNTHETIC-CANARY-7f3c1e"


def _chain(error: BaseException) -> list[BaseException]:
    """`error` and everything on its `__cause__`/`__context__` chain, cycle-safe."""
    seen: list[BaseException] = []
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop()
        if any(current is known for known in seen):
            continue
        seen.append(current)
        pending.extend(e for e in (current.__cause__, current.__context__) if e is not None)
    return seen


def test_a_refused_write_carries_no_cell_text(
    repository: SqlProjectReportsRepository, connection: Connection
) -> None:
    """S2: the server's "Failing row contains ..." and the bound parameters never leave."""
    canary_row = ProjectReportRowRecord(1, _CANARY, "lf", (_CANARY,), True)
    cases = (
        # A CHECK refusal: the server's DETAIL quotes the whole row.
        (
            SNAP_2,
            "b" * 64,
            (replace(canary_row, terminator="bogus"),),
            CHECK_VIOLATION,
            "a_report_row_terminator_is_known",
        ),
        # A duplicate key: the bound parameters carry the cell.
        (
            SNAP_3,
            "c" * 64,
            (canary_row, canary_row),
            UNIQUE_VIOLATION,
            "project_report_rows_pkey",
        ),
    )
    for snapshot_id, digest, rows, sqlstate, constraint in cases:
        head = _snapshot(snapshot_id, digest, len(rows))
        refusal = _refusal(connection, lambda h=head, r=rows: repository.insert_snapshot(P, h, r))
        assert refusal is not None
        assert (refusal.sqlstate, refusal.constraint) == (sqlstate, constraint)
        assert refusal.__cause__ is None
        assert refusal.__context__ is None
        for linked in _chain(refusal):
            assert _CANARY not in str(linked)
            assert _CANARY not in repr(linked)
            assert _CANARY not in repr(linked.args)


def test_a_supersedes_cycle_is_refused_through_the_repository(
    repository: SqlProjectReportsRepository, connection: Connection
) -> None:
    """B1: a revision or derivation may supersede only a row that already exists."""
    _bound(repository)
    _layer_a(repository)
    ahead = _revision(
        R2, supersedes_revision_id=R3, reason_code=BindingReason.CORRECTION, recorded_at=LATER
    )
    refusal = _refusal(connection, lambda: repository.insert_binding_revision(P, ahead))
    assert refusal is not None
    assert (refusal.sqlstate, refusal.constraint) == (
        RESTRICT_VIOLATION,
        "project_report_binding_revisions_supersede_an_existing_one",
    )
    repository.insert_derivation(P, _derivation(D1))
    early = _derivation(D2, trigger=DerivationTrigger.REDERIVE_ADAPTER, supersedes_derivation_id=D3)
    refusal = _refusal(connection, lambda: repository.insert_derivation(P, early))
    assert refusal is not None
    assert (refusal.sqlstate, refusal.constraint) == (
        RESTRICT_VIOLATION,
        "project_report_derivations_supersede_an_existing_one",
    )


def test_a_new_pointer_naming_a_superseded_revision_is_refused(
    repository: SqlProjectReportsRepository, connection: Connection
) -> None:
    """N2: only an unsuperseded revision can be named by a new pointer."""
    repository.insert_binding_revision(P, _revision(R1))
    repository.insert_binding_revision(
        P,
        _revision(
            R2,
            supersedes_revision_id=R1,
            reason_code=BindingReason.CORRECTION,
            recorded_at=LATER,
        ),
    )
    stale = ProjectReportBindingRecord(SOURCE, R1, PROJECT, BindingState.ACTIVE)
    refusal = _refusal(connection, lambda: repository.insert_binding(P, stale))
    assert refusal is not None
    assert (refusal.sqlstate, refusal.constraint) == (
        RESTRICT_VIOLATION,
        "project_report_bindings_name_an_unsuperseded_revision",
    )
    current = ProjectReportBindingRecord(SOURCE, R2, PROJECT, BindingState.ACTIVE)
    repository.insert_binding(P, current)
    assert repository.get_binding(P, SOURCE) == current


# ---- the lifecycle read and the unit of work -----------------------------------------


def test_the_paths_of_a_snapshot_list_in_first_seen_order(connection: Connection) -> None:
    repository_fixture = SqlIngestionRepository(connection)
    repository_fixture.insert_source(
        P,
        IngestSourceRecord(
            ingest_source_id=SOURCE,
            consumer=IngestConsumer.PULSE_CSV_EXPORT,
            workspace_id="mcp",
            path_prefix="exports/",
            file_pattern="*.csv",
            enabled=True,
            admitted_at=WHEN,
        ),
    )
    repository_fixture.insert_snapshot(
        P,
        IngestSnapshotRecord(
            snapshot_id=SNAP,
            ingest_source_id=SOURCE,
            file_sha256="a" * 64,
            byte_count=10,
            observed_version_token=None,
            first_seen_at=WHEN,
        ),
    )
    later = IngestSnapshotPathRecord(SNAP, SOURCE, "exports/20261124-a.csv", LATER)
    earlier = IngestSnapshotPathRecord(SNAP, SOURCE, "exports/20261125-z.csv", WHEN)
    repository_fixture.insert_snapshot_path(P, later)
    repository_fixture.insert_snapshot_path(P, earlier)
    assert repository_fixture.list_paths_of_snapshot(P, SNAP) == (earlier, later)
    assert repository_fixture.list_paths_of_snapshot(OTHER, SNAP) == ()


def test_the_unit_of_work_exposes_the_repository(migrated_engine: Engine) -> None:
    with SqlAlchemyUnitOfWork(migrated_engine, audit=SqlAlchemyAuditSink(migrated_engine)) as uow:
        assert isinstance(uow.project_reports, SqlProjectReportsRepository)
        assert uow.project_reports.list_bindings(P) == ()
