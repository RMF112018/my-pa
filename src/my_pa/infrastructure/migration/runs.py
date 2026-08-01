"""Reading and writing the control plane.

Every statement here is small and explicit. There is no ORM session, no unit of
work, and no repository interface: the callers are one loader and one CLI, and a
layer between them and eight tables would be an abstraction with one
implementation.

Two invariants are enforced rather than documented. A checkpoint's `batch_key`
and `watermark` must both advance, so a stale or replayed checkpoint cannot move
the resume point backwards. And a lease is taken with a single conditional
statement, so two writers cannot both believe they hold one table.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Connection, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.infrastructure.migration.binding import RunBinding
from my_pa.infrastructure.migration.control_plane import (
    AuditEvent,
    PhaseStatus,
    QuarantineCode,
    RunStatus,
    TableState,
    audit_events,
    batch_checkpoints,
    identifier_map,
    leases,
    migration_runs,
    phase_status,
    quarantine_records,
    source_key_map,
    table_progress,
)

#: Long enough that a slow batch does not lose its own lease, short enough that a
#: killed process does not block the next run for an afternoon.
DEFAULT_LEASE_SECONDS = 900


class ControlPlaneError(RuntimeError):
    """A control-plane invariant would be violated."""


@dataclass(frozen=True)
class RunRecord:
    """A run as recorded, with the binding it is pinned to."""

    run_id: str
    status: RunStatus
    dry_run: bool
    binding_sha256: str
    binding_bytes: int
    binding_schema_version: int
    binding_revision: str
    created_at: datetime


@dataclass(frozen=True)
class Checkpoint:
    """The furthest committed batch for one table, and the totals behind it."""

    batch_key: int
    watermark: int
    rows_ok: int
    rows_quarantined: int


@dataclass(frozen=True)
class QuarantineEntry:
    """One refused row, by hash. Carries no value from the row."""

    legacy_table: str
    column_name: str | None
    natural_key_hash: str
    error_code: QuarantineCode
    error_class: str


def create_run(connection: Connection, binding: RunBinding, *, dry_run: bool) -> str:
    """Record a new run bound to `binding` and return its id."""
    run_id = str(uuid.uuid4())
    connection.execute(
        insert(migration_runs).values(
            run_id=run_id,
            source_sha256=binding.source_sha256,
            source_bytes=binding.source_bytes,
            source_schema_version=binding.source_schema_version,
            target_alembic_revision=binding.target_alembic_revision,
            status=RunStatus.PENDING.value,
            dry_run=dry_run,
        )
    )
    record_event(connection, run_id, AuditEvent.RUN_CREATED, code=binding.source_sha256[:12])
    return run_id


def read_run(connection: Connection, run_id: str) -> RunRecord:
    """Return the recorded run, or raise if there is none."""
    row = connection.execute(
        select(
            migration_runs.c.run_id,
            migration_runs.c.status,
            migration_runs.c.dry_run,
            migration_runs.c.source_sha256,
            migration_runs.c.source_bytes,
            migration_runs.c.source_schema_version,
            migration_runs.c.target_alembic_revision,
            migration_runs.c.created_at,
        ).where(migration_runs.c.run_id == run_id)
    ).one_or_none()
    if row is None:
        raise ControlPlaneError(f"no migration run {run_id}")
    return RunRecord(
        run_id=str(row.run_id),
        status=RunStatus(row.status),
        dry_run=bool(row.dry_run),
        binding_sha256=str(row.source_sha256),
        binding_bytes=int(row.source_bytes),
        binding_schema_version=int(row.source_schema_version),
        binding_revision=str(row.target_alembic_revision),
        created_at=row.created_at,
    )


def recorded_binding(run: RunRecord, source_path: Path) -> RunBinding:
    """Rebuild the binding a run was created with, for comparison against reality."""
    return RunBinding(
        source_path=source_path,
        source_sha256=run.binding_sha256,
        source_bytes=run.binding_bytes,
        source_schema_version=run.binding_schema_version,
        target_alembic_revision=run.binding_revision,
    )


def set_run_status(connection: Connection, run_id: str, status: RunStatus) -> None:
    """Move a run to `status`, stamping the matching timestamp."""
    values: dict[str, object] = {"status": status.value}
    if status is RunStatus.RUNNING:
        values["started_at"] = func.now()
    if status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
        values["completed_at"] = func.now()
    connection.execute(
        update(migration_runs).where(migration_runs.c.run_id == run_id).values(**values)
    )


def record_event(
    connection: Connection,
    run_id: str | None,
    event_type: AuditEvent,
    *,
    phase: str | None = None,
    legacy_table: str | None = None,
    code: str | None = None,
    row_count: int | None = None,
) -> None:
    """Append an audit event. Codes and counts only; never a payload."""
    connection.execute(
        insert(audit_events).values(
            run_id=run_id,
            phase=phase,
            legacy_table=legacy_table,
            event_type=event_type.value,
            code=code,
            row_count=row_count,
        )
    )


def start_phase(connection: Connection, run_id: str, phase: str, *, tables_total: int) -> None:
    """Mark a phase running, creating its row on first sight."""
    statement = (
        pg_insert(phase_status)
        .values(
            run_id=run_id,
            phase=phase,
            status=PhaseStatus.RUNNING.value,
            started_at=func.now(),
            tables_total=tables_total,
        )
        .on_conflict_do_update(
            index_elements=["run_id", "phase"],
            set_={"status": PhaseStatus.RUNNING.value, "tables_total": tables_total},
        )
    )
    connection.execute(statement)
    record_event(connection, run_id, AuditEvent.PHASE_STARTED, phase=phase, row_count=tables_total)


def finish_phase(connection: Connection, run_id: str, phase: str, status: PhaseStatus) -> None:
    """Close a phase and roll its tables' counters up into it."""
    totals = connection.execute(
        select(
            func.count(),
            func.coalesce(func.sum(table_progress.c.loaded_row_count), 0),
            func.coalesce(func.sum(table_progress.c.quarantined_row_count), 0),
        ).where(
            table_progress.c.run_id == run_id,
            table_progress.c.phase == phase,
            table_progress.c.state == TableState.COMPLETED.value,
        )
    ).one()
    connection.execute(
        update(phase_status)
        .where(phase_status.c.run_id == run_id, phase_status.c.phase == phase)
        .values(
            status=status.value,
            completed_at=func.now(),
            tables_completed=int(totals[0]),
            rows_ok=int(totals[1]),
            rows_quarantined=int(totals[2]),
        )
    )
    record_event(
        connection,
        run_id,
        AuditEvent.PHASE_COMPLETED,
        phase=phase,
        code=status.value,
        row_count=int(totals[1]),
    )


def open_phases(connection: Connection, run_id: str) -> tuple[str, ...]:
    """Return the phases of a run that are not COMPLETED, in order."""
    rows = connection.execute(
        select(phase_status.c.phase)
        .where(
            phase_status.c.run_id == run_id,
            phase_status.c.status != PhaseStatus.COMPLETED.value,
        )
        .order_by(phase_status.c.phase)
    ).scalars()
    return tuple(str(phase) for phase in rows)


def begin_table(
    connection: Connection,
    run_id: str,
    plan_table: str,
    phase: str,
    *,
    source_row_count: int,
) -> None:
    """Mark a table running, creating its progress row on first sight."""
    statement = (
        pg_insert(table_progress)
        .values(
            run_id=run_id,
            legacy_table=plan_table,
            phase=phase,
            state=TableState.RUNNING.value,
            source_row_count=source_row_count,
            started_at=func.now(),
        )
        .on_conflict_do_update(
            index_elements=["run_id", "legacy_table"],
            set_={"state": TableState.RUNNING.value, "source_row_count": source_row_count},
        )
    )
    connection.execute(statement)
    record_event(
        connection,
        run_id,
        AuditEvent.TABLE_STARTED,
        phase=phase,
        legacy_table=plan_table,
        row_count=source_row_count,
    )


def finish_table(
    connection: Connection,
    run_id: str,
    plan_table: str,
    state: TableState,
    *,
    loaded: int,
    quarantined: int,
) -> None:
    """Close a table's progress row with its final counts."""
    connection.execute(
        update(table_progress)
        .where(table_progress.c.run_id == run_id, table_progress.c.legacy_table == plan_table)
        .values(
            state=state.value,
            loaded_row_count=loaded,
            quarantined_row_count=quarantined,
            completed_at=func.now(),
        )
    )
    record_event(
        connection,
        run_id,
        AuditEvent.TABLE_COMPLETED,
        legacy_table=plan_table,
        code=state.value,
        row_count=loaded,
    )


def fail_table(connection: Connection, run_id: str, plan_table: str) -> None:
    """Mark a table failed without disturbing the counts its checkpoints recorded."""
    connection.execute(
        update(table_progress)
        .where(table_progress.c.run_id == run_id, table_progress.c.legacy_table == plan_table)
        .values(state=TableState.FAILED.value, completed_at=func.now())
    )


def table_state(connection: Connection, run_id: str, plan_table: str) -> TableState | None:
    """Return a table's recorded state within a run, if it has one."""
    state = connection.execute(
        select(table_progress.c.state).where(
            table_progress.c.run_id == run_id, table_progress.c.legacy_table == plan_table
        )
    ).scalar_one_or_none()
    return None if state is None else TableState(state)


def last_checkpoint(
    connection: Connection, run_id: str, phase: str, plan_table: str
) -> Checkpoint | None:
    """Return the furthest committed batch for one table, or None if untouched."""
    row = connection.execute(
        select(
            func.max(batch_checkpoints.c.batch_key),
            func.max(batch_checkpoints.c.watermark),
            func.coalesce(func.sum(batch_checkpoints.c.rows_ok), 0),
            func.coalesce(func.sum(batch_checkpoints.c.rows_quarantined), 0),
        ).where(
            batch_checkpoints.c.run_id == run_id,
            batch_checkpoints.c.phase == phase,
            batch_checkpoints.c.legacy_table == plan_table,
        )
    ).one()
    if row[0] is None:
        return None
    return Checkpoint(
        batch_key=int(row[0]),
        watermark=int(row[1]),
        rows_ok=int(row[2]),
        rows_quarantined=int(row[3]),
    )


def record_checkpoint(
    connection: Connection,
    run_id: str,
    phase: str,
    plan_table: str,
    *,
    batch_key: int,
    watermark: int,
    rows_ok: int,
    rows_failed: int,
    rows_quarantined: int,
) -> None:
    """Commit a batch's checkpoint. Both the key and the watermark must advance."""
    previous = last_checkpoint(connection, run_id, phase, plan_table)
    if previous is not None and (
        batch_key <= previous.batch_key or watermark <= previous.watermark
    ):
        raise ControlPlaneError(
            f"checkpoint for {plan_table} would move backwards: "
            f"batch {batch_key} watermark {watermark} after "
            f"batch {previous.batch_key} watermark {previous.watermark}"
        )
    connection.execute(
        insert(batch_checkpoints).values(
            run_id=run_id,
            phase=phase,
            legacy_table=plan_table,
            batch_key=batch_key,
            watermark=watermark,
            rows_ok=rows_ok,
            rows_failed=rows_failed,
            rows_quarantined=rows_quarantined,
        )
    )


def acquire_lease(
    connection: Connection,
    run_id: str,
    resource_key: str,
    *,
    owner: str,
    seconds: int = DEFAULT_LEASE_SECONDS,
) -> None:
    """Take the lease on `resource_key`, or raise if another run holds a live one."""
    expires_at = datetime.now(UTC) + timedelta(seconds=seconds)
    statement = (
        pg_insert(leases)
        .values(resource_key=resource_key, run_id=run_id, owner=owner, expires_at=expires_at)
        .on_conflict_do_update(
            index_elements=["resource_key"],
            set_={
                "run_id": run_id,
                "owner": owner,
                "acquired_at": func.now(),
                "expires_at": expires_at,
            },
            where=(leases.c.expires_at <= func.now()) | (leases.c.run_id == run_id),
        )
        .returning(leases.c.resource_key)
    )
    if connection.execute(statement).scalar_one_or_none() is None:
        raise ControlPlaneError(f"{resource_key} is leased by another run")


def release_lease(connection: Connection, run_id: str, resource_key: str) -> None:
    """Give up a lease this run holds."""
    connection.execute(
        delete(leases).where(leases.c.resource_key == resource_key, leases.c.run_id == run_id)
    )


def known_key_hashes(
    connection: Connection, run_id: str, plan_table: str, hashes: Sequence[str]
) -> frozenset[str]:
    """Return which of `hashes` this run has already mapped for `plan_table`."""
    if not hashes:
        return frozenset()
    rows = connection.execute(
        select(source_key_map.c.natural_key_hash).where(
            source_key_map.c.run_id == run_id,
            source_key_map.c.legacy_table == plan_table,
            source_key_map.c.natural_key_hash.in_(list(hashes)),
        )
    ).scalars()
    return frozenset(str(value) for value in rows)


def record_source_keys(
    connection: Connection,
    run_id: str,
    plan_table: str,
    batch_key: int,
    entries: Sequence[tuple[str, str]],
) -> None:
    """Map natural-key hashes to target keys for one batch (OD-011)."""
    if not entries:
        return
    connection.execute(
        insert(source_key_map),
        [
            {
                "run_id": run_id,
                "legacy_table": plan_table,
                "natural_key_hash": key_hash,
                "target_key": target_key,
                "batch_key": batch_key,
            }
            for key_hash, target_key in entries
        ],
    )


def record_quarantine(
    connection: Connection, run_id: str, phase: str, entries: Sequence[QuarantineEntry]
) -> None:
    """Record refused rows. Table, column, code, class, and a key hash — nothing else."""
    if not entries:
        return
    connection.execute(
        insert(quarantine_records),
        [
            {
                "run_id": run_id,
                "phase": phase,
                "legacy_table": entry.legacy_table,
                "column_name": entry.column_name,
                "natural_key_hash": entry.natural_key_hash,
                "error_code": entry.error_code.value,
                "error_class": entry.error_class,
            }
            for entry in entries
        ],
    )


@dataclass(frozen=True)
class PhaseSummary:
    """One phase's recorded progress."""

    phase: str
    status: PhaseStatus
    tables_total: int
    tables_completed: int
    rows_ok: int
    rows_quarantined: int


@dataclass(frozen=True)
class RunSummary:
    """Everything `status` reports. Counts, states, and table names only."""

    run: RunRecord
    phases: tuple[PhaseSummary, ...]
    tables_by_state: tuple[tuple[str, int], ...]
    rows_loaded: int
    quarantine_by_code: tuple[tuple[str, int], ...]


def summarise(connection: Connection, run_id: str) -> RunSummary:
    """Read back a run's progress for the `status` command."""
    run = read_run(connection, run_id)
    phases = tuple(
        PhaseSummary(
            phase=str(row.phase),
            status=PhaseStatus(row.status),
            tables_total=int(row.tables_total),
            tables_completed=int(row.tables_completed),
            rows_ok=int(row.rows_ok),
            rows_quarantined=int(row.rows_quarantined),
        )
        for row in connection.execute(
            select(phase_status)
            .where(phase_status.c.run_id == run_id)
            .order_by(phase_status.c.phase)
        )
    )
    states = connection.execute(
        select(table_progress.c.state, func.count())
        .where(table_progress.c.run_id == run_id)
        .group_by(table_progress.c.state)
        .order_by(table_progress.c.state)
    ).all()
    loaded = connection.execute(
        select(func.coalesce(func.sum(table_progress.c.loaded_row_count), 0)).where(
            table_progress.c.run_id == run_id
        )
    ).scalar_one()
    codes = connection.execute(
        select(quarantine_records.c.error_code, func.count())
        .where(quarantine_records.c.run_id == run_id)
        .group_by(quarantine_records.c.error_code)
        .order_by(quarantine_records.c.error_code)
    ).all()
    return RunSummary(
        run=run,
        phases=phases,
        tables_by_state=tuple((str(state), int(count)) for state, count in states),
        rows_loaded=int(loaded),
        quarantine_by_code=tuple((str(code), int(count)) for code, count in codes),
    )


def seed_identifier_map(connection: Connection, renames: Iterable[dict[str, str]]) -> int:
    """Replace `identifier_map` with `renames`. Reference data, not run data."""
    rows = [
        {
            "object_kind": rename["object_kind"],
            "owning_table": rename["owner"],
            "original": rename["original"],
            "shortened": rename["shortened"],
        }
        for rename in renames
    ]
    connection.execute(delete(identifier_map))
    if rows:
        connection.execute(insert(identifier_map), rows)
    return len(rows)
