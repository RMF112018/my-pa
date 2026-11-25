"""A FAST project-reports scene over the synthetic fixtures (WP3P-S5).

The lifecycle rows are the in-memory `IngestWorld`; the Projects and the
project-report rows the general `World` (`ProjectReportsWorld`); the workspace
the in-memory `FakeStore`. Every fixture directory of
`tests/fixtures/project_reports/csv` is placed in its own folder with a
distinctive synthetic folder name and distinctive synthetic file names, so a
leak of a name into any output is detectable (the log-line no-content guard);
the bytes are the fixtures' own. Each folder is one admitted, enabled source
bound to its own synthetic Project.

Everything here is synthetic.
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Final

from my_pa.application.ingestion import IngestionLifecycle
from my_pa.application.project_reports_ingest import ExportReader, ProjectReportsHandler
from my_pa.application.project_reports_rederive import ProjectReportsRederiver
from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.project_reports import PROJECT_REPORTS_WORKSPACE_ID, PulseExportReader
from my_pa.contracts.ports import (
    IngestConsumer,
    ProjectReportBindingRecord,
    ProjectReportBindingRevisionRecord,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.project_reports.model import BindingReason, BindingState
from my_pa.domain.situation.situation import Project, ProjectState
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import World
from tests.unit.communications_ingest_fakes import FakeStore, IngestUnitOfWork, IngestWorld

FIXTURES: Final = Path(__file__).resolve().parents[1] / "fixtures" / "project_reports" / "csv"
WHEN: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
EXPORT_ROOT: Final = "Synthetic Export Root Zulu"
#: Every placed file's date label (so the cross-report pair shares one).
DATE_LABEL: Final = "20261120"
#: The fixture directories, each its own source (`sources/*` are two).
DIRECTORIES: Final = (
    "hostile",
    "rejected",
    "rfc",
    "signatures",
    "sources/source_a",
    "sources/source_b",
    "two_level",
    "variants",
)
#: The bound number of the financial fixtures (their codes carry it, ruling D11).
FINANCIAL_NUMBER: Final = "SYN-0001"


def folder_of(directory: str) -> str:
    """The distinctive synthetic folder a fixture directory is placed in."""
    token = directory.replace("/", "-").replace("_", "-")
    return f"{EXPORT_ROOT}/Qx {token.title()} Synthfolder"


def name_of(index: int) -> str:
    """The distinctive synthetic name of the `index`-th file of a folder (dated, slugged)."""
    return f"{DATE_LABEL}-qxsynthslug-{index:02d}.csv"


def project_number_of(directory: str) -> str:
    if directory == "signatures":
        return FINANCIAL_NUMBER
    return f"SYN-{9100 + DIRECTORIES.index(directory)}"


def project_of(directory: str) -> str:
    return f"prj_synpulse{DIRECTORIES.index(directory):04d}x"


def fixture_files(directory: str) -> list[Path]:
    return sorted((FIXTURES / directory).glob("*.csv"))


class _RollbackUnitOfWork(IngestUnitOfWork):
    """`IngestUnitOfWork` that also rolls the project-report rows back on an exception.

    As PostgreSQL does: a snapshot whose transaction raises leaves no row at all.
    """

    def __enter__(self) -> UnitOfWork:
        reports = self._world.project_reports
        self._reports_saved = {
            f.name: copy.copy(getattr(reports, f.name)) for f in dataclasses.fields(reports)
        }
        return super().__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        super().__exit__(exc_type, exc, traceback)
        if exc is not None:
            for name, saved in self._reports_saved.items():
                setattr(self._world.project_reports, name, saved)


class Clock:
    def __init__(self) -> None:
        self.now = WHEN

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@dataclass
class Scene:
    """The fakes, the lifecycle, the rederiver and the sources by fixture directory."""

    reader: ExportReader = field(default_factory=PulseExportReader)
    ingest: IngestWorld = field(default_factory=IngestWorld)
    world: World = field(default_factory=World)
    store: FakeStore = field(default_factory=FakeStore)
    clock: Clock = field(default_factory=Clock)
    sources: dict[str, str] = field(default_factory=dict)
    placed: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.principal = local_principal().principal_id
        self.lifecycle = self._lifecycle()

    def unit(self) -> UnitOfWork:
        return _RollbackUnitOfWork(self.ingest, meetings=self.world)

    def stores(self, workspace_id: str) -> FakeStore:
        if workspace_id != PROJECT_REPORTS_WORKSPACE_ID:
            raise LookupError(workspace_id)
        return self.store

    def _lifecycle(self) -> IngestionLifecycle:
        return IngestionLifecycle(
            unit_of_work=self.unit,
            stores=self.stores,
            handlers=[ProjectReportsHandler(reader=self.reader, clock=self.clock)],
            clock=self.clock,
        )

    def use_reader(self, reader: ExportReader) -> None:
        self.reader = reader
        self.lifecycle = self._lifecycle()

    def rederiver(self) -> ProjectReportsRederiver:
        return ProjectReportsRederiver(unit_of_work=self.unit, reader=self.reader, clock=self.clock)

    def place(self, directories: tuple[str, ...] = DIRECTORIES) -> None:
        """Put each directory's files in the store, admit its source and bind it."""
        for directory in directories:
            folder = folder_of(directory)
            names = []
            for index, path in enumerate(fixture_files(directory)):
                name = f"{folder}/{name_of(index)}"
                self.store.put(name, path.read_bytes())
                names.append(name)
            self.placed[directory] = names
            self.bind(directory)

    def bind(self, directory: str) -> None:
        project_id = project_of(directory)
        self.world.projects.append(
            Project(
                project_id=project_id,
                principal_id=self.principal,
                name="Synthetic project",
                state=ProjectState.ACTIVE,
                opened_at=WHEN,
                created_at=WHEN,
                updated_at=WHEN,
                project_number=project_number_of(directory),
            )
        )
        source = self.lifecycle.admit(
            self.principal,
            consumer=IngestConsumer.PULSE_CSV_EXPORT,
            workspace_id=PROJECT_REPORTS_WORKSPACE_ID,
            path_prefix=folder_of(directory) + "/",
            file_pattern="*.csv",
        )
        self.sources[directory] = source.ingest_source_id
        revision = ProjectReportBindingRevisionRecord(
            binding_revision_id=issue_identifier(IdKind.PROJECT_REPORT_BINDING_REVISION),
            ingest_source_id=source.ingest_source_id,
            project_id=project_id,
            declared_project_number=project_number_of(directory),
            state=BindingState.ACTIVE,
            currency="USD",
            recorded_at=self.clock(),
            change_set_sha256="0" * 64,
            reason_code=BindingReason.INITIAL,
        )
        with self.unit() as unit:
            unit.project_reports.insert_binding_revision(self.principal, revision)
            unit.project_reports.insert_binding(
                self.principal,
                ProjectReportBindingRecord(
                    ingest_source_id=source.ingest_source_id,
                    binding_revision_id=revision.binding_revision_id,
                    project_id=project_id,
                    state=BindingState.ACTIVE,
                ),
            )

    def rebind(self, directory: str, *, state: BindingState, number: str | None = None) -> str:
        """Append a superseding revision (a correction or a retire) and move the pointer."""
        source_id = self.sources[directory]
        with self.unit() as unit:
            repository = unit.project_reports
            binding = repository.get_binding(self.principal, source_id)
            assert binding is not None
            prior = repository.get_binding_revision(self.principal, binding.binding_revision_id)
            assert prior is not None
            revision = ProjectReportBindingRevisionRecord(
                binding_revision_id=issue_identifier(IdKind.PROJECT_REPORT_BINDING_REVISION),
                ingest_source_id=source_id,
                project_id=prior.project_id,
                declared_project_number=number or prior.declared_project_number,
                state=state,
                currency="USD",
                recorded_at=self.clock(),
                change_set_sha256="1" * 64,
                reason_code=BindingReason.RETIRE
                if state is BindingState.RETIRED
                else BindingReason.CORRECTION,
                supersedes_revision_id=prior.binding_revision_id,
            )
            repository.insert_binding_revision(self.principal, revision)
            repository.move_binding(
                self.principal,
                ProjectReportBindingRecord(
                    ingest_source_id=source_id,
                    binding_revision_id=revision.binding_revision_id,
                    project_id=prior.project_id,
                    state=state,
                ),
            )
        return revision.binding_revision_id

    def backfill_all(self) -> dict[str, Mapping[str, int]]:
        return {
            directory: self.lifecycle.backfill(self.principal, source).counts
            for directory, source in self.sources.items()
        }

    def project_numbers(self) -> dict[Path, str]:
        """The file-level aggregate's `--project-number` bindings, as the scene binds them."""
        return {FIXTURES / d: project_number_of(d) for d in self.sources}
