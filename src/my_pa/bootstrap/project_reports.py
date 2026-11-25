"""Composition of the project-reports consumer (WP3P; rulings D5, D6, D7).

The one place the project-reports lifecycle and its bindings service are
built, so the operator CLI (`apps/cli/project_reports.py`) and the cycles-plane
step (slice S5) cannot compose them differently:

* **A separate lifecycle instance (ruling D5).** `project_reports_lifecycle()`
  is an `IngestionLifecycle` whose handler registry holds only the
  `pulse_csv_export` handler (`application.project_reports_ingest`, its
  reader `PulseExportReader` below). The communications lifecycle
  (`bootstrap.communications_ingest`) never holds it, so the generic `admit`
  refuses the consumer and a project-report source is admitted only by
  `bindings apply`.
* **Its own lock.** `PROJECT_REPORTS_POLL_LOCK_KEY`, taken without waiting
  (`single_flight`); the bindings apply holds it for its one transaction.
* **No audit rows (ruling D6).** The unit of work's audit sink refuses, as the
  communications ingestion's does: the append-only binding revisions are the
  audit, so an attempt to audit is a defect that fails loudly. It is restated
  here rather than imported, because no project-reports module imports a
  communications one (`tests/architecture/test_project_reports_scope.py`).
* **The workspace stores come from settings, once.** `MY_PA_FILES_WORKSPACES`
  composed by `bootstrap.gateway.files_workspace_stores`, so a `read_only`
  workspace is refused unless it is mounted read-only. The bindings service
  calls only `stat` and `list_directory` on them. Composition is lazy, or
  `eager` for the long-lived cycles plane (a misconfigured root refuses at
  start).
* **The reader is injected (WP3P-S5).** `PulseExportReader` adapts
  `infrastructure.project_reports.pulse_csv` (the reader, the signature
  registry and the 15 adapters) to the application's `ExportReader` port. Its
  registry is a parameter, so a test registers an adapter for a quarantined
  signature and watches the re-derivation pick it up.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Final

from sqlalchemy import Engine

from my_pa.application.ingestion import IngestionLifecycle, StabilityMemory
from my_pa.application.project_reports_bindings import ProjectReportBindings
from my_pa.application.project_reports_ingest import (
    DerivedExport,
    DerivedLine,
    ExportImage,
    ExportReader,
    ProjectReportsHandler,
    ReadOutcome,
)
from my_pa.application.project_reports_rederive import ProjectReportsRederiver
from my_pa.bootstrap.gateway import files_workspace_stores
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.ports import (
    AuditSink,
    FileWorkspaceStore,
    ProjectReportLineValueRecord,
    ProjectReportRowRecord,
    UnitOfWork,
)
from my_pa.domain.audit.events import AuditEvent
from my_pa.domain.common.time import utc_now
from my_pa.domain.project_reports.model import IDENTITY_VERSION
from my_pa.domain.project_reports.reconciliation import CrossReportCheck
from my_pa.domain.project_reports.signature import SIGNATURE_VERSION
from my_pa.infrastructure.jobs.cycle_scheduler import PROJECT_REPORTS_POLL_LOCK_KEY, single_flight
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.project_reports import pulse_csv

__all__ = [
    "PROJECT_REPORTS_WORKSPACE_ID",
    "PulseExportReader",
    "bindings_service",
    "poll_lock",
    "project_reports_handler",
    "project_reports_lifecycle",
    "project_reports_unit_of_work",
    "project_reports_workspace_stores",
    "rederiver",
]

_TERMINATOR_TEXT: Final = {"crlf": "\r\n", "lf": "\n", "cr": "\r", "none": ""}

#: The one file workspace the PULSE exports live in (design section 3.1).
PROJECT_REPORTS_WORKSPACE_ID: Final = "mcp"


class _ProjectReportsWriteNoAudit(AuditSink):
    """The audit sink of a project-reports transaction: it refuses (module docstring)."""

    def record(self, event: AuditEvent) -> None:
        raise RuntimeError("a project-reports transaction writes no audit event")


def project_reports_unit_of_work(engine: Engine) -> Callable[[], UnitOfWork]:
    """One plain transaction per call, with the refusing audit sink."""
    audit = _ProjectReportsWriteNoAudit()
    return lambda: SqlAlchemyUnitOfWork(engine, audit=audit)


def project_reports_workspace_stores(
    settings: Settings, engine: Engine, *, eager: bool = False
) -> Callable[[str], FileWorkspaceStore]:
    """`workspace_id -> store`, composed from settings on first use (or at once, `eager`).

    An unknown workspace id is a `LookupError`; a misconfigured root raises the
    store's `FileWorkspaceRootError` at composition, which callers report as a
    code.
    """
    composed: dict[str, FileWorkspaceStore] | None = None
    if eager:
        composed = files_workspace_stores(settings, engine)

    def store(workspace_id: str) -> FileWorkspaceStore:
        nonlocal composed
        if composed is None:
            composed = files_workspace_stores(settings, engine)
        return composed[workspace_id]

    return store


class PulseExportReader(ExportReader):
    """The application's `ExportReader` over `infrastructure.project_reports.pulse_csv`."""

    def __init__(
        self, registry: Mapping[str, pulse_csv.FamilyAdapter] = pulse_csv.REGISTRY
    ) -> None:
        self._registry = registry

    @property
    def identity_version(self) -> str:
        return IDENTITY_VERSION

    @property
    def status_map_version(self) -> str:
        return pulse_csv.STATUS_MAP_VERSION

    def read(self, data: bytes) -> ReadOutcome:
        try:
            plan = pulse_csv.prepare_export(data)
        except pulse_csv.ExportRejectedError as rejected:
            # The record number and byte offset stay here (ruling D16): code only.
            return ReadOutcome(rejection_code=rejected.code.value, image=None)
        width = len(plan.header.cells)
        return ReadOutcome(
            rejection_code=None,
            image=ExportImage(
                file_sha256=plan.file_sha256,
                bom_present=plan.bom_present,
                header_raw_record=plan.header.raw_record,
                header_terminator=plan.header.terminator.value,
                header_cells=plan.header.cells,
                header_signature=plan.signature,
                signature_version=SIGNATURE_VERSION,
                reader_version=plan.reader_version,
                rows=tuple(
                    ProjectReportRowRecord(
                        row_ordinal=row.ordinal,
                        raw_record=row.raw_record,
                        terminator=row.terminator.value,
                        cells=row.cells,
                        width_matches=len(row.cells) == width,
                    )
                    for row in plan.rows
                ),
                embedded_line_break_count=sum(r.embedded_line_breaks for r in plan.records),
            ),
        )

    @staticmethod
    def _layer_a(image: ExportImage) -> pulse_csv.LayerAPlan:
        """The reader's plan rebuilt from an image (stored rows are never re-parsed)."""
        offset = 3 if image.bom_present else 0
        records: list[pulse_csv.RawRecord] = []
        entries = [
            (0, image.header_raw_record, image.header_terminator, image.header_cells),
            *((r.row_ordinal, r.raw_record, r.terminator, r.cells) for r in image.rows),
        ]
        for ordinal, raw, terminator, cells in entries:
            crlf = raw.count("\r\n")
            kind = pulse_csv.Terminator(terminator)
            records.append(
                pulse_csv.RawRecord(
                    ordinal,
                    raw,
                    kind,
                    tuple(cells),
                    offset,
                    crlf,
                    raw.count("\n") - crlf,
                    raw.count("\r") - crlf,
                )
            )
            offset += len((raw + _TERMINATOR_TEXT[terminator]).encode("utf-8"))
        return pulse_csv.LayerAPlan(
            reader_version=image.reader_version,
            file_sha256=image.file_sha256,
            byte_count=offset,
            bom_present=image.bom_present,
            header=records[0],
            rows=tuple(records[1:]),
            signature=image.header_signature,
        )

    def derive(self, image: ExportImage, *, project_number: str | None) -> DerivedExport:
        plan = pulse_csv.derive(
            self._layer_a(image), project_number=project_number, registry=self._registry
        )
        adapter = plan.adapter
        return DerivedExport(
            state=plan.state,
            quarantine_reason=plan.quarantine_reason,
            family=None if adapter is None else adapter.family,
            view=None if adapter is None else adapter.view,
            adapter_version=None if adapter is None else adapter.adapter_version,
            completeness=plan.completeness,
            role_counts=dict(plan.role_counts),
            rows=plan.rows,
            lines=tuple(
                DerivedLine(
                    ordinal=line.ordinal,
                    line_kind=line.line_kind,
                    observation_state=line.state,
                    degraded_reasons=line.reasons,
                    identity=line.identity,
                    identity_reason=line.identity_reason,
                    status_raw=line.status_raw,
                    status_class=line.status_class,
                    values=tuple(
                        ProjectReportLineValueRecord(
                            field_key=value.field_key,
                            value_kind=value.value_kind,
                            raw_text=value.raw_text,
                            value=value.value,
                            value_reason=value.reason,
                        )
                        for value in line.values
                    ),
                )
                for line in plan.lines
            ),
            stated_totals=plan.stated_totals,
            reconciliation=plan.reconciliation,
            project_number_check=plan.cross_check,
            plan=plan,
        )

    def adapter_version(self, header_signature: str) -> str | None:
        adapter = self._registry.get(header_signature)
        return None if adapter is None else adapter.adapter_version

    def cross_report(
        self, buyout: DerivedExport, reconciliation: DerivedExport
    ) -> CrossReportCheck:
        left, right = buyout.plan, reconciliation.plan
        if not isinstance(left, pulse_csv.DerivationPlan) or not isinstance(
            right, pulse_csv.DerivationPlan
        ):
            raise TypeError("a cross-report pairs two of this reader's derivations")
        return pulse_csv.pair_cross_report(left, right)


def project_reports_handler(
    *,
    clock: Callable[[], datetime] = utc_now,
    reader: ExportReader | None = None,
) -> ProjectReportsHandler:
    """The `pulse_csv_export` handler with the export reader wired in."""
    return ProjectReportsHandler(
        reader=PulseExportReader() if reader is None else reader,
        clock=clock,
        max_bytes=pulse_csv.MAX_EXPORT_BYTES,
    )


def project_reports_lifecycle(
    settings: Settings,
    engine: Engine,
    *,
    clock: Callable[[], datetime] = utc_now,
    stability: StabilityMemory | None = None,
    reader: ExportReader | None = None,
    eager: bool = False,
) -> IngestionLifecycle:
    """The project-reports lifecycle: only the `pulse_csv_export` handler (ruling D5)."""
    return IngestionLifecycle(
        unit_of_work=project_reports_unit_of_work(engine),
        stores=project_reports_workspace_stores(settings, engine, eager=eager),
        handlers=[project_reports_handler(clock=clock, reader=reader)],
        clock=clock,
        stability=stability,
    )


def rederiver(
    engine: Engine,
    *,
    clock: Callable[[], datetime] = utc_now,
    reader: ExportReader | None = None,
) -> ProjectReportsRederiver:
    """The bounded re-derivation sweep over the project-reports transactions."""
    return ProjectReportsRederiver(
        unit_of_work=project_reports_unit_of_work(engine),
        reader=PulseExportReader() if reader is None else reader,
        clock=clock,
    )


def poll_lock(engine: Engine) -> Callable[[], AbstractContextManager[bool]]:
    """The project-reports poll lock, taken without waiting; yields whether it is held."""
    return lambda: single_flight(engine, key=PROJECT_REPORTS_POLL_LOCK_KEY)


def bindings_service(
    settings: Settings, engine: Engine, *, clock: Callable[[], datetime] = utc_now
) -> ProjectReportBindings:
    """`bindings check` and `bindings apply` over the project-reports lifecycle."""
    stores = project_reports_workspace_stores(settings, engine)
    return ProjectReportBindings(
        unit_of_work=project_reports_unit_of_work(engine),
        lifecycle=project_reports_lifecycle(settings, engine, clock=clock),
        stores=stores,
        workspace_id=PROJECT_REPORTS_WORKSPACE_ID,
        lock=poll_lock(engine),
        clock=clock,
    )
