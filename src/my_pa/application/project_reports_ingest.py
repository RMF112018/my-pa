"""The project-report consumer's lifecycle handler (WP3P-S5; rulings D1, D3, D5, D11, D12, D17).

The project-reports lifecycle is a separate `IngestionLifecycle` instance whose
handler registry holds exactly one handler, `ProjectReportsHandler`, for
`pulse_csv_export`, composed in `bootstrap/project_reports.py` and nowhere
else. The communications lifecycle never holds it, so a project-report source
is admitted only by `bindings apply` (ruling D7).

**The reader is injected.** `ExportReader` is the port this module reads
exports through; the bootstrap wires it to the reader, registry and adapters of
`infrastructure/project_reports/pulse_csv.py` (application code never imports
infrastructure). It answers in this module's own types: `ExportImage` (the
Layer A image: the head fields and every raw row) and `DerivedExport` (one
derivation plan: roles, typed lines, stated totals, the project-number check).

`prepare` reads the bytes into an `ExportImage` -- or a rejection code
(`not_utf8`, `malformed_csv`, `invalid_header`, `nul_byte`) -- and derives a
*candidate* plan with no project number, for the dry-run counts. `apply`, in
the snapshot's transaction, in order (design section 3.8):

1. reads the source's binding pointer and revision; a source with no pointer,
   or a retired one, raises `ProjectReportsSourceUnboundError`
   (`source_unbound`), so the snapshot rolls back whole and the run counts it
   `snapshots_failed`: nothing unbound is written (ruling D12);
2. reads its own path rows, for the filename labels (`filename_labels` of the
   earliest-first-seen path: the date label pairs the cross-report check);
3. the project-number cross-check of ruling D11 runs inside the derivation,
   against the revision's declared project number: a mismatch quarantines;
4. inserts the Layer A head and every raw row;
5. re-reads the stored rows in ordinal order and hashes their reconstruction:
   a hash other than the lifecycle digest raises
   `ProjectReportsReconstructionError` (the database CHECK and the composite
   foreign key to the digest are the third proof);
6. derives **from the stored rows** -- the same path every later re-derivation
   takes (`write_derivation`), so a re-derivation never re-reads the file --
   and writes the derivation bare, its record identities, then its row roles,
   lines with their typed values, and stated totals; then the cross-report
   check against every current classified partner of the same Project and date
   label, whichever of the pair arrives second (the left side is always the
   buyout summary, the right the reconciliation);
7. reconciles the totals in memory and against the stored rows, raising
   `ProjectReportsTotalsError` on any difference (the `MeetingSyncTotalsError`
   precedent), so a short write rolls back rather than committing.

A quarantined derivation (unknown signature, malformed ratio, project-number
mismatch; ruling D3) keeps every Layer A row and writes no row role, line or
total; its role counts read `{"unclassified": n}`.

**Counts, closed keys only** (`RECORD_COUNT_KEYS`, all `records_*`, never
content): `records_rows_total`, `records_rows_<role>` and
`records_rows_unclassified`; `records_snapshot_classified`,
`records_snapshot_quarantined`, `records_snapshot_quarantined_<reason>`;
`records_lines_typed`, `records_lines_degraded`,
`records_lines_degraded_<reason>`; `records_stated_totals_<outcome>`;
`records_project_number_<outcome>` (the D11 check, when the view has one);
`records_cross_checks_<outcome>` (cross-report rows written);
`records_records_created`. Nothing here logs.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from my_pa.contracts.ports import (
    IngestApplied,
    IngestConsumer,
    IngestConsumerHandler,
    IngestPrepared,
    IngestSnapshotRecord,
    ProjectReportBindingRevisionRecord,
    ProjectReportCrossCheckRecord,
    ProjectReportDerivationRecord,
    ProjectReportLineRecord,
    ProjectReportLineValueRecord,
    ProjectReportRecordEntry,
    ProjectReportRowRecord,
    ProjectReportRowRoleRecord,
    ProjectReportSnapshotRecord,
    ProjectReportStatedTotalRecord,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.project_reports.identity import RecordIdentity, split_rfi_number
from my_pa.domain.project_reports.labels import FilenameLabels, filename_labels
from my_pa.domain.project_reports.model import (
    UNCLASSIFIED_COUNT_KEY,
    BindingState,
    CompletenessClass,
    DerivationState,
    DerivationTrigger,
    FamilyView,
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
)
from my_pa.domain.project_reports.reconciliation import (
    CROSS_CHECK_KIND,
    CrossReportCheck,
    ReconciliationSummary,
    StatedTotalCheck,
)
from my_pa.domain.project_reports.roles import ClassifiedRow
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "MAX_EXPORT_BYTES",
    "READER_VERSION",
    "RECORD_COUNT_KEYS",
    "DerivedExport",
    "DerivedLine",
    "ExportImage",
    "ExportReader",
    "ProjectReportsHandler",
    "ProjectReportsReconstructionError",
    "ProjectReportsSourceUnboundError",
    "ProjectReportsTotalsError",
    "ReadOutcome",
    "bound_revision",
    "reconstruction_sha256",
    "snapshot_labels",
    "stored_image",
    "write_derivation",
]

#: Ruling D17: the reader version and the largest export read.
READER_VERSION: Final = "pulse_csv_reader_v1"
MAX_EXPORT_BYTES: Final = 16 * 1024 * 1024

_BOM: Final = b"\xef\xbb\xbf"
_TERMINATOR_TEXT: Final = {"crlf": "\r\n", "lf": "\n", "cr": "\r", "none": ""}
_HEADER_ROLES: Final = frozenset({RowRole.GROUP_HEADER, RowRole.GROUPING_ONLY})
#: The cross-report pair (design section 3.6): left buyout summary, right reconciliation.
_PAIR: Final = (FamilyView.BUYOUT_SUMMARY, FamilyView.RECONCILIATION)
_RFI_NUMBER_FIELD: Final = "rfi.number"


def _record_count_keys() -> frozenset[str]:
    keys = {
        "records_rows_total",
        f"records_rows_{UNCLASSIFIED_COUNT_KEY}",
        "records_snapshot_classified",
        "records_snapshot_quarantined",
        "records_lines_typed",
        "records_lines_degraded",
        "records_records_created",
    }
    keys |= {f"records_rows_{role.value}" for role in RowRole}
    keys |= {f"records_snapshot_quarantined_{reason.value}" for reason in QuarantineReason}
    keys |= {f"records_lines_degraded_{reason.value}" for reason in RowReason}
    for outcome in ReconciliationOutcome:
        keys |= {
            f"records_stated_totals_{outcome.value}",
            f"records_project_number_{outcome.value}",
            f"records_cross_checks_{outcome.value}",
        }
    return frozenset(keys)


#: Every key a project-report handler count may carry (the closed vocabulary).
RECORD_COUNT_KEYS: Final = _record_count_keys()


class ProjectReportsSourceUnboundError(Exception):
    """The snapshot's source has no active binding (ruling D12): it rolls back whole."""

    code: Final = "source_unbound"

    def __init__(self) -> None:
        super().__init__(self.code)


class ProjectReportsReconstructionError(Exception):
    """The stored Layer A rows do not reconstruct the lifecycle digest; the snapshot rolls back."""


class ProjectReportsTotalsError(Exception):
    """A derivation's stored rows do not reconcile to its plan; the snapshot rolls back."""


# --- the reader port ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExportImage:
    """The Layer A image of one export: everything stored, nothing classified (ruling D1)."""

    file_sha256: str
    bom_present: bool
    header_raw_record: str
    header_terminator: str
    header_cells: tuple[str, ...]
    header_signature: str
    signature_version: str
    reader_version: str
    rows: tuple[ProjectReportRowRecord, ...]
    embedded_line_break_count: int


@dataclass(frozen=True, slots=True)
class ReadOutcome:
    """The reader's answer: exactly one of a rejection code and an image."""

    rejection_code: str | None
    image: ExportImage | None

    def __post_init__(self) -> None:
        if (self.rejection_code is None) == (self.image is None):
            raise ValueError("a read is rejected or imaged, not both")


@dataclass(frozen=True, slots=True)
class DerivedLine:
    """One detail row as a typed line (Layer B), before its record is resolved."""

    ordinal: int
    line_kind: LineKind
    observation_state: ObservationState
    degraded_reasons: tuple[RowReason, ...]
    identity: RecordIdentity
    identity_reason: RowReason | None
    status_raw: str | None
    status_class: StatusClass | None
    values: tuple[ProjectReportLineValueRecord, ...]


@dataclass(frozen=True, slots=True)
class DerivedExport:
    """One derivation plan; `plan` is the reader's own form, opaque here (cross-report)."""

    state: DerivationState
    quarantine_reason: QuarantineReason | None
    family: RecordFamily | None
    view: FamilyView | None
    adapter_version: str | None
    completeness: CompletenessClass | None
    role_counts: Mapping[str, int]
    rows: tuple[ClassifiedRow, ...]
    lines: tuple[DerivedLine, ...]
    stated_totals: tuple[StatedTotalCheck, ...]
    reconciliation: ReconciliationSummary | None
    project_number_check: ReconciliationOutcome | None
    plan: object = None


class ExportReader(ABC):
    """The reader, registry and adapters, injected from the bootstrap (module docstring)."""

    @property
    @abstractmethod
    def identity_version(self) -> str:
        """The version of the per-family identity rules every derivation records."""

    @property
    @abstractmethod
    def status_map_version(self) -> str:
        """The version of the status maps every derivation records."""

    @abstractmethod
    def read(self, data: bytes) -> ReadOutcome:
        """The Layer A image of one export's bytes, or its rejection code."""

    @abstractmethod
    def derive(self, image: ExportImage, *, project_number: str | None) -> DerivedExport:
        """The derivation of an image; the header signature alone chooses the adapter."""

    @abstractmethod
    def adapter_version(self, header_signature: str) -> str | None:
        """The registered adapter's version for a signature, or `None` when unregistered."""

    @abstractmethod
    def cross_report(
        self, buyout: DerivedExport, reconciliation: DerivedExport
    ) -> CrossReportCheck:
        """The buyout-versus-reconciliation check of two derivations of one Project."""


# --- Layer A helpers --------------------------------------------------------------------


def reconstruction_sha256(
    bom_present: bool,
    header_raw_record: str,
    header_terminator: str,
    rows: Sequence[ProjectReportRowRecord],
) -> str:
    """The SHA-256 of the bytes the stored records re-encode to (design section 3.5)."""
    body = header_raw_record + _TERMINATOR_TEXT[header_terminator]
    body += "".join(row.raw_record + _TERMINATOR_TEXT[row.terminator] for row in rows)
    return hashlib.sha256((_BOM if bom_present else b"") + body.encode("utf-8")).hexdigest()


def stored_image(
    head: ProjectReportSnapshotRecord, rows: Sequence[ProjectReportRowRecord]
) -> ExportImage:
    """The image of a stored snapshot: what every re-derivation derives from."""
    return ExportImage(
        file_sha256=head.file_sha256,
        bom_present=head.bom_present,
        header_raw_record=head.header_raw_record,
        header_terminator=head.header_terminator,
        header_cells=tuple(head.header_cells),
        header_signature=head.header_signature,
        signature_version=head.signature_version,
        reader_version=head.reader_version,
        rows=tuple(sorted(rows, key=lambda row: row.row_ordinal)),
        embedded_line_break_count=head.embedded_line_break_count,
    )


def _head(snapshot: IngestSnapshotRecord, image: ExportImage) -> ProjectReportSnapshotRecord:
    return ProjectReportSnapshotRecord(
        snapshot_id=snapshot.snapshot_id,
        ingest_source_id=snapshot.ingest_source_id,
        file_sha256=image.file_sha256,
        bom_present=image.bom_present,
        header_raw_record=image.header_raw_record,
        header_terminator=image.header_terminator,
        header_cells=image.header_cells,
        header_signature=image.header_signature,
        signature_version=image.signature_version,
        reader_version=image.reader_version,
        data_row_count=len(image.rows),
        embedded_line_break_count=image.embedded_line_break_count,
        reconstruction_sha256=reconstruction_sha256(
            image.bom_present, image.header_raw_record, image.header_terminator, image.rows
        ),
    )


def _read_stored(unit: UnitOfWork, principal_id: str, snapshot_id: str) -> ExportImage:
    """The stored image, verified to reconstruct its digest (step 5)."""
    repository = unit.project_reports
    head = repository.get_snapshot(principal_id, snapshot_id)
    if head is None:
        raise ProjectReportsReconstructionError("the snapshot has no Layer A head")
    rows = repository.list_rows(principal_id, snapshot_id)
    if [row.row_ordinal for row in rows] != list(range(1, len(rows) + 1)) or (
        len(rows) != head.data_row_count
    ):
        raise ProjectReportsReconstructionError("the stored rows are not the snapshot's rows")
    digest = reconstruction_sha256(
        head.bom_present, head.header_raw_record, head.header_terminator, rows
    )
    if digest != head.file_sha256 or digest != head.reconstruction_sha256:
        raise ProjectReportsReconstructionError("the stored rows do not reconstruct the file")
    return stored_image(head, rows)


# --- bindings and labels ----------------------------------------------------------------


def bound_revision(
    unit: UnitOfWork, principal_id: str, ingest_source_id: str
) -> ProjectReportBindingRevisionRecord:
    """The source's active binding revision, or `source_unbound` (ruling D12).

    The pointer's state is its revision's (a composite foreign key holds the
    two equal), so the pointer alone decides.
    """
    repository = unit.project_reports
    binding = repository.get_binding(principal_id, ingest_source_id)
    if binding is None or binding.state is not BindingState.ACTIVE:
        raise ProjectReportsSourceUnboundError
    revision = repository.get_binding_revision(principal_id, binding.binding_revision_id)
    if revision is None:
        raise ProjectReportsSourceUnboundError
    return revision


def snapshot_labels(unit: UnitOfWork, principal_id: str, snapshot_id: str) -> FilenameLabels:
    """The labels of a snapshot's earliest-first-seen path (ruling D4), or none."""
    paths = unit.ingestion.list_paths_of_snapshot(principal_id, snapshot_id)
    return filename_labels(paths[0].relative_path) if paths else FilenameLabels(None, None)


# --- the derivation writer ----------------------------------------------------------


def _summary_json(
    summary: ReconciliationSummary | None, project_number_check: ReconciliationOutcome | None
) -> dict[str, object]:
    if summary is None:
        raise ProjectReportsTotalsError("a classified derivation has its reconciliation summary")
    return {
        "column_groups": dict(sorted(summary.group_columns.items())),
        "groups_checked": summary.groups_checked,
        "groups_all_columns_match": summary.groups_all_columns_match,
        "grand": dict(sorted(summary.grand_columns.items())),
        "project_number_check": None
        if project_number_check is None
        else project_number_check.value,
    }


def _plan_counts(image: ExportImage, derived: DerivedExport) -> Counter[str]:
    """Counts a plan implies on its own (no record or cross-check is known yet)."""
    counts: Counter[str] = Counter()
    data_rows = len(image.rows)
    counts["records_rows_total"] += data_rows
    if sum(derived.role_counts.values()) != data_rows:
        raise ProjectReportsTotalsError("the role counts do not sum to the data rows")
    for role, count in derived.role_counts.items():
        counts[f"records_rows_{role}"] += count
    if derived.state is DerivationState.QUARANTINED:
        counts["records_snapshot_quarantined"] += 1
        if derived.quarantine_reason is not None:
            counts[f"records_snapshot_quarantined_{derived.quarantine_reason.value}"] += 1
    else:
        counts["records_snapshot_classified"] += 1
    for line in derived.lines:
        counts[f"records_lines_{line.observation_state.value}"] += 1
        counts.update(f"records_lines_degraded_{r.value}" for r in line.degraded_reasons)
    counts.update(f"records_stated_totals_{t.outcome.value}" for t in derived.stated_totals)
    if derived.project_number_check is not None:
        counts[f"records_project_number_{derived.project_number_check.value}"] += 1
    return counts


def _closed(counts: Counter[str]) -> dict[str, int]:
    for base in (
        "records_rows_total",
        "records_snapshot_classified",
        "records_snapshot_quarantined",
    ):
        counts.setdefault(base, 0)
    if set(counts) - RECORD_COUNT_KEYS:
        raise ProjectReportsTotalsError("a count key outside the closed vocabulary")
    return dict(sorted(counts.items()))


def _role_record(
    derivation_id: str, snapshot_id: str, row: ClassifiedRow
) -> ProjectReportRowRoleRecord:
    header = row.role in _HEADER_ROLES
    return ProjectReportRowRoleRecord(
        derivation_id=derivation_id,
        row_ordinal=row.ordinal,
        snapshot_id=snapshot_id,
        row_role=row.role,
        group_path=tuple((step.level, step.key, step.header_ordinal) for step in row.group_path),
        row_reason=row.reason if row.role is RowRole.MALFORMED else None,
        group_level=row.group_level if header else None,
        group_key=row.group_key if header else None,
        parent_header_ordinal=row.parent_header_ordinal,
    )


def _identifier(line: DerivedLine) -> tuple[str | None, int | None]:
    """The RFI number's prefix and numeric suffix (the RFI lookup), or neither."""
    for value in line.values:
        if value.field_key == _RFI_NUMBER_FIELD and value.raw_text != "":
            split = split_rfi_number(value.raw_text)
            if split is not None:
                return split.prefix, split.suffix
    return None, None


def _total_record(derivation_id: str, check: StatedTotalCheck) -> ProjectReportStatedTotalRecord:
    grand = check.scope is TotalScope.GRAND
    return ProjectReportStatedTotalRecord(
        derivation_id=derivation_id,
        row_ordinal=check.row_ordinal,
        column_index=check.column_index,
        row_role=RowRole.GRAND_TOTAL if grand else RowRole.GROUP_HEADER,
        scope=check.scope,
        field_key=check.field_key,
        raw_text=check.raw_text,
        additivity=check.additivity,
        outcome=check.outcome,
        group_level=None if grand else check.group_level,
        group_key=None if grand else check.group_key,
        value=check.value,
        computed_value=check.computed_value,
    )


def write_derivation(
    unit: UnitOfWork,
    principal_id: str,
    *,
    reader: ExportReader,
    snapshot_id: str,
    ingest_source_id: str,
    revision: ProjectReportBindingRevisionRecord,
    trigger: DerivationTrigger,
    supersedes_derivation_id: str | None,
    derived_at: datetime,
) -> tuple[str, dict[str, int]]:
    """Derive one stored snapshot and write the derivation (steps 5 to 7); its id and counts."""
    image = _read_stored(unit, principal_id, snapshot_id)
    derived = reader.derive(image, project_number=revision.declared_project_number)
    counts = _plan_counts(image, derived)
    repository = unit.project_reports
    derivation_id = issue_identifier(IdKind.PROJECT_REPORT_DERIVATION)
    project_id = revision.project_id
    classified = derived.state is DerivationState.CLASSIFIED
    if classified and (derived.family is None or derived.view is None):
        raise ProjectReportsTotalsError("a classified derivation names its adapter")
    repository.insert_derivation(
        principal_id,
        ProjectReportDerivationRecord(
            derivation_id=derivation_id,
            snapshot_id=snapshot_id,
            ingest_source_id=ingest_source_id,
            binding_revision_id=revision.binding_revision_id,
            project_id=project_id,
            state=derived.state,
            identity_version=reader.identity_version,
            status_map_version=reader.status_map_version,
            role_counts=dict(sorted(derived.role_counts.items())),
            trigger=trigger,
            derived_at=derived_at,
            quarantine_reason=derived.quarantine_reason,
            record_family=derived.family,
            family_view=derived.view,
            adapter_version=derived.adapter_version,
            completeness_class=derived.completeness if classified else None,
            reconciliation=_summary_json(derived.reconciliation, derived.project_number_check)
            if classified
            else None,
            supersedes_derivation_id=supersedes_derivation_id,
        ),
    )
    if classified:
        assert derived.family is not None and derived.view is not None  # noqa: S101 - above
        roles = [_role_record(derivation_id, snapshot_id, row) for row in derived.rows]
        lines: list[ProjectReportLineRecord] = []
        for line in derived.lines:
            record_id: str | None = None
            identity = line.identity
            if identity.state is IdentityState.IDENTIFIED:
                if identity.key is None or identity.basis is None:
                    raise ProjectReportsTotalsError("an identified line has its key and basis")
                proposed = issue_identifier(IdKind.PROJECT_REPORT_RECORD)
                record_id = repository.get_or_create_record(
                    principal_id,
                    ProjectReportRecordEntry(
                        record_id=proposed,
                        project_id=project_id,
                        record_family=derived.family,
                        identity_key=identity.key,
                        identity_version=reader.identity_version,
                        identity_basis=identity.basis,
                        created_by_derivation_id=derivation_id,
                    ),
                )
                if record_id == proposed:
                    counts["records_records_created"] += 1
            prefix, suffix = _identifier(line)
            lines.append(
                ProjectReportLineRecord(
                    derivation_id=derivation_id,
                    row_ordinal=line.ordinal,
                    project_id=project_id,
                    record_family=derived.family,
                    family_view=derived.view,
                    line_kind=line.line_kind,
                    identity_state=identity.state,
                    observation_state=line.observation_state,
                    record_id=record_id,
                    identity_reason=line.identity_reason,
                    degraded_reasons=line.degraded_reasons,
                    status_raw=line.status_raw,
                    status_class=line.status_class,
                    identifier_prefix=prefix,
                    identifier_numeric_suffix=suffix,
                    values=line.values,
                )
            )
        totals = [_total_record(derivation_id, check) for check in derived.stated_totals]
        repository.insert_derivation_rows(
            principal_id, derivation_id, row_roles=roles, lines=lines, stated_totals=totals
        )
        if derived.view in _PAIR:
            _cross_report(
                unit,
                principal_id,
                reader=reader,
                derivation_id=derivation_id,
                snapshot_id=snapshot_id,
                project_id=project_id,
                derived=derived,
                checked_at=derived_at,
                counts=counts,
            )
    _reconcile(unit, principal_id, derivation_id, image, derived)
    return derivation_id, _closed(counts)


def _cross_report(
    unit: UnitOfWork,
    principal_id: str,
    *,
    reader: ExportReader,
    derivation_id: str,
    snapshot_id: str,
    project_id: str,
    derived: DerivedExport,
    checked_at: datetime,
    counts: Counter[str],
) -> None:
    """Write the cross-report check against every current partner (order-independent).

    Only exports of one date label pair: an export with no date label pairs with
    nothing, so no check is written (the stored aggregate reads `not_checked`).
    """
    repository = unit.project_reports
    other = _PAIR[1] if derived.view is _PAIR[0] else _PAIR[0]
    date_label = snapshot_labels(unit, principal_id, snapshot_id).date_label
    if date_label is None:
        return
    existing = {
        (check.left_derivation_id, check.right_derivation_id)
        for check in repository.list_cross_checks(principal_id, project_id)
    }
    for partner in repository.list_current_derivations(
        principal_id, state=DerivationState.CLASSIFIED
    ):
        if (
            partner.derivation_id == derivation_id
            or partner.project_id != project_id
            or partner.family_view is not other
            or snapshot_labels(unit, principal_id, partner.snapshot_id).date_label != date_label
        ):
            continue
        partner_revision = repository.get_binding_revision(
            principal_id, partner.binding_revision_id
        )
        if partner_revision is None:
            raise ProjectReportsTotalsError("a derivation names its binding revision")
        partner_derived = reader.derive(
            _read_stored(unit, principal_id, partner.snapshot_id),
            project_number=partner_revision.declared_project_number,
        )
        if derived.view is _PAIR[0]:
            left, right = derivation_id, partner.derivation_id
            check = reader.cross_report(derived, partner_derived)
        else:
            left, right = partner.derivation_id, derivation_id
            check = reader.cross_report(partner_derived, derived)
        if (left, right) in existing:
            continue
        repository.insert_cross_check(
            principal_id,
            ProjectReportCrossCheckRecord(
                check_kind=CROSS_CHECK_KIND,
                left_derivation_id=left,
                right_derivation_id=right,
                project_id=project_id,
                outcome=check.outcome,
                checked_at=checked_at,
                date_label=date_label,
                left_value=check.left_value,
                right_value=check.right_value,
            ),
        )
        counts[f"records_cross_checks_{check.outcome.value}"] += 1


def _reconcile(
    unit: UnitOfWork,
    principal_id: str,
    derivation_id: str,
    image: ExportImage,
    derived: DerivedExport,
) -> None:
    """Step 7: the plan against itself and against the stored rows; raise on any difference."""
    repository = unit.project_reports
    data_rows = len(image.rows)
    stored = repository.get_derivation(principal_id, derivation_id)
    if stored is None:
        raise ProjectReportsTotalsError("the derivation is missing")
    head = repository.get_snapshot(principal_id, stored.snapshot_id)
    if head is None or head.data_row_count != data_rows:
        raise ProjectReportsTotalsError("the derivation's snapshot does not hold its rows")
    if sum(stored.role_counts.values()) != data_rows or dict(stored.role_counts) != dict(
        derived.role_counts
    ):
        raise ProjectReportsTotalsError("the stored role counts do not sum to the rows")
    roles = repository.list_row_roles(principal_id, derivation_id)
    lines = repository.list_lines(principal_id, derivation_id)
    totals = repository.list_stated_totals(principal_id, derivation_id)
    if derived.state is DerivationState.QUARANTINED:
        if roles or lines or totals or derived.rows or derived.lines or derived.stated_totals:
            raise ProjectReportsTotalsError("a quarantined derivation classifies nothing")
        if dict(stored.role_counts) != {UNCLASSIFIED_COUNT_KEY: data_rows}:
            raise ProjectReportsTotalsError(
                "a quarantined derivation counts every row unclassified"
            )
        return
    details = [row.ordinal for row in derived.rows if row.role is RowRole.DETAIL]
    stored_roles = Counter(role.row_role.value for role in roles)
    planned_roles = {key: value for key, value in derived.role_counts.items() if value}
    if (
        len(derived.rows) != data_rows
        or [row.ordinal for row in derived.rows] != list(range(1, data_rows + 1))
        or len(roles) != data_rows
        or dict(stored_roles) != planned_roles
        or [line.ordinal for line in derived.lines] != details
        or [line.row_ordinal for line in lines] != details
        or Counter(line.observation_state for line in lines)
        != Counter(line.observation_state for line in derived.lines)
        or sum(len(line.values) for line in lines)
        != sum(len(line.values) for line in derived.lines)
        or len(totals) != len(derived.stated_totals)
        or Counter(total.outcome for total in totals)
        != Counter(check.outcome for check in derived.stated_totals)
    ):
        raise ProjectReportsTotalsError("the stored rows do not reconcile to the derivation")


# --- the handler -------------------------------------------------------------------


class ProjectReportsHandler(IngestConsumerHandler):
    """The `pulse_csv_export` handler (module docstring)."""

    def __init__(
        self,
        *,
        reader: ExportReader,
        clock: Callable[[], datetime] = utc_now,
        max_bytes: int = MAX_EXPORT_BYTES,
    ) -> None:
        self._reader = reader
        self._clock = clock
        self._max_bytes = max_bytes

    @property
    def consumer(self) -> IngestConsumer:
        return IngestConsumer.PULSE_CSV_EXPORT

    @property
    def parser_version(self) -> str:
        return READER_VERSION

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def prepare(self, data: bytes) -> IngestPrepared:
        outcome = self._reader.read(data)
        if outcome.image is None:
            return IngestPrepared(
                rejection_code=outcome.rejection_code,
                window_start=None,
                coverage=None,
                record_counts={},
            )
        image = outcome.image
        # A candidate plan, without the binding's project number (dry-run counts).
        candidate = self._reader.derive(image, project_number=None)
        return IngestPrepared(
            rejection_code=None,
            window_start=None,
            coverage=None,
            record_counts=_closed(_plan_counts(image, candidate)),
            payload=image,
        )

    def apply(
        self,
        unit: UnitOfWork,
        principal_id: str,
        snapshot: IngestSnapshotRecord,
        prepared: IngestPrepared,
    ) -> IngestApplied:
        image = prepared.payload
        if not isinstance(image, ExportImage):
            raise TypeError("a project-report snapshot carries its Layer A image")
        if image.file_sha256 != snapshot.file_sha256:
            raise ProjectReportsReconstructionError("the image is not the snapshot's bytes")
        revision = bound_revision(unit, principal_id, snapshot.ingest_source_id)
        unit.project_reports.insert_snapshot(principal_id, _head(snapshot, image), image.rows)
        _, counts = write_derivation(
            unit,
            principal_id,
            reader=self._reader,
            snapshot_id=snapshot.snapshot_id,
            ingest_source_id=snapshot.ingest_source_id,
            revision=revision,
            trigger=DerivationTrigger.INGEST,
            supersedes_derivation_id=None,
            derived_at=self._clock(),
        )
        return IngestApplied(record_counts=counts)
