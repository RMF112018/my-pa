"""The project-report bindings service: `bindings check` and `bindings apply` (WP3P-S4).

Rulings D5, D6, D7, D8, D12 and D19; design report section 3.7; plan section 6.4.
The operator's bindings file (`my_pa_project_report_bindings_v1`, validated by
the pure `domain.project_reports.bindings`) is the **whole desired state** of
one workspace: a folder in it is bound to its Project, a bound folder missing
from it is retired.

**Validation, fail-closed, whole file.** After the pure checks (shape,
unknown and duplicate keys, folder rules 3 and 5, `folder_nested`, rule 4
within the file, currency, filter bounds) this service adds the database and
workspace checks, each refusing the whole file with one closed
`BindingRefusal` and writing nothing:

* rule 1 -- the `project_id` is no Project of the Principal: `project_not_found`;
* rule 2 -- the Project has no number (`project_has_no_number`) or another one
  (`project_number_mismatch`); compared exactly;
* ruling D19 -- the folder is not a directory of the workspace, read by `stat`
  through the read-only store: `folder_not_found`;
* rule 4 across the database -- the Projects of the changes cannot be moved in
  any order without two active bindings of one Project at once (a swap):
  `project_duplicated`.

**The diff.** Against the current pointers: an `add` (a folder with no binding
yet, or a retired one bound again), a `correction` (the Project, its number or
the currency changed), a `filter_update` (only the report filter declarations
changed), a `retire` (an active binding whose folder the file omits), or
unchanged. `check` also lists the directories under `export_root` that
directly hold a `*.csv` file and are not a folder of the file (`unbound`),
walking at most `UNBOUND_FOLDER_DEPTH` levels below the root and at most
`MAX_LISTED_DIRECTORIES` directories, both stated in its report.

**Apply: one transaction under the project-reports poll lock.** The lock is
taken without waiting (`lock_held` when another apply or the poll holds it);
then, in one unit of work, the checks run against the state the writes will
change, and the writes follow in an order no guard can refuse: retires, then
the changes (ordered so each Project is released before it is taken), then the
adds. All of it commits or none of it does.

* an add of a new folder admits its source through
  `IngestionLifecycle.admit_within` (consumer `pulse_csv_export`, prefix
  `<folder>/`, pattern `*.csv`, enabled), then writes the first revision and
  the pointer; an add of a retired folder writes a revision superseding the
  retired one, moves the pointer and enables the source;
* a correction or filter update writes the superseding revision and moves the
  pointer;
* a retire writes a `retired` revision (same Project, number and currency),
  moves the pointer to it and disables the source; every row stays;
* every active revision carries the file's filter declarations for its folder
  (declared at the revision's own instant, ruling D8 (i));
* every revision records `change_set_sha256` (the SHA-256 of the file's bytes),
  `recorded_by = operator_cli` and the reason its change kind names; no
  `audit_events` row (ruling D6: the append-only revisions are the audit).

Applying the same file again finds every binding unchanged and writes nothing.

**Counts and project numbers, never content.** A report carries closed codes,
counts and the project numbers of the bindings it names: never a folder, a
path, a file name, a filter description or a slug.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from my_pa.application.ingestion import IngestionLifecycle, IngestRefusalCode, IngestRefusedError
from my_pa.contracts.ports import (
    FileWorkspaceStore,
    FileWorkspaceUnavailableError,
    IngestConsumer,
    IngestSourceRecord,
    ProjectReportBindingRecord,
    ProjectReportBindingRevisionRecord,
    ProjectReportFilterDeclarationRecord,
    ProjectReportsWriteRefusedError,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.files.errors import FilesDomainError
from my_pa.domain.files.versions import EntryKind
from my_pa.domain.project_reports.bindings import (
    BindingEntry,
    BindingsFile,
    BindingsRefusedError,
    ReportFilter,
    change_set_sha256,
    validate_bindings_file,
)
from my_pa.domain.project_reports.model import BindingReason, BindingRefusal, BindingState
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "FILE_PATTERN",
    "MAX_LISTED_DIRECTORIES",
    "UNBOUND_FOLDER_DEPTH",
    "BindingsReport",
    "ProjectReportBindings",
]

#: Every project-report source reads the CSV files directly in its folder.
FILE_PATTERN: Final = "*.csv"
#: `check` lists unbound CSV folders at most this many levels below `export_root`
#: (the root itself is level 0; `<project>/REPORTS/PULSE` is level 3).
UNBOUND_FOLDER_DEPTH: Final = 3
#: ... and visits at most this many directories (the report says when it stopped).
MAX_LISTED_DIRECTORIES: Final = 5000
_PAGE_SIZE: Final = 200
#: The partial unique index a transient second active binding of a Project hits.
_ONE_ACTIVE_PER_PROJECT: Final = "one_active_project_report_binding_per_project"


@dataclass(frozen=True, slots=True)
class _Current:
    """One folder's current state: its source, pointer, revision and declarations."""

    source: IngestSourceRecord
    binding: ProjectReportBindingRecord
    revision: ProjectReportBindingRevisionRecord
    filters: frozenset[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class _Change:
    """One binding the apply writes: the revision's values, the source and its current state."""

    reason: BindingReason
    folder: str
    project_id: str
    project_number: str
    currency: str
    reports: tuple[ReportFilter, ...]
    source: IngestSourceRecord | None
    current: _Current | None

    @classmethod
    def of(
        cls,
        reason: BindingReason,
        entry: BindingEntry,
        source: IngestSourceRecord | None,
        current: _Current | None,
    ) -> _Change:
        return cls(
            reason,
            entry.folder,
            entry.project_id,
            entry.project_number,
            entry.currency,
            entry.reports,
            source,
            current,
        )

    @classmethod
    def retire(cls, current: _Current) -> _Change:
        """A retire keeps the Project, its number and the currency of the current revision."""
        kept = current.revision
        return cls(
            BindingReason.RETIRE,
            current.source.path_prefix.removesuffix("/"),
            kept.project_id,
            kept.declared_project_number,
            kept.currency,
            (),
            current.source,
            current,
        )


@dataclass(frozen=True, slots=True)
class _Plan:
    changes: tuple[_Change, ...]
    unchanged: int
    filter_declarations: int


@dataclass(frozen=True, slots=True)
class BindingsReport:
    """What `check` found or `apply` did: closed keys, counts and project numbers."""

    applied: bool
    #: `add`, `correction`, `filter_update` and `retire` to the project numbers changed.
    project_numbers: Mapping[str, tuple[str, ...]]
    unchanged: int
    #: Filter declarations the changed revisions carry (written by `apply`).
    filter_declarations: int
    #: `apply` only: sources admitted, enabled and disabled, revisions written.
    writes: Mapping[str, int] = field(default_factory=dict)
    #: `check` only: unbound CSV folders, the depth listed, and whether it stopped short.
    unbound_folders: int | None = None
    unbound_folder_depth: int | None = None
    unbound_listing_truncated: bool | None = None

    @property
    def counts(self) -> dict[str, int]:
        counts = {key: len(numbers) for key, numbers in self.project_numbers.items()}
        counts["unchanged"] = self.unchanged
        counts["filter_declarations"] = self.filter_declarations
        return counts


_CHANGE_KEYS: Final = ("add", "correction", "filter_update", "retire")
_WRITE_KEYS: Final = (
    "revisions",
    "filter_declarations",
    "sources_admitted",
    "sources_enabled",
    "sources_disabled",
)


def _change_key(reason: BindingReason) -> str:
    return "add" if reason in (BindingReason.INITIAL, BindingReason.ADD) else reason.value


class ProjectReportBindings:
    """`check` and `apply` of the operator's bindings file (module docstring).

    `unit_of_work` opens one transaction; `lifecycle` is the project-reports
    lifecycle (it holds the `pulse_csv_export` handler, so it admits the
    consumer); `stores` resolves a workspace id to its read-only store;
    `workspace_id` is the one workspace the file must name; `lock` takes the
    project-reports poll lock without waiting and yields whether it is held.
    """

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], UnitOfWork],
        lifecycle: IngestionLifecycle,
        stores: Callable[[str], FileWorkspaceStore],
        workspace_id: str,
        lock: Callable[[], AbstractContextManager[bool]],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if IngestConsumer.PULSE_CSV_EXPORT not in lifecycle.consumers:
            raise ValueError("the bindings service needs the project-reports lifecycle")
        self._unit_of_work = unit_of_work
        self._lifecycle = lifecycle
        self._stores = stores
        self._workspace_id = workspace_id
        self._lock = lock
        self._clock = clock

    # --- the two commands ----------------------------------------------------------

    def check(self, principal_id: str, data: bytes) -> BindingsReport:
        """Validate the file and report its diff and the unbound folders; writes nothing."""
        desired = validate_bindings_file(data, workspace_id=self._workspace_id)
        store = self._store()
        self._require_folders(store, desired)
        with self._unit_of_work() as unit:
            plan = self._plan(unit, principal_id, desired)
        unbound, truncated = self._unbound(store, desired)
        return self._report(
            plan,
            applied=False,
            unbound_folders=unbound,
            unbound_folder_depth=UNBOUND_FOLDER_DEPTH,
            unbound_listing_truncated=truncated,
        )

    def apply(self, principal_id: str, data: bytes) -> BindingsReport:
        """Apply the file whole in one transaction under the poll lock, or refuse it."""
        desired = validate_bindings_file(data, workspace_id=self._workspace_id)
        digest = change_set_sha256(data)
        store = self._store()
        with self._lock() as held:
            if not held:
                raise BindingsRefusedError(BindingRefusal.LOCK_HELD)
            self._require_folders(store, desired)
            try:
                with self._unit_of_work() as unit:
                    plan = self._plan(unit, principal_id, desired)
                    writes = self._write(unit, principal_id, plan, digest)
            except ProjectReportsWriteRefusedError as refused:
                if refused.constraint == _ONE_ACTIVE_PER_PROJECT:
                    raise BindingsRefusedError(BindingRefusal.PROJECT_DUPLICATED) from None
                raise
        return self._report(plan, applied=True, writes=writes)

    # --- checks ------------------------------------------------------------------

    def _store(self) -> FileWorkspaceStore:
        try:
            return self._stores(self._workspace_id)
        except LookupError:
            raise IngestRefusedError(IngestRefusalCode.WORKSPACE_UNAVAILABLE) from None

    def _require_folders(self, store: FileWorkspaceStore, desired: BindingsFile) -> None:
        """Ruling D19: every folder of the file is a directory of the workspace."""
        for entry in desired.bindings:
            try:
                found = store.stat(entry.folder)
            except FilesDomainError:
                raise BindingsRefusedError(BindingRefusal.FOLDER_NOT_FOUND) from None
            except FileWorkspaceUnavailableError:
                raise IngestRefusedError(IngestRefusalCode.WORKSPACE_UNAVAILABLE) from None
            if found.kind is not EntryKind.DIRECTORY:
                raise BindingsRefusedError(BindingRefusal.FOLDER_NOT_FOUND)

    @staticmethod
    def _require_project(unit: UnitOfWork, principal_id: str, entry: BindingEntry) -> None:
        """Rules 1 and 2 against `knowledge.projects`."""
        project = unit.projects.get_project(principal_id, entry.project_id)
        if project is None:
            raise BindingsRefusedError(BindingRefusal.PROJECT_NOT_FOUND)
        if project.project_number is None:
            raise BindingsRefusedError(BindingRefusal.PROJECT_HAS_NO_NUMBER)
        if project.project_number != entry.project_number:
            raise BindingsRefusedError(BindingRefusal.PROJECT_NUMBER_MISMATCH)

    # --- the diff ----------------------------------------------------------------

    def _current(self, unit: UnitOfWork, principal_id: str) -> dict[str, _Current]:
        """The workspace's bound folders (prefix -> current state), retired ones included."""
        sources = {
            source.ingest_source_id: source
            for source in unit.ingestion.list_sources(principal_id)
            if source.consumer is IngestConsumer.PULSE_CSV_EXPORT
            and source.workspace_id == self._workspace_id
        }
        found: dict[str, _Current] = {}
        for binding in unit.project_reports.list_bindings(principal_id):
            source = sources.get(binding.ingest_source_id)
            if source is None:
                continue
            revision = unit.project_reports.get_binding_revision(
                principal_id, binding.binding_revision_id
            )
            if revision is None:  # the pointer's foreign key makes this unreachable
                raise RuntimeError("a binding pointer names no revision")
            filters = frozenset(
                (declaration.slug_label, declaration.description)
                for declaration in unit.project_reports.list_filter_declarations(
                    principal_id, revision.binding_revision_id
                )
            )
            found[source.path_prefix] = _Current(source, binding, revision, filters)
        return found

    def _plan(self, unit: UnitOfWork, principal_id: str, desired: BindingsFile) -> _Plan:
        current = self._current(unit, principal_id)
        first_ever = not unit.project_reports.list_bindings(principal_id)
        sources = {
            source.path_prefix: source
            for source in unit.ingestion.list_sources(principal_id)
            if source.consumer is IngestConsumer.PULSE_CSV_EXPORT
            and source.workspace_id == self._workspace_id
            and source.file_pattern == FILE_PATTERN
        }
        changes: list[_Change] = []
        adds: list[_Change] = []
        unchanged = 0
        declarations = 0
        wanted: set[str] = set()
        for entry in desired.bindings:
            self._require_project(unit, principal_id, entry)
            prefix = entry.folder + "/"
            wanted.add(prefix)
            now = current.get(prefix)
            filters = frozenset((report.slug, report.description) for report in entry.reports)
            if now is None:
                reason = BindingReason.INITIAL if first_ever else BindingReason.ADD
                adds.append(_Change.of(reason, entry, sources.get(prefix), None))
            elif now.binding.state is BindingState.RETIRED:
                adds.append(_Change.of(BindingReason.ADD, entry, now.source, now))
            elif (now.revision.project_id, now.revision.declared_project_number) != (
                entry.project_id,
                entry.project_number,
            ) or now.revision.currency != entry.currency:
                changes.append(_Change.of(BindingReason.CORRECTION, entry, now.source, now))
            elif now.filters != filters:
                changes.append(_Change.of(BindingReason.FILTER_UPDATE, entry, now.source, now))
            else:
                unchanged += 1
                continue
            declarations += len(entry.reports)
        retires = [
            _Change.retire(now)
            for prefix, now in sorted(current.items())
            if prefix not in wanted and now.binding.state is BindingState.ACTIVE
        ]
        return _Plan((*retires, *_released_first(changes), *adds), unchanged, declarations)

    # --- the writes --------------------------------------------------------------

    def _write(
        self, unit: UnitOfWork, principal_id: str, plan: _Plan, digest: str
    ) -> dict[str, int]:
        writes = dict.fromkeys(_WRITE_KEYS, 0)
        repository = unit.project_reports
        recorded_at = self._clock()  # one instant for the whole change set
        for change in plan.changes:
            source = change.source
            if source is None:
                source = self._lifecycle.admit_within(
                    unit,
                    principal_id,
                    consumer=IngestConsumer.PULSE_CSV_EXPORT,
                    workspace_id=self._workspace_id,
                    path_prefix=change.folder + "/",
                    file_pattern=FILE_PATTERN,
                    enabled=True,
                )
                writes["sources_admitted"] += 1
            revision = _revision(change, source, recorded_at, digest)
            repository.insert_binding_revision(principal_id, revision)
            writes["revisions"] += 1
            if change.reports:
                repository.insert_filter_declarations(
                    principal_id,
                    [
                        ProjectReportFilterDeclarationRecord(
                            binding_revision_id=revision.binding_revision_id,
                            slug_label=report.slug,
                            description=report.description,
                            declared_at=recorded_at,
                        )
                        for report in change.reports
                    ],
                )
                writes["filter_declarations"] += len(change.reports)
            pointer = ProjectReportBindingRecord(
                ingest_source_id=source.ingest_source_id,
                binding_revision_id=revision.binding_revision_id,
                project_id=revision.project_id,
                state=revision.state,
            )
            if change.current is None:
                repository.insert_binding(principal_id, pointer)
            else:
                repository.move_binding(principal_id, pointer)
            # A retire stops the scheduled poll; an add of a source admitted
            # earlier starts it again. A correction leaves the switch alone.
            if change.reason is BindingReason.RETIRE and source.enabled:
                unit.ingestion.set_source_enabled(principal_id, source.ingest_source_id, False)
                writes["sources_disabled"] += 1
            elif _change_key(change.reason) == "add" and not source.enabled:
                unit.ingestion.set_source_enabled(principal_id, source.ingest_source_id, True)
                writes["sources_enabled"] += 1
        return writes

    # --- the unbound folders -------------------------------------------------------

    def _unbound(self, store: FileWorkspaceStore, desired: BindingsFile) -> tuple[int, bool]:
        """CSV folders under `export_root` that the file binds to nothing, bounded."""
        bound = {entry.folder for entry in desired.bindings}
        unbound = 0
        visited = 0
        pending: list[tuple[str, int]] = [(desired.export_root, 0)]
        while pending:
            directory, depth = pending.pop()
            visited += 1
            if visited > MAX_LISTED_DIRECTORIES:
                return unbound, True
            holds_csv = False
            after: str | None = None
            while True:
                try:
                    page = store.list_directory(directory, after=after, page_size=_PAGE_SIZE)
                except FilesDomainError:
                    if depth == 0:
                        raise BindingsRefusedError(BindingRefusal.FOLDER_NOT_FOUND) from None
                    break  # removed while listed: nothing to count there
                except FileWorkspaceUnavailableError:
                    raise IngestRefusedError(IngestRefusalCode.WORKSPACE_UNAVAILABLE) from None
                for entry in page.entries:
                    if entry.kind is EntryKind.FILE and fnmatch.fnmatchcase(
                        entry.name, FILE_PATTERN
                    ):
                        holds_csv = True
                    elif entry.kind is EntryKind.DIRECTORY and depth < UNBOUND_FOLDER_DEPTH:
                        pending.append((entry.path, depth + 1))
                if page.next_after is None:
                    break
                after = page.next_after
            if holds_csv and directory not in bound:
                unbound += 1
        return unbound, False

    # --- the report --------------------------------------------------------------

    @staticmethod
    def _report(
        plan: _Plan,
        *,
        applied: bool,
        writes: Mapping[str, int] | None = None,
        unbound_folders: int | None = None,
        unbound_folder_depth: int | None = None,
        unbound_listing_truncated: bool | None = None,
    ) -> BindingsReport:
        numbers: dict[str, list[str]] = {key: [] for key in _CHANGE_KEYS}
        for change in plan.changes:
            numbers[_change_key(change.reason)].append(change.project_number)
        return BindingsReport(
            applied=applied,
            project_numbers={key: tuple(sorted(value)) for key, value in numbers.items()},
            unchanged=plan.unchanged,
            filter_declarations=plan.filter_declarations,
            writes=dict(writes or {}),
            unbound_folders=unbound_folders,
            unbound_folder_depth=unbound_folder_depth,
            unbound_listing_truncated=unbound_listing_truncated,
        )


def _revision(
    change: _Change, source: IngestSourceRecord, recorded_at: datetime, digest: str
) -> ProjectReportBindingRevisionRecord:
    """The revision one change writes (`retired` exactly for a retire)."""
    retire = change.reason is BindingReason.RETIRE
    return ProjectReportBindingRevisionRecord(
        binding_revision_id=issue_identifier(IdKind.PROJECT_REPORT_BINDING_REVISION),
        ingest_source_id=source.ingest_source_id,
        project_id=change.project_id,
        declared_project_number=change.project_number,
        state=BindingState.RETIRED if retire else BindingState.ACTIVE,
        currency=change.currency,
        recorded_at=recorded_at,
        change_set_sha256=digest,
        reason_code=change.reason,
        supersedes_revision_id=(
            None if change.current is None else change.current.revision.binding_revision_id
        ),
    )


def _released_first(changes: list[_Change]) -> list[_Change]:
    """The changes ordered so a Project is released before another binding takes it.

    A change taking Project X waits while another pending change still holds X
    actively; a cycle (a swap) cannot be ordered and is `project_duplicated`.
    """
    pending = list(changes)
    ordered: list[_Change] = []
    while pending:
        for change in pending:
            taken = change.project_id
            if not any(
                other is not change
                and other.current is not None
                and other.current.revision.project_id == taken
                for other in pending
            ):
                ordered.append(change)
                pending.remove(change)
                break
        else:
            raise BindingsRefusedError(BindingRefusal.PROJECT_DUPLICATED)
    return ordered
