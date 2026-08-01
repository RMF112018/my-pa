"""The `migration_control` schema: run identity, checkpoints, quarantine, audit.

This is a ledger, not a workflow engine. It answers four questions and no
others: what source is this run bound to, how far did it get, what did it refuse
to load, and who is writing to this table right now. There is no scheduler, no
DAG, no retry policy engine, and no plugin surface.

The tables are declared once here and used by both the Alembic revision that
creates them and the loader that writes to them, so the two cannot drift.

Nothing in this schema stores a row value. `quarantine_records` names the table,
the column, an error code, and a key *hash*; `audit_events` carries event types
and counts. A driver's error message can quote the offending value, so only the
exception's class name is ever recorded.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
    func,
)

SCHEMA: Final = "migration_control"

METADATA: Final = MetaData(schema=SCHEMA)


class RunStatus(StrEnum):
    """Lifecycle of a whole migration run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"


class PhaseStatus(StrEnum):
    """Lifecycle of one phase within a run."""

    RUNNING = "RUNNING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class TableState(StrEnum):
    """Lifecycle of one legacy table within a run.

    Only loaded tables get a row here. The tables OD-008 leaves deliberately
    empty have no progress row at all, which is what distinguishes "empty by
    decision" from "did not get its turn".
    """

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class QuarantineCode(StrEnum):
    """Why a row was refused. Stable, enumerable, and content-free."""

    #: OD-023. SQLite permits NULL in a non-INTEGER PRIMARY KEY; PostgreSQL does
    #: not, and 510 source tables key on TEXT.
    NULL_PRIMARY_KEY = "NULL_PRIMARY_KEY"
    #: HZ-ID-COLLISION. Two source rows claim one natural key.
    DUPLICATE_NATURAL_KEY = "DUPLICATE_NATURAL_KEY"
    #: OD-009. A stored value's storage class has no defensible cast to the
    #: column's target type, and coercing it silently is forbidden.
    TYPE_CAST_FAILURE = "TYPE_CAST_FAILURE"
    #: A TEXT value contains U+0000. SQLite stores it; PostgreSQL `text` cannot
    #: represent it at all. Stripping the byte would silently alter the owner's
    #: content, so the row is refused and named instead.
    UNSUPPORTED_TEXT_NUL = "UNSUPPORTED_TEXT_NUL"
    #: PostgreSQL refused the row for a reason the transform did not predict.
    TARGET_REJECTED_ROW = "TARGET_REJECTED_ROW"


class AuditEvent(StrEnum):
    """Event types. Each carries codes and counts, never a payload."""

    RUN_CREATED = "RUN_CREATED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"
    PHASE_STARTED = "PHASE_STARTED"
    PHASE_COMPLETED = "PHASE_COMPLETED"
    TABLE_STARTED = "TABLE_STARTED"
    TABLE_COMPLETED = "TABLE_COMPLETED"
    TABLE_QUARANTINED_ROWS = "TABLE_QUARANTINED_ROWS"
    SEQUENCE_RESET = "SEQUENCE_RESET"
    IDENTITY_DRIFT_DETECTED = "IDENTITY_DRIFT_DETECTED"


def _one_of(column: str, values: type[StrEnum]) -> CheckConstraint:
    literals = ", ".join(f"'{member.value}'" for member in values)
    return CheckConstraint(f"{column} IN ({literals})", name=f"{column}_is_known")


def _run_id_column(*, primary_key: bool = False) -> Column[str]:
    return Column(
        "run_id",
        Uuid(as_uuid=False),
        ForeignKey(f"{SCHEMA}.migration_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        primary_key=primary_key,
    )


#: The run's immutable identity. `source_sha256`, `source_schema_version`, and
#: `target_alembic_revision` are the whole of the drift check (HZ-SRC-DRIFT,
#: HZ-TGT-DRIFT): a resume recomputes all three and refuses on any mismatch.
migration_runs = Table(
    "migration_runs",
    METADATA,
    Column("run_id", Uuid(as_uuid=False), primary_key=True),
    Column("source_sha256", Text, nullable=False),
    Column("source_bytes", BigInteger, nullable=False),
    Column("source_schema_version", Integer, nullable=False),
    Column("target_alembic_revision", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("dry_run", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    _one_of("status", RunStatus),
)

phase_status = Table(
    "phase_status",
    METADATA,
    _run_id_column(primary_key=True),
    Column("phase", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("tables_total", Integer, nullable=False, server_default="0"),
    Column("tables_completed", Integer, nullable=False, server_default="0"),
    Column("rows_ok", BigInteger, nullable=False, server_default="0"),
    Column("rows_quarantined", BigInteger, nullable=False, server_default="0"),
    _one_of("status", PhaseStatus),
)

#: One row per committed batch. This is what makes resume exact: a batch and its
#: checkpoint commit in the same transaction, so a crash either leaves both or
#: neither, and `watermark` is the source rowid the next batch starts after.
batch_checkpoints = Table(
    "batch_checkpoints",
    METADATA,
    _run_id_column(primary_key=True),
    Column("phase", Text, primary_key=True),
    Column("legacy_table", Text, primary_key=True),
    Column("batch_key", BigInteger, primary_key=True),
    Column("rows_ok", BigInteger, nullable=False),
    Column("rows_failed", BigInteger, nullable=False),
    Column("rows_quarantined", BigInteger, nullable=False),
    Column("watermark", BigInteger, nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("batch_key >= 0", name="batch_key_is_ordinal"),
    CheckConstraint("rows_ok >= 0 AND rows_failed >= 0 AND rows_quarantined >= 0", name="counts"),
)

table_progress = Table(
    "table_progress",
    METADATA,
    _run_id_column(primary_key=True),
    Column("legacy_table", Text, primary_key=True),
    Column("phase", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("source_row_count", BigInteger, nullable=False),
    Column("loaded_row_count", BigInteger, nullable=False, server_default="0"),
    Column("quarantined_row_count", BigInteger, nullable=False, server_default="0"),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    _one_of("state", TableState),
)

#: A refused row, named by hash. `error_class` is an exception *class name* and
#: nothing else, because a driver's message text can quote the value it rejected.
quarantine_records = Table(
    "quarantine_records",
    METADATA,
    Column("quarantine_id", BigInteger, Identity(always=True), primary_key=True),
    _run_id_column(),
    Column("phase", Text, nullable=False),
    Column("legacy_table", Text, nullable=False),
    Column("column_name", Text),
    Column("natural_key_hash", Text, nullable=False),
    Column("error_code", Text, nullable=False),
    Column("error_class", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _one_of("error_code", QuarantineCode),
    Index("quarantine_records_by_table", "run_id", "legacy_table", "error_code"),
)

audit_events = Table(
    "audit_events",
    METADATA,
    Column("event_id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "run_id",
        Uuid(as_uuid=False),
        ForeignKey(f"{SCHEMA}.migration_runs.run_id", ondelete="CASCADE"),
    ),
    Column("phase", Text),
    Column("legacy_table", Text),
    Column("event_type", Text, nullable=False),
    Column("code", Text),
    Column("row_count", BigInteger),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _one_of("event_type", AuditEvent),
    Index("audit_events_by_run", "run_id", "recorded_at"),
)

#: Single writer per table. One row per resource; an expired lease may be taken
#: over, a live one held by another run may not.
leases = Table(
    "leases",
    METADATA,
    Column("resource_key", Text, primary_key=True),
    _run_id_column(),
    Column("owner", Text, nullable=False),
    Column("acquired_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

#: OD-011. The legacy natural key hashed, against the target key it became. It
#: is also the loader's in-run duplicate detector: the primary key here is what
#: makes a second row claiming one natural key a quarantine rather than a
#: silent overwrite.
source_key_map = Table(
    "source_key_map",
    METADATA,
    _run_id_column(primary_key=True),
    Column("legacy_table", Text, primary_key=True),
    Column("natural_key_hash", Text, primary_key=True),
    Column("target_key", Text, nullable=False),
    Column("batch_key", BigInteger, nullable=False),
)

#: OD-013 and OD-024. Every identifier the DDL generator had to rename, so the
#: mapping is queryable rather than folklore. Reference data, seeded by the
#: revision that creates this schema and independent of any run.
identifier_map = Table(
    "identifier_map",
    METADATA,
    Column("object_kind", Text, primary_key=True),
    Column("owning_table", Text, primary_key=True),
    Column("original", Text, primary_key=True),
    Column("shortened", Text, nullable=False),
)
