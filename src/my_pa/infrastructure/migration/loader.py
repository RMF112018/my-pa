"""The load: read a batch, transform it, commit it with its checkpoint.

The shape of this module follows three decisions.

*Batches are the unit of everything.* A batch's rows, its key map, its
quarantine records, and its checkpoint commit in one transaction, so a crash
leaves the target and the control plane agreeing exactly. Resume then needs no
reconciliation pass: it reads the last checkpoint's watermark and starts after
it.

*A bad row is quarantined, never dropped and never fatal.* SQLite permits a NULL
in a TEXT primary key and never enforced a declared foreign key, so the corpus
can contain rows PostgreSQL will refuse. Those are recorded by table, column,
error code, and a key *hash* — never a value — and the load continues. A load
that crashed on the first defect would never finish; one that silently skipped it
would be worse.

*COPY first, row-by-row only to isolate a failure.* `COPY` is how a batch lands.
If PostgreSQL refuses the batch, the transform missed something, so the batch is
rolled back to a savepoint and replayed one row at a time to find out which rows
are actually bad. That costs nothing on a clean batch and turns an aborted load
into a precise quarantine entry.

There is no worker pool and no parallelism. 3.3M rows on a local socket does not
need it, and `AGENTS.md` does not permit inventing it in case it might.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.migration import binding, runs
from my_pa.infrastructure.migration.control_plane import (
    AuditEvent,
    PhaseStatus,
    QuarantineCode,
    RunStatus,
    TableState,
)
from my_pa.infrastructure.migration.identifiers import qualify, quote
from my_pa.infrastructure.migration.natural_key import hash_values
from my_pa.infrastructure.migration.plan import (
    PROVENANCE_ONLY,
    ColumnPlan,
    TableLoadPlan,
    TargetType,
    build_plans,
)
from my_pa.infrastructure.migration.reader import (
    DEFAULT_BATCH_SIZE,
    Batch,
    count_rows,
    iter_batches,
    open_source,
)
from my_pa.infrastructure.migration.source import Disposition


class LoadError(RuntimeError):
    """The load cannot proceed correctly and will not proceed approximately."""


class _CastError(Exception):
    """A stored value has no defensible cast to its target column."""

    def __init__(self, column: str) -> None:
        super().__init__(column)
        self.column = column


@dataclass(frozen=True)
class TableOutcome:
    """What one table's load did."""

    legacy_table: str
    phase: str
    source_rows: int
    loaded: int
    quarantined: int
    batches: int
    skipped: bool


@dataclass
class LoadOutcome:
    """What a whole `load` call did. Counts and names only."""

    run_id: str
    dry_run: bool
    tables: list[TableOutcome] = field(default_factory=list)
    quarantine_by_code: dict[str, int] = field(default_factory=dict)

    @property
    def loaded(self) -> int:
        return sum(table.loaded for table in self.tables)

    @property
    def quarantined(self) -> int:
        return sum(table.quarantined for table in self.tables)


@dataclass
class _Row:
    """One transformed source row, or the reason it was refused."""

    key_hash: str
    target_key: str
    values: tuple[object, ...] | None
    quarantine: runs.QuarantineEntry | None


class _DuplicateGuard:
    """Refuses a second row claiming one natural key (HZ-ID-COLLISION).

    A committed load reads `source_key_map`, which survives a resume. A dry run
    has nothing committed to read, so it keeps the keys it has seen in memory for
    the length of one table.
    """

    def __init__(self, *, in_memory: bool) -> None:
        self._in_memory = in_memory
        self._seen: set[str] = set()

    def known(
        self, connection: Connection, run_id: str, legacy_table: str, hashes: Sequence[str]
    ) -> frozenset[str]:
        if self._in_memory:
            return frozenset(self._seen.intersection(hashes))
        return runs.known_key_hashes(connection, run_id, legacy_table, hashes)

    def accept(self, key_hash: str) -> None:
        if self._in_memory:
            self._seen.add(key_hash)


def _coerce(value: object, column: ColumnPlan) -> object:
    """Return `value` as its target type, or refuse it.

    SQLite stores a value's storage class, not its column's declared type, so a
    column declared INTEGER can hold text. OD-009 forbids coercing silently: a
    value that does not already belong in the target type is quarantined with its
    column, never rounded, parsed, or cast into place.
    """
    if value is None:
        return None
    match column.target_type:
        case TargetType.TEXT | TargetType.UUID:
            if isinstance(value, str):
                return value
        case TargetType.BIGINT | TargetType.INTEGER:
            if type(value) is int:
                return value
        case TargetType.DOUBLE_PRECISION:
            if type(value) is int or type(value) is float:
                return float(value)
        case TargetType.BOOLEAN:
            # The promotion rests on the source's own `CHECK (x IN (0, 1))`
            # (OD-015), so anything outside that domain contradicts the source.
            if type(value) is int and value in (0, 1):
                return bool(value)
    raise _CastError(column.source_name)


def _transform(
    plan: TableLoadPlan,
    row: Sequence[object],
    run_id: str,
    schema_version: int,
) -> _Row:
    """Turn one source row into target values, or into a quarantine entry."""
    by_source = dict(zip((column.source_name for column in plan.columns), row, strict=True))
    key_values = (
        [by_source[name] for name in plan.key_columns] if plan.has_natural_key else list(row)
    )
    key_hash = hash_values(key_values)
    if plan.has_natural_key:
        # The target keeps the legacy key columns verbatim (OD-011), so the
        # mapped target key is the legacy key itself, rendered for the ledger.
        target_key = "|".join("" if value is None else str(value) for value in key_values)
    else:
        target_key = key_hash

    if plan.has_natural_key:
        null_key = next(
            (name for name in plan.key_columns if by_source[name] is None),
            None,
        )
        if null_key is not None:
            # OD-023. Do not fabricate a key, substitute an empty string, or drop
            # the constraint to make the load pass.
            return _Row(
                key_hash,
                target_key,
                None,
                runs.QuarantineEntry(
                    legacy_table=plan.legacy_table,
                    column_name=null_key,
                    natural_key_hash=key_hash,
                    error_code=QuarantineCode.NULL_PRIMARY_KEY,
                    error_class="NullPrimaryKey",
                ),
            )

    try:
        values: list[object] = [
            _coerce(value, column) for column, value in zip(plan.columns, row, strict=True)
        ]
    except _CastError as exc:
        return _Row(
            key_hash,
            target_key,
            None,
            runs.QuarantineEntry(
                legacy_table=plan.legacy_table,
                column_name=exc.column,
                natural_key_hash=key_hash,
                error_code=QuarantineCode.TYPE_CAST_FAILURE,
                error_class="StorageClassMismatch",
            ),
        )

    values.extend([run_id, plan.legacy_table, schema_version, key_hash])
    if plan.row_hash_column is not None:
        values.append(key_hash)
    return _Row(key_hash, target_key, tuple(values), None)


def _classify_rejection(
    plan: TableLoadPlan, values: Sequence[object]
) -> tuple[QuarantineCode, str | None]:
    """Name why PostgreSQL refused a row the transform thought was fine.

    Run only on a row that already failed, so it costs nothing on a clean batch.
    The one cause worth naming is a NUL byte in a text value: SQLite stores
    U+0000 happily and PostgreSQL's `text` cannot represent it at any length, so
    the row is refused rather than quietly stripped of a byte of the owner's
    content.
    """
    for column, value in zip(plan.columns, values, strict=False):
        if column.target_type is TargetType.TEXT and isinstance(value, str) and "\x00" in value:
            return QuarantineCode.UNSUPPORTED_TEXT_NUL, column.source_name
    return QuarantineCode.TARGET_REJECTED_ROW, None


def _target_columns(plan: TableLoadPlan) -> tuple[str, ...]:
    names = [column.target_name for column in plan.columns]
    names.extend(plan.provenance_columns)
    if plan.row_hash_column is not None:
        names.append(plan.row_hash_column)
    return tuple(names)


def _copy_batch(
    connection: Connection, plan: TableLoadPlan, rows: Sequence[tuple[object, ...]]
) -> None:
    columns = ", ".join(quote(name) for name in _target_columns(plan))
    statement = f"COPY {qualify(plan.target_schema, plan.target_table)} ({columns}) FROM STDIN"
    driver = connection.connection.driver_connection
    if not isinstance(driver, psycopg.Connection):
        raise LoadError("the loader requires the psycopg driver for COPY")
    with driver.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def _insert_row(connection: Connection, plan: TableLoadPlan, row: tuple[object, ...]) -> None:
    names = _target_columns(plan)
    columns = ", ".join(quote(name) for name in names)
    placeholders = ", ".join(f":p{index}" for index in range(len(names)))
    relation = qualify(plan.target_schema, plan.target_table)
    statement = f"INSERT INTO {relation} ({columns}) VALUES ({placeholders})"  # noqa: S608
    connection.execute(text(statement), {f"p{index}": value for index, value in enumerate(row)})


def _write_rows(
    connection: Connection,
    plan: TableLoadPlan,
    accepted: Sequence[_Row],
) -> tuple[list[_Row], list[runs.QuarantineEntry]]:
    """Land `accepted` with COPY, falling back to per-row inserts to isolate a failure."""
    rows = [row for row in accepted if row.values is not None]
    if not rows:
        return [], []
    savepoint = connection.begin_nested()
    try:
        _copy_batch(connection, plan, [row.values for row in rows if row.values is not None])
    except (DBAPIError, psycopg.Error):
        savepoint.rollback()
    else:
        savepoint.commit()
        return list(rows), []

    written: list[_Row] = []
    refused: list[runs.QuarantineEntry] = []
    for row in rows:
        if row.values is None:  # pragma: no cover - filtered above
            continue
        attempt = connection.begin_nested()
        try:
            _insert_row(connection, plan, row.values)
        except DBAPIError as exc:
            attempt.rollback()
            code, column = _classify_rejection(plan, row.values)
            # Only the exception's class name: a driver message can quote the
            # value PostgreSQL rejected, and that value may be personal data.
            refused.append(
                runs.QuarantineEntry(
                    legacy_table=plan.legacy_table,
                    column_name=column,
                    natural_key_hash=row.key_hash,
                    error_code=code,
                    error_class=type(exc.orig).__name__ if exc.orig else type(exc).__name__,
                )
            )
        else:
            attempt.commit()
            written.append(row)
    return written, refused


@contextmanager
def _committed(connection: Connection, *, dry_run: bool = False) -> Iterator[None]:
    """One transaction per block: committed, or discarded entirely in a dry run.

    Commit-as-you-go rather than `connection.begin()` blocks, because the
    read-only queries between blocks autobegin a transaction of their own and
    nesting those is an error rather than a no-op.
    """
    try:
        yield
    except Exception:
        connection.rollback()
        raise
    if dry_run:
        connection.rollback()
    else:
        connection.commit()


def _reset_identity(connection: Connection, plan: TableLoadPlan) -> None:
    """Move an identity sequence past the keys the load inserted (OD-016, OD-022).

    The DDL made these columns `GENERATED BY DEFAULT AS IDENTITY` so the load
    could carry the source's own keys across, which leaves the sequence at 1.
    Without this, the first ordinary application insert collides.
    """
    if plan.identity_column is None:
        return
    column = quote(plan.identity_column)
    relation = qualify(plan.target_schema, plan.target_table)
    # S608: identifiers cannot be bound parameters, and both of these are quoted
    # names the DDL generator produced, not input.
    statement = (
        f"SELECT setval(pg_get_serial_sequence(:relation, :column), "  # noqa: S608
        f"coalesce(max({column}), 0) + 1, false) FROM {relation}"
    )
    connection.execute(text(statement), {"relation": relation, "column": plan.identity_column})


def _load_table(
    connection: Connection,
    source: sqlite3.Connection,
    plan: TableLoadPlan,
    run_id: str,
    schema_version: int,
    *,
    batch_size: int,
    dry_run: bool,
    owner: str,
    outcome: LoadOutcome,
) -> TableOutcome:
    state = runs.table_state(connection, run_id, plan.legacy_table)
    if state is TableState.COMPLETED:
        # Idempotence at the table level: a completed table is a no-op, not a
        # second copy of itself.
        return TableOutcome(plan.legacy_table, plan.phase, 0, 0, 0, 0, skipped=True)

    source_rows = count_rows(source, plan.legacy_table)
    if plan.treatment == PROVENANCE_ONLY and source_rows:
        raise LoadError(
            f"{plan.legacy_table} is PROVENANCE_ONLY but holds {source_rows} rows; "
            "the generated target keeps its NOT NULL payload columns, so a "
            "provenance-only row cannot be written without inventing values"
        )

    resume = runs.last_checkpoint(connection, run_id, plan.phase, plan.legacy_table)
    watermark = 0 if resume is None else resume.watermark
    batch_key = 0 if resume is None else resume.batch_key + 1
    loaded = 0 if resume is None else resume.rows_ok
    quarantined = 0 if resume is None else resume.rows_quarantined

    if not dry_run:
        with _committed(connection):
            runs.acquire_lease(connection, run_id, f"table:{plan.legacy_table}", owner=owner)
            runs.begin_table(
                connection, run_id, plan.legacy_table, plan.phase, source_row_count=source_rows
            )

    guard = _DuplicateGuard(in_memory=dry_run)
    batches = 0
    for batch in iter_batches(
        source,
        plan.legacy_table,
        [column.source_name for column in plan.columns],
        after_rowid=watermark,
        first_batch_key=batch_key,
        batch_size=batch_size,
    ):
        ok, refused = _load_batch(
            connection,
            plan,
            batch,
            run_id,
            schema_version,
            guard=guard,
            dry_run=dry_run,
            outcome=outcome,
        )
        loaded += ok
        quarantined += refused
        batches += 1

    if not dry_run:
        with _committed(connection):
            _reset_identity(connection, plan)
            if plan.identity_column is not None:
                runs.record_event(
                    connection,
                    run_id,
                    AuditEvent.SEQUENCE_RESET,
                    phase=plan.phase,
                    legacy_table=plan.legacy_table,
                )
            runs.finish_table(
                connection,
                run_id,
                plan.legacy_table,
                TableState.COMPLETED,
                loaded=loaded,
                quarantined=quarantined,
            )
            runs.release_lease(connection, run_id, f"table:{plan.legacy_table}")

    return TableOutcome(
        plan.legacy_table, plan.phase, source_rows, loaded, quarantined, batches, skipped=False
    )


def _load_batch(
    connection: Connection,
    plan: TableLoadPlan,
    batch: Batch,
    run_id: str,
    schema_version: int,
    *,
    guard: _DuplicateGuard,
    dry_run: bool,
    outcome: LoadOutcome,
) -> tuple[int, int]:
    with _committed(connection, dry_run=dry_run):
        transformed = [_transform(plan, row, run_id, schema_version) for row in batch.rows]
        refused = [row.quarantine for row in transformed if row.quarantine is not None]
        candidates = [row for row in transformed if row.quarantine is None]

        if plan.has_natural_key:
            known = set(
                guard.known(
                    connection, run_id, plan.legacy_table, [row.key_hash for row in candidates]
                )
            )
            accepted: list[_Row] = []
            for row in candidates:
                if row.key_hash in known:
                    refused.append(
                        runs.QuarantineEntry(
                            legacy_table=plan.legacy_table,
                            column_name=",".join(plan.key_columns),
                            natural_key_hash=row.key_hash,
                            error_code=QuarantineCode.DUPLICATE_NATURAL_KEY,
                            error_class="DuplicateNaturalKey",
                        )
                    )
                    continue
                known.add(row.key_hash)
                accepted.append(row)
        else:
            # OD-014. Two byte-identical rows in a keyless table are two rows;
            # collapsing them would lose data the source actually holds.
            accepted = candidates

        written, rejected = _write_rows(connection, plan, accepted)
        refused.extend(rejected)

        if not dry_run:
            if plan.has_natural_key:
                runs.record_source_keys(
                    connection,
                    run_id,
                    plan.legacy_table,
                    batch.batch_key,
                    [(row.key_hash, row.target_key) for row in written],
                )
            runs.record_quarantine(connection, run_id, plan.phase, refused)
            runs.record_checkpoint(
                connection,
                run_id,
                plan.phase,
                plan.legacy_table,
                batch_key=batch.batch_key,
                watermark=batch.watermark,
                rows_ok=len(written),
                rows_failed=len(rejected),
                rows_quarantined=len(refused),
            )
        for row in written:
            guard.accept(row.key_hash)
        for entry in refused:
            outcome.quarantine_by_code[entry.error_code.value] = (
                outcome.quarantine_by_code.get(entry.error_code.value, 0) + 1
            )
    return len(written), len(refused)


def load(
    engine: Engine,
    source_path: Path,
    registry: Mapping[str, Disposition],
    run_id: str,
    *,
    phases: Sequence[str] | None = None,
    tables: Sequence[str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> LoadOutcome:
    """Load `phases` (or every loadable table) into the target for `run_id`.

    Re-entrant by construction. A completed table is skipped, a partly loaded one
    resumes after its last checkpoint, and the run's bound identity is
    re-verified before anything is read or written (OD-003).
    """
    owner = f"pid:{os.getpid()}"
    outcome = LoadOutcome(run_id=run_id, dry_run=dry_run)

    with engine.connect() as connection, open_source(source_path) as source:
        run = runs.read_run(connection, run_id)
        dry_run = dry_run or run.dry_run
        outcome.dry_run = dry_run
        observed = binding.observe(source_path, connection)
        try:
            runs.recorded_binding(run, source_path).verify(observed)
        except binding.DriftError:
            with _committed(connection):
                runs.record_event(
                    connection, run_id, AuditEvent.IDENTITY_DRIFT_DETECTED, code="HZ-SRC-DRIFT"
                )
            raise

        plans = build_plans(source, connection, registry, phases=phases, tables=tables)
        if not dry_run:
            with _committed(connection):
                runs.set_run_status(connection, run_id, RunStatus.RUNNING)

        by_phase: dict[str, list[TableLoadPlan]] = {}
        for plan in plans:
            by_phase.setdefault(plan.phase, []).append(plan)

        for phase, phase_plans in sorted(by_phase.items()):
            if not dry_run:
                with _committed(connection):
                    runs.start_phase(connection, run_id, phase, tables_total=len(phase_plans))
            for plan in phase_plans:
                try:
                    outcome.tables.append(
                        _load_table(
                            connection,
                            source,
                            plan,
                            run_id,
                            observed.source_schema_version,
                            batch_size=batch_size,
                            dry_run=dry_run,
                            owner=owner,
                            outcome=outcome,
                        )
                    )
                except Exception:
                    # Leave the failure recorded and re-raise. The committed
                    # checkpoints stay valid, so `resume` picks up exactly where
                    # this stopped rather than starting the table again.
                    if not dry_run:
                        _record_failure(connection, run_id, phase, plan.legacy_table)
                    raise
            if not dry_run:
                with _committed(connection):
                    runs.finish_phase(connection, run_id, phase, PhaseStatus.COMPLETED)

        if not dry_run:
            with _committed(connection):
                runs.set_run_status(connection, run_id, RunStatus.COMPLETED)
                runs.record_event(
                    connection, run_id, AuditEvent.RUN_COMPLETED, row_count=outcome.loaded
                )

    return outcome


def _record_failure(connection: Connection, run_id: str, phase: str, legacy_table: str) -> None:
    """Record a failed table, phase, and run without losing the original error."""
    connection.rollback()
    with _committed(connection):
        runs.fail_table(connection, run_id, legacy_table)
        runs.finish_phase(connection, run_id, phase, PhaseStatus.FAILED)
        runs.set_run_status(connection, run_id, RunStatus.FAILED)
        runs.record_event(
            connection, run_id, AuditEvent.RUN_FAILED, phase=phase, legacy_table=legacy_table
        )
