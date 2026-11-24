"""WP3P-F1 S4: the FAST project-report fake refuses what the database refuses.

Each case builds its parents through `ProjectReportsRepository` alone, then
makes one write the revision refuses, and names the refusal it expects: the
SQLSTATE and the constraint (or guard trigger) name. The same cases run
against the in-memory fake (`tests.conftest._ProjectReports`, FAST) and
against `SqlProjectReportsRepository` on a head-migrated clone (`database`),
so a guard the S4 and S5 services rely on cannot hold in one and not the
other. Every identifier and text here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, insert
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import (
    IngestConsumer,
    IngestSnapshotRecord,
    IngestSourceRecord,
    ProjectReportBindingRecord,
    ProjectReportBindingRevisionRecord,
    ProjectReportCrossCheckRecord,
    ProjectReportDerivationRecord,
    ProjectReportSnapshotRecord,
    ProjectReportsRepository,
    ProjectReportsWriteRefusedError,
)
from my_pa.domain.project_reports.model import (
    BindingReason,
    BindingState,
    CompletenessClass,
    DerivationState,
    DerivationTrigger,
    FamilyView,
    ReconciliationOutcome,
    RecordFamily,
)
from my_pa.domain.project_reports.reconciliation import CROSS_CHECK_KIND
from my_pa.infrastructure.persistence.ingestion import SqlIngestionRepository
from my_pa.infrastructure.persistence.project_reports import SqlProjectReportsRepository
from my_pa.infrastructure.persistence.tables import projects
from tests.conftest import World, _ProjectReports

P: Final = "prn_prparity0001aa"
WHEN: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)
SOURCE: Final = "isrc_prparity0001"
SOURCE_2: Final = "isrc_prparity0002"
PROJECT: Final = "prj_prparity0001"
PROJECT_2: Final = "prj_prparity0002"
#: Lifecycle snapshots of `SOURCE` and their digests.
SNAPSHOTS: Final = (
    ("isnp_prparity0001", "a" * 64),
    ("isnp_prparity0002", "b" * 64),
    ("isnp_prparity0003", "c" * 64),
)
SNAP, SNAP_2, SNAP_3 = (snapshot_id for snapshot_id, _digest in SNAPSHOTS)
R1, R2, R3 = (f"prbnd_prparity000{n}" for n in range(1, 4))
D1, D2, D3 = (f"prdrv_prparity000{n}" for n in range(1, 4))
MISSING_REVISION: Final = "prbnd_prparity0099"
MISSING_DERIVATION: Final = "prdrv_prparity0099"

RESTRICT, FOREIGN, UNIQUE, CHECK = "23001", "23503", "23505", "23514"


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


def _successor(
    revision_id: str, of: str, **overrides: object
) -> ProjectReportBindingRevisionRecord:
    return _revision(
        revision_id,
        supersedes_revision_id=of,
        reason_code=BindingReason.CORRECTION,
        recorded_at=LATER,
        **overrides,
    )


def _snapshot(snapshot_id: str, digest: str, **overrides: object) -> ProjectReportSnapshotRecord:
    values: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "ingest_source_id": SOURCE,
        "file_sha256": digest,
        "bom_present": False,
        "header_raw_record": "A,B",
        "header_terminator": "lf",
        "header_cells": ("A", "B"),
        "header_signature": "e" * 64,
        "signature_version": "pulse_header_signature_v1",
        "reader_version": "pulse_csv_reader_v1",
        "data_row_count": 0,
        "embedded_line_break_count": 0,
        "reconstruction_sha256": digest,
    }
    values.update(overrides)
    return ProjectReportSnapshotRecord(**values)  # type: ignore[arg-type]


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
        "role_counts": {"detail": 0},
        "trigger": DerivationTrigger.INGEST,
        "derived_at": WHEN,
        "record_family": RecordFamily.RFIS,
        "family_view": FamilyView.OPEN_OUTSTANDING,
        "adapter_version": "pulse_adapter_v1",
        "completeness_class": CompletenessClass.VALID_EMPTY,
        "reconciliation": {},
    }
    values.update(overrides)
    return ProjectReportDerivationRecord(**values)  # type: ignore[arg-type]


def _heads(repository: ProjectReportsRepository) -> None:
    """`R1` (the first revision of `SOURCE`) and every Layer A head."""
    repository.insert_binding_revision(P, _revision(R1))
    for snapshot_id, digest in SNAPSHOTS:
        repository.insert_snapshot(P, _snapshot(snapshot_id, digest), ())


@dataclass(frozen=True)
class _Case:
    name: str
    sqlstate: str
    constraint: str | None
    #: Builds the parents, then makes the one refused write.
    run: Callable[[ProjectReportsRepository], object]


def _second_first_revision(r: ProjectReportsRepository) -> None:
    r.insert_binding_revision(P, _revision(R1))
    r.insert_binding_revision(P, _revision(R2))


def _superseding_a_missing_revision(r: ProjectReportsRepository) -> None:
    r.insert_binding_revision(P, _revision(R1))
    r.insert_binding_revision(P, _successor(R2, MISSING_REVISION))


def _superseding_another_sources_revision(r: ProjectReportsRepository) -> None:
    r.insert_binding_revision(P, _revision(R1))
    r.insert_binding_revision(P, _revision(R2, ingest_source_id=SOURCE_2))
    r.insert_binding_revision(P, _successor(R3, R2))


def _superseding_a_revision_twice(r: ProjectReportsRepository) -> None:
    r.insert_binding_revision(P, _revision(R1))
    r.insert_binding_revision(P, _successor(R2, R1))
    r.insert_binding_revision(P, _successor(R3, R1))


def _a_pointer_on_a_superseded_revision(r: ProjectReportsRepository) -> None:
    r.insert_binding_revision(P, _revision(R1))
    r.insert_binding_revision(P, _successor(R2, R1))
    r.insert_binding(P, ProjectReportBindingRecord(SOURCE, R1, PROJECT, BindingState.ACTIVE))


def _a_pointer_moved_back(r: ProjectReportsRepository) -> None:
    r.insert_binding_revision(P, _revision(R1))
    r.insert_binding(P, ProjectReportBindingRecord(SOURCE, R1, PROJECT, BindingState.ACTIVE))
    r.insert_binding_revision(P, _successor(R2, R1))
    r.move_binding(P, ProjectReportBindingRecord(SOURCE, R2, PROJECT, BindingState.ACTIVE))
    r.move_binding(P, ProjectReportBindingRecord(SOURCE, R1, PROJECT, BindingState.ACTIVE))


def _a_second_active_pointer_for_a_project(r: ProjectReportsRepository) -> None:
    r.insert_binding_revision(P, _revision(R1))
    r.insert_binding_revision(P, _revision(R2, ingest_source_id=SOURCE_2))
    r.insert_binding(P, ProjectReportBindingRecord(SOURCE, R1, PROJECT, BindingState.ACTIVE))
    r.insert_binding(P, ProjectReportBindingRecord(SOURCE_2, R2, PROJECT, BindingState.ACTIVE))


def _second_first_derivation(r: ProjectReportsRepository) -> None:
    _heads(r)
    r.insert_derivation(P, _derivation(D1))
    r.insert_derivation(P, _derivation(D2))


def _a_successor_marked_as_an_ingest(r: ProjectReportsRepository) -> None:
    _heads(r)
    r.insert_derivation(P, _derivation(D1))
    r.insert_derivation(P, _derivation(D2, supersedes_derivation_id=D1))


def _a_first_derivation_marked_as_a_rederive(r: ProjectReportsRepository) -> None:
    _heads(r)
    r.insert_derivation(P, _derivation(D1, trigger=DerivationTrigger.REDERIVE_ADAPTER))


def _superseding_a_missing_derivation(r: ProjectReportsRepository) -> None:
    _heads(r)
    r.insert_derivation(P, _derivation(D1))
    r.insert_derivation(
        P,
        _derivation(
            D2,
            trigger=DerivationTrigger.REDERIVE_ADAPTER,
            supersedes_derivation_id=MISSING_DERIVATION,
        ),
    )


def _superseding_another_snapshots_derivation(r: ProjectReportsRepository) -> None:
    _heads(r)
    r.insert_derivation(P, _derivation(D1))
    r.insert_derivation(
        P,
        _derivation(
            D2,
            snapshot_id=SNAP_2,
            trigger=DerivationTrigger.REDERIVE_ADAPTER,
            supersedes_derivation_id=D1,
        ),
    )


def _a_derivation_under_another_projects_revision(r: ProjectReportsRepository) -> None:
    _heads(r)
    r.insert_derivation(P, _derivation(D1, project_id=PROJECT_2))


def _a_derivation_of_another_sources_snapshot(r: ProjectReportsRepository) -> None:
    _heads(r)
    r.insert_binding_revision(P, _revision(R2, ingest_source_id=SOURCE_2))
    r.insert_derivation(P, _derivation(D1, ingest_source_id=SOURCE_2, binding_revision_id=R2))


def _a_snapshot_that_does_not_reconstruct(r: ProjectReportsRepository) -> None:
    snapshot_id, digest = SNAPSHOTS[0]
    r.insert_snapshot(P, _snapshot(snapshot_id, digest, reconstruction_sha256="d" * 64), ())


def _a_cross_check_in_reversed_roles(r: ProjectReportsRepository) -> None:
    _heads(r)
    r.insert_derivation(
        P,
        _derivation(
            D1,
            snapshot_id=SNAP_2,
            record_family=RecordFamily.BUYOUT,
            family_view=FamilyView.BUYOUT_SUMMARY,
        ),
    )
    r.insert_derivation(
        P,
        _derivation(
            D2,
            snapshot_id=SNAP_3,
            record_family=RecordFamily.CHANGE_ORDER_RECONCILIATION,
            family_view=FamilyView.RECONCILIATION,
        ),
    )
    r.insert_cross_check(
        P,
        ProjectReportCrossCheckRecord(
            check_kind=CROSS_CHECK_KIND,
            left_derivation_id=D2,
            right_derivation_id=D1,
            project_id=PROJECT,
            outcome=ReconciliationOutcome.NOT_CHECKED,
            checked_at=WHEN,
        ),
    )


_REVISION_SUPERSEDES: Final = "project_report_binding_revisions_supersede_an_existing_one"
_DERIVATION_SUPERSEDES: Final = "project_report_derivations_supersede_an_existing_one"

CASES: Final = (
    _Case(
        "second_first_revision",
        UNIQUE,
        "one_first_binding_revision_per_source",
        _second_first_revision,
    ),
    _Case(
        "superseding_a_missing_revision",
        RESTRICT,
        _REVISION_SUPERSEDES,
        _superseding_a_missing_revision,
    ),
    _Case(
        "superseding_another_sources_revision",
        RESTRICT,
        _REVISION_SUPERSEDES,
        _superseding_another_sources_revision,
    ),
    _Case(
        "superseding_a_revision_twice",
        UNIQUE,
        "one_binding_revision_supersedes_each",
        _superseding_a_revision_twice,
    ),
    _Case(
        "a_pointer_on_a_superseded_revision",
        RESTRICT,
        "project_report_bindings_name_an_unsuperseded_revision",
        _a_pointer_on_a_superseded_revision,
    ),
    _Case("a_pointer_moved_back", RESTRICT, None, _a_pointer_moved_back),
    _Case(
        "a_second_active_pointer_for_a_project",
        UNIQUE,
        "one_active_project_report_binding_per_project",
        _a_second_active_pointer_for_a_project,
    ),
    _Case(
        "second_first_derivation",
        UNIQUE,
        "one_first_derivation_per_report_snapshot",
        _second_first_derivation,
    ),
    _Case(
        "a_successor_marked_as_an_ingest",
        CHECK,
        "only_a_first_derivation_is_an_ingest",
        _a_successor_marked_as_an_ingest,
    ),
    _Case(
        "a_first_derivation_marked_as_a_rederive",
        CHECK,
        "only_a_first_derivation_is_an_ingest",
        _a_first_derivation_marked_as_a_rederive,
    ),
    _Case(
        "superseding_a_missing_derivation",
        RESTRICT,
        _DERIVATION_SUPERSEDES,
        _superseding_a_missing_derivation,
    ),
    _Case(
        "superseding_another_snapshots_derivation",
        RESTRICT,
        _DERIVATION_SUPERSEDES,
        _superseding_another_snapshots_derivation,
    ),
    _Case(
        "a_derivation_under_another_projects_revision",
        FOREIGN,
        "a_derivation_names_a_binding_revision_of_its_source",
        _a_derivation_under_another_projects_revision,
    ),
    _Case(
        "a_derivation_of_another_sources_snapshot",
        FOREIGN,
        "a_derivation_names_a_report_snapshot_of_its_source",
        _a_derivation_of_another_sources_snapshot,
    ),
    _Case(
        "a_snapshot_that_does_not_reconstruct",
        CHECK,
        "a_report_snapshot_reconstructs_its_file",
        _a_snapshot_that_does_not_reconstruct,
    ),
    _Case(
        "a_cross_check_in_reversed_roles",
        RESTRICT,
        "project_report_cross_checks_keep_their_roles",
        _a_cross_check_in_reversed_roles,
    ),
)


def _refusal_of(case: _Case, repository: ProjectReportsRepository) -> tuple[str | None, ...]:
    with pytest.raises(ProjectReportsWriteRefusedError) as refused:
        case.run(repository)
    return (refused.value.sqlstate, refused.value.constraint)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_the_fake_refuses_each_case_as_the_database_does(case: _Case) -> None:
    assert _refusal_of(case, _ProjectReports(World())) == (case.sqlstate, case.constraint)


@pytest.fixture
def connection(migrated_engine: Engine) -> Iterator[Connection]:
    """The lifecycle parents of `P`, in one transaction rolled back after the test."""
    with migrated_engine.connect() as opened:
        transaction = opened.begin()
        try:
            ingestion = SqlIngestionRepository(opened)
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
            for snapshot_id, digest in SNAPSHOTS:
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
                opened.execute(
                    insert(projects).values(
                        project_id=project,
                        principal_id=P,
                        name="Synthetic project",
                        opened_at=WHEN,
                        created_at=WHEN,
                        updated_at=WHEN,
                    )
                )
            yield opened
        finally:
            transaction.rollback()


@pytest.mark.database
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_the_database_refuses_each_case_as_named(case: _Case, connection: Connection) -> None:
    savepoint = connection.begin_nested()
    try:
        refusal = _refusal_of(case, SqlProjectReportsRepository(connection))
    finally:
        savepoint.rollback()
    assert refusal == (case.sqlstate, case.constraint)


def test_every_case_name_is_unique() -> None:
    assert len({case.name for case in CASES}) == len(CASES)
