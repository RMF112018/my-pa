"""The PULSE-AC-17 figures from stored rows (WP3P-S5; rulings D14, D16; design section 3.9).

`stored_counts` computes, from what the project-reports lifecycle stored --
the lifecycle snapshots and paths, the Layer A heads and raw rows, the
**current** derivations with their row roles, lines, stated totals and
records, and the cross-report checks -- the same closed count document as the
file-level `aggregate_cli` (`count_template`), key for key, so the two compare
mechanically and the committed `evidence_aggregate_v1.json` applies to either.

**A file is a current path row.** Each unsuperseded path of a source counts as
one file, as the file-level tool counts each file it reads; two paths holding
the same bytes in one source are one snapshot counted twice, exactly as two
identical files are. Each path's numbers are its snapshot's current
derivation's. The keys a stored run cannot know are zero by construction: a
file the lifecycle skipped (`files.skipped_too_large`, `files.unreadable`)
left no row, `files.internal_error` has no stored form, and
`inputs.project_numbers_unmatched` is zero because a binding's number is
always that of an admitted source.

Reads go through the repository ports of one unit of work (read-only). The
output is counts only: no path, name, number, amount or cell text.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

from my_pa.contracts.ports import (
    IngestSnapshotStatus,
    ProjectReportDerivationRecord,
    ProjectReportRowRecord,
    ProjectReportSnapshotRecord,
    UnitOfWork,
)
from my_pa.domain.project_reports.model import (
    UNCLASSIFIED_COUNT_KEY,
    DerivationState,
    FamilyView,
    IdentityState,
    QuarantineReason,
    ReconciliationOutcome,
    RowRole,
    TotalScope,
)
from my_pa.infrastructure.project_reports.aggregate_cli import count_template
from my_pa.infrastructure.project_reports.pulse_csv import REGISTRY, FamilyAdapter

__all__ = ["stored_counts"]

_BREAK_KINDS: Final = ("crlf", "lf", "cr")
_HASH_BOM: Final = b"\xef\xbb\xbf"
_TERMINATOR_TEXT: Final = {"crlf": "\r\n", "lf": "\n", "cr": "\r", "none": ""}


def _breaks(raw: str) -> tuple[int, int, int]:
    crlf = raw.count("\r\n")
    return crlf, raw.count("\n") - crlf, raw.count("\r") - crlf


def _reconstructs(
    head: ProjectReportSnapshotRecord, rows: Sequence[ProjectReportRowRecord]
) -> bool:
    body = head.header_raw_record + _TERMINATOR_TEXT[head.header_terminator]
    body += "".join(row.raw_record + _TERMINATOR_TEXT[row.terminator] for row in rows)
    data = (_HASH_BOM if head.bom_present else b"") + body.encode("utf-8")
    return hashlib.sha256(data).hexdigest() == head.file_sha256


def _role_key(role: RowRole, level: int | None) -> str:
    if role in (RowRole.GROUP_HEADER, RowRole.GROUPING_ONLY):
        return f"{role.value}_l{level}"
    return role.value


class _Counter:
    def __init__(self, unit: UnitOfWork, principal_id: str) -> None:
        self.unit = unit
        self.principal_id = principal_id
        self.counts: Counter[str] = Counter()
        self.records: set[tuple[int, str, str]] = set()
        self._record_keys: dict[str, str] = {}

    def _record_key(self, record_id: str) -> str:
        if record_id not in self._record_keys:
            record = self.unit.project_reports.get_record(self.principal_id, record_id)
            if record is None:
                raise LookupError("a line names a stored record")
            self._record_keys[record_id] = record.identity_key
        return self._record_keys[record_id]

    def add(
        self,
        source: int,
        head: ProjectReportSnapshotRecord,
        rows: Sequence[ProjectReportRowRecord],
        derivation: ProjectReportDerivationRecord,
    ) -> None:
        counts = self.counts
        repository = self.unit.project_reports
        counts["rows.data"] += head.data_row_count
        breaks = [0, 0, 0]
        for raw in (head.header_raw_record, *(row.raw_record for row in rows)):
            for index, value in enumerate(_breaks(raw)):
                breaks[index] += value
        view = derivation.family_view
        for kind, value in zip(_BREAK_KINDS, breaks, strict=True):
            counts[f"rows.embedded_line_breaks.{kind}"] += value
            if view is not None:
                counts[f"rows.by_view.{view.value}.embedded_line_breaks.{kind}"] += value
        if view is not None:
            counts[f"signatures.files_by_view.{view.value}"] += 1
        if derivation.state is DerivationState.QUARANTINED:
            counts["derivations.quarantined"] += 1
            reason = derivation.quarantine_reason
            if reason is not None:
                counts[f"quarantines.{reason.value}"] += 1
            counts[f"rows.{UNCLASSIFIED_COUNT_KEY}"] += derivation.role_counts.get(
                UNCLASSIFIED_COUNT_KEY, 0
            )
            if reason is QuarantineReason.BINDING_PROJECT_NUMBER_MISMATCH:
                counts[f"cross_checks.{ReconciliationOutcome.MISMATCH.value}"] += 1
            return
        if view is None or derivation.record_family is None:
            raise AssertionError("a classified derivation names its view")
        v = view.value
        counts["derivations.classified"] += 1
        for role in repository.list_row_roles(self.principal_id, derivation.derivation_id):
            counts[f"rows.by_role.{role.row_role.value}"] += 1
            counts[f"rows.by_view.{v}.{_role_key(role.row_role, role.group_level)}"] += 1
        if derivation.completeness_class is not None:
            counts[f"completeness.{derivation.completeness_class.value}"] += 1
            counts[f"completeness.by_view.{v}.{derivation.completeness_class.value}"] += 1
        for line in repository.list_lines(self.principal_id, derivation.derivation_id):
            counts[f"lines.by_view.{v}.{line.observation_state.value}"] += 1
            counts[f"lines.by_view.{v}.line_kind.{line.line_kind.value}"] += 1
            for degraded in line.degraded_reasons:
                counts[f"lines.degraded_reasons.{degraded.value}"] += 1
            counts[f"identity.{line.identity_state.value}"] += 1
            counts[f"identity.by_view.{v}.{line.identity_state.value}"] += 1
            if line.identity_reason is not None:
                counts[f"identity.reasons.{line.identity_reason.value}"] += 1
            if line.status_class is not None:
                counts[f"status.by_view.{v}.{line.status_class.value}"] += 1
            if line.identity_state is IdentityState.IDENTIFIED and line.record_id is not None:
                self.records.add(
                    (source, derivation.record_family.value, self._record_key(line.record_id))
                )
        for total in repository.list_stated_totals(self.principal_id, derivation.derivation_id):
            unit = "column_groups" if total.scope is TotalScope.GROUP else "grand"
            counts[f"reconciliation.by_view.{v}.{unit}.{total.outcome.value}"] += 1
            if total.outcome is ReconciliationOutcome.MISMATCH:
                counts["reconciliation.mismatch_total"] += 1
        summary = derivation.reconciliation or {}
        checked, agreeing = summary.get("groups_checked"), summary.get("groups_all_columns_match")
        if type(checked) is not int or type(agreeing) is not int:
            raise AssertionError("a classified derivation stores its group counts")
        counts[f"reconciliation.by_view.{v}.groups.checked"] += checked
        counts[f"reconciliation.by_view.{v}.groups.all_columns_match"] += agreeing
        check = summary.get("project_number_check")
        if check is not None:
            counts[f"cross_checks.{ReconciliationOutcome(str(check)).value}"] += 1


def stored_counts(
    unit: UnitOfWork,
    principal_id: str,
    ingest_source_ids: Sequence[str],
    *,
    registry: Mapping[str, FamilyAdapter] = REGISTRY,
) -> dict[str, int]:
    """The `count_template` document of the given sources, from stored rows only."""
    tally = _Counter(unit, principal_id)
    counts = tally.counts
    ingestion = unit.ingestion
    repository = unit.project_reports
    shas: dict[str, set[int]] = {}
    signatures: dict[str, bool] = {}
    sources_seen = 0
    for source, source_id in enumerate(sorted(set(ingest_source_ids))):
        paths = [
            path
            for path in ingestion.list_snapshot_paths(principal_id, source_id)
            if path.superseded_by_snapshot_id is None
        ]
        if paths:
            sources_seen += 1
        pairs: dict[FamilyView, list[ProjectReportDerivationRecord]] = {
            FamilyView.BUYOUT_SUMMARY: [],
            FamilyView.RECONCILIATION: [],
        }
        for path in paths:
            snapshot = ingestion.get_snapshot(principal_id, path.snapshot_id)
            if snapshot is None or snapshot.status is IngestSnapshotStatus.PENDING:
                continue
            counts["files.total"] += 1
            counts["files.bytes_total"] += snapshot.byte_count
            if snapshot.status is IngestSnapshotStatus.REJECTED:
                counts["files.rejected"] += 1
                counts[f"rejections.{snapshot.rejection_code}"] += 1
                continue
            head = repository.get_snapshot(principal_id, snapshot.snapshot_id)
            derivation = repository.current_derivation(principal_id, snapshot.snapshot_id)
            if head is None or derivation is None:
                counts["files.internal_error"] += 1
                continue
            rows = repository.list_rows(principal_id, snapshot.snapshot_id)
            counts["files.prepared"] += 1
            if _reconstructs(head, rows):
                counts["reconstruction.ok"] += 1
            shas.setdefault(head.file_sha256, set()).add(source)
            signatures[head.header_signature] = head.header_signature in registry
            tally.add(source, head, rows, derivation)
            if derivation.state is DerivationState.CLASSIFIED and derivation.family_view in pairs:
                pairs[derivation.family_view].append(derivation)
        buyouts, reconciliations = (
            pairs[FamilyView.BUYOUT_SUMMARY],
            pairs[FamilyView.RECONCILIATION],
        )
        if not buyouts and not reconciliations:
            continue
        outcome = ReconciliationOutcome.NOT_CHECKED
        if len(buyouts) == 1 and len(reconciliations) == 1:
            left, right = buyouts[0], reconciliations[0]
            for check in repository.list_cross_checks(principal_id, left.project_id):
                if (check.left_derivation_id, check.right_derivation_id) == (
                    left.derivation_id,
                    right.derivation_id,
                ):
                    outcome = check.outcome
        counts[f"cross_report.{outcome.value}"] += 1
    counts["signatures.distinct"] = len(signatures)
    counts["signatures.registered_distinct"] = sum(1 for known in signatures.values() if known)
    counts["signatures.unregistered_distinct"] = sum(
        1 for known in signatures.values() if not known
    )
    counts["sources.total"] = sources_seen
    counts["sources.byte_identical_across_sources"] = sum(1 for s in shas.values() if len(s) > 1)
    for _source, family, _key in tally.records:
        counts[f"records.by_family.{family}"] += 1
    template = count_template()
    if set(counts) - set(template):
        raise AssertionError("a count key outside the closed vocabulary")
    template.update(counts)
    return template
