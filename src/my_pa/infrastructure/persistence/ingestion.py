"""The ingestion lifecycle tables, behind `contracts.ports.IngestionRepository` (WP3a).

Six tables are reached here and nowhere else: `ingest_sources`,
`ingest_snapshots`, `ingest_snapshot_paths`, `ingest_runs`,
`ingest_run_snapshots` and `ingest_coverage_windows` (contract sections 1.2 and
1.3, revision `52a829ef718a`). The lifecycle is consumer-neutral: nothing here
knows what a snapshot's bytes mean.

**The partition is reached through the guard, never written by hand.** The
`persistence/meetings.py` idiom: every SELECT, UPDATE and DELETE composes `_mine`
(a one-line wrapper over `partition_criterion`) and every INSERT composes
`_bound` (a one-line wrapper over `principal_bound_values`). The Principal is a
parameter; nothing here reads it back from a row or a record.

**The database guards are the authority.** A second finalization, a second
supersession or a second finish is refused by the revision's triggers with
`restrict_violation`; this module does not pre-check and absorb it, so the
caller sees the refusal. A missing row on a targeted update is
`RepositoryFailureError`.

**The operator aggregate.** `ingest_aggregate` is the one read here outside the
port: counts by closed code over a set of sources, for the operator CLI's
`aggregate` and monitoring reads (contract section 19). It returns counts and
closed codes only, never a path, a digest or an identifier.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from sqlalchemy import ColumnElement, Table, func, insert, select, update
from sqlalchemy.engine import Connection, Result, Row

from my_pa.contracts.ports import (
    IngestConsumer,
    IngestCoverageWindowRecord,
    IngestionRepository,
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
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    ingest_coverage_windows,
    ingest_run_snapshots,
    ingest_runs,
    ingest_snapshot_paths,
    ingest_snapshots,
    ingest_sources,
)

__all__ = ["SqlIngestionRepository", "ingest_aggregate"]


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


_SOURCE_COLUMNS: Final = (
    ingest_sources.c.ingest_source_id,
    ingest_sources.c.consumer,
    ingest_sources.c.workspace_id,
    ingest_sources.c.path_prefix,
    ingest_sources.c.file_pattern,
    ingest_sources.c.enabled,
    ingest_sources.c.admitted_at,
    ingest_sources.c.admitted_by,
)

_SNAPSHOT_COLUMNS: Final = (
    ingest_snapshots.c.snapshot_id,
    ingest_snapshots.c.ingest_source_id,
    ingest_snapshots.c.file_sha256,
    ingest_snapshots.c.byte_count,
    ingest_snapshots.c.observed_version_token,
    ingest_snapshots.c.first_seen_at,
    ingest_snapshots.c.status,
    ingest_snapshots.c.rejection_code,
    ingest_snapshots.c.parser_version,
)

_PATH_COLUMNS: Final = (
    ingest_snapshot_paths.c.snapshot_id,
    ingest_snapshot_paths.c.ingest_source_id,
    ingest_snapshot_paths.c.relative_path,
    ingest_snapshot_paths.c.first_seen_at,
    ingest_snapshot_paths.c.superseded_by_snapshot_id,
    ingest_snapshot_paths.c.superseded_at,
)

_RUN_COLUMNS: Final = (
    ingest_runs.c.run_id,
    ingest_runs.c.ingest_source_id,
    ingest_runs.c.trigger,
    ingest_runs.c.started_at,
    ingest_runs.c.finished_at,
    ingest_runs.c.outcome,
    ingest_runs.c.counts,
)

_RUN_SNAPSHOT_COLUMNS: Final = (
    ingest_run_snapshots.c.run_id,
    ingest_run_snapshots.c.snapshot_id,
    ingest_run_snapshots.c.ingest_source_id,
    ingest_run_snapshots.c.outcome,
    ingest_run_snapshots.c.recorded_at,
)

_COVERAGE_COLUMNS: Final = (
    ingest_coverage_windows.c.coverage_window_id,
    ingest_coverage_windows.c.ingest_source_id,
    ingest_coverage_windows.c.snapshot_id,
    ingest_coverage_windows.c.start_utc,
    ingest_coverage_windows.c.end_utc,
    ingest_coverage_windows.c.coverage_state,
    ingest_coverage_windows.c.lane_states,
    ingest_coverage_windows.c.recorded_at,
)


def _to_source(row: Row[Any]) -> IngestSourceRecord:
    return IngestSourceRecord(
        ingest_source_id=row.ingest_source_id,
        consumer=IngestConsumer(row.consumer),
        workspace_id=row.workspace_id,
        path_prefix=row.path_prefix,
        file_pattern=row.file_pattern,
        enabled=row.enabled,
        admitted_at=row.admitted_at,
        admitted_by=row.admitted_by,
    )


def _to_snapshot(row: Row[Any]) -> IngestSnapshotRecord:
    return IngestSnapshotRecord(
        snapshot_id=row.snapshot_id,
        ingest_source_id=row.ingest_source_id,
        file_sha256=row.file_sha256,
        byte_count=row.byte_count,
        observed_version_token=row.observed_version_token,
        first_seen_at=row.first_seen_at,
        status=IngestSnapshotStatus(row.status),
        rejection_code=row.rejection_code,
        parser_version=row.parser_version,
    )


def _to_path(row: Row[Any]) -> IngestSnapshotPathRecord:
    return IngestSnapshotPathRecord(
        snapshot_id=row.snapshot_id,
        ingest_source_id=row.ingest_source_id,
        relative_path=row.relative_path,
        first_seen_at=row.first_seen_at,
        superseded_by_snapshot_id=row.superseded_by_snapshot_id,
        superseded_at=row.superseded_at,
    )


def _to_run(row: Row[Any]) -> IngestRunRecord:
    return IngestRunRecord(
        run_id=row.run_id,
        ingest_source_id=row.ingest_source_id,
        trigger=IngestRunTrigger(row.trigger),
        started_at=row.started_at,
        finished_at=row.finished_at,
        outcome=None if row.outcome is None else IngestRunOutcome(row.outcome),
        counts=None if row.counts is None else dict(row.counts),
    )


def _to_run_snapshot(row: Row[Any]) -> IngestRunSnapshotRecord:
    return IngestRunSnapshotRecord(
        run_id=row.run_id,
        snapshot_id=row.snapshot_id,
        ingest_source_id=row.ingest_source_id,
        outcome=IngestRunSnapshotOutcome(row.outcome),
        recorded_at=row.recorded_at,
    )


def _to_coverage(row: Row[Any]) -> IngestCoverageWindowRecord:
    return IngestCoverageWindowRecord(
        coverage_window_id=row.coverage_window_id,
        ingest_source_id=row.ingest_source_id,
        snapshot_id=row.snapshot_id,
        start_utc=row.start_utc,
        end_utc=row.end_utc,
        coverage_state=row.coverage_state,
        lane_states=tuple(dict(lane) for lane in row.lane_states),
        recorded_at=row.recorded_at,
    )


class SqlIngestionRepository(IngestionRepository):
    """`IngestionRepository`, over the general unit of work's `Connection`.

    Takes the connection rather than opening one: the caller owns the
    transaction, and this class only issues statements on it. Nothing here
    commits.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # --- sources -------------------------------------------------------------

    def insert_source(self, principal_id: str, source: IngestSourceRecord) -> None:
        self._connection.execute(
            insert(ingest_sources).values(
                _bound(
                    ingest_sources,
                    principal_id,
                    {
                        "ingest_source_id": source.ingest_source_id,
                        "consumer": source.consumer.value,
                        "workspace_id": source.workspace_id,
                        "path_prefix": source.path_prefix,
                        "file_pattern": source.file_pattern,
                        "enabled": source.enabled,
                        "admitted_at": source.admitted_at,
                        "admitted_by": source.admitted_by,
                    },
                )
            )
        )

    def get_source(self, principal_id: str, ingest_source_id: str) -> IngestSourceRecord | None:
        row = self._connection.execute(
            select(*_SOURCE_COLUMNS).where(
                _mine(ingest_sources, principal_id),
                ingest_sources.c.ingest_source_id == ingest_source_id,
            )
        ).one_or_none()
        return None if row is None else _to_source(row)

    def list_sources(
        self, principal_id: str, *, enabled_only: bool = False
    ) -> tuple[IngestSourceRecord, ...]:
        statement = select(*_SOURCE_COLUMNS).where(_mine(ingest_sources, principal_id))
        if enabled_only:
            statement = statement.where(ingest_sources.c.enabled.is_(True))
        rows = self._connection.execute(statement.order_by(ingest_sources.c.ingest_source_id))
        return tuple(_to_source(row) for row in rows)

    def set_source_enabled(self, principal_id: str, ingest_source_id: str, enabled: bool) -> None:
        changed = self._connection.execute(
            update(ingest_sources)
            .where(
                _mine(ingest_sources, principal_id),
                ingest_sources.c.ingest_source_id == ingest_source_id,
            )
            .values(enabled=enabled)
            .returning(ingest_sources.c.ingest_source_id)
        ).first()
        if changed is None:
            raise RepositoryFailureError

    # --- snapshots -----------------------------------------------------------

    def find_snapshot(
        self, principal_id: str, ingest_source_id: str, file_sha256: str
    ) -> IngestSnapshotRecord | None:
        row = self._connection.execute(
            select(*_SNAPSHOT_COLUMNS).where(
                _mine(ingest_snapshots, principal_id),
                ingest_snapshots.c.ingest_source_id == ingest_source_id,
                ingest_snapshots.c.file_sha256 == file_sha256,
            )
        ).one_or_none()
        return None if row is None else _to_snapshot(row)

    def get_snapshot(self, principal_id: str, snapshot_id: str) -> IngestSnapshotRecord | None:
        row = self._connection.execute(
            select(*_SNAPSHOT_COLUMNS).where(
                _mine(ingest_snapshots, principal_id),
                ingest_snapshots.c.snapshot_id == snapshot_id,
            )
        ).one_or_none()
        return None if row is None else _to_snapshot(row)

    def list_snapshots(
        self, principal_id: str, ingest_source_id: str
    ) -> tuple[IngestSnapshotRecord, ...]:
        rows = self._connection.execute(
            select(*_SNAPSHOT_COLUMNS)
            .where(
                _mine(ingest_snapshots, principal_id),
                ingest_snapshots.c.ingest_source_id == ingest_source_id,
            )
            .order_by(ingest_snapshots.c.first_seen_at, ingest_snapshots.c.snapshot_id)
        )
        return tuple(_to_snapshot(row) for row in rows)

    def insert_snapshot(self, principal_id: str, snapshot: IngestSnapshotRecord) -> None:
        self._connection.execute(
            insert(ingest_snapshots).values(
                _bound(
                    ingest_snapshots,
                    principal_id,
                    {
                        "snapshot_id": snapshot.snapshot_id,
                        "ingest_source_id": snapshot.ingest_source_id,
                        "file_sha256": snapshot.file_sha256,
                        "byte_count": snapshot.byte_count,
                        "observed_version_token": snapshot.observed_version_token,
                        "first_seen_at": snapshot.first_seen_at,
                        "status": snapshot.status.value,
                        "rejection_code": snapshot.rejection_code,
                        "parser_version": snapshot.parser_version,
                    },
                )
            )
        )

    def finalize_snapshot(
        self,
        principal_id: str,
        snapshot_id: str,
        *,
        status: IngestSnapshotStatus,
        rejection_code: str | None,
        parser_version: str | None,
    ) -> None:
        changed = self._connection.execute(
            update(ingest_snapshots)
            .where(
                _mine(ingest_snapshots, principal_id),
                ingest_snapshots.c.snapshot_id == snapshot_id,
            )
            .values(
                status=status.value,
                rejection_code=rejection_code,
                parser_version=parser_version,
            )
            .returning(ingest_snapshots.c.snapshot_id)
        ).first()
        if changed is None:
            raise RepositoryFailureError

    # --- paths ---------------------------------------------------------------

    def insert_snapshot_path(self, principal_id: str, path: IngestSnapshotPathRecord) -> None:
        self._connection.execute(
            insert(ingest_snapshot_paths).values(
                _bound(
                    ingest_snapshot_paths,
                    principal_id,
                    {
                        "snapshot_id": path.snapshot_id,
                        "ingest_source_id": path.ingest_source_id,
                        "relative_path": path.relative_path,
                        "first_seen_at": path.first_seen_at,
                        "superseded_by_snapshot_id": path.superseded_by_snapshot_id,
                        "superseded_at": path.superseded_at,
                    },
                )
            )
        )

    def current_path(
        self, principal_id: str, ingest_source_id: str, relative_path: str
    ) -> IngestSnapshotPathRecord | None:
        row = self._connection.execute(
            select(*_PATH_COLUMNS).where(
                _mine(ingest_snapshot_paths, principal_id),
                ingest_snapshot_paths.c.ingest_source_id == ingest_source_id,
                ingest_snapshot_paths.c.relative_path == relative_path,
                ingest_snapshot_paths.c.superseded_by_snapshot_id.is_(None),
            )
        ).one_or_none()
        return None if row is None else _to_path(row)

    def supersede_path(
        self,
        principal_id: str,
        snapshot_id: str,
        relative_path: str,
        *,
        superseded_by_snapshot_id: str,
        superseded_at: datetime,
    ) -> None:
        changed = self._connection.execute(
            update(ingest_snapshot_paths)
            .where(
                _mine(ingest_snapshot_paths, principal_id),
                ingest_snapshot_paths.c.snapshot_id == snapshot_id,
                ingest_snapshot_paths.c.relative_path == relative_path,
            )
            .values(
                superseded_by_snapshot_id=superseded_by_snapshot_id,
                superseded_at=superseded_at,
            )
            .returning(ingest_snapshot_paths.c.snapshot_id)
        ).first()
        if changed is None:
            raise RepositoryFailureError

    def list_snapshot_paths(
        self, principal_id: str, ingest_source_id: str
    ) -> tuple[IngestSnapshotPathRecord, ...]:
        rows = self._connection.execute(
            select(*_PATH_COLUMNS)
            .where(
                _mine(ingest_snapshot_paths, principal_id),
                ingest_snapshot_paths.c.ingest_source_id == ingest_source_id,
            )
            .order_by(
                ingest_snapshot_paths.c.relative_path,
                ingest_snapshot_paths.c.first_seen_at,
                ingest_snapshot_paths.c.snapshot_id,
            )
        )
        return tuple(_to_path(row) for row in rows)

    def find_snapshot_path(
        self, principal_id: str, snapshot_id: str, relative_path: str
    ) -> IngestSnapshotPathRecord | None:
        row = self._connection.execute(
            select(*_PATH_COLUMNS).where(
                _mine(ingest_snapshot_paths, principal_id),
                ingest_snapshot_paths.c.snapshot_id == snapshot_id,
                ingest_snapshot_paths.c.relative_path == relative_path,
            )
        ).one_or_none()
        return None if row is None else _to_path(row)

    # --- runs ----------------------------------------------------------------

    def insert_run(self, principal_id: str, run: IngestRunRecord) -> None:
        if run.finished_at is not None or run.outcome is not None or run.counts is not None:
            # A run is started unfinished; `finish_run` sets the three together.
            raise ValueError("insert_run takes an unfinished run")
        values: dict[str, object] = {
            "run_id": run.run_id,
            "ingest_source_id": run.ingest_source_id,
            "trigger": run.trigger.value,
            "started_at": run.started_at,
        }
        self._connection.execute(
            insert(ingest_runs).values(_bound(ingest_runs, principal_id, values))
        )

    def get_run(self, principal_id: str, run_id: str) -> IngestRunRecord | None:
        row = self._connection.execute(
            select(*_RUN_COLUMNS).where(
                _mine(ingest_runs, principal_id), ingest_runs.c.run_id == run_id
            )
        ).one_or_none()
        return None if row is None else _to_run(row)

    def finish_run(
        self,
        principal_id: str,
        run_id: str,
        *,
        finished_at: datetime,
        outcome: IngestRunOutcome,
        counts: Mapping[str, int],
    ) -> None:
        changed = self._connection.execute(
            update(ingest_runs)
            .where(_mine(ingest_runs, principal_id), ingest_runs.c.run_id == run_id)
            .values(finished_at=finished_at, outcome=outcome.value, counts=dict(counts))
            .returning(ingest_runs.c.run_id)
        ).first()
        if changed is None:
            raise RepositoryFailureError

    def link_run_snapshot(self, principal_id: str, link: IngestRunSnapshotRecord) -> None:
        self._connection.execute(
            insert(ingest_run_snapshots).values(
                _bound(
                    ingest_run_snapshots,
                    principal_id,
                    {
                        "run_id": link.run_id,
                        "snapshot_id": link.snapshot_id,
                        "ingest_source_id": link.ingest_source_id,
                        "outcome": link.outcome.value,
                        "recorded_at": link.recorded_at,
                    },
                )
            )
        )

    def list_run_snapshots(
        self, principal_id: str, run_id: str
    ) -> tuple[IngestRunSnapshotRecord, ...]:
        rows = self._connection.execute(
            select(*_RUN_SNAPSHOT_COLUMNS)
            .where(
                _mine(ingest_run_snapshots, principal_id),
                ingest_run_snapshots.c.run_id == run_id,
            )
            .order_by(ingest_run_snapshots.c.recorded_at, ingest_run_snapshots.c.snapshot_id)
        )
        return tuple(_to_run_snapshot(row) for row in rows)

    # --- coverage --------------------------------------------------------------

    def insert_coverage_window(self, principal_id: str, window: IngestCoverageWindowRecord) -> None:
        self._connection.execute(
            insert(ingest_coverage_windows).values(
                _bound(
                    ingest_coverage_windows,
                    principal_id,
                    {
                        "coverage_window_id": window.coverage_window_id,
                        "ingest_source_id": window.ingest_source_id,
                        "snapshot_id": window.snapshot_id,
                        "start_utc": window.start_utc,
                        "end_utc": window.end_utc,
                        "coverage_state": window.coverage_state,
                        "lane_states": [dict(lane) for lane in window.lane_states],
                        "recorded_at": window.recorded_at,
                    },
                )
            )
        )

    def list_coverage_windows(
        self, principal_id: str, ingest_source_id: str
    ) -> tuple[IngestCoverageWindowRecord, ...]:
        rows = self._connection.execute(
            select(*_COVERAGE_COLUMNS)
            .where(
                _mine(ingest_coverage_windows, principal_id),
                ingest_coverage_windows.c.ingest_source_id == ingest_source_id,
            )
            .order_by(
                ingest_coverage_windows.c.start_utc,
                ingest_coverage_windows.c.end_utc,
                ingest_coverage_windows.c.coverage_window_id,
            )
        )
        return tuple(_to_coverage(row) for row in rows)

    def get_coverage_window(
        self, principal_id: str, snapshot_id: str
    ) -> IngestCoverageWindowRecord | None:
        row = self._connection.execute(
            select(*_COVERAGE_COLUMNS).where(
                _mine(ingest_coverage_windows, principal_id),
                ingest_coverage_windows.c.snapshot_id == snapshot_id,
            )
        ).one_or_none()
        return None if row is None else _to_coverage(row)


def _grouped(
    connection: Connection,
    *columns: ColumnElement[Any],
    where: Sequence[ColumnElement[bool]],
) -> Result[Any]:
    return connection.execute(
        select(*columns, func.count()).where(*where).group_by(*columns).order_by(*columns)
    )


def ingest_aggregate(
    connection: Connection, principal_id: str, ingest_source_ids: Sequence[str]
) -> dict[str, object]:
    """Snapshot and run counts over `ingest_source_ids`, by closed code (module docstring).

    `snapshots` counts by status and `rejections` by rejection code;
    `superseded_paths` counts path rows a newer snapshot replaced; `runs`
    counts by `trigger` then `outcome` (`unfinished` for a run with no finish).
    """
    ids = sorted(set(ingest_source_ids))
    snapshots = _grouped(
        connection,
        ingest_snapshots.c.status,
        where=(
            _mine(ingest_snapshots, principal_id),
            ingest_snapshots.c.ingest_source_id.in_(ids),
        ),
    )
    rejections = _grouped(
        connection,
        ingest_snapshots.c.rejection_code,
        where=(
            _mine(ingest_snapshots, principal_id),
            ingest_snapshots.c.ingest_source_id.in_(ids),
            ingest_snapshots.c.rejection_code.is_not(None),
        ),
    )
    superseded = connection.execute(
        select(func.count()).where(
            _mine(ingest_snapshot_paths, principal_id),
            ingest_snapshot_paths.c.ingest_source_id.in_(ids),
            ingest_snapshot_paths.c.superseded_by_snapshot_id.is_not(None),
        )
    ).scalar_one()
    runs: dict[str, dict[str, int]] = {}
    for trigger, outcome, count in _grouped(
        connection,
        ingest_runs.c.trigger,
        ingest_runs.c.outcome,
        where=(_mine(ingest_runs, principal_id), ingest_runs.c.ingest_source_id.in_(ids)),
    ):
        runs.setdefault(str(trigger), {})[str(outcome or "unfinished")] = int(count)
    return {
        "snapshots": {str(status): int(count) for status, count in snapshots},
        "rejections": {str(code): int(count) for code, count in rejections},
        "superseded_paths": int(superseded),
        "runs": runs,
    }
