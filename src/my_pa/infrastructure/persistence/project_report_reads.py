"""The project-report reads, behind `ProjectReportReadsRepository` (WP4P-S2).

Read-only. **Every derivation is reached through the view
`project_report_current_derivations`**, never the derivations table: each
statement over a line, a line value, a row role or a stated total joins the
view on its derivation, so a superseded derivation (a binding correction, an
adapter, identity or status-map re-derivation) is never answered or counted.
`tests/architecture/test_project_report_reads_use_current_derivations.py`
holds that from the source.

* **Detail rows only.** A line exists only on a detail row (the database
  refuses any other), and the group context is read from that detail row's own
  role, joined on its ordinal and its `detail` role, so no header row can join
  a line.
* **"Latest" is computed in Python** with `version_order_key`, the one
  definition of the D10 order; no statement orders versions.
* **Series labels** come from each snapshot's earliest-first-seen path (ruling
  D4), the same rule as `snapshot_labels`; the path, the slug's filter
  description and the cells never leave as anything but the typed records.
* **Text never crosses a field.** The `text` filter tests each value of the
  searched field keys on its own: `strpos(lower(value), lower(:needle))`, so
  PostgreSQL folds both sides (ruling R1-08). Folding is case-insensitive for
  ASCII in every locale; non-ASCII letters fold only as the cluster's ctype does.
* **RFI numbers match exactly**: the numeric suffix by equality, the prefix by
  equality when given (`normalize_rfi_prefix`), never a textual prefix.

The partition is reached through the guard: every statement composes `_mine`
over `partition_criterion`, and every join `matching_partition_criterion`.
Nothing here writes or logs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Final

from sqlalchemy import (
    ColumnElement,
    Table,
    Text,
    and_,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    tuple_,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.engine import Connection, Row
from sqlalchemy.sql.selectable import Join

from my_pa.contracts.ports import (
    IngestSnapshotStatus,
    ProjectReportCrossCheckRecord,
    ProjectReportLineQuery,
    ProjectReportLineValueRecord,
    ProjectReportReadLine,
    ProjectReportReadsRepository,
    ProjectReportRecordEntry,
    ProjectReportRfiCandidate,
    ProjectReportStatedTotalRecord,
    ProjectReportVersionRecord,
)
from my_pa.domain.project_reports.identity import normalize_rfi_prefix
from my_pa.domain.project_reports.labels import filename_labels
from my_pa.domain.project_reports.model import (
    BindingState,
    CompletenessClass,
    DerivationState,
    FamilyView,
    IdentityState,
    LineKind,
    ObservationState,
    QuarantineReason,
    RecordFamily,
    RowReason,
    RowRole,
    StatusClass,
)
from my_pa.domain.project_reports.reads import series_id
from my_pa.domain.project_reports.versions import VersionRef, version_order_key
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    matching_partition_criterion,
    partition_criterion,
)
from my_pa.infrastructure.persistence.project_reports import (
    _to_cross_check,
    _to_record,
    _to_total,
    _to_value,
)
from my_pa.infrastructure.persistence.tables import (
    ingest_snapshot_paths,
    ingest_snapshots,
    project_report_binding_revisions,
    project_report_bindings,
    project_report_cross_checks,
    project_report_current_derivations,
    project_report_filter_declarations,
    project_report_line_values,
    project_report_lines,
    project_report_records,
    project_report_row_roles,
    project_report_snapshots,
    project_report_stated_totals,
)

__all__ = ["SqlProjectReportReadsRepository"]

_DETAIL: Final = RowRole.DETAIL.value


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _optional[T](value: str | None, kind: Callable[[str], T]) -> T | None:
    return None if value is None else kind(value)


def _current(child: Table) -> ColumnElement[bool]:
    """The join of a derivation's child table to the current-derivations view."""
    return and_(
        matching_partition_criterion(child, project_report_current_derivations),
        child.c.derivation_id == project_report_current_derivations.c.derivation_id,
    )


def _detail_role() -> ColumnElement[bool]:
    """A line's own row role: the same ordinal, and only ever a `detail` row."""
    return and_(
        matching_partition_criterion(project_report_lines, project_report_row_roles),
        project_report_row_roles.c.derivation_id == project_report_lines.c.derivation_id,
        project_report_row_roles.c.row_ordinal == project_report_lines.c.row_ordinal,
        project_report_row_roles.c.row_role == _DETAIL,
    )


def _line_columns() -> tuple[Any, ...]:
    lines = project_report_lines
    return (
        lines.c.derivation_id,
        lines.c.row_ordinal,
        lines.c.record_family,
        lines.c.family_view,
        lines.c.line_kind,
        lines.c.identity_state,
        lines.c.observation_state,
        lines.c.record_id,
        lines.c.degraded_reasons,
        lines.c.status_raw,
        lines.c.status_class,
        lines.c.identifier_prefix,
        lines.c.identifier_numeric_suffix,
        project_report_current_derivations.c.snapshot_id,
        project_report_row_roles.c.group_path,
        project_report_records.c.identity_key,
    )


def _lines_joined() -> Join:
    """Lines, their current derivation, their own detail role and their record (if any)."""
    return (
        project_report_lines.join(
            project_report_current_derivations, _current(project_report_lines)
        )
        .join(project_report_row_roles, _detail_role())
        .outerjoin(
            project_report_records,
            and_(
                matching_partition_criterion(project_report_lines, project_report_records),
                project_report_records.c.record_id == project_report_lines.c.record_id,
            ),
        )
    )


def _value_of(column: str) -> ColumnElement[bool]:
    """A correlated value predicate on the line being read (see the callers)."""
    values = project_report_line_values
    return and_(
        matching_partition_criterion(values, project_report_lines),
        values.c.derivation_id == project_report_lines.c.derivation_id,
        values.c.row_ordinal == project_report_lines.c.row_ordinal,
        values.c.field_key == column,
    )


def _to_read_line(
    row: Row[Any], values: tuple[ProjectReportLineValueRecord, ...]
) -> ProjectReportReadLine:
    return ProjectReportReadLine(
        derivation_id=row.derivation_id,
        snapshot_id=row.snapshot_id,
        row_ordinal=row.row_ordinal,
        record_family=RecordFamily(row.record_family),
        family_view=FamilyView(row.family_view),
        line_kind=LineKind(row.line_kind),
        identity_state=IdentityState(row.identity_state),
        observation_state=ObservationState(row.observation_state),
        record_id=row.record_id,
        identity_key=row.identity_key,
        degraded_reasons=tuple(RowReason(reason) for reason in row.degraded_reasons),
        status_raw=row.status_raw,
        status_class=_optional(row.status_class, StatusClass),
        identifier_prefix=row.identifier_prefix,
        identifier_numeric_suffix=row.identifier_numeric_suffix,
        group_path=tuple((int(s[0]), str(s[1]), int(s[2])) for s in row.group_path),
        values=values,
    )


class SqlProjectReportReadsRepository(ProjectReportReadsRepository):
    """`ProjectReportReadsRepository` over the general unit of work's `Connection`."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # --- versions -----------------------------------------------------------------

    def list_report_versions(
        self,
        principal_id: str,
        *,
        project_ids: Sequence[str] | None = None,
        record_family: RecordFamily | None = None,
    ) -> tuple[ProjectReportVersionRecord, ...]:
        if project_ids is not None and not project_ids:
            return ()
        view = project_report_current_derivations
        heads = project_report_snapshots
        lifecycle = ingest_snapshots
        revisions = project_report_binding_revisions
        statement = (
            select(
                view.c.derivation_id,
                view.c.snapshot_id,
                view.c.ingest_source_id,
                view.c.binding_revision_id,
                view.c.project_id,
                view.c.state,
                view.c.quarantine_reason,
                view.c.record_family,
                view.c.family_view,
                view.c.adapter_version,
                view.c.identity_version,
                view.c.status_map_version,
                view.c.completeness_class,
                view.c.reconciliation,
                heads.c.header_signature,
                lifecycle.c.first_seen_at,
                revisions.c.currency,
                revisions.c.declared_project_number,
            )
            .select_from(
                view.join(
                    heads,
                    and_(
                        matching_partition_criterion(view, heads),
                        heads.c.snapshot_id == view.c.snapshot_id,
                    ),
                )
                .join(
                    lifecycle,
                    and_(
                        matching_partition_criterion(view, lifecycle),
                        lifecycle.c.snapshot_id == view.c.snapshot_id,
                        lifecycle.c.status == IngestSnapshotStatus.INGESTED.value,
                    ),
                )
                .join(
                    revisions,
                    and_(
                        matching_partition_criterion(view, revisions),
                        revisions.c.binding_revision_id == view.c.binding_revision_id,
                    ),
                )
            )
            .where(_mine(view, principal_id))
        )
        if project_ids is not None:
            statement = statement.where(view.c.project_id.in_(list(project_ids)))
        if record_family is not None:
            statement = statement.where(view.c.record_family == record_family.value)
        rows = list(self._connection.execute(statement))
        if not rows:
            return ()
        paths = self._earliest_paths(principal_id, [row.snapshot_id for row in rows])
        declared = self._declarations(principal_id, {row.ingest_source_id for row in rows})
        versions: list[ProjectReportVersionRecord] = []
        for row in rows:
            labels = filename_labels(paths.get(row.snapshot_id, ""))
            versions.append(
                ProjectReportVersionRecord(
                    series_id=series_id(
                        principal_id, row.ingest_source_id, labels.slug_label, row.header_signature
                    ),
                    snapshot_id=row.snapshot_id,
                    derivation_id=row.derivation_id,
                    ingest_source_id=row.ingest_source_id,
                    project_id=row.project_id,
                    binding_revision_id=row.binding_revision_id,
                    state=DerivationState(row.state),
                    quarantine_reason=_optional(row.quarantine_reason, QuarantineReason),
                    record_family=_optional(row.record_family, RecordFamily),
                    family_view=_optional(row.family_view, FamilyView),
                    adapter_version=row.adapter_version,
                    identity_version=row.identity_version,
                    status_map_version=row.status_map_version,
                    completeness_class=_optional(row.completeness_class, CompletenessClass),
                    reconciliation=None if row.reconciliation is None else dict(row.reconciliation),
                    header_signature=row.header_signature,
                    first_seen_at=row.first_seen_at,
                    date_label=labels.date_label,
                    slug_label=labels.slug_label,
                    currency=row.currency,
                    declared_project_number=row.declared_project_number,
                    filter_declared_at=None
                    if labels.slug_label is None
                    else declared.get((row.ingest_source_id, labels.slug_label)),
                )
            )
        return _in_series_order(versions)

    def _earliest_paths(self, principal_id: str, snapshot_ids: list[str]) -> dict[str, str]:
        paths = ingest_snapshot_paths
        earliest: dict[str, str] = {}
        for row in self._connection.execute(
            select(paths.c.snapshot_id, paths.c.relative_path)
            .where(_mine(paths, principal_id), paths.c.snapshot_id.in_(snapshot_ids))
            .order_by(paths.c.snapshot_id, paths.c.first_seen_at, paths.c.relative_path)
        ):
            earliest.setdefault(row.snapshot_id, row.relative_path)
        return earliest

    def _declarations(
        self, principal_id: str, source_ids: set[str]
    ) -> dict[tuple[str, str], datetime]:
        """The current active revision's declaration instant per `(source, slug)`."""
        bindings = project_report_bindings
        declarations = project_report_filter_declarations
        rows = self._connection.execute(
            select(
                bindings.c.ingest_source_id, declarations.c.slug_label, declarations.c.declared_at
            )
            .select_from(
                bindings.join(
                    declarations,
                    and_(
                        matching_partition_criterion(bindings, declarations),
                        declarations.c.binding_revision_id == bindings.c.binding_revision_id,
                    ),
                )
            )
            .where(
                _mine(bindings, principal_id),
                bindings.c.ingest_source_id.in_(sorted(source_ids)),
                bindings.c.state == BindingState.ACTIVE.value,
            )
        )
        return {(row.ingest_source_id, row.slug_label): row.declared_at for row in rows}

    # --- lines -------------------------------------------------------------------------

    def query_lines(
        self, principal_id: str, query: ProjectReportLineQuery
    ) -> tuple[ProjectReportReadLine, ...]:
        if not query.derivation_ids or query.limit < 1:
            return ()
        lines = project_report_lines
        values = project_report_line_values
        position = func.array_position(
            literal(list(query.derivation_ids), ARRAY(Text)), lines.c.derivation_id
        )
        statement = (
            select(*_line_columns())
            .select_from(_lines_joined())
            .where(
                _mine(lines, principal_id),
                lines.c.derivation_id.in_(list(query.derivation_ids)),
            )
        )
        if query.after is not None:
            statement = statement.where(
                tuple_(position, lines.c.row_ordinal)
                > tuple_(literal(query.after[0] + 1), literal(query.after[1]))
            )
        if query.status_classes:
            statement = statement.where(
                lines.c.status_class.in_([status.value for status in query.status_classes])
            )
        if query.statuses:
            statement = statement.where(lines.c.status_raw.in_(list(query.statuses)))
        if query.date_field is not None and (
            query.date_from is not None or query.date_to is not None
        ):
            bounds = [_value_of(query.date_field)]
            if query.date_from is not None:
                bounds.append(values.c.value_date >= query.date_from)
            if query.date_to is not None:
                bounds.append(values.c.value_date <= query.date_to)
            statement = statement.where(exists(select(literal(1)).where(*bounds)))
        if query.rfi_terms:
            statement = statement.where(
                or_(
                    *(
                        and_(
                            lines.c.identifier_numeric_suffix == term.suffix,
                            lines.c.identifier_prefix == normalize_rfi_prefix(term.prefix),
                        )
                        if term.prefix is not None
                        else lines.c.identifier_numeric_suffix == term.suffix
                        for term in query.rfi_terms
                    )
                )
            )
        if query.identifiers:
            statement = statement.where(
                or_(
                    *(
                        exists(
                            select(literal(1)).where(
                                _value_of(term.field_key), values.c.value_text == term.value
                            )
                        )
                        for term in query.identifiers
                    )
                )
            )
        if query.group_keys:
            step = func.jsonb_array_elements(project_report_row_roles.c.group_path).table_valued(
                "value"
            )
            statement = statement.where(
                exists(
                    select(literal(1))
                    .select_from(step)
                    .where(step.c.value.op("->>")(1).in_(list(query.group_keys)))
                )
            )
        if query.text is not None:
            if not query.text_fields:
                statement = statement.where(false())
            else:
                # Ruling R1-08: one engine folds both sides (never Python's `lower()`
                # on the needle against PostgreSQL's on the value).
                needle = func.lower(literal(query.text, Text))
                statement = statement.where(
                    exists(
                        select(literal(1)).where(
                            matching_partition_criterion(values, lines),
                            values.c.derivation_id == lines.c.derivation_id,
                            values.c.row_ordinal == lines.c.row_ordinal,
                            values.c.field_key.in_(list(query.text_fields)),
                            func.strpos(func.lower(values.c.value_text), needle) > 0,
                        )
                    )
                )
        rows = list(
            self._connection.execute(
                statement.order_by(position, lines.c.row_ordinal).limit(query.limit)
            )
        )
        return self._with_values(principal_id, rows)

    def lines_of_records(
        self, principal_id: str, record_ids: Sequence[str]
    ) -> tuple[ProjectReportReadLine, ...]:
        if not record_ids:
            return ()
        lines = project_report_lines
        rows = list(
            self._connection.execute(
                select(*_line_columns())
                .select_from(_lines_joined())
                .where(_mine(lines, principal_id), lines.c.record_id.in_(list(record_ids)))
                .order_by(
                    lines.c.record_id,
                    project_report_current_derivations.c.snapshot_id,
                    lines.c.row_ordinal,
                )
            )
        )
        return self._with_values(principal_id, rows)

    def _with_values(
        self, principal_id: str, rows: list[Row[Any]]
    ) -> tuple[ProjectReportReadLine, ...]:
        if not rows:
            return ()
        values = project_report_line_values
        keys = sorted({(row.derivation_id, row.row_ordinal) for row in rows})
        by_line: dict[tuple[str, int], list[ProjectReportLineValueRecord]] = {}
        for row in self._connection.execute(
            select(
                values.c.derivation_id,
                values.c.row_ordinal,
                values.c.field_key,
                values.c.value_kind,
                values.c.raw_text,
                values.c.value_reason,
                values.c.value_decimal,
                values.c.value_date,
                values.c.value_boolean,
                values.c.value_text,
            )
            .select_from(values.join(project_report_current_derivations, _current(values)))
            .where(
                _mine(values, principal_id),
                tuple_(values.c.derivation_id, values.c.row_ordinal).in_(keys),
            )
            # Bytewise, whatever the cluster's collation (a UTF-8 locale sorts
            # `commitment_line.amount` before `commitment.number`; the fake does not).
            .order_by(values.c.derivation_id, values.c.row_ordinal, values.c.field_key.collate("C"))
        ):
            by_line.setdefault((row.derivation_id, row.row_ordinal), []).append(_to_value(row))
        return tuple(
            _to_read_line(row, tuple(by_line.get((row.derivation_id, row.row_ordinal), ())))
            for row in rows
        )

    # --- evidence ------------------------------------------------------------------------

    def stated_totals_of(
        self, principal_id: str, derivation_ids: Sequence[str]
    ) -> tuple[ProjectReportStatedTotalRecord, ...]:
        if not derivation_ids:
            return ()
        totals = project_report_stated_totals
        rows = self._connection.execute(
            select(*(column for column in totals.c if column.name != "principal_id"))
            .select_from(totals.join(project_report_current_derivations, _current(totals)))
            .where(_mine(totals, principal_id), totals.c.derivation_id.in_(list(derivation_ids)))
            .order_by(totals.c.derivation_id, totals.c.row_ordinal, totals.c.column_index)
        )
        return tuple(_to_total(row) for row in rows)

    def cross_checks_of(
        self, principal_id: str, derivation_ids: Sequence[str]
    ) -> tuple[ProjectReportCrossCheckRecord, ...]:
        if not derivation_ids:
            return ()
        checks = project_report_cross_checks
        # Ruling A4: a check counts only while both of its sides are current; one
        # whose other side was superseded (a re-derivation) is stale and ignored.
        view = project_report_current_derivations

        def current(side: ColumnElement[str]) -> ColumnElement[bool]:
            return exists(
                select(literal(1)).where(
                    matching_partition_criterion(checks, view), view.c.derivation_id == side
                )
            )

        named = list(derivation_ids)
        rows = self._connection.execute(
            select(*(column for column in checks.c if column.name != "principal_id"))
            .where(
                _mine(checks, principal_id),
                or_(
                    checks.c.left_derivation_id.in_(named),
                    checks.c.right_derivation_id.in_(named),
                ),
                current(checks.c.left_derivation_id),
                current(checks.c.right_derivation_id),
            )
            .order_by(
                checks.c.check_kind, checks.c.left_derivation_id, checks.c.right_derivation_id
            )
        )
        return tuple(_to_cross_check(row) for row in rows)

    def rfi_candidates(
        self, principal_id: str, derivation_ids: Sequence[str], suffixes: Sequence[int]
    ) -> tuple[ProjectReportRfiCandidate, ...]:
        if not derivation_ids or not suffixes:
            return ()
        lines = project_report_lines
        rows = self._connection.execute(
            select(
                lines.c.derivation_id,
                lines.c.row_ordinal,
                lines.c.identifier_prefix,
                lines.c.identifier_numeric_suffix,
                lines.c.record_id,
            )
            .select_from(lines.join(project_report_current_derivations, _current(lines)))
            .where(
                _mine(lines, principal_id),
                lines.c.derivation_id.in_(list(derivation_ids)),
                lines.c.record_family == RecordFamily.RFIS.value,
                lines.c.identifier_numeric_suffix.in_(sorted(set(suffixes))),
            )
            .order_by(lines.c.derivation_id, lines.c.row_ordinal)
        )
        return tuple(
            ProjectReportRfiCandidate(
                derivation_id=row.derivation_id,
                row_ordinal=row.row_ordinal,
                prefix=row.identifier_prefix,
                suffix=row.identifier_numeric_suffix,
                record_id=row.record_id,
            )
            for row in rows
        )

    def find_records(
        self,
        principal_id: str,
        project_id: str,
        record_family: RecordFamily,
        identity_key: str,
    ) -> tuple[ProjectReportRecordEntry, ...]:
        records = project_report_records
        rows = self._connection.execute(
            select(*(column for column in records.c if column.name != "principal_id"))
            .where(
                _mine(records, principal_id),
                records.c.project_id == project_id,
                records.c.record_family == record_family.value,
                records.c.identity_key == identity_key,
            )
            .order_by(records.c.identity_version, records.c.record_id)
        )
        return tuple(_to_record(row) for row in rows)


def _in_series_order(
    versions: list[ProjectReportVersionRecord],
) -> tuple[ProjectReportVersionRecord, ...]:
    """Series by their first first-seen instant, then id; versions in the D10 order."""

    def ref(version: ProjectReportVersionRecord) -> VersionRef:
        return VersionRef(version.snapshot_id, version.date_label, version.first_seen_at)

    series: dict[str, list[ProjectReportVersionRecord]] = {}
    for version in versions:
        series.setdefault(version.series_id, []).append(version)
    ordered = sorted(
        series.items(), key=lambda item: (min(v.first_seen_at for v in item[1]), item[0])
    )
    return tuple(
        version
        for _key, members in ordered
        for version in sorted(members, key=lambda v: version_order_key(ref(v)))
    )
