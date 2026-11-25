"""The pure rules of the project-report reads (WP4P design 2.2-2.6; rulings D2, D9).

* **Series identity** (`series_id`, ruling D2): a derived, stable token for one
  report series, `prser_` and the first 32 hex characters of SHA-256 over the
  canonical JSON of the series key. Nothing stores or issues it; it reveals
  neither the slug nor the signature.
* **Decimal strings** (`format_amount`): plain fixed point, never an exponent,
  never rounded; trailing zeros removed down to 2 decimals for money and to
  none for a number (ADR-018 decision 4: rounding is for presentation only).
* **Filter semantics per version** (ruling D8 (i)): a declaration applies to a
  version first seen at or after it. The once-per-answer qualifier is set
  when **any** version used is `unknown`, never judged by the latest alone.
* **Comparison**: identified records added, not observed or changed between
  two versions (never "closed"), and snapshot-scoped lines matched as a
  multiset by their content signature.
* **The measure planner** (`plan_measure`): a catalogue measure over a
  version's lines, wrapping `measures.py` with the derivation's blockers, a
  derivation-wide reconciliation mismatch (ruling D9) and a cross-report check
  mismatch on the columns it concerns. No zero is ever substituted. A record
  or row count is never withheld for a reconciliation mismatch (ruling A2: a
  mismatch concerns reconciled amounts, not counts); it carries the
  `reconciliation_mismatch` qualifier instead.
* **Measure scope** (ruling B1, amended): a measure is computed over the
  detail lines the query's row filters select, `measure_scope: "filtered"`,
  or over the whole version when no row filter applies, `"version"`. The
  reconciliation inputs (stated totals and cross-checks, with their blockers
  and qualifiers) always judge the whole version, under either scope.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.project_reports.catalogue import (
    STATUS_CLASSES,
    MeasureBasis,
    MeasureSpec,
    StatusBasis,
)
from my_pa.domain.project_reports.measures import (
    MeasureColumn,
    MeasureRow,
    MeasureValue,
    derivation_blockers,
    detail_sum,
    keyed_detail_sums,
    status_measures,
)
from my_pa.domain.project_reports.model import (
    Additivity,
    DerivationState,
    FilterSemantics,
    LineKind,
    NotReportableReason,
    QuarantineReason,
    ReconciliationOutcome,
    ReportQualifier,
    RowRole,
    StatusClass,
)
from my_pa.domain.project_reports.money import NumericCell, amount_sum
from my_pa.domain.project_reports.versions import VersionRef

__all__ = [
    "SERIES_ID_PREFIX",
    "ContentEntry",
    "MeasureAnswer",
    "MeasureInputs",
    "MeasureScope",
    "PlannedLine",
    "RecordDiff",
    "RecordState",
    "UsedVersion",
    "answer_qualifiers",
    "changed_fields",
    "compare_by_content",
    "compare_records",
    "content_signature",
    "format_amount",
    "is_series_id",
    "measure_scope",
    "plan_measure",
    "reconciliation_outcomes",
    "series_id",
    "version_filter_semantics",
]

SERIES_ID_PREFIX: Final = "prser_"
_SERIES_ID_VERSION: Final = 1
_HEX_32: Final = frozenset("0123456789abcdef")


def _canonical(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def series_id(
    principal_id: str, ingest_source_id: str, slug_label: str | None, header_signature: str
) -> str:
    """The derived token of one report series (ruling D2)."""
    digest = hashlib.sha256(
        _canonical(
            {
                "header_signature": header_signature,
                "ingest_source_id": ingest_source_id,
                "principal_id": principal_id,
                "slug_label": slug_label,
                "v": _SERIES_ID_VERSION,
            }
        )
    ).hexdigest()
    return SERIES_ID_PREFIX + digest[:32]


def is_series_id(value: object) -> bool:
    """The token's shape only; whether it names a series is a read's question."""
    if not isinstance(value, str) or not value.startswith(SERIES_ID_PREFIX):
        return False
    tail = value[len(SERIES_ID_PREFIX) :]
    return len(tail) == 32 and set(tail) <= _HEX_32


def format_amount(value: Decimal, *, money: bool) -> str:
    """Plain fixed point: trailing zeros removed to 2 decimals (money) or none (a number)."""
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("an amount is a finite Decimal")
    if value.is_zero():
        value = abs(value)
    text = format(value, "f")
    sign = "-" if text.startswith("-") else ""
    whole, _, fraction = text.lstrip("-").partition(".")
    fraction = fraction.rstrip("0").ljust(2 if money else 0, "0")
    return f"{sign}{whole}.{fraction}" if fraction else f"{sign}{whole}"


# --- filter semantics -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsedVersion:
    """One version an answer used, with its own filter semantics."""

    version: VersionRef
    filter_semantics: FilterSemantics


def version_filter_semantics(
    declared_at: datetime | None, first_seen_at: datetime
) -> FilterSemantics:
    """`operator_declared` when the series' declaration is at or before this version."""
    if declared_at is not None and declared_at <= first_seen_at:
        return FilterSemantics.OPERATOR_DECLARED
    return FilterSemantics.UNKNOWN


def answer_qualifiers(used: Sequence[UsedVersion]) -> tuple[ReportQualifier, ...]:
    """Once per answer: `filter_semantics_unknown` when any version used is `unknown`."""
    if any(entry.filter_semantics is FilterSemantics.UNKNOWN for entry in used):
        return (ReportQualifier.FILTER_SEMANTICS_UNKNOWN,)
    return ()


# --- comparison -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordState:
    """An identified record as one version observed it: status and raw text by field."""

    status_class: StatusClass | None
    raw: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class RecordDiff:
    added: tuple[str, ...]
    #: Absent from the later version: `not_observed`, never closed.
    not_observed: tuple[str, ...]
    #: `(record key, changed field keys, old status class, new status class)`.
    changed: tuple[tuple[str, tuple[str, ...], StatusClass | None, StatusClass | None], ...]


def changed_fields(old: Mapping[str, str], new: Mapping[str, str]) -> tuple[str, ...]:
    """The field keys whose raw text differs (an absent field is the empty text)."""
    return tuple(sorted(key for key in set(old) | set(new) if old.get(key, "") != new.get(key, "")))


def compare_records(
    before: Mapping[str, RecordState], after: Mapping[str, RecordState]
) -> RecordDiff:
    """Records added, not observed and changed (fields or status) between two versions."""
    changed = []
    for key in sorted(set(before) & set(after)):
        fields = changed_fields(before[key].raw, after[key].raw)
        old, new = before[key].status_class, after[key].status_class
        if fields or old is not new:
            changed.append((key, fields, old, new))
    return RecordDiff(
        added=tuple(sorted(set(after) - set(before))),
        not_observed=tuple(sorted(set(before) - set(after))),
        changed=tuple(changed),
    )


def content_signature(
    line_kind: LineKind, group_keys: Sequence[str], raw: Mapping[str, str]
) -> str:
    """A snapshot-scoped line's content: its kind, group keys and sorted raw fields."""
    return hashlib.sha256(
        _canonical([line_kind.value, list(group_keys), sorted(raw.items())])
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ContentEntry:
    signature: str
    #: `from` (only in the earlier version) or `to` (in the later one).
    side: str
    content_matched: bool


def compare_by_content(before: Sequence[str], after: Sequence[str]) -> tuple[ContentEntry, ...]:
    """Multiset matching: each later line is matched by at most one earlier equal line.

    Every later line is answered (`content_matched` true or false); an earlier
    line no later line matched is answered on the `from` side.
    """
    remaining = Counter(before)
    entries: list[ContentEntry] = []
    for signature in after:
        matched = remaining[signature] > 0
        if matched:
            remaining[signature] -= 1
        entries.append(ContentEntry(signature, "to", matched))
    for signature in sorted(remaining.elements()):
        entries.append(ContentEntry(signature, "from", False))
    return tuple(entries)


# --- the measure planner --------------------------------------------------------------------


class MeasureScope(StrEnum):
    """The lines a measure was computed over (ruling B1, amended)."""

    #: Every detail line of the version: no row filter applies.
    VERSION = "version"
    #: Only the detail lines the query's row filters select.
    FILTERED = "filtered"


def measure_scope(*, row_filtered: bool) -> MeasureScope:
    """`filtered` when any row filter applies, `version` otherwise."""
    return MeasureScope.FILTERED if row_filtered else MeasureScope.VERSION


@dataclass(frozen=True, slots=True)
class PlannedLine:
    """One detail line of one version, as a measure reads it."""

    line_kind: LineKind
    status_class: StatusClass | None
    record_key: str | None
    #: The measured column's cell; `None` when the measure reads no column.
    cell: NumericCell | None = None


@dataclass(frozen=True, slots=True)
class MeasureInputs:
    """The derivation-level facts of the version a measure reads."""

    state: DerivationState | None
    quarantine_reason: QuarantineReason | None = None
    reconciliation: Mapping[str, object] | None = None
    #: A cross-report check involving this derivation answered `mismatch`.
    cross_check_mismatch: bool = False


@dataclass(frozen=True, slots=True)
class MeasureAnswer:
    spec: MeasureSpec
    #: The whole figure; `None` for a per-status-class measure (none exists).
    total: MeasureValue | None
    by_status: Mapping[StatusClass, MeasureValue]
    by_key: Mapping[tuple[str, ...], MeasureValue]
    #: Attached to the measure, never a refusal (a count under a mismatch, ruling A2).
    qualifiers: frozenset[ReportQualifier] = frozenset()

    @property
    def status_basis(self) -> StatusBasis | None:
        return self.spec.status_basis


_EMPTY: Final[Mapping[StatusClass, MeasureValue]] = MappingProxyType({})


def reconciliation_outcomes(
    reconciliation: Mapping[str, object] | None,
) -> frozenset[ReconciliationOutcome]:
    """`{mismatch}` when any stated total of the derivation mismatched (ruling D9)."""
    if reconciliation is None:
        return frozenset()
    for unit in ("column_groups", "grand"):
        counts = reconciliation.get(unit)
        if isinstance(counts, Mapping):
            mismatches = counts.get(ReconciliationOutcome.MISMATCH.value, 0)
            if isinstance(mismatches, int) and mismatches > 0:
                return frozenset({ReconciliationOutcome.MISMATCH})
    return frozenset()


def _blockers(spec: MeasureSpec, inputs: MeasureInputs) -> frozenset[NotReportableReason]:
    reasons = set(derivation_blockers(inputs.state, inputs.quarantine_reason))
    if spec.cross_checked and inputs.cross_check_mismatch:
        reasons.add(NotReportableReason.RECONCILIATION_MISMATCH)
    return frozenset(reasons)


def _count(value: int) -> Decimal:
    return Decimal(value)


def _counts(
    spec: MeasureSpec,
    lines: Sequence[PlannedLine],
    reasons: frozenset[NotReportableReason],
    qualifiers: frozenset[ReportQualifier],
) -> MeasureAnswer:
    def value(found: Iterable[PlannedLine]) -> MeasureValue:
        if reasons:
            return MeasureValue(None, reasons)
        chosen = list(found)
        if spec.basis is MeasureBasis.ROW_COUNT:
            return MeasureValue(_count(len(chosen)))
        return MeasureValue(_count(len({line.record_key for line in chosen if line.record_key})))

    statuses = STATUS_CLASSES.get(spec.view, ())
    if spec.basis is MeasureBasis.RECORD_COUNT and statuses:
        by_status = {
            status: value(
                line for line in lines if (line.status_class or StatusClass.UNKNOWN) is status
            )
            for status in statuses
        }
        return MeasureAnswer(
            spec, value(lines), MappingProxyType(by_status), MappingProxyType({}), qualifiers
        )
    return MeasureAnswer(spec, value(lines), _EMPTY, MappingProxyType({}), qualifiers)


def _keyed_total(values: Mapping[tuple[str, ...], MeasureValue]) -> MeasureValue:
    """The sum of the keys, only when every key is reportable (else their reasons)."""
    reasons = frozenset(reason for value in values.values() for reason in value.reasons)
    if reasons:
        return MeasureValue(None, reasons)
    return MeasureValue(amount_sum(v.value for v in values.values() if v.value is not None))


def plan_measure(
    spec: MeasureSpec,
    lines: Sequence[PlannedLine],
    inputs: MeasureInputs,
    *,
    version_lines: Sequence[PlannedLine] | None = None,
) -> MeasureAnswer:
    """The measure over detail lines of one version (the caller chooses the version and lines).

    `inputs` are always the whole version's: under a row filter `lines` are
    the filtered ones, but the blockers and the reconciliation still judge the
    version (ruling B1, amended). So do a column's population, a failed cell
    (`type_error_present`, ruling R1-07) and the `unknown` status block: they
    are judged over `version_lines`, every detail line of the version, when
    `lines` is a filtered slice of it.
    """
    reasons = _blockers(spec, inputs)
    reconciliation = reconciliation_outcomes(inputs.reconciliation)

    def measured(found: Sequence[PlannedLine]) -> list[PlannedLine]:
        return [line for line in found if not spec.line_kinds or line.line_kind in spec.line_kinds]

    chosen = measured(lines)
    if spec.basis in (MeasureBasis.RECORD_COUNT, MeasureBasis.ROW_COUNT):
        # Ruling A2: qualified, never blocked, by a reconciliation mismatch.
        qualifiers = (
            frozenset({ReportQualifier.RECONCILIATION_MISMATCH})
            if ReconciliationOutcome.MISMATCH in reconciliation
            else frozenset()
        )
        return _counts(spec, chosen, reasons, qualifiers)
    if spec.field_key is None:
        raise ValueError("a column measure names its column")
    column = MeasureColumn(
        spec.field_key,
        Additivity.ADDITIVE,
        unpopulated_when_all_zero=spec.unpopulated_when_all_zero,
    )

    def as_rows(found: Sequence[PlannedLine]) -> list[MeasureRow]:
        return [
            MeasureRow(
                spec.view,
                RowRole.DETAIL,
                line.cell if line.cell is not None else NumericCell("", None),
                line.status_class,
                (line.record_key or "",),
            )
            for line in found
        ]

    rows = as_rows(chosen)
    whole = None if version_lines is None else as_rows(measured(version_lines))
    view, blockers = spec.view, reasons
    if spec.basis is MeasureBasis.PER_STATUS_CLASS:
        separated = status_measures(
            rows,
            column,
            view=view,
            reconciliation=reconciliation,
            blockers=blockers,
            judged_over=whole,
        )
        return MeasureAnswer(
            spec,
            None,
            MappingProxyType({status: separated[status] for status in STATUS_CLASSES[view]}),
            MappingProxyType({}),
        )
    if spec.basis is MeasureBasis.KEYED_DETAIL_SUM:
        keyed = keyed_detail_sums(
            rows,
            column,
            view=view,
            reconciliation=reconciliation,
            blockers=blockers,
            judged_over=whole,
        )
        total = (
            _keyed_total(keyed)
            if keyed
            else detail_sum(
                rows,
                column,
                view=view,
                reconciliation=reconciliation,
                blockers=blockers,
                judged_over=whole,
            )
        )
        return MeasureAnswer(spec, total, _EMPTY, keyed)
    total = detail_sum(
        rows,
        column,
        view=view,
        reconciliation=reconciliation,
        blockers=blockers,
        judged_over=whole,
    )
    return MeasureAnswer(spec, total, _EMPTY, MappingProxyType({}))
