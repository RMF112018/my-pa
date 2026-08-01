"""Recompute the migration's result from the source and the target directly.

This is the acceptance harness for Phase 10. It answers OD-012 by measuring, not
by reading what the load reported about itself: every count here comes from a
``count(*)`` against the legacy SQLite file or against PostgreSQL, and the
control plane is treated as one more thing to check rather than as the answer.
That distinction is the whole point. A loader that miscounted would also
miscount its own ledger, so a reconciliation built on the ledger would agree
with the mistake.

Four things are worth naming about how the checks are shaped.

*A discrepancy is never aggregated away.* Every loaded table gets a row in the
parity table with both numbers, and a mismatch is listed individually with the
quarantine records that do or do not account for it.

*Deliberately empty is asserted, not assumed.* The classes OD-025 leaves empty
are queried and required to be empty. An empty table that nobody checked and an
empty table that was proven empty look identical in a row count and are not the
same evidence.

*The keyless table is reconciled by content.* ``schedule_cpm_relationship_results``
has no source-side key (OD-014), so row-count equality would not catch
reordering, duplication, or truncation. The check recomputes the row hash of
every source row and compares the two multisets.

*Nothing here writes.* The source is opened ``immutable=1`` and the target is
read through ordinary queries; an unvalidated foreign key is counted, never
validated, because validating it would change the database the report is
describing.

No value from any row is read into this module's output. The counts, names,
codes, and digests it emits are the whole of it (OD-004).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text

from my_pa.infrastructure.migration import redaction
from my_pa.infrastructure.migration.binding import file_digest, target_revision
from my_pa.infrastructure.migration.generator import (
    PROVENANCE_COLUMNS,
    SOURCE_ROW_HASH_COLUMN,
    SURROGATE_KEY_COLUMN,
)
from my_pa.infrastructure.migration.identifiers import qualify, quote, target_name
from my_pa.infrastructure.migration.natural_key import hash_values
from my_pa.infrastructure.migration.plan import LOADED_TREATMENTS, phase_of
from my_pa.infrastructure.migration.reader import (
    count_rows,
    open_source,
    read_shape,
    schema_version,
)
from my_pa.infrastructure.migration.source import Disposition

#: OD-007. The domain schemas the migration owns, plus the control plane. Every
#: catalogue sweep covers all of them so a stray object cannot hide in one.
DOMAIN_SCHEMAS: tuple[str, ...] = (
    "core",
    "procore",
    "email",
    "calendar",
    "contacts",
    "financial",
    "schedule",
    "construction",
)
CONTROL_SCHEMA = "migration_control"
ALL_SCHEMAS: tuple[str, ...] = (*DOMAIN_SCHEMAS, CONTROL_SCHEMA)

#: OD-001, verbatim. The 15 plan objects that do not exist in the schema-128
#: source, all of them v129-v135 additions. Written out here rather than read
#: from the registry so that the registry is checked against the decision instead
#: of against itself.
ABSENT_FROM_SOURCE_AT_SCHEMA_128: tuple[str, ...] = (
    "apple_contact_raw_content",
    "apple_contact_structured",
    "calendar_event_current_selection",
    "calendar_event_revisions",
    "calendar_event_source_observations",
    "contact_current_selection",
    "contact_email_hashes",
    "contact_entities",
    "contact_linkage_candidates",
    "contact_phone_hashes",
    "contact_revisions",
    "contact_source_observations",
    "email_message_current_selection",
    "email_message_revisions",
    "email_message_source_observations",
)

#: Treatments that create no target table, with the reason each one exists.
NOT_CREATED_REASONS: Mapping[str, str] = {
    "NOT_CREATED": "obsolete or empty in the source (OD-025)",
    "NOT_CREATED_SUPERSEDED": "a newer table holds these facts authoritatively (OD-025)",
    "NOT_CREATED_FTS_REBUILT_IN_POSTGRES": (
        "SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010)"
    ),
    "NOT_CREATED_PRIVACY_GATED": "withheld by the privacy gate (OD-025, OP-PROD-001)",
}

#: Treatments that create a table and require it to hold no rows.
ASSERTED_EMPTY_TREATMENTS: Mapping[str, str] = {
    "SCHEMA_ONLY_EMPTY_BY_DESIGN": "operational state, empty by design (OD-025)",
    "SCHEMA_ONLY_ASSERT_EMPTY": "schema-empty in the source (OD-008)",
    "PROVENANCE_ONLY": "provenance without payload; empty at schema 128 (OD-026)",
}

#: OD-028. The five operational-state tables that are loaded, so the report can
#: say why the asserted-empty class has 85 members and not 90.
OPERATIONAL_STATE_LOADED: tuple[str, ...] = (
    "forecast_runs",
    "procore_live_sync_runs",
    "schedule_cost_mapping_runs",
    "schedule_cpm_runs",
    "schedule_quality_evaluation_runs",
)

#: OD-024. Surfaced by name so a reader searching for the legacy identifier finds
#: the mapping rather than concluding the column was lost.
NEUTRALISED_COLUMN = ("construction_project_identity", "hb_project_number", "project_number")

#: Suffixes SQLite creates beside a database it has written to. None may exist
#: for the live source file (OD-003).
JOURNAL_SUFFIXES: tuple[str, ...] = ("-wal", "-shm", "-journal")

#: What a criterion can come out as. `UNEVALUATED` exists so a check that could
#: not run is never silently counted as one that passed, and `WAIVED` exists so a
#: shortfall a decision explicitly authorised is neither hidden as a pass nor
#: reported as a defect. The phase plan's own dispositions include
#: `PASS_WITH_WAIVERS`; a waiver here always names the decision that grants it.
PASSED = "PASS"
FAILED = "FAIL"
WAIVED = "WAIVED"
UNEVALUATED = "UNEVALUATED"

#: The verdict for a run where every criterion passed except ones a named
#: decision authorises.
PASSED_WITH_WAIVERS = "PASS_WITH_WAIVERS"

#: Quarantine codes a decision has already adjudicated, with the decision that
#: did it. A shortfall explained entirely by these is waived; a shortfall
#: explained by anything else is a failure, because no decision has looked at it.
WAIVED_QUARANTINE_CODES: Mapping[str, str] = {
    "UNSUPPORTED_TEXT_NUL": "OD-029",
    "NULL_PRIMARY_KEY": "OD-023",
}


@dataclass(frozen=True)
class Criterion:
    """One acceptance criterion and how it came out."""

    identifier: str
    statement: str
    status: str
    detail: str
    waiver: str | None = None


@dataclass(frozen=True)
class RunRecord:
    """One row of `migration_control.migration_runs`. No path, no credential."""

    run_id: str
    source_sha256: str
    source_bytes: int
    source_schema_version: int
    target_alembic_revision: str
    status: str
    dry_run: bool


@dataclass(frozen=True)
class SourceIntegrity:
    """The legacy file as it stands now, against what the runs recorded."""

    file_name: str
    sha256: str
    byte_count: int
    schema_version: int
    journal_siblings: tuple[str, ...]
    runs_agreeing: int
    runs_disagreeing: tuple[str, ...]

    @property
    def intact(self) -> bool:
        return not self.journal_siblings and not self.runs_disagreeing


@dataclass(frozen=True)
class TableParity:
    """One loaded table's source count against its target count."""

    legacy_table: str
    phase: str
    treatment: str
    planning_disposition: str
    target_schema: str
    target_table: str
    source_rows: int
    target_rows: int
    quarantined_rows: int

    @property
    def exact(self) -> bool:
        """True when the target holds every source row."""
        return self.source_rows == self.target_rows

    @property
    def accounted(self) -> bool:
        """True when every source row is either loaded or named in quarantine."""
        return self.source_rows == self.target_rows + self.quarantined_rows


@dataclass(frozen=True)
class QuarantineGroup:
    """Refused rows, grouped the way OD-023 and OD-029 require them reported."""

    error_code: str
    legacy_table: str
    column_name: str | None
    rows: int


@dataclass(frozen=True)
class IdentityCoverage:
    """`source_key_map` entries against rows actually in the target."""

    legacy_table: str
    key_map_entries: int
    target_rows: int
    keyed: bool

    @property
    def covered(self) -> bool:
        """Keyed tables need one map entry per row; keyless ones have none by design."""
        if not self.keyed:
            return self.key_map_entries == 0
        return self.key_map_entries == self.target_rows


@dataclass(frozen=True)
class KeylessTableCheck:
    """OD-014. Content equality for a table the source gave no key."""

    legacy_table: str
    target_schema: str
    target_table: str
    source_rows: int
    target_rows: int
    distinct_surrogate_ids: int
    distinct_source_hashes: int
    hashes_only_in_source: int
    hashes_only_in_target: int

    @property
    def multisets_equal(self) -> bool:
        return self.hashes_only_in_source == 0 and self.hashes_only_in_target == 0


@dataclass(frozen=True)
class ForeignKeyState:
    """One foreign key that PostgreSQL has not validated, and its orphan count."""

    schema: str
    table: str
    constraint: str
    referenced: str
    orphan_rows: int


@dataclass(frozen=True)
class ForeignKeySummary:
    """Validity across every schema the migration owns."""

    total: int
    validated: int
    not_valid: tuple[ForeignKeyState, ...]
    by_schema: tuple[tuple[str, int, int], ...]

    @property
    def orphan_rows(self) -> int:
        return sum(state.orphan_rows for state in self.not_valid)


@dataclass(frozen=True)
class EmptyAssertion:
    """A table required to hold no rows, and what it actually holds."""

    legacy_table: str
    treatment: str
    reason: str
    target_schema: str
    target_table: str
    source_rows: int
    target_rows: int

    @property
    def empty(self) -> bool:
        return self.target_rows == 0


@dataclass(frozen=True)
class Exclusion:
    """A source object with no target table, named with its reason and its cost."""

    legacy_object: str
    object_type: str
    planning_disposition: str
    treatment: str
    reason: str
    source_rows: int
    present_in_target: bool


@dataclass(frozen=True)
class AbsentObject:
    """A plan object the schema-128 source does not contain (OD-001)."""

    legacy_object: str
    planning_disposition: str


@dataclass(frozen=True)
class AbsenceCheck:
    """The registry's absence list against OD-001 as written."""

    expected: tuple[str, ...]
    observed: tuple[AbsentObject, ...]
    missing_from_registry: tuple[str, ...]
    unexpected_in_registry: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return not self.missing_from_registry and not self.unexpected_in_registry


@dataclass(frozen=True)
class IdentifierRename:
    """One row of `migration_control.identifier_map`."""

    object_kind: str
    owning_table: str
    original: str
    shortened: str


@dataclass(frozen=True)
class RenameReport:
    """Every recorded rename, and the one that carries a policy decision."""

    total: int
    by_kind: tuple[tuple[str, int], ...]
    neutralised: tuple[IdentifierRename, ...]
    longest_originals: tuple[IdentifierRename, ...]


@dataclass(frozen=True)
class ProvenanceGap:
    """A loaded table holding a row with an incomplete provenance stamp."""

    legacy_table: str
    target_schema: str
    target_table: str
    rows_with_null_provenance: int


@dataclass(frozen=True)
class ProvenanceReport:
    """OD-011 completeness across every loaded row."""

    columns: tuple[str, ...]
    tables_checked: int
    rows_checked: int
    gaps: tuple[ProvenanceGap, ...]

    @property
    def complete(self) -> bool:
        return not self.gaps


@dataclass(frozen=True)
class SequenceState:
    """One identity sequence against the keys its table holds."""

    schema: str
    table: str
    column: str
    sequence: str
    max_key: int | None
    next_value: int
    expected_next_value: int

    @property
    def correct(self) -> bool:
        return self.next_value == self.expected_next_value


@dataclass(frozen=True)
class ViewCheck:
    """OD-018. A source read model and the target view that should mirror it."""

    legacy_view: str
    target_schema: str
    target_view: str
    source_rows: int
    present_in_target: bool
    target_rows: int | None

    @property
    def reconciled(self) -> bool:
        """OD-018 asks for existence *and* a matching count, so both are required."""
        return self.present_in_target and self.target_rows == self.source_rows


@dataclass(frozen=True)
class RowAccounting:
    """Every source row placed in exactly one bucket (P10-AC-01).

    Coverage is the check that matters here: a disposition matrix that leaves an
    object out is how a table goes missing without anyone noticing, so the sweep
    starts from the source's own catalogue rather than from the registry.
    """

    source_tables: int
    source_rows: int
    registry_tables: int
    loaded_rows: int
    excluded_rows: int
    asserted_empty_rows: int
    objects_missing_from_registry: tuple[str, ...]
    objects_in_no_bucket: tuple[str, ...]

    @property
    def bucketed_rows(self) -> int:
        return self.loaded_rows + self.excluded_rows + self.asserted_empty_rows

    @property
    def withheld_rows(self) -> int:
        """Source rows that reached no target table, by either route.

        Recomputed rather than quoted. OD-025's 64,960 was derived before OD-028
        moved five tables into scope and is stale by exactly those 5,388 rows;
        anything that restates it inherits the error.
        """
        return self.excluded_rows + self.asserted_empty_rows

    @property
    def withheld_share(self) -> float:
        return 0.0 if not self.source_rows else self.withheld_rows / self.source_rows

    @property
    def balanced(self) -> bool:
        return (
            self.bucketed_rows == self.source_rows
            and not self.objects_missing_from_registry
            and not self.objects_in_no_bucket
        )


@dataclass(frozen=True)
class SiblingFile:
    """A file beside the source, named and sized. Never opened for its content."""

    file_name: str
    byte_count: int
    identical_to_source: bool


@dataclass(frozen=True)
class RetentionRisk:
    """OD-030. What exists only inside the one source file, and in how many copies.

    The excluded and quarantined rows are the ones with no target-side copy, so
    the source file is their sole custodian. The siblings beside it are earlier
    snapshots at earlier schema versions rather than backups of it, and this
    check proves that by size, digesting only a sibling whose size could make it
    a copy.

    Nothing is copied anywhere to mitigate this. Moving personal data off this
    machine is the owner's disclosure decision (`AGENTS.md` section 5), not a
    step a reconciliation harness may take on its own.
    """

    source_file_name: str
    source_bytes: int
    source_sha256: str
    siblings: tuple[SiblingFile, ...]
    verified_copies: int
    rows_held_only_here: int

    @property
    def mitigated(self) -> bool:
        return self.verified_copies > 0


@dataclass
class Reconciliation:
    """Everything Phase 10 measured, in one record."""

    generated_at: str
    source_schema_version: int
    target_alembic_revision: str
    source: SourceIntegrity
    runs: tuple[RunRecord, ...]
    parity: tuple[TableParity, ...]
    quarantine: tuple[QuarantineGroup, ...]
    identity: tuple[IdentityCoverage, ...]
    keyless: tuple[KeylessTableCheck, ...]
    foreign_keys: ForeignKeySummary
    empty_assertions: tuple[EmptyAssertion, ...]
    exclusions: tuple[Exclusion, ...]
    absence: AbsenceCheck
    renames: RenameReport
    provenance: ProvenanceReport
    sequences: tuple[SequenceState, ...]
    views: tuple[ViewCheck, ...]
    accounting: RowAccounting
    retention: RetentionRisk
    scan: redaction.ScanResult
    criteria: tuple[Criterion, ...] = field(default_factory=tuple)

    @property
    def source_rows(self) -> int:
        return sum(table.source_rows for table in self.parity)

    @property
    def target_rows(self) -> int:
        return sum(table.target_rows for table in self.parity)

    @property
    def quarantined_rows(self) -> int:
        return sum(group.rows for group in self.quarantine)

    @property
    def excluded_rows(self) -> int:
        return sum(item.source_rows for item in self.exclusions)

    @property
    def verdict(self) -> str:
        """The strictest status any criterion reached.

        A waiver does not fail the phase, but it does keep the verdict from
        being a plain pass, so a reader cannot mistake an authorised shortfall
        for its absence.
        """
        statuses = {criterion.status for criterion in self.criteria}
        if FAILED in statuses:
            return FAILED
        if UNEVALUATED in statuses:
            return UNEVALUATED
        if WAIVED in statuses:
            return PASSED_WITH_WAIVERS
        return PASSED


def _loaded(registry: Mapping[str, Disposition]) -> list[Disposition]:
    return sorted(
        (
            disposition
            for disposition in registry.values()
            if disposition.object_type == "table"
            and disposition.target_treatment in LOADED_TREATMENTS
        ),
        key=lambda item: item.legacy_object,
    )


def _target_count(connection: Connection, schema: str, table: str) -> int:
    # S608: both identifiers are quoted catalogue names produced by the DDL
    # generator, never input.
    statement = f"SELECT count(*) FROM {qualify(schema, table)}"  # noqa: S608
    return int(connection.execute(text(statement)).scalar_one())


def _relation_exists(connection: Connection, schema: str, table: str) -> bool:
    return bool(
        connection.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_name = :table"
            ),
            {"schema": schema, "table": table},
        ).first()
    )


def read_runs(connection: Connection) -> tuple[RunRecord, ...]:
    """Read every recorded migration run, oldest first."""
    rows = connection.execute(
        text(
            # S608: `CONTROL_SCHEMA` is a module constant, not input.
            "SELECT run_id, source_sha256, source_bytes, source_schema_version, "  # noqa: S608
            "target_alembic_revision, status, dry_run "
            f"FROM {CONTROL_SCHEMA}.migration_runs ORDER BY created_at"
        )
    ).all()
    return tuple(
        RunRecord(
            run_id=str(row[0]),
            source_sha256=str(row[1]),
            source_bytes=int(row[2]),
            source_schema_version=int(row[3]),
            target_alembic_revision=str(row[4]),
            status=str(row[5]),
            dry_run=bool(row[6]),
        )
        for row in rows
    )


def check_source_integrity(
    source_path: Path, source: sqlite3.Connection, runs: Sequence[RunRecord]
) -> SourceIntegrity:
    """Digest the legacy file and compare it with what every run bound itself to."""
    sha256, size = file_digest(source_path)
    version = schema_version(source)
    siblings = tuple(
        suffix
        for suffix in JOURNAL_SUFFIXES
        if source_path.with_name(source_path.name + suffix).exists()
    )
    disagreeing = tuple(
        run.run_id
        for run in runs
        if (run.source_sha256, run.source_bytes, run.source_schema_version)
        != (sha256, size, version)
    )
    return SourceIntegrity(
        file_name=source_path.name,
        sha256=sha256,
        byte_count=size,
        schema_version=version,
        journal_siblings=siblings,
        runs_agreeing=len(runs) - len(disagreeing),
        runs_disagreeing=disagreeing,
    )


def read_quarantine(connection: Connection) -> tuple[QuarantineGroup, ...]:
    """Group every quarantined row by code, table, and column."""
    rows = connection.execute(
        text(
            # S608: `CONTROL_SCHEMA` is a module constant, not input.
            "SELECT error_code, legacy_table, column_name, count(*) "  # noqa: S608
            f"FROM {CONTROL_SCHEMA}.quarantine_records "
            "GROUP BY error_code, legacy_table, column_name "
            "ORDER BY error_code, legacy_table, column_name"
        )
    ).all()
    return tuple(
        QuarantineGroup(
            error_code=str(row[0]),
            legacy_table=str(row[1]),
            column_name=None if row[2] is None else str(row[2]),
            rows=int(row[3]),
        )
        for row in rows
    )


def check_parity(
    connection: Connection,
    source: sqlite3.Connection,
    dispositions: Sequence[Disposition],
    quarantine: Sequence[QuarantineGroup],
) -> tuple[TableParity, ...]:
    """Count every loaded table on both sides."""
    refused: dict[str, int] = {}
    for group in quarantine:
        refused[group.legacy_table] = refused.get(group.legacy_table, 0) + group.rows
    parity: list[TableParity] = []
    for disposition in dispositions:
        table = target_name(disposition.legacy_object)
        parity.append(
            TableParity(
                legacy_table=disposition.legacy_object,
                phase=phase_of(disposition),
                treatment=disposition.target_treatment,
                planning_disposition=disposition.planning_disposition,
                target_schema=disposition.target_schema,
                target_table=table,
                source_rows=count_rows(source, disposition.legacy_object),
                target_rows=_target_count(connection, disposition.target_schema, table),
                quarantined_rows=refused.get(disposition.legacy_object, 0),
            )
        )
    return tuple(parity)


def check_identity_coverage(
    connection: Connection,
    source: sqlite3.Connection,
    parity: Sequence[TableParity],
) -> tuple[IdentityCoverage, ...]:
    """Compare `source_key_map` entries with the rows each table actually holds."""
    rows = connection.execute(
        text(
            # S608: `CONTROL_SCHEMA` is a module constant, not input.
            "SELECT legacy_table, count(*) "  # noqa: S608
            f"FROM {CONTROL_SCHEMA}.source_key_map GROUP BY legacy_table"
        )
    ).all()
    mapped = {str(row[0]): int(row[1]) for row in rows}
    coverage: list[IdentityCoverage] = []
    for table in parity:
        keyed = bool(read_shape(source, table.legacy_table).primary_key)
        coverage.append(
            IdentityCoverage(
                legacy_table=table.legacy_table,
                key_map_entries=mapped.get(table.legacy_table, 0),
                target_rows=table.target_rows,
                keyed=keyed,
            )
        )
    return tuple(coverage)


def check_keyless_tables(
    connection: Connection,
    source: sqlite3.Connection,
    parity: Sequence[TableParity],
    coverage: Sequence[IdentityCoverage],
) -> tuple[KeylessTableCheck, ...]:
    """OD-014. Reconcile a keyless table by the multiset of its row hashes.

    Row count equality is not the guarantee here, because a table with no
    source-side key has nothing to reconcile *against*. Recomputing the hash of
    every source tuple and comparing the two multisets catches reordering,
    duplication, and truncation, which a count does not.
    """
    keyless = {item.legacy_table for item in coverage if not item.keyed}
    checks: list[KeylessTableCheck] = []
    for table in parity:
        if table.legacy_table not in keyless:
            continue
        shape = read_shape(source, table.legacy_table)
        projection = ", ".join(quote(column) for column in shape.column_names)
        # S608: identifiers cannot be bound; every one is a quoted name read from
        # the source's own catalogue in a read-only file.
        statement = f"SELECT {projection} FROM {quote(table.legacy_table)}"  # noqa: S608
        source_hashes: dict[str, int] = {}
        for row in source.execute(statement):
            digest = hash_values(list(row))
            source_hashes[digest] = source_hashes.get(digest, 0) + 1

        relation = qualify(table.target_schema, table.target_table)
        target_hashes: dict[str, int] = {
            str(digest): int(count)
            for digest, count in connection.execute(
                text(
                    f"SELECT {quote(SOURCE_ROW_HASH_COLUMN)}, count(*) "  # noqa: S608
                    f"FROM {relation} GROUP BY 1"
                )
            ).all()
        }
        surrogates = int(
            connection.execute(
                text(
                    f"SELECT count(DISTINCT {quote(SURROGATE_KEY_COLUMN)}) "  # noqa: S608
                    f"FROM {relation}"
                )
            ).scalar_one()
        )
        only_source = sum(
            max(count - target_hashes.get(digest, 0), 0) for digest, count in source_hashes.items()
        )
        only_target = sum(
            max(count - source_hashes.get(digest, 0), 0) for digest, count in target_hashes.items()
        )
        checks.append(
            KeylessTableCheck(
                legacy_table=table.legacy_table,
                target_schema=table.target_schema,
                target_table=table.target_table,
                source_rows=table.source_rows,
                target_rows=table.target_rows,
                distinct_surrogate_ids=surrogates,
                distinct_source_hashes=len(source_hashes),
                hashes_only_in_source=only_source,
                hashes_only_in_target=only_target,
            )
        )
    return tuple(checks)


_FOREIGN_KEYS = """
SELECT n.nspname, c.relname, con.conname, con.convalidated,
       (SELECT array_agg(a.attname ORDER BY k.ord)
          FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum),
       pn.nspname, p.relname,
       (SELECT array_agg(a.attname ORDER BY k.ord)
          FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum)
  FROM pg_constraint con
  JOIN pg_class c ON c.oid = con.conrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_class p ON p.oid = con.confrelid
  JOIN pg_namespace pn ON pn.oid = p.relnamespace
 WHERE con.contype = 'f' AND n.nspname = ANY(:schemas)
 ORDER BY n.nspname, c.relname, con.conname
"""


def _orphan_count(
    connection: Connection,
    schema: str,
    table: str,
    columns: Sequence[str],
    parent_schema: str,
    parent_table: str,
    parent_columns: Sequence[str],
) -> int:
    """Count child rows with no parent, under MATCH SIMPLE semantics.

    A row with any NULL in the key is exempt from the constraint and is therefore
    not an orphan.
    """
    present = " AND ".join(f"c.{quote(column)} IS NOT NULL" for column in columns)
    joined = " AND ".join(
        f"p.{quote(parent)} = c.{quote(column)}"
        for column, parent in zip(columns, parent_columns, strict=True)
    )
    statement = (
        f"SELECT count(*) FROM {qualify(schema, table)} AS c WHERE {present} "  # noqa: S608
        f"AND NOT EXISTS (SELECT 1 FROM {qualify(parent_schema, parent_table)} AS p "
        f"WHERE {joined})"
    )
    return int(connection.execute(text(statement)).scalar_one())


def check_foreign_keys(connection: Connection, schemas: Sequence[str]) -> ForeignKeySummary:
    """Count valid against `NOT VALID`, and price every unvalidated constraint.

    Read-only: an unvalidated constraint is counted and its orphans measured, and
    it is never validated here. Validating it would change the database this
    report is describing.
    """
    rows = connection.execute(text(_FOREIGN_KEYS), {"schemas": list(schemas)}).all()
    per_schema: dict[str, list[int]] = {}
    not_valid: list[ForeignKeyState] = []
    for row in rows:
        schema = str(row[0])
        validated = bool(row[3])
        totals = per_schema.setdefault(schema, [0, 0])
        totals[0] += 1
        totals[1] += int(validated)
        if validated:
            continue
        not_valid.append(
            ForeignKeyState(
                schema=schema,
                table=str(row[1]),
                constraint=str(row[2]),
                referenced=f"{row[5]}.{row[6]}",
                orphan_rows=_orphan_count(
                    connection,
                    schema,
                    str(row[1]),
                    [str(name) for name in row[4]],
                    str(row[5]),
                    str(row[6]),
                    [str(name) for name in row[7]],
                ),
            )
        )
    return ForeignKeySummary(
        total=len(rows),
        validated=len(rows) - len(not_valid),
        not_valid=tuple(not_valid),
        by_schema=tuple(
            (schema, totals[0], totals[1]) for schema, totals in sorted(per_schema.items())
        ),
    )


def check_empty_assertions(
    connection: Connection,
    source: sqlite3.Connection,
    registry: Mapping[str, Disposition],
) -> tuple[EmptyAssertion, ...]:
    """Assert every deliberately-empty class actually holds no rows."""
    assertions: list[EmptyAssertion] = []
    for disposition in sorted(registry.values(), key=lambda item: item.legacy_object):
        reason = ASSERTED_EMPTY_TREATMENTS.get(disposition.target_treatment)
        if reason is None or disposition.object_type != "table":
            continue
        table = target_name(disposition.legacy_object)
        assertions.append(
            EmptyAssertion(
                legacy_table=disposition.legacy_object,
                treatment=disposition.target_treatment,
                reason=reason,
                target_schema=disposition.target_schema,
                target_table=table,
                source_rows=count_rows(source, disposition.legacy_object),
                target_rows=_target_count(connection, disposition.target_schema, table),
            )
        )
    return tuple(assertions)


def check_exclusions(
    connection: Connection,
    source: sqlite3.Connection,
    registry: Mapping[str, Disposition],
) -> tuple[Exclusion, ...]:
    """Name every source object with no target table, with its reason and its rows."""
    exclusions: list[Exclusion] = []
    for disposition in sorted(registry.values(), key=lambda item: item.legacy_object):
        reason = NOT_CREATED_REASONS.get(disposition.target_treatment)
        if reason is None:
            continue
        table = target_name(disposition.legacy_object)
        rows = (
            0
            if disposition.object_type != "table"
            else count_rows(source, disposition.legacy_object)
        )
        exclusions.append(
            Exclusion(
                legacy_object=disposition.legacy_object,
                object_type=disposition.object_type,
                planning_disposition=disposition.planning_disposition,
                treatment=disposition.target_treatment,
                reason=reason,
                source_rows=rows,
                present_in_target=_relation_exists(connection, disposition.target_schema, table),
            )
        )
    return tuple(exclusions)


def check_absence(registry_document: Mapping[str, Any]) -> AbsenceCheck:
    """Compare the registry's absence list with OD-001 as written."""
    observed = tuple(
        AbsentObject(
            legacy_object=str(entry["legacy_object"]),
            planning_disposition=str(entry["planning_disposition"]),
        )
        for entry in sorted(
            registry_document.get("absent_from_source", ()),
            key=lambda entry: str(entry["legacy_object"]),
        )
    )
    names = {item.legacy_object for item in observed}
    expected = set(ABSENT_FROM_SOURCE_AT_SCHEMA_128)
    return AbsenceCheck(
        expected=ABSENT_FROM_SOURCE_AT_SCHEMA_128,
        observed=observed,
        missing_from_registry=tuple(sorted(expected - names)),
        unexpected_in_registry=tuple(sorted(names - expected)),
    )


def read_renames(connection: Connection) -> RenameReport:
    """Read `migration_control.identifier_map` and surface the OD-024 rename."""
    rows = connection.execute(
        text(
            # S608: `CONTROL_SCHEMA` is a module constant, not input.
            "SELECT object_kind, owning_table, original, shortened "  # noqa: S608
            f"FROM {CONTROL_SCHEMA}.identifier_map ORDER BY object_kind, owning_table, original"
        )
    ).all()
    renames = tuple(
        IdentifierRename(
            object_kind=str(row[0]),
            owning_table=str(row[1]),
            original=str(row[2]),
            shortened=str(row[3]),
        )
        for row in rows
    )
    by_kind: dict[str, int] = {}
    for rename in renames:
        by_kind[rename.object_kind] = by_kind.get(rename.object_kind, 0) + 1
    owner, original, _ = NEUTRALISED_COLUMN
    neutralised = tuple(
        rename for rename in renames if rename.owning_table == owner and rename.original == original
    )
    longest = tuple(sorted(renames, key=lambda item: -len(item.original))[:5])
    return RenameReport(
        total=len(renames),
        by_kind=tuple(sorted(by_kind.items())),
        neutralised=neutralised,
        longest_originals=longest,
    )


def check_provenance(connection: Connection, parity: Sequence[TableParity]) -> ProvenanceReport:
    """OD-011. Every loaded row must name its run, source table, schema, and key."""
    columns = tuple(name for name, _ in PROVENANCE_COLUMNS)
    predicate = " OR ".join(f"{quote(name)} IS NULL" for name in columns)
    gaps: list[ProvenanceGap] = []
    checked = 0
    for table in parity:
        if table.target_rows == 0:
            continue
        checked += 1
        statement = (
            f"SELECT count(*) FROM {qualify(table.target_schema, table.target_table)} "  # noqa: S608
            f"WHERE {predicate}"
        )
        missing = int(connection.execute(text(statement)).scalar_one())
        if missing:
            gaps.append(
                ProvenanceGap(
                    legacy_table=table.legacy_table,
                    target_schema=table.target_schema,
                    target_table=table.target_table,
                    rows_with_null_provenance=missing,
                )
            )
    return ProvenanceReport(
        columns=columns,
        tables_checked=checked,
        rows_checked=sum(table.target_rows for table in parity),
        gaps=tuple(gaps),
    )


_IDENTITY_COLUMNS = """
SELECT n.nspname, c.relname, a.attname
  FROM pg_attribute a
  JOIN pg_class c ON c.oid = a.attrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE a.attidentity IN ('a', 'd')
   AND NOT a.attisdropped
   AND c.relkind = 'r'
   AND n.nspname = ANY(:schemas)
 ORDER BY n.nspname, c.relname, a.attname
"""


def check_sequences(connection: Connection, schemas: Sequence[str]) -> tuple[SequenceState, ...]:
    """Every identity sequence against the largest key its table holds.

    The load inserts the source's own keys into `GENERATED BY DEFAULT` columns,
    which leaves the sequence behind the data until it is reset (OD-016, OD-022).
    The expected next value is therefore `max(key) + 1`, or 1 for an empty table.
    """
    states: list[SequenceState] = []
    for schema, table, column in connection.execute(
        text(_IDENTITY_COLUMNS), {"schemas": list(schemas)}
    ).all():
        relation = qualify(str(schema), str(table))
        sequence = connection.execute(
            text("SELECT pg_get_serial_sequence(:relation, :column)"),
            {"relation": relation, "column": str(column)},
        ).scalar_one()
        if sequence is None:  # pragma: no cover - an identity column always has one
            continue
        # S608: quoted catalogue names throughout.
        maximum = connection.execute(
            text(f"SELECT max({quote(str(column))}) FROM {relation}")  # noqa: S608
        ).scalar_one()
        last_value, is_called = connection.execute(
            text(f"SELECT last_value, is_called FROM {sequence}")  # noqa: S608
        ).one()
        states.append(
            SequenceState(
                schema=str(schema),
                table=str(table),
                column=str(column),
                sequence=str(sequence),
                max_key=None if maximum is None else int(maximum),
                next_value=int(last_value) + (1 if is_called else 0),
                expected_next_value=1 if maximum is None else int(maximum) + 1,
            )
        )
    return tuple(states)


def check_views(
    connection: Connection,
    source: sqlite3.Connection,
    registry: Mapping[str, Disposition],
) -> tuple[ViewCheck, ...]:
    """OD-018. The two SQLite read models against the target views that mirror them.

    A view carries no rows of its own, so the check is existence plus row count
    against the source view once the base tables are loaded. A missing view is a
    named gap, not an omission from the report: it is one of the plan's 595
    objects and it has to land somewhere.
    """
    checks: list[ViewCheck] = []
    for disposition in sorted(registry.values(), key=lambda item: item.legacy_object):
        if disposition.object_type != "view":
            continue
        name = target_name(disposition.legacy_object)
        present = bool(
            connection.execute(
                text(
                    "SELECT 1 FROM information_schema.views "
                    "WHERE table_schema = :schema AND table_name = :view"
                ),
                {"schema": disposition.target_schema, "view": name},
            ).first()
        )
        checks.append(
            ViewCheck(
                legacy_view=disposition.legacy_object,
                target_schema=disposition.target_schema,
                target_view=name,
                source_rows=count_rows(source, disposition.legacy_object),
                present_in_target=present,
                target_rows=(
                    _target_count(connection, disposition.target_schema, name) if present else None
                ),
            )
        )
    return tuple(checks)


def account_rows(
    source: sqlite3.Connection,
    registry: Mapping[str, Disposition],
    parity: Sequence[TableParity],
    exclusions: Sequence[Exclusion],
    empty: Sequence[EmptyAssertion],
) -> RowAccounting:
    """Place every source row in exactly one bucket, starting from the catalogue.

    The sweep begins at `sqlite_master` rather than at the registry, because a
    registry that omitted an object would otherwise reconcile perfectly against
    itself while a table went missing.
    """
    names = [
        str(row[0])
        for row in source.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY 1")
    ]
    total = sum(count_rows(source, name) for name in names)
    missing = tuple(name for name in names if name not in registry)

    loaded = {table.legacy_table: table.source_rows for table in parity}
    excluded = {
        item.legacy_object: item.source_rows for item in exclusions if item.object_type == "table"
    }
    asserted = {
        item.legacy_table: item.source_rows
        for item in empty
        # A `PROVENANCE_ONLY` table is both loaded and asserted empty; count it
        # once, on the loaded side, so the arithmetic cannot double-credit it.
        if item.legacy_table not in loaded
    }
    bucketed = set(loaded) | set(excluded) | set(asserted)
    return RowAccounting(
        source_tables=len(names),
        source_rows=total,
        registry_tables=sum(1 for item in registry.values() if item.object_type == "table"),
        loaded_rows=sum(loaded.values()),
        excluded_rows=sum(excluded.values()),
        asserted_empty_rows=sum(asserted.values()),
        objects_missing_from_registry=missing,
        objects_in_no_bucket=tuple(name for name in names if name not in bucketed),
    )


def check_retention(
    source_path: Path,
    integrity: SourceIntegrity,
    accounting: RowAccounting,
    quarantined_rows: int,
) -> RetentionRisk:
    """Count verified copies of the source, and price what only it holds."""
    siblings: list[SiblingFile] = []
    copies = 0
    for candidate in sorted(source_path.parent.glob(f"{source_path.name}*")):
        if candidate == source_path or not candidate.is_file():
            continue
        size = candidate.stat().st_size
        # Only a same-sized file could be a byte-identical copy, so only that one
        # is worth reading 4.4 GB to rule in or out.
        identical = size == integrity.byte_count and file_digest(candidate)[0] == integrity.sha256
        copies += int(identical)
        siblings.append(
            SiblingFile(file_name=candidate.name, byte_count=size, identical_to_source=identical)
        )
    return RetentionRisk(
        source_file_name=source_path.name,
        source_bytes=integrity.byte_count,
        source_sha256=integrity.sha256,
        siblings=tuple(siblings),
        verified_copies=copies,
        rows_held_only_here=accounting.withheld_rows + quarantined_rows,
    )


def _waived_shortfall(
    table: TableParity, quarantine: Sequence[QuarantineGroup]
) -> tuple[bool, tuple[str, ...]]:
    """Say whether a table's shortfall is one a decision has already adjudicated."""
    codes = {group.error_code for group in quarantine if group.legacy_table == table.legacy_table}
    if not table.accounted or not codes:
        return False, ()
    unadjudicated = codes - set(WAIVED_QUARANTINE_CODES)
    if unadjudicated:
        return False, ()
    return True, tuple(sorted({WAIVED_QUARANTINE_CODES[code] for code in codes}))


def evaluate(report: Reconciliation) -> tuple[Criterion, ...]:
    """Evaluate OD-012 against what was measured. Nothing is assumed to pass."""
    unaccounted = [table for table in report.parity if not table.accounted]
    inexact = [table for table in report.parity if not table.exact]
    migrate_data = [
        table for table in report.parity if table.planning_disposition == "MIGRATE_DATA"
    ]
    migrate_data_inexact = [
        table for table in inexact if table.planning_disposition == "MIGRATE_DATA"
    ]
    adjudications = [_waived_shortfall(table, report.quarantine) for table in migrate_data_inexact]
    unwaived = [
        table
        for table, (waived, _) in zip(migrate_data_inexact, adjudications, strict=True)
        if not waived
    ]
    waivers = tuple(sorted({decision for _, decisions in adjudications for decision in decisions}))
    uncovered = [item for item in report.identity if not item.covered]
    duplicates = [
        group for group in report.quarantine if group.error_code == "DUPLICATE_NATURAL_KEY"
    ]
    non_empty = [item for item in report.empty_assertions if not item.empty]
    leaked = [item for item in report.exclusions if item.present_in_target]
    unequal = [item for item in report.keyless if not item.multisets_equal]
    wrong_sequences = [item for item in report.sequences if not item.correct]
    unreconciled_views = [view for view in report.views if not view.reconciled]

    return (
        Criterion(
            "P10-01",
            "every loaded table's source rows are either in the target or in quarantine",
            PASSED if not unaccounted else FAILED,
            f"{len(report.parity)} tables; {len(unaccounted)} unaccounted",
        ),
        Criterion(
            "P10-02",
            "every MIGRATE_DATA table's target count equals its source count",
            (PASSED if not migrate_data_inexact else (FAILED if unwaived else WAIVED)),
            (
                f"{len(migrate_data_inexact)} of {len(migrate_data)} differ; "
                f"{len(unwaived)} without an adjudicating decision"
            ),
            waiver=", ".join(waivers) or None,
        ),
        Criterion(
            "P10-03",
            "no row was lost silently: every shortfall is a named quarantine record",
            PASSED if not unaccounted else FAILED,
            f"{report.quarantined_rows} quarantined rows in {len(report.quarantine)} groups",
        ),
        Criterion(
            "P10-04",
            "identity coverage: one source_key_map entry per loaded row of a keyed table",
            PASSED if not uncovered else FAILED,
            f"{len(uncovered)} tables with incomplete coverage",
        ),
        Criterion(
            "P10-05",
            "keyless tables reconcile by source_row_hash multiset equality (OD-014)",
            PASSED if report.keyless and not unequal else (FAILED if unequal else UNEVALUATED),
            f"{len(report.keyless)} keyless tables; {len(unequal)} unequal",
        ),
        Criterion(
            "P10-06",
            "no orphan on a required foreign key",
            PASSED if not report.foreign_keys.not_valid else FAILED,
            (
                f"{report.foreign_keys.validated}/{report.foreign_keys.total} validated; "
                f"{report.foreign_keys.orphan_rows} orphan rows"
            ),
        ),
        Criterion(
            "P10-07",
            "no duplicate on a required unique key",
            PASSED if not duplicates else FAILED,
            f"{sum(group.rows for group in duplicates)} DUPLICATE_NATURAL_KEY records",
        ),
        Criterion(
            "P10-08",
            "deliberately empty classes are asserted empty",
            PASSED if not non_empty else FAILED,
            f"{len(report.empty_assertions)} tables asserted; {len(non_empty)} not empty",
        ),
        Criterion(
            "P10-09",
            "every excluded object is named, priced, and absent from the target",
            PASSED if not leaked else FAILED,
            f"{len(report.exclusions)} excluded objects, {report.excluded_rows} source rows",
        ),
        Criterion(
            "P10-10",
            "the ABSENT_FROM_SOURCE_AT_SCHEMA_128 list matches OD-001 exactly",
            PASSED if report.absence.matches else FAILED,
            f"{len(report.absence.observed)} objects",
        ),
        Criterion(
            "P10-11",
            "every loaded row carries a complete provenance stamp",
            PASSED if report.provenance.complete else FAILED,
            f"{report.provenance.rows_checked} rows over {report.provenance.tables_checked} tables",
        ),
        Criterion(
            "P10-12",
            "every identity sequence is at max(key) + 1, or at 1 for an empty table",
            PASSED if not wrong_sequences else FAILED,
            f"{len(report.sequences)} sequences; {len(wrong_sequences)} misplaced",
        ),
        Criterion(
            "P10-13",
            "the source file is byte-identical to what every run bound itself to, "
            "and no journal sibling was created",
            PASSED if report.source.intact else FAILED,
            (
                f"{report.source.runs_agreeing}/{len(report.runs)} runs agree; "
                f"{len(report.source.journal_siblings)} journal siblings"
            ),
        ),
        Criterion(
            "P10-14",
            "the evidence tree passes the personal-data redaction scan (OD-004)",
            PASSED if report.scan.clean else FAILED,
            f"{len(report.scan.findings)} findings over {report.scan.files_scanned} files",
        ),
        Criterion(
            "P10-15",
            "every source object has a disposition and every source row is in one bucket",
            PASSED if report.accounting.balanced else FAILED,
            (
                f"{report.accounting.source_tables} source tables, "
                f"{report.accounting.source_rows} rows; "
                f"{len(report.accounting.objects_in_no_bucket)} in no bucket"
            ),
        ),
        Criterion(
            "P10-16",
            "each SQLite read model is ported as a target view whose row count "
            "equals the source view's (OD-018)",
            (FAILED if unreconciled_views else (PASSED if report.views else UNEVALUATED)),
            f"{len(report.views)} source views; {len(unreconciled_views)} unreconciled",
        ),
    )


def reconcile(
    engine: Engine,
    source_path: Path,
    registry: Mapping[str, Disposition],
    registry_document: Mapping[str, Any],
    scan: redaction.ScanResult,
) -> Reconciliation:
    """Measure the whole migration and evaluate OD-012 against the result."""
    dispositions = _loaded(registry)
    with engine.connect() as connection, open_source(source_path) as source:
        runs = read_runs(connection)
        integrity = check_source_integrity(source_path, source, runs)
        quarantine = read_quarantine(connection)
        parity = check_parity(connection, source, dispositions, quarantine)
        identity = check_identity_coverage(connection, source, parity)
        keyless = check_keyless_tables(connection, source, parity, identity)
        foreign_keys = check_foreign_keys(connection, ALL_SCHEMAS)
        empty = check_empty_assertions(connection, source, registry)
        exclusions = check_exclusions(connection, source, registry)
        renames = read_renames(connection)
        provenance = check_provenance(connection, parity)
        sequences = check_sequences(connection, ALL_SCHEMAS)
        views = check_views(connection, source, registry)
        accounting = account_rows(source, registry, parity, exclusions, empty)
        retention = check_retention(
            source_path, integrity, accounting, sum(group.rows for group in quarantine)
        )
        revision = target_revision(connection)

    report = Reconciliation(
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        source_schema_version=integrity.schema_version,
        target_alembic_revision=revision,
        source=integrity,
        runs=runs,
        parity=parity,
        quarantine=quarantine,
        identity=identity,
        keyless=keyless,
        foreign_keys=foreign_keys,
        empty_assertions=empty,
        exclusions=exclusions,
        absence=check_absence(registry_document),
        renames=renames,
        provenance=provenance,
        sequences=sequences,
        views=views,
        accounting=accounting,
        retention=retention,
        scan=scan,
    )
    report.criteria = evaluate(report)
    return report


def as_dict(report: Reconciliation) -> dict[str, Any]:
    """Render the report as JSON-ready data, with the derived totals made explicit."""
    document = asdict(report)
    document["record_type"] = "MIGRATION_PHASE_10_RECONCILIATION"
    document["verdict"] = report.verdict
    document["totals"] = {
        "loaded_tables": len(report.parity),
        "source_rows": report.source_rows,
        "target_rows": report.target_rows,
        "quarantined_rows": report.quarantined_rows,
        "excluded_objects": len(report.exclusions),
        "excluded_rows": report.excluded_rows,
        "tables_asserted_empty": len(report.empty_assertions),
        "foreign_keys": report.foreign_keys.total,
        "foreign_keys_validated": report.foreign_keys.validated,
        "identifier_renames": report.renames.total,
        "sequences": len(report.sequences),
        "source_tables": report.accounting.source_tables,
        "source_rows_all_tables": report.accounting.source_rows,
        "withheld_rows": report.accounting.withheld_rows,
        "withheld_share": round(report.accounting.withheld_share, 6),
    }
    document["parity_mismatches"] = [asdict(table) for table in report.parity if not table.exact]
    return document
