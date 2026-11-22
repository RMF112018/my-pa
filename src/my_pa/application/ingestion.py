"""The consumer-neutral ingestion lifecycle (communications WP3a; contract 1.2, 1.3, 10, 11).

`IngestionLifecycle` turns files in a file workspace into snapshots, paths, runs
and coverage windows, and hands each new snapshot's bytes to the
`IngestConsumerHandler` registered for its source's consumer. It knows files,
digests, paths and windows; it never knows what the bytes mean, and it imports
no consumer slice (`tests/architecture/test_ingestion_lifecycle_is_consumer_neutral.py`).

**The store is read, never written.** The only `FileWorkspaceStore` calls are
`list_directory`, `stat` and `open_download` (Manager ruling m5, guarded).
Candidates are the direct children of the source's `path_prefix` whose name
matches `file_pattern` under `fnmatch.fnmatchcase`, every page of one
directory, no recursion (ruling m3).

**Stability (contract section 11, ruling m6).** A scheduled poll reads a file
only once its size and version token are unchanged across two consecutive
polls, remembered in this process. An operator run (`run_once`) and a backfill
are explicit operator actions on files at rest, so they read on first sight
(contract section 10 names a file list, not a wait). In every mode the read is
bound to the observed version (`open_download(expected_version=...)`, which
refuses an in-place change), the byte count must equal the observed size, and a
file the consumer refuses is re-`stat`ed: if it moved since it was observed it
was still being written and is retried on a later run (`skipped_changing`),
never rejected; only a file that held still is rejected.

**Unchanged files are not re-read.** A path whose size and version token equal
the ones this process last finished with is counted `skipped_unchanged` without
a read. The token is a change detector here, never identity: identity is the
SHA-256, and a restarted process re-reads and finds the digest known.

**Identity is the SHA-256 (contract section 1.3).** A digest the source already
holds is never re-ingested: the run links it `already_known`, and the path
bookkeeping follows the bytes:

* the same bytes at the path they are current at: nothing else;
* the same bytes at another path: an alias row, superseding that path's
  previous current row;
* **path revert** -- bytes reappearing at a path whose row for them was already
  superseded: the supersession is one-way (ruling M3), so nothing is written,
  the newer snapshot stays current for the path, and the run counts
  `snapshots_path_reverted`;
* new bytes: a new snapshot, superseding the path's previous current row, in
  the same transaction as everything the consumer writes for it.

**One snapshot, one transaction (contract section 10).** The run row is written
first and finished last, each in its own transaction; every snapshot (with its
paths, its run link, the consumer's rows and its coverage window) commits or
rolls back alone. A handler failure rolls back that snapshot only and counts
`snapshots_failed`; the run is `completed` with no failure, `partial` with
failures beside successes, `failed` when nothing succeeded or the listing
itself failed. A rejected snapshot writes its snapshot row, its path rows and
its run link, nothing else.

**Ordering (contract sections 10 and 11).** Within a run, accepted snapshots
are applied oldest declared window first: by `window_start`, then the declared
window end, then the file SHA-256 (a total order, independent of listing order
and arrival). Known digests and rejections write no consumer rows, so they are
handled as they are met (paths in name order).

**Dry run (contract section 10).** Lists, reads, hashes, prepares and counts
exactly as a run would, reads what the source already holds, and writes
nothing: no run, no snapshot, no path, and no stability memory.

**Counts, never content.** A run's `counts` are the `RUN_COUNT_KEYS` plus the
handler's `records_*` code counts. Nothing here logs; a path is stored only as
the workspace-relative `relative_path` of a path row.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from my_pa.contracts.ports import (
    INGEST_ADMITTED_BY_OPERATOR_CLI,
    FileWorkspaceEntry,
    FileWorkspaceStore,
    FileWorkspaceUnavailableError,
    IngestConsumer,
    IngestConsumerHandler,
    IngestCoverageWindowRecord,
    IngestionRepository,
    IngestPrepared,
    IngestRunOutcome,
    IngestRunRecord,
    IngestRunSnapshotOutcome,
    IngestRunSnapshotRecord,
    IngestRunTrigger,
    IngestSnapshotPathRecord,
    IngestSnapshotRecord,
    IngestSnapshotStatus,
    IngestSourceRecord,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.files.errors import FilesDomainError, FilesRefusal
from my_pa.domain.files.versions import EntryKind
from my_pa.domain.files.vocabulary import FilesReason
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "RUN_COUNT_KEYS",
    "IngestRefusalCode",
    "IngestRefusedError",
    "IngestRunReport",
    "IngestionLifecycle",
    "StabilityMemory",
]

#: The lifecycle's own run counts, always present (zero when nothing happened).
RUN_COUNT_KEYS: Final = (
    "snapshots_seen",
    "snapshots_new",
    "snapshots_ingested",
    "snapshots_rejected",
    "snapshots_failed",
    "snapshots_already_known",
    "snapshots_aliased",
    "snapshots_superseded",
    "snapshots_path_reverted",
    "snapshots_skipped",
    "skipped_unstable",
    "skipped_unchanged",
    "skipped_changing",
    "skipped_too_large",
    "skipped_unreadable",
    "skipped_missing",
)
_SKIP_KEYS: Final = tuple(key for key in RUN_COUNT_KEYS if key.startswith("skipped_"))

_WORKSPACE_ID: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")
_MAX_PREFIX: Final = 1024
_MAX_PATTERN: Final = 256
_PAGE_SIZE: Final = 200
_READ_CHUNK: Final = 1024 * 1024
#: An accepted snapshot that declares no window sorts after every one that does.
_NO_WINDOW: Final = datetime.max.replace(tzinfo=UTC)
#: Refusals that mean "the file moved while being looked at" (retried, never rejected).
_CHANGING: Final = frozenset({FilesReason.EXTERNAL_CHANGE_DETECTED, FilesReason.VERSION_CONFLICT})


class IngestRefusalCode(StrEnum):
    """Why an admission or a run was refused. Closed; carries no path or name."""

    CONSUMER_NOT_REGISTERED = "consumer_not_registered"
    SOURCE_ALREADY_ADMITTED = "source_already_admitted"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_DISABLED = "source_disabled"
    INVALID_LOCATION = "invalid_location"
    PATH_OUTSIDE_SOURCE = "path_outside_source"
    WORKSPACE_UNAVAILABLE = "workspace_unavailable"


class IngestRefusedError(Exception):
    """A refused admission or run; `code` is the whole answer."""

    def __init__(self, code: IngestRefusalCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class IngestRunReport:
    """What one run did. `run_id` is `None` for a dry run (nothing was written)."""

    ingest_source_id: str
    trigger: IngestRunTrigger
    dry_run: bool
    run_id: str | None
    outcome: IngestRunOutcome
    counts: Mapping[str, int]


type _PathKey = tuple[str, str, str]


@dataclass
class StabilityMemory:
    """In-process memory of what each path looked like (ruling m6).

    `observed` is the last `(size, version)` a poll saw at a path; `finished` is
    the `(size, version)` a run last finished with there. Lost on restart, which
    only costs one more poll and one re-read.
    """

    observed: dict[_PathKey, tuple[int, str]] = field(default_factory=dict)
    finished: dict[_PathKey, tuple[int, str]] = field(default_factory=dict)

    def stable(self, key: _PathKey, shape: tuple[int, str]) -> bool:
        """Record this poll's shape; true when the previous poll saw the same one."""
        previous = self.observed.get(key)
        self.observed[key] = shape
        return previous == shape

    def forget(self, key: _PathKey) -> None:
        self.observed.pop(key, None)
        self.finished.pop(key, None)


@dataclass(frozen=True, slots=True)
class _Read:
    """One candidate file, read whole: the bytes, their digest, and where it was seen."""

    path: str
    entry: FileWorkspaceEntry
    data: bytes = field(repr=False)
    digest: str


@dataclass(frozen=True, slots=True)
class _Accepted:
    reads: tuple[_Read, ...]
    prepared: IngestPrepared

    @property
    def order(self) -> tuple[datetime, datetime, str]:
        coverage = self.prepared.coverage
        return (
            self.prepared.window_start or _NO_WINDOW,
            coverage.end_utc if coverage is not None else _NO_WINDOW,
            self.reads[0].digest,
        )


class _RunState:
    """Counts and the per-run set of snapshots already linked (one link per snapshot)."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter(dict.fromkeys(RUN_COUNT_KEYS, 0))
        self.linked: set[str] = set()
        self.listing_failed = False

    def skip(self, key: str) -> None:
        self.counts[key] += 1
        self.counts["snapshots_skipped"] += 1

    def add_records(self, record_counts: Mapping[str, int]) -> None:
        for name, value in record_counts.items():
            self.counts[name] += value

    def outcome(self) -> IngestRunOutcome:
        failed = self.counts["snapshots_failed"]
        succeeded = (
            self.counts["snapshots_ingested"]
            + self.counts["snapshots_rejected"]
            + self.counts["snapshots_already_known"]
        )
        if self.listing_failed or (failed and not succeeded):
            return IngestRunOutcome.FAILED
        return IngestRunOutcome.PARTIAL if failed else IngestRunOutcome.COMPLETED


def _valid_prefix(path_prefix: str) -> bool:
    if len(path_prefix) > _MAX_PREFIX or path_prefix.startswith("/") or "\\" in path_prefix:
        return False
    if path_prefix == "":
        return True
    body = path_prefix.removesuffix("/")
    return bool(body) and all(part not in {"", ".", ".."} for part in body.split("/"))


def _directory(path_prefix: str) -> str:
    return path_prefix.removesuffix("/")


def _child_of(path: str, directory: str) -> str | None:
    """The name of `path` when it is a direct child of `directory`, else `None`."""
    if directory == "":
        name = path
    elif path.startswith(directory + "/"):
        name = path[len(directory) + 1 :]
    else:
        return None
    return name if name and "/" not in name else None


class IngestionLifecycle:
    """Admission, polling, backfill and dry runs over the lifecycle tables.

    `unit_of_work` opens one transaction; `stores` resolves a source's
    `workspace_id` to its file workspace store; `handlers` holds at most one
    handler per consumer (a consumer without one cannot be admitted or run).
    `stability` is the in-process poll memory, shared across this object's runs.
    """

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], UnitOfWork],
        stores: Callable[[str], FileWorkspaceStore],
        handlers: Sequence[IngestConsumerHandler],
        clock: Callable[[], datetime] = utc_now,
        stability: StabilityMemory | None = None,
    ) -> None:
        by_consumer: dict[IngestConsumer, IngestConsumerHandler] = {}
        for handler in handlers:
            if handler.consumer in by_consumer:
                raise ValueError("one handler per consumer")
            by_consumer[handler.consumer] = handler
        self._unit_of_work = unit_of_work
        self._stores = stores
        self._handlers: Mapping[IngestConsumer, IngestConsumerHandler] = by_consumer
        self._clock = clock
        self._stability = stability if stability is not None else StabilityMemory()

    # --- admission -----------------------------------------------------------

    def admit(
        self,
        principal_id: str,
        *,
        consumer: IngestConsumer,
        workspace_id: str,
        path_prefix: str,
        file_pattern: str,
        enabled: bool = True,
    ) -> IngestSourceRecord:
        """Admit one source (operator CLI only, ruling m8); refused with a closed code."""
        if consumer not in self._handlers:
            raise IngestRefusedError(IngestRefusalCode.CONSUMER_NOT_REGISTERED)
        if (
            _WORKSPACE_ID.fullmatch(workspace_id) is None
            or not _valid_prefix(path_prefix)
            or not 1 <= len(file_pattern) <= _MAX_PATTERN
            or "/" in file_pattern
        ):
            raise IngestRefusedError(IngestRefusalCode.INVALID_LOCATION)
        source = IngestSourceRecord(
            ingest_source_id=issue_identifier(IdKind.INGEST_SOURCE),
            consumer=consumer,
            workspace_id=workspace_id,
            path_prefix=path_prefix,
            file_pattern=file_pattern,
            enabled=enabled,
            admitted_at=self._clock(),
            admitted_by=INGEST_ADMITTED_BY_OPERATOR_CLI,
        )
        with self._unit_of_work() as unit:
            location = (consumer, workspace_id, path_prefix, file_pattern)
            if any(
                (s.consumer, s.workspace_id, s.path_prefix, s.file_pattern) == location
                for s in unit.ingestion.list_sources(principal_id)
            ):
                raise IngestRefusedError(IngestRefusalCode.SOURCE_ALREADY_ADMITTED)
            unit.ingestion.insert_source(principal_id, source)
        return source

    def set_enabled(self, principal_id: str, ingest_source_id: str, enabled: bool) -> None:
        """Enable or disable one source's scheduled polling."""
        with self._unit_of_work() as unit:
            try:
                unit.ingestion.set_source_enabled(principal_id, ingest_source_id, enabled)
            except RepositoryFailureError:
                raise IngestRefusedError(IngestRefusalCode.SOURCE_NOT_FOUND) from None

    # --- runs ----------------------------------------------------------------

    def poll_enabled(self, principal_id: str) -> tuple[IngestRunReport, ...]:
        """The scheduled step: one stability-gated poll of every enabled source."""
        with self._unit_of_work() as unit:
            sources = unit.ingestion.list_sources(principal_id, enabled_only=True)
        return tuple(
            self._run(principal_id, source, IngestRunTrigger.SCHEDULE, paths=None, dry_run=False)
            for source in sources
            if source.consumer in self._handlers
        )

    def poll(self, principal_id: str, ingest_source_id: str) -> IngestRunReport:
        """One stability-gated poll of one enabled source (trigger `schedule`)."""
        source = self._source(principal_id, ingest_source_id)
        if not source.enabled:
            raise IngestRefusedError(IngestRefusalCode.SOURCE_DISABLED)
        return self._run(principal_id, source, IngestRunTrigger.SCHEDULE, paths=None, dry_run=False)

    def run_once(self, principal_id: str, ingest_source_id: str) -> IngestRunReport:
        """The operator's one run of the poll step over an enabled source (trigger `operator`)."""
        source = self._source(principal_id, ingest_source_id)
        if not source.enabled:
            raise IngestRefusedError(IngestRefusalCode.SOURCE_DISABLED)
        return self._run(principal_id, source, IngestRunTrigger.OPERATOR, paths=None, dry_run=False)

    def backfill(
        self,
        principal_id: str,
        ingest_source_id: str,
        *,
        paths: Sequence[str] | None = None,
        dry_run: bool = False,
    ) -> IngestRunReport:
        """A backfill (trigger `backfill`) of the listed files, or of every candidate.

        `paths` are workspace-relative and must be direct children of the
        source's prefix matching its pattern. A disabled source may be
        backfilled: `enabled` governs only the scheduled poll.
        """
        source = self._source(principal_id, ingest_source_id)
        if paths is not None:
            directory = _directory(source.path_prefix)
            for path in paths:
                name = _child_of(path, directory)
                if name is None or not fnmatch.fnmatchcase(name, source.file_pattern):
                    raise IngestRefusedError(IngestRefusalCode.PATH_OUTSIDE_SOURCE)
        return self._run(
            principal_id,
            source,
            IngestRunTrigger.BACKFILL,
            paths=None if paths is None else tuple(sorted(set(paths))),
            dry_run=dry_run,
        )

    def _source(self, principal_id: str, ingest_source_id: str) -> IngestSourceRecord:
        with self._unit_of_work() as unit:
            source = unit.ingestion.get_source(principal_id, ingest_source_id)
        if source is None:
            raise IngestRefusedError(IngestRefusalCode.SOURCE_NOT_FOUND)
        if source.consumer not in self._handlers:
            raise IngestRefusedError(IngestRefusalCode.CONSUMER_NOT_REGISTERED)
        return source

    def _run(
        self,
        principal_id: str,
        source: IngestSourceRecord,
        trigger: IngestRunTrigger,
        *,
        paths: Sequence[str] | None,
        dry_run: bool,
    ) -> IngestRunReport:
        handler = self._handlers[source.consumer]
        try:
            store = self._stores(source.workspace_id)
        except (LookupError, FileWorkspaceUnavailableError):
            raise IngestRefusedError(IngestRefusalCode.WORKSPACE_UNAVAILABLE) from None
        state = _RunState()
        run_id: str | None = None
        if not dry_run:
            run_id = issue_identifier(IdKind.INGEST_RUN)
            with self._unit_of_work() as unit:
                unit.ingestion.insert_run(
                    principal_id,
                    IngestRunRecord(
                        run_id=run_id,
                        ingest_source_id=source.ingest_source_id,
                        trigger=trigger,
                        started_at=self._clock(),
                    ),
                )
        run = _Run(
            self,
            principal_id=principal_id,
            source=source,
            handler=handler,
            store=store,
            state=state,
            run_id=run_id,
            stability_gated=trigger is IngestRunTrigger.SCHEDULE,
        )
        run.execute(paths)
        outcome = state.outcome()
        counts = dict(sorted(state.counts.items()))
        if run_id is not None:
            with self._unit_of_work() as unit:
                unit.ingestion.finish_run(
                    principal_id,
                    run_id,
                    finished_at=self._clock(),
                    outcome=outcome,
                    counts=counts,
                )
        return IngestRunReport(
            ingest_source_id=source.ingest_source_id,
            trigger=trigger,
            dry_run=dry_run,
            run_id=run_id,
            outcome=outcome,
            counts=counts,
        )


class _Run:
    """One run of one source: candidate discovery, reads, then the snapshot transactions."""

    def __init__(
        self,
        lifecycle: IngestionLifecycle,
        *,
        principal_id: str,
        source: IngestSourceRecord,
        handler: IngestConsumerHandler,
        store: FileWorkspaceStore,
        state: _RunState,
        run_id: str | None,
        stability_gated: bool,
    ) -> None:
        self._lifecycle = lifecycle
        self._principal_id = principal_id
        self._source = source
        self._handler = handler
        self._store = store
        self._state = state
        self._run_id = run_id
        self._stability_gated = stability_gated
        self._memory = lifecycle._stability

    @property
    def _dry(self) -> bool:
        return self._run_id is None

    def _key(self, path: str) -> _PathKey:
        return (self._principal_id, self._source.ingest_source_id, path)

    def _now(self) -> datetime:
        return self._lifecycle._clock()

    def _unit(self) -> UnitOfWork:
        return self._lifecycle._unit_of_work()

    # --- discovery and reads -------------------------------------------------

    def _listed(self) -> Iterator[FileWorkspaceEntry]:
        directory = _directory(self._source.path_prefix)
        after: str | None = None
        while True:
            page = self._store.list_directory(directory, after=after, page_size=_PAGE_SIZE)
            for entry in page.entries:
                if entry.kind is EntryKind.FILE and fnmatch.fnmatchcase(
                    entry.name, self._source.file_pattern
                ):
                    yield entry
            if page.next_after is None:
                return
            after = page.next_after

    def _candidates(self, paths: Sequence[str] | None) -> list[FileWorkspaceEntry]:
        if paths is None:
            return sorted(self._listed(), key=lambda entry: entry.path)
        entries: list[FileWorkspaceEntry] = []
        for path in paths:
            try:
                entry = self._store.stat(path)
            except FilesDomainError:
                self._state.counts["snapshots_seen"] += 1
                self._state.skip("skipped_missing")
                continue
            if entry.kind is not EntryKind.FILE:
                self._state.counts["snapshots_seen"] += 1
                self._state.skip("skipped_missing")
                continue
            entries.append(entry)
        return entries

    def _read(self, entry: FileWorkspaceEntry) -> _Read | None:
        """The whole file, bound to the observed version; `None` (counted) when it moved."""
        reader = None
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        try:
            reader = self._store.open_download(entry.path, expected_version=entry.version)
            for chunk in reader.read_range(0, reader.size):
                digest.update(chunk)
                chunks.append(chunk)
        except FilesRefusal as refusal:
            self._state.skip(
                "skipped_changing" if refusal.reason in _CHANGING else "skipped_unreadable"
            )
            return None
        except (FilesDomainError, FileWorkspaceUnavailableError):
            self._state.skip("skipped_unreadable")
            return None
        finally:
            if reader is not None:
                reader.close()
        data = b"".join(chunks)
        if len(data) != entry.size:
            self._state.skip("skipped_changing")
            return None
        return _Read(entry.path, entry, data, digest.hexdigest())

    def _held_still(self, entry: FileWorkspaceEntry) -> bool:
        try:
            again = self._store.stat(entry.path)
        except (FilesDomainError, FileWorkspaceUnavailableError):
            return False
        return (again.size, again.version) == (entry.size, entry.version)

    def _finished(self, read: _Read) -> None:
        if not self._dry and read.entry.size is not None:
            self._memory.finished[self._key(read.path)] = (read.entry.size, read.entry.version)

    # --- the run -------------------------------------------------------------

    def execute(self, paths: Sequence[str] | None) -> None:
        try:
            candidates = self._candidates(paths)
        except (FilesDomainError, FileWorkspaceUnavailableError):
            self._state.listing_failed = True
            return
        fresh: dict[str, list[_Read]] = {}
        for entry in candidates:
            self._state.counts["snapshots_seen"] += 1
            read = self._admit_candidate(entry)
            if read is None:
                continue
            if read.digest in fresh:
                fresh[read.digest].append(read)
                continue
            if self._known(read):
                continue
            fresh[read.digest] = [read]
        accepted: list[_Accepted] = []
        for digest in sorted(fresh):
            reads = tuple(fresh[digest])
            self._state.counts["snapshots_new"] += 1
            prepared = self._prepare(reads)
            if prepared is None:
                continue
            if prepared.rejection_code is not None:
                self._reject(reads, prepared)
            else:
                accepted.append(_Accepted(reads, prepared))
        for item in sorted(accepted, key=lambda a: a.order):
            self._ingest(item)

    def _admit_candidate(self, entry: FileWorkspaceEntry) -> _Read | None:
        size = entry.size
        if size is None:
            self._state.skip("skipped_missing")
            return None
        shape = (size, entry.version)
        key = self._key(entry.path)
        if not self._dry and self._memory.finished.get(key) == shape:
            self._state.skip("skipped_unchanged")
            return None
        if self._stability_gated and not self._memory.stable(key, shape):
            self._state.skip("skipped_unstable")
            return None
        if size > self._handler.max_bytes:
            self._state.skip("skipped_too_large")
            if not self._dry:
                self._memory.finished[key] = shape
            return None
        return self._read(entry)

    def _prepare(self, reads: tuple[_Read, ...]) -> IngestPrepared | None:
        primary = reads[0]
        try:
            prepared = self._handler.prepare(primary.data)
        except Exception:  # one file's failure never stops the run
            self._state.counts["snapshots_failed"] += 1
            return None
        if prepared.rejection_code is not None and not all(
            self._held_still(read.entry) for read in reads
        ):
            # Refused while still changing: retried on a later run, never rejected.
            for read in reads:
                self._state.skip("skipped_changing")
                if not self._dry:
                    self._memory.forget(self._key(read.path))
            self._state.counts["snapshots_new"] -= 1
            return None
        return prepared

    # --- snapshot transactions ---------------------------------------------

    def _link(
        self,
        ingestion: IngestionRepository,
        snapshot_id: str,
        outcome: IngestRunSnapshotOutcome,
    ) -> None:
        if self._run_id is None or snapshot_id in self._state.linked:
            return
        ingestion.link_run_snapshot(
            self._principal_id,
            IngestRunSnapshotRecord(
                run_id=self._run_id,
                snapshot_id=snapshot_id,
                ingest_source_id=self._source.ingest_source_id,
                outcome=outcome,
                recorded_at=self._now(),
            ),
        )

    def _place(
        self, ingestion: IngestionRepository, snapshot_id: str, path: str, *, alias: bool
    ) -> None:
        """Record `snapshot_id` as current at `path` (module docstring, path bookkeeping)."""
        principal_id, source_id = self._principal_id, self._source.ingest_source_id
        current = ingestion.current_path(principal_id, source_id, path)
        if current is not None and current.snapshot_id == snapshot_id:
            return
        if alias and ingestion.find_snapshot_path(principal_id, snapshot_id, path) is not None:
            self._state.counts["snapshots_path_reverted"] += 1
            return
        now = self._now()
        if current is not None:
            self._state.counts["snapshots_superseded"] += 1
            if not self._dry:
                ingestion.supersede_path(
                    principal_id,
                    current.snapshot_id,
                    path,
                    superseded_by_snapshot_id=snapshot_id,
                    superseded_at=now,
                )
        if alias:
            self._state.counts["snapshots_aliased"] += 1
        if not self._dry:
            ingestion.insert_snapshot_path(
                principal_id,
                IngestSnapshotPathRecord(
                    snapshot_id=snapshot_id,
                    ingest_source_id=source_id,
                    relative_path=path,
                    first_seen_at=now,
                ),
            )

    def _known(self, read: _Read) -> bool:
        """Handle a digest the source already holds; `False` when it is new.

        A failure of this transaction (the path bookkeeping or the run link) is
        counted `snapshots_failed` and rolls back alone, like any snapshot's.
        """
        counts_before = Counter(self._state.counts)
        try:
            with self._unit() as unit:
                known = unit.ingestion.find_snapshot(
                    self._principal_id, self._source.ingest_source_id, read.digest
                )
                if known is None:
                    return False
                self._state.counts["snapshots_already_known"] += 1
                self._place(unit.ingestion, known.snapshot_id, read.path, alias=True)
                self._link(
                    unit.ingestion, known.snapshot_id, IngestRunSnapshotOutcome.ALREADY_KNOWN
                )
        except Exception:  # this snapshot's bookkeeping rolls back; the run continues
            self._state.counts = counts_before
            self._state.counts["snapshots_failed"] += 1
            return True
        self._state.linked.add(known.snapshot_id)
        self._finished(read)
        return True

    def _new_snapshot(self, ingestion: IngestionRepository, primary: _Read) -> IngestSnapshotRecord:
        snapshot = IngestSnapshotRecord(
            snapshot_id=issue_identifier(IdKind.INGEST_SNAPSHOT),
            ingest_source_id=self._source.ingest_source_id,
            file_sha256=primary.digest,
            byte_count=len(primary.data),
            observed_version_token=primary.entry.version,
            first_seen_at=self._now(),
        )
        if not self._dry:
            ingestion.insert_snapshot(self._principal_id, snapshot)
        return snapshot

    def _reject(self, reads: tuple[_Read, ...], prepared: IngestPrepared) -> None:
        self._state.counts["snapshots_rejected"] += 1
        if self._dry:
            return
        try:
            with self._unit() as unit:
                ingestion = unit.ingestion
                snapshot = self._new_snapshot(ingestion, reads[0])
                ingestion.finalize_snapshot(
                    self._principal_id,
                    snapshot.snapshot_id,
                    status=IngestSnapshotStatus.REJECTED,
                    rejection_code=prepared.rejection_code,
                    parser_version=self._handler.parser_version,
                )
                for index, read in enumerate(reads):
                    self._place(ingestion, snapshot.snapshot_id, read.path, alias=index > 0)
                self._link(ingestion, snapshot.snapshot_id, IngestRunSnapshotOutcome.REJECTED)
        except Exception:  # this snapshot rolls back; the run continues
            self._state.counts["snapshots_rejected"] -= 1
            self._state.counts["snapshots_failed"] += 1
            return
        self._state.linked.add(snapshot.snapshot_id)
        for read in reads:
            self._finished(read)

    def _ingest(self, item: _Accepted) -> None:
        prepared, reads = item.prepared, item.reads
        if self._dry:
            self._state.counts["snapshots_ingested"] += 1
            self._state.add_records(prepared.record_counts)
            return
        counts_before = Counter(self._state.counts)
        try:
            with self._unit() as unit:
                ingestion = unit.ingestion
                snapshot = self._new_snapshot(ingestion, reads[0])
                for index, read in enumerate(reads):
                    self._place(ingestion, snapshot.snapshot_id, read.path, alias=index > 0)
                applied = self._handler.apply(unit, self._principal_id, snapshot, prepared)
                coverage = prepared.coverage
                if coverage is not None:
                    ingestion.insert_coverage_window(
                        self._principal_id,
                        IngestCoverageWindowRecord(
                            coverage_window_id=issue_identifier(IdKind.INGEST_COVERAGE_WINDOW),
                            ingest_source_id=self._source.ingest_source_id,
                            snapshot_id=snapshot.snapshot_id,
                            start_utc=coverage.start_utc,
                            end_utc=coverage.end_utc,
                            coverage_state=coverage.coverage_state,
                            lane_states=coverage.lane_states,
                            recorded_at=self._now(),
                        ),
                    )
                ingestion.finalize_snapshot(
                    self._principal_id,
                    snapshot.snapshot_id,
                    status=IngestSnapshotStatus.INGESTED,
                    rejection_code=None,
                    parser_version=self._handler.parser_version,
                )
                self._link(ingestion, snapshot.snapshot_id, IngestRunSnapshotOutcome.INGESTED)
        except Exception:  # this snapshot rolls back; the run continues
            # Counts the rolled-back transaction would have contributed are undone.
            self._state.counts = counts_before
            self._state.counts["snapshots_failed"] += 1
            return
        self._state.counts["snapshots_ingested"] += 1
        self._state.add_records(applied.record_counts)
        self._state.linked.add(snapshot.snapshot_id)
        for read in reads:
            self._finished(read)
