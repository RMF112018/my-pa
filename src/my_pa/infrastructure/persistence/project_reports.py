"""The project-report tables, behind `ProjectReportsRepository` (project reports WP3P-S3).

Twelve tables are reached here and nowhere else (revision `0d4e247d03cb`,
Manager rulings D1, D2, D6, D10 and D11): the binding revisions, filter
declarations and binding pointers; the Layer A snapshot heads and raw rows; the
derivations with their row roles, lines, line values and stated totals; the
record identities; and the cross-checks. Current derivations are read through
the view `project_report_current_derivations`, never by re-deriving "current"
here, so a superseded derivation cannot be counted.

**The partition is reached through the guard, never written by hand.** The
`persistence/ingestion.py` idiom: every SELECT and UPDATE composes `_mine` (a
one-line wrapper over `partition_criterion`) and every INSERT composes `_bound`
(a one-line wrapper over `principal_bound_values`). The Principal is a
parameter; nothing here reads it back from a row or a record.

**The database guards are the authority.** Any change to an append-only row,
a pointer moved anywhere but to the revision superseding its own, a second
active binding for one Project, a snapshot whose reconstruction digest is not
its lifecycle digest, and a value held by the wrong column are refused by the
revision's triggers, keys and CHECKs; this module does not pre-check and
absorb them, so the caller sees the refusal. The one exception is the record
identity, which is get-or-create by contract (`ON CONFLICT DO NOTHING`, then a
read). A missing pointer on a move is `RepositoryFailureError`.

Nothing here logs: rows hold raw export text (names, descriptions, minutes).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import ColumnElement, Table, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Row

from my_pa.contracts.ports import (
    ProjectReportBindingRecord,
    ProjectReportBindingRevisionRecord,
    ProjectReportCrossCheckRecord,
    ProjectReportDerivationRecord,
    ProjectReportFilterDeclarationRecord,
    ProjectReportLineRecord,
    ProjectReportLineValueRecord,
    ProjectReportRecordEntry,
    ProjectReportRowRecord,
    ProjectReportRowRoleRecord,
    ProjectReportSnapshotRecord,
    ProjectReportsRepository,
    ProjectReportStatedTotalRecord,
    RepositoryFailureError,
)
from my_pa.domain.project_reports.model import (
    Additivity,
    BindingReason,
    BindingState,
    CompletenessClass,
    DerivationState,
    DerivationTrigger,
    FamilyView,
    IdentityBasis,
    IdentityState,
    LineKind,
    ObservationState,
    QuarantineReason,
    ReconciliationOutcome,
    RecordFamily,
    RowReason,
    RowRole,
    StatusClass,
    TotalScope,
    ValueKind,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    project_report_binding_revisions,
    project_report_bindings,
    project_report_cross_checks,
    project_report_current_derivations,
    project_report_derivations,
    project_report_filter_declarations,
    project_report_line_values,
    project_report_lines,
    project_report_records,
    project_report_row_roles,
    project_report_rows,
    project_report_snapshots,
    project_report_stated_totals,
)

__all__ = ["SqlProjectReportsRepository"]


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


def _columns(table: Table) -> tuple[Any, ...]:
    """Every column but the partition, which is never read back into a record."""
    return tuple(column for column in table.c if column.name != "principal_id")


def _optional[T](value: str | None, kind: Callable[[str], T]) -> T | None:
    return None if value is None else kind(value)


#: The typed column of each value kind (the CHECK holds the others NULL).
_VALUE_COLUMN: Final = {
    ValueKind.MONEY: "value_decimal",
    ValueKind.NUMBER: "value_decimal",
    ValueKind.DATE: "value_date",
    ValueKind.BOOLEAN: "value_boolean",
    ValueKind.TEXT: "value_text",
    ValueKind.IDENTIFIER: "value_text",
}


# --- row mappers ---------------------------------------------------------------------


def _to_revision(row: Row[Any]) -> ProjectReportBindingRevisionRecord:
    return ProjectReportBindingRevisionRecord(
        binding_revision_id=row.binding_revision_id,
        ingest_source_id=row.ingest_source_id,
        project_id=row.project_id,
        declared_project_number=row.declared_project_number,
        state=BindingState(row.state),
        currency=row.currency,
        recorded_at=row.recorded_at,
        change_set_sha256=row.change_set_sha256,
        reason_code=BindingReason(row.reason_code),
        supersedes_revision_id=row.supersedes_revision_id,
        recorded_by=row.recorded_by,
    )


def _to_binding(row: Row[Any]) -> ProjectReportBindingRecord:
    return ProjectReportBindingRecord(
        ingest_source_id=row.ingest_source_id,
        binding_revision_id=row.binding_revision_id,
        project_id=row.project_id,
        state=BindingState(row.state),
    )


def _to_snapshot(row: Row[Any]) -> ProjectReportSnapshotRecord:
    return ProjectReportSnapshotRecord(
        snapshot_id=row.snapshot_id,
        ingest_source_id=row.ingest_source_id,
        file_sha256=row.file_sha256,
        bom_present=row.bom_present,
        header_raw_record=row.header_raw_record,
        header_terminator=row.header_terminator,
        header_cells=tuple(row.header_cells),
        header_signature=row.header_signature,
        signature_version=row.signature_version,
        reader_version=row.reader_version,
        data_row_count=row.data_row_count,
        embedded_line_break_count=row.embedded_line_break_count,
        reconstruction_sha256=row.reconstruction_sha256,
    )


def _to_row(row: Row[Any]) -> ProjectReportRowRecord:
    return ProjectReportRowRecord(
        row_ordinal=row.row_ordinal,
        raw_record=row.raw_record,
        terminator=row.terminator,
        cells=tuple(row.cells),
        width_matches=row.width_matches,
    )


def _to_derivation(row: Row[Any]) -> ProjectReportDerivationRecord:
    return ProjectReportDerivationRecord(
        derivation_id=row.derivation_id,
        snapshot_id=row.snapshot_id,
        ingest_source_id=row.ingest_source_id,
        binding_revision_id=row.binding_revision_id,
        project_id=row.project_id,
        state=DerivationState(row.state),
        identity_version=row.identity_version,
        status_map_version=row.status_map_version,
        role_counts=dict(row.role_counts),
        trigger=DerivationTrigger(row.trigger),
        derived_at=row.derived_at,
        quarantine_reason=_optional(row.quarantine_reason, QuarantineReason),
        record_family=_optional(row.record_family, RecordFamily),
        family_view=_optional(row.family_view, FamilyView),
        adapter_version=row.adapter_version,
        completeness_class=_optional(row.completeness_class, CompletenessClass),
        reconciliation=None if row.reconciliation is None else dict(row.reconciliation),
        supersedes_derivation_id=row.supersedes_derivation_id,
    )


def _to_row_role(row: Row[Any]) -> ProjectReportRowRoleRecord:
    return ProjectReportRowRoleRecord(
        derivation_id=row.derivation_id,
        row_ordinal=row.row_ordinal,
        snapshot_id=row.snapshot_id,
        row_role=RowRole(row.row_role),
        group_path=tuple((int(s[0]), str(s[1]), int(s[2])) for s in row.group_path),
        row_reason=_optional(row.row_reason, RowReason),
        group_level=row.group_level,
        group_key=row.group_key,
        parent_header_ordinal=row.parent_header_ordinal,
    )


def _to_value(row: Row[Any]) -> ProjectReportLineValueRecord:
    kind = ValueKind(row.value_kind)
    held: dict[str, Decimal | date | bool | str | None] = {
        "value_decimal": row.value_decimal,
        "value_date": row.value_date,
        "value_boolean": row.value_boolean,
        "value_text": row.value_text,
    }
    value = held[_VALUE_COLUMN[kind]]
    return ProjectReportLineValueRecord(
        field_key=row.field_key,
        value_kind=kind,
        raw_text=row.raw_text,
        value=value,
        value_reason=_optional(row.value_reason, RowReason),
    )


def _to_line(
    row: Row[Any], values: tuple[ProjectReportLineValueRecord, ...]
) -> ProjectReportLineRecord:
    return ProjectReportLineRecord(
        derivation_id=row.derivation_id,
        row_ordinal=row.row_ordinal,
        project_id=row.project_id,
        record_family=RecordFamily(row.record_family),
        family_view=FamilyView(row.family_view),
        line_kind=LineKind(row.line_kind),
        identity_state=IdentityState(row.identity_state),
        observation_state=ObservationState(row.observation_state),
        record_id=row.record_id,
        identity_reason=_optional(row.identity_reason, RowReason),
        degraded_reasons=tuple(RowReason(reason) for reason in row.degraded_reasons),
        status_raw=row.status_raw,
        status_class=_optional(row.status_class, StatusClass),
        identifier_prefix=row.identifier_prefix,
        identifier_numeric_suffix=row.identifier_numeric_suffix,
        values=values,
    )


def _to_total(row: Row[Any]) -> ProjectReportStatedTotalRecord:
    return ProjectReportStatedTotalRecord(
        derivation_id=row.derivation_id,
        row_ordinal=row.row_ordinal,
        column_index=row.column_index,
        row_role=RowRole(row.row_role),
        scope=TotalScope(row.scope),
        field_key=row.field_key,
        raw_text=row.raw_text,
        additivity=Additivity(row.additivity),
        outcome=ReconciliationOutcome(row.outcome),
        group_level=row.group_level,
        group_key=row.group_key,
        value=row.value,
        computed_value=row.computed_value,
    )


def _to_record(row: Row[Any]) -> ProjectReportRecordEntry:
    return ProjectReportRecordEntry(
        record_id=row.record_id,
        project_id=row.project_id,
        record_family=RecordFamily(row.record_family),
        identity_key=row.identity_key,
        identity_version=row.identity_version,
        identity_basis=IdentityBasis(row.identity_basis),
        created_by_derivation_id=row.created_by_derivation_id,
    )


def _to_cross_check(row: Row[Any]) -> ProjectReportCrossCheckRecord:
    return ProjectReportCrossCheckRecord(
        check_kind=row.check_kind,
        left_derivation_id=row.left_derivation_id,
        right_derivation_id=row.right_derivation_id,
        project_id=row.project_id,
        outcome=ReconciliationOutcome(row.outcome),
        checked_at=row.checked_at,
        date_label=row.date_label,
        left_value=row.left_value,
        right_value=row.right_value,
    )


# --- value builders --------------------------------------------------------------------


def _derivation_values(derivation: ProjectReportDerivationRecord) -> dict[str, object]:
    values: dict[str, object] = {
        "derivation_id": derivation.derivation_id,
        "snapshot_id": derivation.snapshot_id,
        "ingest_source_id": derivation.ingest_source_id,
        "binding_revision_id": derivation.binding_revision_id,
        "project_id": derivation.project_id,
        "state": derivation.state.value,
        "quarantine_reason": _value(derivation.quarantine_reason),
        "record_family": _value(derivation.record_family),
        "family_view": _value(derivation.family_view),
        "adapter_version": derivation.adapter_version,
        "identity_version": derivation.identity_version,
        "status_map_version": derivation.status_map_version,
        "completeness_class": _value(derivation.completeness_class),
        "role_counts": dict(derivation.role_counts),
        "trigger": derivation.trigger.value,
        "supersedes_derivation_id": derivation.supersedes_derivation_id,
        "derived_at": derivation.derived_at,
    }
    if derivation.reconciliation is not None:
        # Omitted rather than bound to `None`: a bound `None` is a JSON null,
        # not SQL NULL (the `structured_content` precedent in `tables.py`).
        values["reconciliation"] = dict(derivation.reconciliation)
    return values


def _value(member: object) -> str | None:
    return None if member is None else str(getattr(member, "value", member))


def _role_values(role: ProjectReportRowRoleRecord) -> dict[str, object]:
    return {
        "derivation_id": role.derivation_id,
        "row_ordinal": role.row_ordinal,
        "snapshot_id": role.snapshot_id,
        "row_role": role.row_role.value,
        "row_reason": _value(role.row_reason),
        "group_level": role.group_level,
        "group_key": role.group_key,
        "group_path": [list(step) for step in role.group_path],
        "parent_header_ordinal": role.parent_header_ordinal,
    }


def _line_values(line: ProjectReportLineRecord) -> dict[str, object]:
    return {
        "derivation_id": line.derivation_id,
        "row_ordinal": line.row_ordinal,
        "row_role": RowRole.DETAIL.value,
        "project_id": line.project_id,
        "record_family": line.record_family.value,
        "family_view": line.family_view.value,
        "line_kind": line.line_kind.value,
        "record_id": line.record_id,
        "identity_state": line.identity_state.value,
        "identity_reason": _value(line.identity_reason),
        "observation_state": line.observation_state.value,
        "degraded_reasons": [reason.value for reason in line.degraded_reasons],
        "status_raw": line.status_raw,
        "status_class": _value(line.status_class),
        "identifier_prefix": line.identifier_prefix,
        "identifier_numeric_suffix": line.identifier_numeric_suffix,
    }


def _cell_values(
    line: ProjectReportLineRecord, value: ProjectReportLineValueRecord
) -> dict[str, object]:
    values: dict[str, object] = {
        "derivation_id": line.derivation_id,
        "row_ordinal": line.row_ordinal,
        "field_key": value.field_key,
        "value_kind": value.value_kind.value,
        "raw_text": value.raw_text,
        "value_reason": _value(value.value_reason),
        "value_decimal": None,
        "value_date": None,
        "value_boolean": None,
        "value_text": None,
    }
    if value.value is not None:
        values[_VALUE_COLUMN[value.value_kind]] = value.value
    return values


def _total_values(total: ProjectReportStatedTotalRecord) -> dict[str, object]:
    return {
        "derivation_id": total.derivation_id,
        "row_ordinal": total.row_ordinal,
        "column_index": total.column_index,
        "row_role": total.row_role.value,
        "scope": total.scope.value,
        "group_level": total.group_level,
        "group_key": total.group_key,
        "field_key": total.field_key,
        "raw_text": total.raw_text,
        "value": total.value,
        "additivity": total.additivity.value,
        "computed_value": total.computed_value,
        "outcome": total.outcome.value,
    }


class SqlProjectReportsRepository(ProjectReportsRepository):
    """`ProjectReportsRepository`, over the general unit of work's `Connection`.

    Takes the connection rather than opening one: the caller owns the
    transaction, and this class only issues statements on it. Nothing here
    commits.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _insert_many(
        self, table: Table, principal_id: str, rows: Sequence[dict[str, object]]
    ) -> None:
        if rows:
            self._connection.execute(
                insert(table), [_bound(table, principal_id, row) for row in rows]
            )

    # --- bindings ---------------------------------------------------------------

    def insert_binding_revision(
        self, principal_id: str, revision: ProjectReportBindingRevisionRecord
    ) -> None:
        values: dict[str, object] = {
            "binding_revision_id": revision.binding_revision_id,
            "ingest_source_id": revision.ingest_source_id,
            "project_id": revision.project_id,
            "declared_project_number": revision.declared_project_number,
            "state": revision.state.value,
            "supersedes_revision_id": revision.supersedes_revision_id,
            "currency": revision.currency,
            "recorded_at": revision.recorded_at,
            "recorded_by": revision.recorded_by,
            "change_set_sha256": revision.change_set_sha256,
            "reason_code": revision.reason_code.value,
        }
        self._connection.execute(
            insert(project_report_binding_revisions).values(
                _bound(project_report_binding_revisions, principal_id, values)
            )
        )

    def get_binding_revision(
        self, principal_id: str, binding_revision_id: str
    ) -> ProjectReportBindingRevisionRecord | None:
        row = self._connection.execute(
            select(*_columns(project_report_binding_revisions)).where(
                _mine(project_report_binding_revisions, principal_id),
                project_report_binding_revisions.c.binding_revision_id == binding_revision_id,
            )
        ).one_or_none()
        return None if row is None else _to_revision(row)

    def list_binding_revisions(
        self, principal_id: str, ingest_source_id: str
    ) -> tuple[ProjectReportBindingRevisionRecord, ...]:
        table = project_report_binding_revisions
        rows = self._connection.execute(
            select(*_columns(table))
            .where(_mine(table, principal_id), table.c.ingest_source_id == ingest_source_id)
            .order_by(table.c.recorded_at, table.c.binding_revision_id)
        )
        return tuple(_to_revision(row) for row in rows)

    def insert_filter_declarations(
        self, principal_id: str, declarations: Sequence[ProjectReportFilterDeclarationRecord]
    ) -> None:
        self._insert_many(
            project_report_filter_declarations,
            principal_id,
            [
                {
                    "binding_revision_id": declaration.binding_revision_id,
                    "slug_label": declaration.slug_label,
                    "description": declaration.description,
                    "declared_at": declaration.declared_at,
                }
                for declaration in declarations
            ],
        )

    def list_filter_declarations(
        self, principal_id: str, binding_revision_id: str
    ) -> tuple[ProjectReportFilterDeclarationRecord, ...]:
        table = project_report_filter_declarations
        rows = self._connection.execute(
            select(*_columns(table))
            .where(_mine(table, principal_id), table.c.binding_revision_id == binding_revision_id)
            .order_by(table.c.slug_label)
        )
        return tuple(
            ProjectReportFilterDeclarationRecord(
                binding_revision_id=row.binding_revision_id,
                slug_label=row.slug_label,
                description=row.description,
                declared_at=row.declared_at,
            )
            for row in rows
        )

    def insert_binding(self, principal_id: str, binding: ProjectReportBindingRecord) -> None:
        values: dict[str, object] = {
            "ingest_source_id": binding.ingest_source_id,
            "binding_revision_id": binding.binding_revision_id,
            "project_id": binding.project_id,
            "state": binding.state.value,
        }
        self._connection.execute(
            insert(project_report_bindings).values(
                _bound(project_report_bindings, principal_id, values)
            )
        )

    def move_binding(self, principal_id: str, binding: ProjectReportBindingRecord) -> None:
        table = project_report_bindings
        changed = self._connection.execute(
            update(table)
            .where(_mine(table, principal_id), table.c.ingest_source_id == binding.ingest_source_id)
            .values(
                binding_revision_id=binding.binding_revision_id,
                project_id=binding.project_id,
                state=binding.state.value,
            )
            .returning(table.c.ingest_source_id)
        ).first()
        if changed is None:
            raise RepositoryFailureError

    def get_binding(
        self, principal_id: str, ingest_source_id: str
    ) -> ProjectReportBindingRecord | None:
        table = project_report_bindings
        row = self._connection.execute(
            select(*_columns(table)).where(
                _mine(table, principal_id), table.c.ingest_source_id == ingest_source_id
            )
        ).one_or_none()
        return None if row is None else _to_binding(row)

    def list_bindings(
        self, principal_id: str, *, active_only: bool = False
    ) -> tuple[ProjectReportBindingRecord, ...]:
        table = project_report_bindings
        statement = select(*_columns(table)).where(_mine(table, principal_id))
        if active_only:
            statement = statement.where(table.c.state == BindingState.ACTIVE.value)
        rows = self._connection.execute(statement.order_by(table.c.ingest_source_id))
        return tuple(_to_binding(row) for row in rows)

    # --- Layer A ----------------------------------------------------------------

    def insert_snapshot(
        self,
        principal_id: str,
        snapshot: ProjectReportSnapshotRecord,
        rows: Sequence[ProjectReportRowRecord],
    ) -> None:
        values: dict[str, object] = {
            "snapshot_id": snapshot.snapshot_id,
            "ingest_source_id": snapshot.ingest_source_id,
            "file_sha256": snapshot.file_sha256,
            "bom_present": snapshot.bom_present,
            "header_raw_record": snapshot.header_raw_record,
            "header_terminator": snapshot.header_terminator,
            "header_cells": list(snapshot.header_cells),
            "header_signature": snapshot.header_signature,
            "signature_version": snapshot.signature_version,
            "reader_version": snapshot.reader_version,
            "data_row_count": snapshot.data_row_count,
            "embedded_line_break_count": snapshot.embedded_line_break_count,
            "reconstruction_sha256": snapshot.reconstruction_sha256,
        }
        self._connection.execute(
            insert(project_report_snapshots).values(
                _bound(project_report_snapshots, principal_id, values)
            )
        )
        self._insert_many(
            project_report_rows,
            principal_id,
            [
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "row_ordinal": row.row_ordinal,
                    "raw_record": row.raw_record,
                    "terminator": row.terminator,
                    "cells": list(row.cells),
                    "width_matches": row.width_matches,
                }
                for row in rows
            ],
        )

    def get_snapshot(
        self, principal_id: str, snapshot_id: str
    ) -> ProjectReportSnapshotRecord | None:
        table = project_report_snapshots
        row = self._connection.execute(
            select(*_columns(table)).where(
                _mine(table, principal_id), table.c.snapshot_id == snapshot_id
            )
        ).one_or_none()
        return None if row is None else _to_snapshot(row)

    def list_rows(self, principal_id: str, snapshot_id: str) -> tuple[ProjectReportRowRecord, ...]:
        table = project_report_rows
        rows = self._connection.execute(
            select(*_columns(table))
            .where(_mine(table, principal_id), table.c.snapshot_id == snapshot_id)
            .order_by(table.c.row_ordinal)
        )
        return tuple(_to_row(row) for row in rows)

    # --- derivations ------------------------------------------------------------

    def insert_derivation(
        self,
        principal_id: str,
        derivation: ProjectReportDerivationRecord,
        *,
        row_roles: Sequence[ProjectReportRowRoleRecord] = (),
        lines: Sequence[ProjectReportLineRecord] = (),
        stated_totals: Sequence[ProjectReportStatedTotalRecord] = (),
    ) -> None:
        self._connection.execute(
            insert(project_report_derivations).values(
                _bound(project_report_derivations, principal_id, _derivation_values(derivation))
            )
        )
        self._insert_many(
            project_report_row_roles, principal_id, [_role_values(role) for role in row_roles]
        )
        self._insert_many(
            project_report_lines, principal_id, [_line_values(line) for line in lines]
        )
        self._insert_many(
            project_report_line_values,
            principal_id,
            [_cell_values(line, value) for line in lines for value in line.values],
        )
        self._insert_many(
            project_report_stated_totals,
            principal_id,
            [_total_values(total) for total in stated_totals],
        )

    def get_derivation(
        self, principal_id: str, derivation_id: str
    ) -> ProjectReportDerivationRecord | None:
        table = project_report_derivations
        row = self._connection.execute(
            select(*_columns(table)).where(
                _mine(table, principal_id), table.c.derivation_id == derivation_id
            )
        ).one_or_none()
        return None if row is None else _to_derivation(row)

    def current_derivation(
        self, principal_id: str, snapshot_id: str
    ) -> ProjectReportDerivationRecord | None:
        view = project_report_current_derivations
        row = self._connection.execute(
            select(*_columns(view)).where(
                _mine(view, principal_id), view.c.snapshot_id == snapshot_id
            )
        ).one_or_none()
        return None if row is None else _to_derivation(row)

    def list_current_derivations(
        self,
        principal_id: str,
        *,
        ingest_source_id: str | None = None,
        state: DerivationState | None = None,
    ) -> tuple[ProjectReportDerivationRecord, ...]:
        view = project_report_current_derivations
        statement = select(*_columns(view)).where(_mine(view, principal_id))
        if ingest_source_id is not None:
            statement = statement.where(view.c.ingest_source_id == ingest_source_id)
        if state is not None:
            statement = statement.where(view.c.state == state.value)
        rows = self._connection.execute(statement.order_by(view.c.snapshot_id))
        return tuple(_to_derivation(row) for row in rows)

    def list_row_roles(
        self, principal_id: str, derivation_id: str
    ) -> tuple[ProjectReportRowRoleRecord, ...]:
        table = project_report_row_roles
        rows = self._connection.execute(
            select(*_columns(table))
            .where(_mine(table, principal_id), table.c.derivation_id == derivation_id)
            .order_by(table.c.row_ordinal)
        )
        return tuple(_to_row_role(row) for row in rows)

    def list_lines(
        self, principal_id: str, derivation_id: str
    ) -> tuple[ProjectReportLineRecord, ...]:
        cells = project_report_line_values
        by_line: dict[int, list[ProjectReportLineValueRecord]] = {}
        for row in self._connection.execute(
            select(*_columns(cells))
            .where(_mine(cells, principal_id), cells.c.derivation_id == derivation_id)
            .order_by(cells.c.row_ordinal, cells.c.field_key)
        ):
            by_line.setdefault(row.row_ordinal, []).append(_to_value(row))
        table = project_report_lines
        rows = self._connection.execute(
            select(*_columns(table))
            .where(_mine(table, principal_id), table.c.derivation_id == derivation_id)
            .order_by(table.c.row_ordinal)
        )
        return tuple(_to_line(row, tuple(by_line.get(row.row_ordinal, ()))) for row in rows)

    def list_stated_totals(
        self, principal_id: str, derivation_id: str
    ) -> tuple[ProjectReportStatedTotalRecord, ...]:
        table = project_report_stated_totals
        rows = self._connection.execute(
            select(*_columns(table))
            .where(_mine(table, principal_id), table.c.derivation_id == derivation_id)
            .order_by(table.c.row_ordinal, table.c.column_index)
        )
        return tuple(_to_total(row) for row in rows)

    # --- records and cross-checks -----------------------------------------------

    def get_or_create_record(self, principal_id: str, entry: ProjectReportRecordEntry) -> str:
        table = project_report_records
        values: dict[str, object] = {
            "record_id": entry.record_id,
            "project_id": entry.project_id,
            "record_family": entry.record_family.value,
            "identity_key": entry.identity_key,
            "identity_version": entry.identity_version,
            "identity_basis": entry.identity_basis.value,
            "created_by_derivation_id": entry.created_by_derivation_id,
        }
        self._connection.execute(
            pg_insert(table)
            .values(_bound(table, principal_id, values))
            .on_conflict_do_nothing(constraint="one_report_record_per_identity")
        )
        record_id = self._connection.execute(
            select(table.c.record_id).where(
                _mine(table, principal_id),
                table.c.project_id == entry.project_id,
                table.c.record_family == entry.record_family.value,
                table.c.identity_key == entry.identity_key,
                table.c.identity_version == entry.identity_version,
            )
        ).scalar_one()
        return str(record_id)

    def get_record(self, principal_id: str, record_id: str) -> ProjectReportRecordEntry | None:
        table = project_report_records
        row = self._connection.execute(
            select(*_columns(table)).where(
                _mine(table, principal_id), table.c.record_id == record_id
            )
        ).one_or_none()
        return None if row is None else _to_record(row)

    def insert_cross_check(self, principal_id: str, check: ProjectReportCrossCheckRecord) -> None:
        values: dict[str, object] = {
            "check_kind": check.check_kind,
            "left_derivation_id": check.left_derivation_id,
            "right_derivation_id": check.right_derivation_id,
            "project_id": check.project_id,
            "date_label": check.date_label,
            "left_value": check.left_value,
            "right_value": check.right_value,
            "outcome": check.outcome.value,
            "checked_at": check.checked_at,
        }
        self._connection.execute(
            insert(project_report_cross_checks).values(
                _bound(project_report_cross_checks, principal_id, values)
            )
        )

    def list_cross_checks(
        self, principal_id: str, project_id: str
    ) -> tuple[ProjectReportCrossCheckRecord, ...]:
        table = project_report_cross_checks
        rows = self._connection.execute(
            select(*_columns(table))
            .where(_mine(table, principal_id), table.c.project_id == project_id)
            .order_by(table.c.check_kind, table.c.left_derivation_id, table.c.right_derivation_id)
        )
        return tuple(_to_cross_check(row) for row in rows)
