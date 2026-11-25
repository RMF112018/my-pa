"""WP4P-S1: the pure rules of the project-report reads (design 2.3, 2.6, 2.8).

PULSE-AC-06 (detail only, through the planner), AC-07 (status classes kept
apart per view), AC-08 part 1 (no non-additive or unknown column is ever a
measure, and the catalogue cannot drift from the adapters), AC-09 (not
reportable with reasons, no zero substituted), AC-10 (filter semantics per
version, the qualifier once per answer) and AC-11 (comparison never infers
closure; snapshot-scoped lines matched by content). Every value is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from my_pa.domain.project_reports.catalogue import (
    IDENTIFIER_KINDS,
    MEASURES,
    STATUS_CLASSES,
    VIEW_FIELDS,
    MeasureBasis,
    StatusBasis,
    date_fields,
    measure_names,
    searchable_text_fields,
)
from my_pa.domain.project_reports.model import (
    FAMILY_OF_VIEW,
    Additivity,
    DerivationState,
    FamilyView,
    FilterSemantics,
    LineKind,
    NotReportableReason,
    QuarantineReason,
    RecordFamily,
    ReportQualifier,
    StatusClass,
    ValueKind,
)
from my_pa.domain.project_reports.money import read_cell
from my_pa.domain.project_reports.reads import (
    MeasureInputs,
    PlannedLine,
    RecordState,
    UsedVersion,
    answer_qualifiers,
    compare_by_content,
    compare_records,
    content_signature,
    format_amount,
    is_series_id,
    plan_measure,
    reconciliation_outcomes,
    series_id,
    version_filter_semantics,
)
from my_pa.domain.project_reports.versions import VersionRef
from my_pa.infrastructure.project_reports.pulse_csv import REGISTRY

WHEN = datetime(2026, 11, 24, 12, tzinfo=UTC)
CLASSIFIED = MeasureInputs(DerivationState.CLASSIFIED)


# --- the catalogue ----------------------------------------------------------------------


def test_every_adapter_equals_its_catalogue_entry() -> None:
    """Field keys, value kinds and additivity, in column order (the catalogue cannot drift)."""
    assert {adapter.view for adapter in REGISTRY.values()} == set(VIEW_FIELDS) == set(FamilyView)
    for adapter in REGISTRY.values():
        assert [(f.field_key, f.value_kind, f.additivity) for f in adapter.fields] == [
            (e.field_key, e.value_kind, e.additivity) for e in VIEW_FIELDS[adapter.view]
        ], adapter.view


def test_no_measure_reads_a_non_additive_or_unknown_column() -> None:
    """AC-08 part 1: the measure set is the adapters' additive set plus the counts."""
    additive = {
        f"{adapter.view.value}.{field.field_key}"
        for adapter in REGISTRY.values()
        for field in adapter.fields
        if field.additivity is Additivity.ADDITIVE
    }
    refused = {
        f"{adapter.view.value}.{field.field_key}"
        for adapter in REGISTRY.values()
        for field in adapter.fields
        if field.additivity is not Additivity.ADDITIVE
    }
    columns = {name for name, spec in MEASURES.items() if spec.field_key is not None}
    assert columns == additive
    assert not refused & set(MEASURES)
    for name in (
        "open_outstanding.rfi.due_date_variance_days",
        "recently_closed.rfi.count",
        "linked_to_drawings.drawing_link.count",
        "with_date_closed.observation.count",
        "open_by_vendor.observation.count",
        "weather.weather.precipitation_since_midnight",
    ):
        assert name not in MEASURES
    for spec in MEASURES.values():
        if spec.field_key is None:
            assert spec.basis in (MeasureBasis.RECORD_COUNT, MeasureBasis.ROW_COUNT)


def test_the_measure_set_per_family_is_closed() -> None:
    assert measure_names(RecordFamily.CHANGE_ORDER_RECONCILIATION) == (
        "reconciliation.commitment_co_line.amount",
        "reconciliation.prime_co_line.amount",
    )
    assert measure_names(RecordFamily.BUDGET_CHANGES) == (
        "by_code.adjustment.amount",
        "grouped_by_change.adjustment.amount",
    )
    assert measure_names(RecordFamily.RFIS) == (
        "linked_to_drawings.record_count",
        "linked_to_drawings.row_count",
        "open_outstanding.record_count",
        "open_outstanding.row_count",
        "recently_closed.record_count",
        "recently_closed.row_count",
    )
    assert len(measure_names(RecordFamily.BUYOUT)) == 5
    assert measure_names(RecordFamily.DAILY_LOG) == (
        "manpower.manpower.hours",
        "manpower.manpower.total_hours",
        "manpower.manpower.workers",
    )
    assert MEASURES["by_code.adjustment.amount"].status_basis is StatusBasis.NOT_EXPORTED
    assert MEASURES["buyout_summary.commitment_line.amount"].basis is (
        MeasureBasis.KEYED_DETAIL_SUM
    )
    assert {name for name, spec in MEASURES.items() if spec.cross_checked} == {
        "buyout_summary.prime_co_line.approved_amount",
        "reconciliation.prime_co_line.amount",
    }


def test_dates_text_and_identifier_kinds_come_from_the_catalogue() -> None:
    assert date_fields(RecordFamily.RFIS) == (
        "rfi.date_closed",
        "rfi.date_initiated",
        "rfi.due_date",
    )
    assert "rfi.subject" in searchable_text_fields(RecordFamily.RFIS)
    assert "rfi.number" not in searchable_text_fields(RecordFamily.RFIS)
    assert set(IDENTIFIER_KINDS) == set(RecordFamily)
    for family, kinds in IDENTIFIER_KINDS.items():
        for field_key in kinds.values():
            views = [v for v, f in FAMILY_OF_VIEW.items() if f is family]
            entries = [e for v in views for e in VIEW_FIELDS[v] if e.field_key == field_key]
            assert entries and all(e.value_kind is ValueKind.IDENTIFIER for e in entries)


# --- Decimal strings and the series id ------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "money", "expected"),
    [
        (Decimal("1234.5000"), True, "1234.50"),
        (Decimal("0.1250"), True, "0.125"),
        (Decimal("-5"), True, "-5.00"),
        (Decimal("1E+3"), True, "1000.00"),
        (Decimal("-0.0000"), True, "0.00"),
        (Decimal("0.0001"), True, "0.0001"),
        (Decimal("12.5000"), False, "12.5"),
        (Decimal("40.0000"), False, "40"),
        (Decimal("123456789012345.6789"), True, "123456789012345.6789"),
    ],
)
def test_decimal_strings_are_exact_plain_fixed_point(
    value: Decimal, money: bool, expected: str
) -> None:
    assert format_amount(value, money=money) == expected


def test_a_non_decimal_or_non_finite_amount_is_refused() -> None:
    with pytest.raises(ValueError, match="finite Decimal"):
        format_amount(Decimal("NaN"), money=True)
    with pytest.raises(ValueError, match="finite Decimal"):
        format_amount(5, money=True)  # type: ignore[arg-type]


def test_the_series_id_is_stable_and_names_every_part() -> None:
    first = series_id("prn_synthetic0001", "isrc_synthetic0001", "slug-a", "a" * 64)
    assert first == series_id("prn_synthetic0001", "isrc_synthetic0001", "slug-a", "a" * 64)
    assert is_series_id(first) and first.startswith("prser_") and len(first) == 38
    others = {
        series_id("prn_synthetic0002", "isrc_synthetic0001", "slug-a", "a" * 64),
        series_id("prn_synthetic0001", "isrc_synthetic0002", "slug-a", "a" * 64),
        series_id("prn_synthetic0001", "isrc_synthetic0001", "slug-b", "a" * 64),
        series_id("prn_synthetic0001", "isrc_synthetic0001", None, "a" * 64),
        series_id("prn_synthetic0001", "isrc_synthetic0001", "slug-a", "b" * 64),
    }
    assert len(others) == 5 and first not in others
    assert "slug" not in first
    assert not is_series_id("prser_" + "g" * 32)
    assert not is_series_id("prser_" + "a" * 31)
    assert not is_series_id(None)


# --- filter semantics (AC-10) ----------------------------------------------------------------


def _ref(name: str, label: str | None, seen: datetime) -> VersionRef:
    return VersionRef(f"isnp_{name}", label, seen)


def test_a_declaration_applies_to_versions_first_seen_at_or_after_it() -> None:
    declared = WHEN
    assert version_filter_semantics(None, WHEN) is FilterSemantics.UNKNOWN
    assert version_filter_semantics(declared, WHEN - timedelta(seconds=1)) is (
        FilterSemantics.UNKNOWN
    )
    assert version_filter_semantics(declared, WHEN) is FilterSemantics.OPERATOR_DECLARED
    assert version_filter_semantics(declared, WHEN + timedelta(days=1)) is (
        FilterSemantics.OPERATOR_DECLARED
    )


def test_the_qualifier_is_once_per_answer_over_every_version_used() -> None:
    """An earlier `unknown` version qualifies the answer even when the latest is declared."""
    older = UsedVersion(_ref("synth0001", "20261101", WHEN), FilterSemantics.UNKNOWN)
    latest = UsedVersion(
        _ref("synth0002", "20261120", WHEN + timedelta(days=1)), FilterSemantics.OPERATOR_DECLARED
    )
    assert answer_qualifiers([older, latest]) == (ReportQualifier.FILTER_SEMANTICS_UNKNOWN,)
    assert answer_qualifiers([latest, older]) == (ReportQualifier.FILTER_SEMANTICS_UNKNOWN,)
    assert answer_qualifiers([latest]) == ()
    assert answer_qualifiers([]) == ()


# --- comparison (AC-11) ----------------------------------------------------------------------


def test_a_record_absent_later_is_not_observed_never_closed() -> None:
    before = {
        "rfi:GMP-1": RecordState(None, {"rfi.subject": "Synthetic a"}),
        "rfi:GMP-2": RecordState(StatusClass.OPEN, {"rfi.subject": "Synthetic b"}),
        "rfi:GMP-3": RecordState(StatusClass.OPEN, {"rfi.subject": "Synthetic c"}),
    }
    after = {
        "rfi:GMP-2": RecordState(StatusClass.OPEN, {"rfi.subject": "Synthetic b2"}),
        "rfi:GMP-3": RecordState(StatusClass.CLOSED, {"rfi.subject": "Synthetic c"}),
        "rfi:GMP-4": RecordState(None, {"rfi.subject": "Synthetic d"}),
    }
    diff = compare_records(before, after)
    assert diff.added == ("rfi:GMP-4",)
    assert diff.not_observed == ("rfi:GMP-1",)
    assert diff.changed == (
        ("rfi:GMP-2", ("rfi.subject",), StatusClass.OPEN, StatusClass.OPEN),
        ("rfi:GMP-3", (), StatusClass.OPEN, StatusClass.CLOSED),
    )
    assert "closed" not in {f.name for f in diff.__dataclass_fields__.values()}


def test_snapshot_scoped_lines_are_matched_as_a_multiset_by_content() -> None:
    a = content_signature(LineKind.BUDGET_CHANGE_LINE, ["SYN-01"], {"adjustment.amount": "$1"})
    b = content_signature(LineKind.BUDGET_CHANGE_LINE, ["SYN-01"], {"adjustment.amount": "$2"})
    assert a != b
    assert a == content_signature(
        LineKind.BUDGET_CHANGE_LINE, ["SYN-01"], {"adjustment.amount": "$1"}
    )
    assert a != content_signature(
        LineKind.BUDGET_CHANGE_LINE, ["SYN-02"], {"adjustment.amount": "$1"}
    )
    entries = compare_by_content([a, a, b], [a, b, b])
    assert [(e.side, e.content_matched) for e in entries] == [
        ("to", True),
        ("to", True),
        ("to", False),
        ("from", False),
    ]
    assert entries[3].signature == a


# --- the measure planner (AC-06, AC-07, AC-09) ----------------------------------------------


def _money(
    kind: LineKind, text: str, status: StatusClass | None = None, key: str | None = None
) -> PlannedLine:
    return PlannedLine(kind, status, key, read_cell(text, money=True))


def _reconciliation_lines() -> list[PlannedLine]:
    pco = LineKind.PRIME_PCO_LINE
    return [
        _money(pco, "$100.00", StatusClass.APPROVED),
        _money(pco, "$40.00", StatusClass.PENDING),
        _money(pco, "$5.00", StatusClass.PENDING),
        _money(pco, "$10.00", StatusClass.VOID),
        _money(LineKind.COMMITMENT_CO_LINE, "", StatusClass.APPROVED),
    ]


def test_status_classes_are_separate_per_view() -> None:
    """AC-07: approved, pending, void and unknown apart; no all-status figure."""
    spec = MEASURES["reconciliation.prime_co_line.amount"]
    answer = plan_measure(spec, _reconciliation_lines(), CLASSIFIED)
    assert answer.total is None
    assert tuple(answer.by_status) == (
        StatusClass.APPROVED,
        StatusClass.PENDING,
        StatusClass.VOID,
        StatusClass.UNKNOWN,
    )
    values = {status: value.value for status, value in answer.by_status.items()}
    assert values == {
        StatusClass.APPROVED: Decimal("100.0000"),
        StatusClass.PENDING: Decimal("45.0000"),
        StatusClass.VOID: Decimal("10.0000"),
        StatusClass.UNKNOWN: Decimal("0.0000"),
    }
    assert STATUS_CLASSES[FamilyView.GROUPED_BY_CHANGE] == tuple(answer.by_status)
    assert set(STATUS_CLASSES[FamilyView.BY_STATUS]) == {
        StatusClass.OPEN,
        StatusClass.CLOSED,
        StatusClass.UNKNOWN,
    }


def test_an_unknown_status_blocks_every_class() -> None:
    lines = [*_reconciliation_lines(), _money(LineKind.PRIME_PCO_LINE, "$1.00", None)]
    answer = plan_measure(MEASURES["reconciliation.prime_co_line.amount"], lines, CLASSIFIED)
    for value in answer.by_status.values():
        assert value.value is None
        assert value.reasons == {NotReportableReason.STATUS_UNKNOWN_PRESENT}


def test_by_code_is_a_detail_sum_without_status() -> None:
    spec = MEASURES["by_code.adjustment.amount"]
    lines = [
        _money(LineKind.BUDGET_CHANGE_LINE, "$10.00"),
        _money(LineKind.BUDGET_CHANGE_LINE, "($2.50)"),
    ]
    answer = plan_measure(spec, lines, CLASSIFIED)
    assert answer.total is not None and answer.total.value == Decimal("7.5000")
    assert answer.status_basis is StatusBasis.NOT_EXPORTED and not answer.by_status


def test_an_unloaded_original_budget_is_unpopulated_not_zero() -> None:
    """AC-09: the all-zero buyout original budget is `source_column_unpopulated`."""
    spec = MEASURES["buyout_summary.budget_line.original_amount"]
    lines = [_money(LineKind.BUDGET_LINE, "$0.00"), _money(LineKind.BUDGET_LINE, "")]
    answer = plan_measure(spec, lines, CLASSIFIED)
    assert answer.total is not None
    assert answer.total.value is None
    assert answer.total.reasons == {NotReportableReason.SOURCE_COLUMN_UNPOPULATED}


def test_a_reconciliation_mismatch_blocks_every_measure_of_the_derivation() -> None:
    """Ruling D9: derivation-wide; the value is withheld, never zero."""
    mismatch = {"column_groups": {"match": 3, "mismatch": 1}, "grand": {"match": 1}}
    assert reconciliation_outcomes(mismatch)
    assert not reconciliation_outcomes({"column_groups": {"match": 3}, "grand": {"mismatch": 0}})
    assert not reconciliation_outcomes(None)
    inputs = MeasureInputs(DerivationState.CLASSIFIED, reconciliation=mismatch)
    for name in ("by_code.adjustment.amount", "open_outstanding.record_count"):
        lines = [PlannedLine(LineKind.RFI_ROW, None, "rfi:GMP-1", read_cell("$1.00", money=True))]
        total = plan_measure(MEASURES[name], lines, inputs).total
        assert total is not None and total.value is None
        assert NotReportableReason.RECONCILIATION_MISMATCH in total.reasons


def test_a_cross_check_mismatch_concerns_only_its_two_columns() -> None:
    inputs = MeasureInputs(DerivationState.CLASSIFIED, cross_check_mismatch=True)
    checked = plan_measure(
        MEASURES["buyout_summary.prime_co_line.approved_amount"],
        [_money(LineKind.PRIME_CHANGE_ORDER, "$5.00")],
        inputs,
    ).total
    assert checked is not None and checked.reasons == {NotReportableReason.RECONCILIATION_MISMATCH}
    for status_value in plan_measure(
        MEASURES["reconciliation.prime_co_line.amount"], _reconciliation_lines(), inputs
    ).by_status.values():
        assert status_value.value is None
    other = plan_measure(
        MEASURES["buyout_summary.budget_change_line.amount"],
        [_money(LineKind.BUDGET_CHANGE, "$5.00")],
        inputs,
    ).total
    assert other is not None and other.value == Decimal("5.0000")


def test_a_quarantined_or_absent_version_is_not_reportable() -> None:
    spec = MEASURES["by_code.adjustment.amount"]
    lines = [_money(LineKind.BUDGET_CHANGE_LINE, "$1.00")]
    quarantined = plan_measure(
        spec,
        lines,
        MeasureInputs(
            DerivationState.QUARANTINED, QuarantineReason.BINDING_PROJECT_NUMBER_MISMATCH
        ),
    ).total
    assert quarantined is not None and quarantined.reasons == {
        NotReportableReason.SNAPSHOT_QUARANTINED,
        NotReportableReason.BINDING_PROJECT_NUMBER_MISMATCH,
    }
    absent = plan_measure(spec, [], MeasureInputs(None)).total
    assert absent is not None and absent.reasons >= {NotReportableReason.NO_SNAPSHOT}


def test_a_failed_cell_is_type_error_present() -> None:
    spec = MEASURES["by_code.adjustment.amount"]
    lines = [
        _money(LineKind.BUDGET_CHANGE_LINE, "$1.00"),
        _money(LineKind.BUDGET_CHANGE_LINE, "$1.00001"),
    ]
    total = plan_measure(spec, lines, CLASSIFIED).total
    assert total is not None and total.reasons == {NotReportableReason.TYPE_ERROR_PRESENT}


def test_commitments_are_keyed_and_totalled_only_when_every_key_is_reportable() -> None:
    spec = MEASURES["buyout_summary.commitment_line.amount"]
    commitment = LineKind.COMMITMENT
    lines = [
        _money(commitment, "$10.00", key="commitment:SYN-0001-001.1@SYN-0001-A"),
        _money(commitment, "$5.00", key="commitment:SYN-0001-001.1@SYN-0001-B"),
        _money(commitment, "$1.00", key="commitment:SYN-0001-001.1@SYN-0001-A"),
        _money(LineKind.BUDGET_LINE, "$999.00"),
    ]
    answer = plan_measure(spec, lines, CLASSIFIED)
    assert {key: value.value for key, value in answer.by_key.items()} == {
        ("commitment:SYN-0001-001.1@SYN-0001-A",): Decimal("11.0000"),
        ("commitment:SYN-0001-001.1@SYN-0001-B",): Decimal("5.0000"),
    }
    assert answer.total is not None and answer.total.value == Decimal("16.0000")
    failed = [*lines, _money(commitment, "$1.00001", key="commitment:SYN-0001-002.1@SYN-0001-B")]
    total = plan_measure(spec, failed, CLASSIFIED).total
    assert total is not None and total.value is None
    assert total.reasons == {NotReportableReason.TYPE_ERROR_PRESENT}


def test_record_counts_are_distinct_records_per_status_class() -> None:
    spec = MEASURES["by_status.record_count"]
    lines = [
        PlannedLine(LineKind.ISSUE, StatusClass.OPEN, "coordination_issue:1"),
        PlannedLine(LineKind.ISSUE, StatusClass.OPEN, "coordination_issue:1"),
        PlannedLine(LineKind.ISSUE, StatusClass.OPEN, "coordination_issue:2"),
        PlannedLine(LineKind.ISSUE, StatusClass.CLOSED, "coordination_issue:3"),
        PlannedLine(LineKind.ISSUE, None, None),
    ]
    answer = plan_measure(spec, lines, CLASSIFIED)
    assert answer.total is not None and answer.total.value == Decimal(3)
    assert {s: v.value for s, v in answer.by_status.items()} == {
        StatusClass.OPEN: Decimal(2),
        StatusClass.CLOSED: Decimal(1),
        StatusClass.UNKNOWN: Decimal(0),
    }
    rfis = [
        PlannedLine(LineKind.RFI_ROW, None, "rfi:GMP-1"),
        PlannedLine(LineKind.RFI_ROW, None, "rfi:GMP-1"),
        PlannedLine(LineKind.RFI_ROW, None, None),
    ]
    records = plan_measure(MEASURES["open_outstanding.record_count"], rfis, CLASSIFIED).total
    rows = plan_measure(MEASURES["open_outstanding.row_count"], rfis, CLASSIFIED).total
    assert records is not None and records.value == Decimal(1)
    assert rows is not None and rows.value == Decimal(3)
