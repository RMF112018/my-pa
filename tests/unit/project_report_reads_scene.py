"""One synthetic project-report world for the WP4P read tests, FAST or on PostgreSQL.

`ReadsScene` drives the real WP3P path (the lifecycle, the project-reports
handler, the re-derivation sweep) over an in-memory file store, against a
unit of work it is given: the FAST fakes (`fast_scene`) or a head-migrated
database (`database_scene`, the DB tier only). `build_world` places the same
files in the same order under the same clock, so a read answers the same in
both (the fake's parity test compares them).

Every file is generated from the adapters' own headers (no header string is
written here) and every value is synthetic: synthetic project numbers, RFI
numbers, vendors, texts and dates. The two-level observation export is the
committed synthetic fixture.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import Engine, insert

from my_pa.application.ingestion import IngestionLifecycle
from my_pa.application.project_reports_ingest import ProjectReportsHandler
from my_pa.application.project_reports_rederive import ProjectReportsRederiver
from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.project_reports import (
    PROJECT_REPORTS_WORKSPACE_ID,
    PulseExportReader,
    project_reports_unit_of_work,
)
from my_pa.contracts.ports import (
    IngestConsumer,
    ProjectReportBindingRecord,
    ProjectReportBindingRevisionRecord,
    ProjectReportFilterDeclarationRecord,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.project_reports.model import (
    BindingReason,
    BindingState,
    FamilyView,
    ValueKind,
)
from my_pa.domain.situation.situation import Project, ProjectState
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import projects
from my_pa.infrastructure.project_reports import pulse_csv
from tests.conftest import World
from tests.unit.communications_ingest_fakes import FakeStore, IngestWorld
from tests.unit.project_reports_scene import FIXTURES, _RollbackUnitOfWork

WHEN: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
ROOT: Final = "Synthetic Reads Root Zulu"

#: The Projects of the world: `(key, project_id, project number)`.
RFI_PROJECT: Final = ("rfis", "prj_synreads0001x", "SYN-7101")
OBS_PROJECT: Final = ("observations", "prj_synreads0002x", "SYN-7102")
NOTE_PROJECT: Final = ("notes", "prj_synreads0003x", "SYN-7103")

#: The RFI series `qxrfis`: the later label is first seen first (ruling D10).
RFI_LATER: Final = "20261120-qxrfis.csv"
RFI_EARLIER: Final = "20261110-qxrfis.csv"
#: The RFI series `qxrfiq`: a classified version, then a quarantined latest one.
QUARANTINE_FIRST: Final = "20261101-qxrfiq.csv"
QUARANTINE_LATEST: Final = "20261115-qxrfiq.csv"
OBSERVATIONS: Final = "20261120-qxobs.csv"
UNKNOWN: Final = "20261120-qxunknown.csv"
#: The declaration of the `qxrfis` filter, after the later-label version was first seen.
DECLARED_SLUG: Final = "qxrfis"


def adapter(view: FamilyView) -> pulse_csv.FamilyAdapter:
    return next(a for a in pulse_csv.REGISTRY.values() if a.view is view)


def _cell(text: str) -> str:
    if any(ch in text for ch in ',"\r\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def csv_bytes(header: Sequence[str], rows: Sequence[Sequence[str]]) -> bytes:
    lines = [",".join(_cell(c) for c in header)] + [",".join(_cell(c) for c in r) for r in rows]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def rfi_export(rows: Sequence[Sequence[str]]) -> bytes:
    """An open-outstanding RFI export: number, subject, ball in court, priority, 2 dates, days."""
    return csv_bytes(adapter(FamilyView.OPEN_OUTSTANDING).header, rows)


#: The later-label RFI version: exact matching, text boundaries, inclusive dates.
RFI_ROWS_LATER: Final = (
    ("GMP-174", "Synthetic alpha", "Synthetic Person", "High", "11/1/2026", "11/8/2026", "3"),
    ("CD 50%-174", "Synthetic bravo", "", "Low", "11/5/2026", "11/9/2026", "1"),
    ("174", "Synthetic charlie", "", "", "11/6/2026", "", ""),
    ("1740", "Synthetic delta", "", "", "11/10/2026", "", ""),
    ("17", "Synthetic echo", "", "", "10/31/2026", "", ""),
    ("GMP-175", "Kilo", "Kilo", "", "11/2/2026", "", ""),
    ("GMP-176", "Synthetic foxtrot", "", "", "11/3/2026", "", ""),
)
RFI_ROWS_EARLIER: Final = (
    ("GMP-174", "Synthetic alpha", "", "High", "11/1/2026", "11/8/2026", "3"),
    ("GMP-170", "Synthetic golf", "", "", "10/20/2026", "", ""),
)
QUARANTINE_ROWS: Final = (("GMP-201", "Synthetic hotel", "", "", "11/1/2026", "", ""),)


def quarantined_export() -> bytes:
    """The same header, with one short row in two: over 1 % malformed, so quarantined."""
    good = rfi_export(QUARANTINE_ROWS)
    return good + b"GMP-202,Synthetic india\r\n"


def unknown_adapter_registry() -> dict[str, pulse_csv.FamilyAdapter]:
    """The registry plus a test adapter for the committed unknown-family fixture."""
    data = (FIXTURES / "variants" / "unknown_family.csv").read_bytes()
    header = pulse_csv.prepare_export(data).header.cells
    notes = adapter(FamilyView.NOTES)
    fields = tuple(
        pulse_csv.FieldSpec(index, cell, f"note.synthetic_{index}", ValueKind.TEXT)
        for index, cell in enumerate(header)
    )
    registered = dataclasses.replace(notes, fields=fields)
    return {**pulse_csv.REGISTRY, registered.signature: registered}


class Clock:
    def __init__(self) -> None:
        self.now = WHEN

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@dataclass
class ReadsScene:
    unit: Callable[[], UnitOfWork]
    add_project: Callable[[str, str], None]
    store: FakeStore = field(default_factory=FakeStore)
    clock: Clock = field(default_factory=Clock)
    sources: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.principal = local_principal().principal_id
        self.lifecycle = IngestionLifecycle(
            unit_of_work=self.unit,
            stores=self._stores,
            handlers=[ProjectReportsHandler(reader=PulseExportReader(), clock=self.clock)],
            clock=self.clock,
        )

    def _stores(self, workspace_id: str) -> FakeStore:
        if workspace_id != PROJECT_REPORTS_WORKSPACE_ID:
            raise LookupError(workspace_id)
        return self.store

    @staticmethod
    def folder(key: str) -> str:
        return f"{ROOT}/Qx {key.title()} Readsfolder"

    def bind(self, key: str, project_id: str, number: str) -> str:
        self.add_project(project_id, number)
        source = self.lifecycle.admit(
            self.principal,
            consumer=IngestConsumer.PULSE_CSV_EXPORT,
            workspace_id=PROJECT_REPORTS_WORKSPACE_ID,
            path_prefix=self.folder(key) + "/",
            file_pattern="*.csv",
        )
        self.sources[key] = source.ingest_source_id
        revision = ProjectReportBindingRevisionRecord(
            binding_revision_id=issue_identifier(IdKind.PROJECT_REPORT_BINDING_REVISION),
            ingest_source_id=source.ingest_source_id,
            project_id=project_id,
            declared_project_number=number,
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
        return source.ingest_source_id

    def ingest(self, key: str, name: str, data: bytes) -> None:
        path = f"{self.folder(key)}/{name}"
        self.store.put(path, data)
        report = self.lifecycle.backfill(self.principal, self.sources[key], paths=[path])
        assert report.counts["snapshots_failed"] == 0, report.counts

    def _revision(self, key: str) -> ProjectReportBindingRevisionRecord:
        with self.unit() as unit:
            binding = unit.project_reports.get_binding(self.principal, self.sources[key])
            assert binding is not None
            revision = unit.project_reports.get_binding_revision(
                self.principal, binding.binding_revision_id
            )
            assert revision is not None
            return revision

    def declare(self, key: str, slug: str) -> datetime:
        declared_at = self.clock()
        revision = self._revision(key)
        with self.unit() as unit:
            unit.project_reports.insert_filter_declarations(
                self.principal,
                [
                    ProjectReportFilterDeclarationRecord(
                        binding_revision_id=revision.binding_revision_id,
                        slug_label=slug,
                        description="Synthetic filter description",
                        declared_at=declared_at,
                    )
                ],
            )
        return declared_at

    def correct(self, key: str) -> None:
        """A binding correction (same Project and number), declarations carried over."""
        prior = self._revision(key)
        revision = dataclasses.replace(
            prior,
            binding_revision_id=issue_identifier(IdKind.PROJECT_REPORT_BINDING_REVISION),
            recorded_at=self.clock(),
            change_set_sha256="1" * 64,
            reason_code=BindingReason.CORRECTION,
            supersedes_revision_id=prior.binding_revision_id,
        )
        with self.unit() as unit:
            repository = unit.project_reports
            declarations = repository.list_filter_declarations(
                self.principal, prior.binding_revision_id
            )
            repository.insert_binding_revision(self.principal, revision)
            repository.insert_filter_declarations(
                self.principal,
                [
                    dataclasses.replace(d, binding_revision_id=revision.binding_revision_id)
                    for d in declarations
                ],
            )
            repository.move_binding(
                self.principal,
                ProjectReportBindingRecord(
                    ingest_source_id=prior.ingest_source_id,
                    binding_revision_id=revision.binding_revision_id,
                    project_id=prior.project_id,
                    state=BindingState.ACTIVE,
                ),
            )

    def rederive(self, registry: dict[str, pulse_csv.FamilyAdapter] | None = None) -> None:
        reader = PulseExportReader() if registry is None else PulseExportReader(registry)
        ProjectReportsRederiver(unit_of_work=self.unit, reader=reader, clock=self.clock).sweep(
            self.principal
        )


def build_world(scene: ReadsScene) -> None:
    """The synthetic world every read test uses, in one fixed order under one clock."""
    scene.bind(*RFI_PROJECT)
    scene.ingest("rfis", RFI_LATER, rfi_export(RFI_ROWS_LATER))
    scene.declare("rfis", DECLARED_SLUG)
    scene.ingest("rfis", RFI_EARLIER, rfi_export(RFI_ROWS_EARLIER))
    scene.ingest("rfis", QUARANTINE_FIRST, rfi_export(QUARANTINE_ROWS))
    scene.ingest("rfis", QUARANTINE_LATEST, quarantined_export())
    scene.bind(*OBS_PROJECT)
    scene.ingest(
        "observations", OBSERVATIONS, (FIXTURES / "two_level" / "observations_99.csv").read_bytes()
    )
    scene.bind(*NOTE_PROJECT)
    scene.ingest("notes", UNKNOWN, (FIXTURES / "variants" / "unknown_family.csv").read_bytes())


def fast_scene() -> tuple[ReadsScene, IngestWorld, World]:
    ingest, world = IngestWorld(), World()

    def add_project(project_id: str, number: str) -> None:
        world.projects.append(
            Project(
                project_id=project_id,
                principal_id=local_principal().principal_id,
                name="Synthetic project",
                state=ProjectState.ACTIVE,
                opened_at=WHEN,
                created_at=WHEN,
                updated_at=WHEN,
                project_number=number,
            )
        )

    scene = ReadsScene(
        unit=lambda: _RollbackUnitOfWork(ingest, meetings=world), add_project=add_project
    )
    return scene, ingest, world


def database_scene(engine: Engine) -> ReadsScene:
    """The same scene over a head-migrated database (the `database` tier only)."""
    principal = local_principal().principal_id

    def add_project(project_id: str, number: str) -> None:
        with engine.begin() as connection:
            connection.execute(
                insert(projects).values(
                    project_id=project_id,
                    principal_id=principal,
                    name="Synthetic project",
                    opened_at=WHEN,
                    created_at=WHEN,
                    updated_at=WHEN,
                    project_number=number,
                )
            )

    return ReadsScene(unit=project_reports_unit_of_work(engine), add_project=add_project)
