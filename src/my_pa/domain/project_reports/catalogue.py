"""The closed per-view field catalogue and the measures it allows (WP4P design 2.6).

The reads need to know, per family view, which fields are dates, which are
searchable text, which are additive measures, which status classes a view
uses and which identifier kinds a family answers. The adapters hold the same
facts beside the export's header strings (`infrastructure/project_reports`),
which the application may not import, so they are restated here by field key
only. No header string appears here. A FAST parity test holds every adapter's
field keys, value kinds and additivity equal to this catalogue, so the two
cannot drift.

**Measures are generated, never listed by hand.** Every `additive` money or
number column of a view is a measure; a column declared `non_additive` or
`unknown` never is (PULSE-AC-08), so a measure enum built from `MEASURES`
cannot offer one. A per-column rule chooses only the basis: per status class,
keyed by record, or a plain detail sum. The record and row counts are the
only measures that read no column.

Measure names are `<view>.<field key>` (a column) or `<view>.record_count` /
`<view>.row_count` (a count).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.project_reports.model import (
    FAMILY_OF_VIEW,
    Additivity,
    FamilyView,
    LineKind,
    RecordFamily,
    StatusClass,
    ValueKind,
)

__all__ = [
    "IDENTIFIER_KINDS",
    "MEASURES",
    "STATUS_CLASSES",
    "VIEW_FIELDS",
    "FieldEntry",
    "MeasureBasis",
    "MeasureSpec",
    "StatusBasis",
    "date_fields",
    "field_entry",
    "measure_names",
    "searchable_text_fields",
]


@dataclass(frozen=True, slots=True)
class FieldEntry:
    """One field of a view: its closed key, its value kind and its additivity."""

    field_key: str
    value_kind: ValueKind
    additivity: Additivity = Additivity.UNKNOWN

    @property
    def searchable_text(self) -> bool:
        """A text field is searched by the `text` filter; identifiers and figures never are."""
        return self.value_kind is ValueKind.TEXT

    @property
    def date_field(self) -> bool:
        return self.value_kind is ValueKind.DATE


_ID = ValueKind.IDENTIFIER
_TEXT = ValueKind.TEXT
_DATE = ValueKind.DATE
_NUM = ValueKind.NUMBER
_MONEY = ValueKind.MONEY
_BOOL = ValueKind.BOOLEAN
_ADD = Additivity.ADDITIVE
_NON = Additivity.NON_ADDITIVE


def _entries(
    *specs: tuple[str, ValueKind] | tuple[str, ValueKind, Additivity],
) -> tuple[FieldEntry, ...]:
    return tuple(FieldEntry(*spec) for spec in specs)


_OBSERVATION_9: Final = _entries(
    ("observation.assignee_vendor", _TEXT),
    ("observation.status", _TEXT),
    ("observation.count", _NUM, _NON),
    ("observation.date_created", _DATE),
    ("observation.date_closed", _DATE),
    ("observation.number", _ID),
    ("observation.title", _TEXT),
    ("observation.type", _TEXT),
    ("observation.description", _TEXT),
)
_OBSERVATION_8: Final = tuple(
    entry for entry in _OBSERVATION_9 if entry.field_key != "observation.date_closed"
)

#: Every view's fields, in the export's column order.
VIEW_FIELDS: Final[Mapping[FamilyView, tuple[FieldEntry, ...]]] = MappingProxyType(
    {
        FamilyView.OAC: _entries(
            ("meeting.number", _ID),
            ("meeting.date", _DATE),
            ("item.category", _TEXT),
            ("item.number", _ID),
            ("item.title", _TEXT),
            ("item.description", _TEXT),
            ("item.date_updated", _DATE),
            ("item.minutes", _TEXT),
        ),
        FamilyView.WITH_DATE_CLOSED: _OBSERVATION_9,
        FamilyView.OPEN_BY_VENDOR: _OBSERVATION_8,
        FamilyView.BY_STATUS: _entries(
            ("issue.status", _TEXT),
            ("issue.number", _ID),
            ("issue.title", _TEXT),
            ("issue.description", _TEXT),
            ("issue.assignee_company", _TEXT),
            ("issue.assignee_name", _TEXT),
            ("issue.date_created", _DATE),
            ("issue.due_date", _DATE),
            ("issue.type", _TEXT),
            ("issue.trade", _TEXT),
            ("issue.date_updated", _DATE),
        ),
        FamilyView.LINKED_TO_DRAWINGS: _entries(
            ("rfi.number", _ID),
            ("rfi.subject", _TEXT),
            ("rfi.drawing_number", _ID),
            ("drawing_link.count", _NUM, _NON),
            ("drawing_link.tool_type", _TEXT),
            ("drawing_link.type", _TEXT),
        ),
        FamilyView.OPEN_OUTSTANDING: _entries(
            ("rfi.number", _ID),
            ("rfi.subject", _TEXT),
            ("rfi.ball_in_court", _TEXT),
            ("rfi.priority", _TEXT),
            ("rfi.date_initiated", _DATE),
            ("rfi.due_date", _DATE),
            ("rfi.due_date_variance_days", _NUM, _NON),
        ),
        FamilyView.RECENTLY_CLOSED: _entries(
            ("rfi.number", _ID),
            ("rfi.subject", _TEXT),
            ("rfi.priority", _TEXT),
            ("rfi.date_initiated", _DATE),
            ("rfi.date_closed", _DATE),
            ("rfi.count", _NUM, _NON),
        ),
        FamilyView.GROUPED_BY_CHANGE: _entries(
            ("budget_change.number", _ID),
            ("budget_change.date_created", _DATE),
            ("budget_change.title", _TEXT),
            ("budget_change.status", _TEXT),
            ("budget_code.code", _ID),
            ("budget_code.description", _TEXT),
            ("adjustment.amount", _MONEY, _ADD),
            ("adjustment.description", _TEXT),
        ),
        FamilyView.BY_CODE: _entries(
            ("budget_code.code", _ID),
            ("budget_code.description", _TEXT),
            ("adjustment.amount", _MONEY, _ADD),
            ("adjustment.description", _TEXT),
            ("budget_change.number", _ID),
            ("budget_change.date_created", _DATE),
        ),
        FamilyView.BUYOUT_SUMMARY: _entries(
            ("budget_code.code", _ID),
            ("budget_line.original_amount", _MONEY, _ADD),
            ("budget_change_line.amount", _MONEY, _ADD),
            ("prime_co_line.approved_amount", _MONEY, _ADD),
            ("commitment.number", _ID),
            ("vendor.name", _TEXT),
            ("commitment_line.amount", _MONEY, _ADD),
            ("commitment_co_line.approved_amount_with_markup", _MONEY, _ADD),
        ),
        FamilyView.RECONCILIATION: _entries(
            ("prime_co.number", _ID),
            ("pco.number", _ID),
            ("pco.date_created", _DATE),
            ("pco.status", _TEXT),
            ("prime_co_line.description", _TEXT),
            ("prime_co_line.amount", _MONEY, _ADD),
            ("prime_co_line.date_created", _DATE),
            ("commitment_co.number", _ID),
            ("commitment_co.status", _TEXT),
            ("commitment_co_line.description", _TEXT),
            ("commitment_co_line.amount", _MONEY, _ADD),
        ),
        FamilyView.DELAYS: _entries(
            ("delay.date", _DATE),
            ("delay.type", _TEXT),
            ("delay.start_time", _TEXT),
            ("delay.end_time", _TEXT),
            ("delay.comments", _TEXT),
            ("weather.is_weather_delay", _BOOL),
        ),
        FamilyView.MANPOWER: _entries(
            ("manpower.date", _DATE),
            ("manpower.vendor", _TEXT),
            ("manpower.workers", _NUM, _ADD),
            ("manpower.hours", _NUM, _ADD),
            ("manpower.total_hours", _NUM, _ADD),
            ("manpower.comments", _TEXT),
        ),
        FamilyView.NOTES: _entries(
            ("note.date", _DATE),
            ("note.comment", _TEXT),
        ),
        FamilyView.WEATHER: _entries(
            ("weather.date", _DATE),
            ("weather.humidity_average", _NUM, _NON),
            ("weather.temperature_average", _NUM, _NON),
            ("weather.wind_speed_average", _NUM, _NON),
            ("weather.dew_point", _NUM, _NON),
            ("weather.precipitation_since_midnight", _NUM),
        ),
    }
)

#: The status classes each view's status map yields (`status_map_v1`); a view
#: without a status column has none. `unknown` is always kept apart (7.3).
STATUS_CLASSES: Final[Mapping[FamilyView, tuple[StatusClass, ...]]] = MappingProxyType(
    {
        **dict.fromkeys(
            (FamilyView.WITH_DATE_CLOSED, FamilyView.OPEN_BY_VENDOR, FamilyView.BY_STATUS),
            (StatusClass.OPEN, StatusClass.CLOSED, StatusClass.UNKNOWN),
        ),
        **dict.fromkeys(
            (FamilyView.GROUPED_BY_CHANGE, FamilyView.RECONCILIATION),
            (StatusClass.APPROVED, StatusClass.PENDING, StatusClass.VOID, StatusClass.UNKNOWN),
        ),
    }
)

#: The identifier kinds a `query` may name per family, each with its field.
IDENTIFIER_KINDS: Final[Mapping[RecordFamily, Mapping[str, str]]] = MappingProxyType(
    {
        RecordFamily.MEETING_ITEMS: MappingProxyType({"item": "item.number"}),
        RecordFamily.OBSERVATIONS: MappingProxyType({"observation": "observation.number"}),
        RecordFamily.COORDINATION_ISSUES: MappingProxyType({"coordination_issue": "issue.number"}),
        RecordFamily.RFIS: MappingProxyType({"rfi": "rfi.number"}),
        RecordFamily.BUDGET_CHANGES: MappingProxyType({"budget_change": "budget_change.number"}),
        RecordFamily.BUYOUT: MappingProxyType({"commitment": "commitment.number"}),
        RecordFamily.CHANGE_ORDER_RECONCILIATION: MappingProxyType(
            {"pco": "pco.number", "prime_co": "prime_co.number"}
        ),
        RecordFamily.DAILY_LOG: MappingProxyType({}),
    }
)


class MeasureBasis(StrEnum):
    #: The exact sum of one column over the view's detail lines.
    DETAIL_SUM = "detail_sum"
    #: Detail sums per record (a buyout commitment: `(commitment, budget code)`).
    KEYED_DETAIL_SUM = "keyed_detail_sum"
    #: One sum per status class; there is no all-status figure.
    PER_STATUS_CLASS = "per_status_class"
    #: Distinct identified records (per status class when the view has one).
    RECORD_COUNT = "record_count"
    #: Detail lines, beside `RECORD_COUNT` where a record repeats (RFIs).
    ROW_COUNT = "row_count"


class StatusBasis(StrEnum):
    #: The view exports no status, so its figure is not separated by one.
    NOT_EXPORTED = "not_exported"


@dataclass(frozen=True, slots=True)
class MeasureSpec:
    name: str
    view: FamilyView
    basis: MeasureBasis
    #: The measured column; `None` for a count.
    field_key: str | None = None
    #: The line kinds measured; empty is every line kind of the view.
    line_kinds: frozenset[LineKind] = frozenset()
    #: An all-blank-or-zero column is an unloaded one (`source_column_unpopulated`).
    unpopulated_when_all_zero: bool = False
    status_basis: StatusBasis | None = None
    #: The column a cross-report check concerns: a mismatch makes it not reportable.
    cross_checked: bool = False

    @property
    def family(self) -> RecordFamily:
        return FAMILY_OF_VIEW[self.view]


@dataclass(frozen=True, slots=True)
class _Rule:
    basis: MeasureBasis
    line_kinds: frozenset[LineKind] = frozenset()
    unpopulated_when_all_zero: bool = False
    status_basis: StatusBasis | None = None
    cross_checked: bool = False


#: The basis of a column measure when it is not a plain detail sum. A rule
#: never makes a column a measure: only its additivity does.
_RULES: Final[Mapping[tuple[FamilyView, str], _Rule]] = MappingProxyType(
    {
        (FamilyView.BUYOUT_SUMMARY, "budget_line.original_amount"): _Rule(
            MeasureBasis.DETAIL_SUM, unpopulated_when_all_zero=True
        ),
        (FamilyView.BUYOUT_SUMMARY, "prime_co_line.approved_amount"): _Rule(
            MeasureBasis.DETAIL_SUM, cross_checked=True
        ),
        (FamilyView.BUYOUT_SUMMARY, "commitment_line.amount"): _Rule(
            MeasureBasis.KEYED_DETAIL_SUM, frozenset({LineKind.COMMITMENT})
        ),
        (FamilyView.RECONCILIATION, "prime_co_line.amount"): _Rule(
            MeasureBasis.PER_STATUS_CLASS,
            frozenset({LineKind.PRIME_PCO_LINE}),
            cross_checked=True,
        ),
        (FamilyView.RECONCILIATION, "commitment_co_line.amount"): _Rule(
            MeasureBasis.PER_STATUS_CLASS, frozenset({LineKind.COMMITMENT_CO_LINE})
        ),
        (FamilyView.GROUPED_BY_CHANGE, "adjustment.amount"): _Rule(MeasureBasis.PER_STATUS_CLASS),
        (FamilyView.BY_CODE, "adjustment.amount"): _Rule(
            MeasureBasis.DETAIL_SUM, status_basis=StatusBasis.NOT_EXPORTED
        ),
    }
)

#: The views whose identified records are counted, and those whose rows are too.
_RECORD_COUNTED: Final = (
    FamilyView.OAC,
    FamilyView.WITH_DATE_CLOSED,
    FamilyView.OPEN_BY_VENDOR,
    FamilyView.BY_STATUS,
    FamilyView.LINKED_TO_DRAWINGS,
    FamilyView.OPEN_OUTSTANDING,
    FamilyView.RECENTLY_CLOSED,
)
_ROW_COUNTED: Final = frozenset(
    view for view in _RECORD_COUNTED if FAMILY_OF_VIEW[view] is RecordFamily.RFIS
)


def _measures() -> dict[str, MeasureSpec]:
    found: dict[str, MeasureSpec] = {}
    for view, entries in VIEW_FIELDS.items():
        for entry in entries:
            if entry.additivity is not Additivity.ADDITIVE or entry.value_kind not in (
                ValueKind.MONEY,
                ValueKind.NUMBER,
            ):
                continue
            rule = _RULES.get((view, entry.field_key), _Rule(MeasureBasis.DETAIL_SUM))
            name = f"{view.value}.{entry.field_key}"
            found[name] = MeasureSpec(
                name=name,
                view=view,
                basis=rule.basis,
                field_key=entry.field_key,
                line_kinds=rule.line_kinds,
                unpopulated_when_all_zero=rule.unpopulated_when_all_zero,
                status_basis=rule.status_basis,
                cross_checked=rule.cross_checked,
            )
        if view in _RECORD_COUNTED:
            name = f"{view.value}.record_count"
            found[name] = MeasureSpec(name, view, MeasureBasis.RECORD_COUNT)
        if view in _ROW_COUNTED:
            name = f"{view.value}.row_count"
            found[name] = MeasureSpec(name, view, MeasureBasis.ROW_COUNT)
    return dict(sorted(found.items()))


#: Every measure, by name (closed: generated from the additive set and the counts).
MEASURES: Final[Mapping[str, MeasureSpec]] = MappingProxyType(_measures())


def field_entry(view: FamilyView, field_key: str) -> FieldEntry | None:
    return next((e for e in VIEW_FIELDS[view] if e.field_key == field_key), None)


def measure_names(family: RecordFamily) -> tuple[str, ...]:
    """The closed measure names of a family, sorted (a measure enum is built from this)."""
    return tuple(name for name, spec in MEASURES.items() if spec.family is family)


def _keys_of(family: RecordFamily, wanted: str) -> tuple[str, ...]:
    keys = {
        entry.field_key
        for view, entries in VIEW_FIELDS.items()
        if FAMILY_OF_VIEW[view] is family
        for entry in entries
        if (entry.date_field if wanted == "date" else entry.searchable_text)
    }
    return tuple(sorted(keys))


def date_fields(family: RecordFamily) -> tuple[str, ...]:
    """The date field keys any view of the family has, sorted."""
    return _keys_of(family, "date")


def searchable_text_fields(family: RecordFamily) -> tuple[str, ...]:
    """The text field keys the `text` filter searches in the family, sorted."""
    return _keys_of(family, "text")
