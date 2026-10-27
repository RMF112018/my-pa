"""The pure Full-Schedule domain: enums, records, grammars, outcome, canonical bytes.

FAST: no PDF. Contract `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 3.3, 3.4, 4.7, 4.8, 5.13 and 6. Every value here is synthetic.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import date
from decimal import Decimal

import pytest

from my_pa.domain.schedule import (
    CELLS_SCHEMA,
    ISSUE_SEVERITY,
    RESULT_SCHEMA,
    ROW_CELL_FIELDS,
    ParsedScheduleRow,
    ScheduleBox,
    ScheduleCellEvidence,
    ScheduleCellFragment,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleFieldCode,
    ScheduleIssueCode,
    ScheduleIssueSeverity,
    ScheduleParseCounts,
    ScheduleParseEngine,
    ScheduleParseIssue,
    ScheduleParseResult,
    SchedulePublicationStatus,
    ScheduleRowType,
    canonical_json_bytes,
    cell_evidence_bytes,
    cell_evidence_object,
    derive_outcome,
    format_millipoints,
    normalize_activity_id,
    normalize_display_text,
    normalized_box_strings,
    parse_profile_date,
    parse_profile_duration,
    parse_result_object,
    parse_result_sha256,
    stable_link_candidates,
)

VALUE = ScheduleCellState.PUBLISHED_VALUE
BLANK = ScheduleCellState.PUBLISHED_BLANK
FAILED_CELL = ScheduleCellState.EXTRACTION_FAILED
AMBIGUOUS_CELL = ScheduleCellState.AMBIGUOUS
DIGEST = "0" * 64


# --- builders ----------------------------------------------------------------


def _fragment(raw: str, x0: int = 52_570) -> ScheduleCellFragment:
    return ScheduleCellFragment(
        raw=raw,
        box=ScheduleBox(x0, 598_600, x0 + 3_500 * len(raw), 604_900),
        font_base_name="Arial",
        font_size_mpt=7_000,
    )


def _cells(**texts: str | None) -> tuple[ScheduleCellEvidence, ...]:
    cells = []
    for fld in ROW_CELL_FIELDS:
        text = texts.get(fld.value)
        if text is None:
            cells.append(ScheduleCellEvidence(fld, BLANK, None, ()))
        else:
            cells.append(ScheduleCellEvidence(fld, VALUE, text, (_fragment(text),)))
    return tuple(cells)


def _row(**overrides: object) -> ParsedScheduleRow:
    fields: dict[str, object] = {
        "row_ordinal": 1,
        "page_number": 1,
        "physical_line_ordinal": 1,
        "row_type": ScheduleRowType.ACTIVITY,
        "indent_level": 2,
        "parent_row_ordinal": None,
        "hierarchy_path": (),
        "published_activity_id": "SYN-1000",
        "activity_name": "Synthetic activity 001",
        "original_duration": ScheduleDurationCell(VALUE, Decimal("10.000")),
        "remaining_duration": ScheduleDurationCell(VALUE, Decimal("5.000")),
        "start": ScheduleDateCell(VALUE, date(2026, 5, 4), None),
        "finish": ScheduleDateCell(VALUE, date(2026, 5, 15), "*"),
        "box": ScheduleBox(52_570, 598_600, 593_500, 604_900),
        "page_width_mpt": 1_224_000,
        "page_height_mpt": 792_000,
        "cells": _cells(activity_id="SYN-1000", activity_name="Synthetic activity 001"),
        "warning_codes": (),
    }
    fields.update(overrides)
    return ParsedScheduleRow(**fields)


def _issue(
    code: ScheduleIssueCode,
    page: int | None = None,
    row: int | None = None,
    fld: ScheduleFieldCode | None = None,
) -> ScheduleParseIssue:
    return ScheduleParseIssue(code, ISSUE_SEVERITY[code], page, row, fld)


def _counts(
    rows: tuple[ParsedScheduleRow, ...], issues: tuple[ScheduleParseIssue, ...]
) -> ScheduleParseCounts:
    by_type = {t: sum(1 for r in rows if r.row_type is t) for t in ScheduleRowType}
    return ScheduleParseCounts(
        pages=1,
        rows=len(rows),
        project_summaries=by_type[ScheduleRowType.PROJECT_SUMMARY],
        wbs_summaries=by_type[ScheduleRowType.WBS_SUMMARY],
        activities=by_type[ScheduleRowType.ACTIVITY],
        milestones=by_type[ScheduleRowType.MILESTONE],
        ambiguous=by_type[ScheduleRowType.AMBIGUOUS],
        chart_objects_excluded=0,
        watermark_objects_excluded=0,
        suppressed_objects=0,
        duplicate_objects_collapsed=0,
        non_embedded_font_objects=0,
        issues=len(issues),
        warnings=sum(1 for i in issues if i.severity is ScheduleIssueSeverity.WARNING),
    )


def _result(
    rows: tuple[ParsedScheduleRow, ...] = (),
    issues: tuple[ScheduleParseIssue, ...] = (),
    outcome: SchedulePublicationStatus = SchedulePublicationStatus.COMPLETE,
    engine: ScheduleParseEngine | None = None,
) -> ScheduleParseResult:
    return ScheduleParseResult(
        parser_name="cpm-workbench-full-parser",
        parser_version="1",
        profile_id="p6_full_v1",
        profile_version=1,
        document_sha256=DIGEST,
        document_size_bytes=100,
        outcome=outcome,
        published_schedule_title="Synthetic Project Schedule",
        data_date=date(2026, 5, 4),
        run_date=date(2026, 5, 11),
        counts=_counts(rows, issues),
        rows=rows,
        issues=issues,
        engine=engine or ScheduleParseEngine("5.13.0", "153.0.7999.0"),
    )


# --- enums -------------------------------------------------------------------


def test_closed_enums_have_exactly_the_r2_members() -> None:
    assert [m.name for m in ScheduleRowType] == [
        "PROJECT_SUMMARY",
        "WBS_SUMMARY",
        "ACTIVITY",
        "MILESTONE",
        "AMBIGUOUS",
    ]
    assert [m.name for m in ScheduleCellState] == [
        "PUBLISHED_VALUE",
        "PUBLISHED_BLANK",
        "EXTRACTION_FAILED",
        "AMBIGUOUS",
    ]
    assert [m.name for m in ScheduleIssueSeverity] == ["WARNING", "ERROR"]
    assert [m.name for m in ScheduleFieldCode] == [
        "ACTIVITY_ID",
        "ACTIVITY_NAME",
        "ORIGINAL_DURATION",
        "REMAINING_DURATION",
        "START",
        "FINISH",
        "HIERARCHY",
    ]
    assert [m.name for m in ScheduleIssueCode] == [
        "SOURCE_VERSION_CHANGED",
        "SOURCE_TOO_LARGE",
        "UNSUPPORTED_MEDIA_TYPE",
        "CORRUPT_PDF",
        "ENCRYPTED_PDF",
        "IMAGE_ONLY_PDF",
        "UNSUPPORTED_LAYOUT",
        "PAGE_METADATA_MISMATCH",
        "EXPECTED_DATA_DATE_MISMATCH",
        "HEADER_SIGNATURE_MISMATCH",
        "HEADER_OD_OCCLUDED",
        "DUPLICATE_TEXT_OBJECT_COLLAPSED",
        "OVERLAPPING_CELL_TEXT",
        "ROW_WRAP_UNSUPPORTED",
        "ACTIVITY_LIKE_ROW_MISSING_ID",
        "DUPLICATE_ACTIVITY_ID",
        "INVALID_DATE",
        "INVALID_DURATION",
        "AMBIGUOUS_CELL",
        "HIERARCHY_AMBIGUOUS",
        "BOUNDS_EXCEEDED",
        "PARSER_EXCEPTION",
        "PROCESSING_BUDGET_EXCEEDED",
    ]
    assert [m.name for m in SchedulePublicationStatus] == [
        "QUEUED",
        "PROCESSING",
        "COMPLETE",
        "PARTIAL",
        "REVIEW_REQUIRED",
        "FAILED",
    ]
    for enum in (
        ScheduleRowType,
        ScheduleCellState,
        ScheduleIssueSeverity,
        ScheduleFieldCode,
        ScheduleIssueCode,
        SchedulePublicationStatus,
    ):
        assert all(member.value == member.name.lower() for member in enum)


def test_issue_severity_is_total() -> None:
    assert set(ISSUE_SEVERITY) == set(ScheduleIssueCode)
    warnings = {c for c, s in ISSUE_SEVERITY.items() if s is ScheduleIssueSeverity.WARNING}
    assert warnings == {
        ScheduleIssueCode.HEADER_OD_OCCLUDED,
        ScheduleIssueCode.DUPLICATE_TEXT_OBJECT_COLLAPSED,
    }


# --- normalization and grammars ------------------------------------------------


def test_activity_id_normalization_is_nfc_and_trim_only() -> None:
    assert normalize_activity_id("  SYN-1000\t") == "SYN-1000"
    assert normalize_activity_id("syn-1000.1") == "syn-1000.1"
    assert normalize_activity_id("SYN  1000") == "SYN  1000"
    assert normalize_activity_id("SYN-É") == "SYN-É"


def test_display_text_normalization_collapses_every_whitespace_run() -> None:
    assert (
        normalize_display_text("  Synthetic\t\n activity" + chr(0xA0) + "001 ")
        == "Synthetic activity 001"
    )
    assert normalize_display_text("Café") == "Café"
    assert normalize_display_text("   ") == ""


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("04-May-26", (date(2026, 5, 4), None)),
        ("31-Dec-99", (date(2099, 12, 31), None)),
        ("01-Jan-00", (date(2000, 1, 1), None)),
        ("29-Feb-28", (date(2028, 2, 29), None)),
        ("11-May-26*", (date(2026, 5, 11), "*")),
        ("31-Feb-27", None),
        ("29-Feb-27", None),
        ("30-Foo-26", None),
        ("4-May-26", None),
        ("04-may-26", None),
        ("04-May-2026", None),
        ("04-May-26**", None),
        ("04-May-26 ", None),
        ("04-May-26\n", None),
        ("00-May-26", None),
        ("32-May-26", None),
        ("", None),
    ],
)
def test_profile_date_grammar(token: str, expected: tuple[date, str | None] | None) -> None:
    assert parse_profile_date(token) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("0", "0.000"),
        ("5", "5.000"),
        ("12.5", "12.500"),
        ("0.125", "0.125"),
        ("999999999.999", "999999999.999"),
        ("05", None),
        ("-1", None),
        ("+1", None),
        ("1,000", None),
        ("1.2345", None),
        ("1000000000", None),
        (".5", None),
        ("5.", None),
        ("15-Mar-28", None),
        ("5\n", None),
        (chr(0x665), None),
        ("", None),
    ],
)
def test_profile_duration_grammar(token: str, expected: str | None) -> None:
    value = parse_profile_duration(token)
    if expected is None:
        assert value is None
    else:
        assert value is not None
        assert str(value) == expected
        assert value.as_tuple().exponent == -3


# --- record invariants --------------------------------------------------------


def test_cell_value_is_present_iff_published_value() -> None:
    ScheduleDurationCell(VALUE, Decimal("0.000"))
    ScheduleDurationCell(FAILED_CELL, None)
    ScheduleDateCell(VALUE, date(2026, 5, 4), "*")
    ScheduleDateCell(AMBIGUOUS_CELL, None, None)
    for state in (BLANK, FAILED_CELL, AMBIGUOUS_CELL):
        with pytest.raises(ValueError, match="present iff"):
            ScheduleDurationCell(state, Decimal("1.000"))
        with pytest.raises(ValueError, match="present iff"):
            ScheduleDateCell(state, date(2026, 5, 4), None)
    with pytest.raises(ValueError, match="present iff"):
        ScheduleDurationCell(VALUE, None)
    with pytest.raises(ValueError, match="present iff"):
        ScheduleDateCell(VALUE, None, None)


@pytest.mark.parametrize(
    "value",
    [Decimal("1"), Decimal("1.00"), Decimal("-1.000"), Decimal("1000000000.000")],
)
def test_duration_values_are_quantized_non_negative_and_bounded(value: Decimal) -> None:
    with pytest.raises(ValueError, match="duration value"):
        ScheduleDurationCell(VALUE, value)


def test_date_marker_is_star_only_and_needs_a_value() -> None:
    with pytest.raises(ValueError, match="marker is absent or"):
        ScheduleDateCell(VALUE, date(2026, 5, 4), "+")
    with pytest.raises(ValueError, match="marker needs"):
        ScheduleDateCell(BLANK, None, "*")


def test_box_and_evidence_invariants() -> None:
    with pytest.raises(ValueError, match="x0 <= x1"):
        ScheduleBox(2, 0, 1, 0)
    with pytest.raises(ValueError, match="integer millipoints"):
        ScheduleBox(True, 0, 1, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="iff it has no fragments"):
        ScheduleCellEvidence(ScheduleFieldCode.START, VALUE, None, (_fragment("x"),))
    with pytest.raises(ValueError, match="no fragments"):
        ScheduleCellEvidence(ScheduleFieldCode.START, BLANK, "x", (_fragment("x"),))
    with pytest.raises(ValueError, match="six table fields"):
        ScheduleCellEvidence(ScheduleFieldCode.HIERARCHY, BLANK, None, ())


def test_issue_severity_must_match_the_code() -> None:
    with pytest.raises(ValueError, match="ISSUE_SEVERITY"):
        ScheduleParseIssue(
            ScheduleIssueCode.HEADER_OD_OCCLUDED, ScheduleIssueSeverity.ERROR, 1, None, None
        )
    with pytest.raises(ValueError, match="1-based"):
        _issue(ScheduleIssueCode.INVALID_DATE, 0)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"published_activity_id": None}, "ID and a name"),
        ({"activity_name": ""}, "ID and a name"),
        ({"row_type": ScheduleRowType.WBS_SUMMARY}, "label and no activity ID"),
        ({"row_type": ScheduleRowType.AMBIGUOUS}, "neither ID nor name"),
        (
            {"row_type": ScheduleRowType.AMBIGUOUS, "activity_name": None},
            "neither ID nor name",
        ),
        (
            {"row_type": ScheduleRowType.AMBIGUOUS, "published_activity_id": None},
            "neither ID nor name",
        ),
        ({"row_ordinal": 0}, "positive integers"),
        ({"parent_row_ordinal": 1}, "parent row precedes"),
        ({"hierarchy_path": tuple("x" * 33)}, "at most 32"),
        ({"warning_codes": tuple(ScheduleIssueCode)[:17]}, "at most 16"),
        (
            {
                "warning_codes": (
                    ScheduleIssueCode.INVALID_DATE,
                    ScheduleIssueCode.AMBIGUOUS_CELL,
                    ScheduleIssueCode.INVALID_DATE,
                )
            },
            "declaration order",
        ),
        (
            {"warning_codes": (ScheduleIssueCode.AMBIGUOUS_CELL, ScheduleIssueCode.INVALID_DATE)},
            "declaration order",
        ),
        ({"cells": _cells()[:5]}, "six cells"),
        ({"cells": tuple(reversed(_cells()))}, "six cells"),
        ({"indent_level": -1}, "indent level"),
    ],
)
def test_row_invariants(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _row(**overrides)


def test_row_type_identity_shapes_that_hold() -> None:
    _row(row_type=ScheduleRowType.MILESTONE)
    _row(row_type=ScheduleRowType.PROJECT_SUMMARY, published_activity_id=None)
    _row(row_type=ScheduleRowType.AMBIGUOUS, published_activity_id=None, activity_name=None)
    _row(row_ordinal=2, parent_row_ordinal=1, hierarchy_path=("Synthetic Project",))


def test_result_invariants() -> None:
    row = _row()
    _result((row,))
    with pytest.raises(ValueError, match="failed parse carries no rows"):
        _result((row,), outcome=SchedulePublicationStatus.FAILED)
    with pytest.raises(ValueError, match=r"numbered 1\.\.N"):
        _result((_row(row_ordinal=2),))
    with pytest.raises(ValueError, match="terminal"):
        _result(outcome=SchedulePublicationStatus.QUEUED)
    with pytest.raises(ValueError, match="64 lowercase hex"):
        dataclasses.replace(_result(), document_sha256="A" * 64)
    good = _result((row,))
    with pytest.raises(ValueError, match="derived from rows and issues"):
        dataclasses.replace(good, counts=dataclasses.replace(good.counts, activities=0))
    with pytest.raises(ValueError, match="derived from rows and issues"):
        dataclasses.replace(good, counts=dataclasses.replace(good.counts, warnings=1))
    with pytest.raises(ValueError, match="non-negative"):
        dataclasses.replace(good.counts, chart_objects_excluded=-1)


# --- outcome -----------------------------------------------------------------

_AMBIGUOUS_ROW = _row(
    row_type=ScheduleRowType.AMBIGUOUS, published_activity_id=None, activity_name=None
)


@pytest.mark.parametrize(
    ("codes", "rows", "expected"),
    [
        ((), (), SchedulePublicationStatus.COMPLETE),
        (
            (
                ScheduleIssueCode.HEADER_OD_OCCLUDED,
                ScheduleIssueCode.DUPLICATE_TEXT_OBJECT_COLLAPSED,
            ),
            (),
            SchedulePublicationStatus.COMPLETE,
        ),
        ((ScheduleIssueCode.INVALID_DATE,), (), SchedulePublicationStatus.PARTIAL),
        ((ScheduleIssueCode.INVALID_DURATION,), (), SchedulePublicationStatus.PARTIAL),
        ((ScheduleIssueCode.OVERLAPPING_CELL_TEXT,), (), SchedulePublicationStatus.PARTIAL),
        ((ScheduleIssueCode.AMBIGUOUS_CELL,), (), SchedulePublicationStatus.PARTIAL),
        ((ScheduleIssueCode.HIERARCHY_AMBIGUOUS,), (), SchedulePublicationStatus.PARTIAL),
        (
            (ScheduleIssueCode.AMBIGUOUS_CELL,),
            (_AMBIGUOUS_ROW,),
            SchedulePublicationStatus.REVIEW_REQUIRED,
        ),
        ((), (_AMBIGUOUS_ROW,), SchedulePublicationStatus.REVIEW_REQUIRED),
        (
            (ScheduleIssueCode.PAGE_METADATA_MISMATCH,),
            (),
            SchedulePublicationStatus.REVIEW_REQUIRED,
        ),
        (
            (ScheduleIssueCode.EXPECTED_DATA_DATE_MISMATCH,),
            (),
            SchedulePublicationStatus.REVIEW_REQUIRED,
        ),
        (
            (ScheduleIssueCode.HEADER_SIGNATURE_MISMATCH,),
            (),
            SchedulePublicationStatus.REVIEW_REQUIRED,
        ),
        ((ScheduleIssueCode.ROW_WRAP_UNSUPPORTED,), (), SchedulePublicationStatus.REVIEW_REQUIRED),
        (
            (ScheduleIssueCode.ACTIVITY_LIKE_ROW_MISSING_ID,),
            (),
            SchedulePublicationStatus.REVIEW_REQUIRED,
        ),
        (
            (ScheduleIssueCode.DUPLICATE_ACTIVITY_ID, ScheduleIssueCode.INVALID_DATE),
            (),
            SchedulePublicationStatus.REVIEW_REQUIRED,
        ),
        *(
            ((code, ScheduleIssueCode.PAGE_METADATA_MISMATCH), (), SchedulePublicationStatus.FAILED)
            for code in (
                ScheduleIssueCode.SOURCE_TOO_LARGE,
                ScheduleIssueCode.UNSUPPORTED_MEDIA_TYPE,
                ScheduleIssueCode.CORRUPT_PDF,
                ScheduleIssueCode.ENCRYPTED_PDF,
                ScheduleIssueCode.IMAGE_ONLY_PDF,
                ScheduleIssueCode.UNSUPPORTED_LAYOUT,
                ScheduleIssueCode.BOUNDS_EXCEEDED,
                ScheduleIssueCode.PARSER_EXCEPTION,
                ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED,
            )
        ),
    ],
)
def test_outcome_derivation_table(
    codes: tuple[ScheduleIssueCode, ...],
    rows: tuple[ParsedScheduleRow, ...],
    expected: SchedulePublicationStatus,
) -> None:
    issues = [_issue(code, 1) for code in codes]
    assert derive_outcome(issues, rows) is expected


def test_outcome_refuses_a_fetch_time_code() -> None:
    with pytest.raises(ValueError, match="not a parser issue"):
        derive_outcome([_issue(ScheduleIssueCode.SOURCE_VERSION_CHANGED)], ())


def test_every_issue_code_has_an_outcome_rule_or_is_refused() -> None:
    for code in ScheduleIssueCode:
        if code is ScheduleIssueCode.SOURCE_VERSION_CHANGED:
            continue
        derive_outcome([_issue(code, 1)], ())


def test_stable_link_candidates_only_for_complete_or_partial() -> None:
    summary = _row(
        row_type=ScheduleRowType.PROJECT_SUMMARY,
        published_activity_id=None,
        activity_name="Synthetic Project",
    )
    activity = _row(row_ordinal=2, parent_row_ordinal=1)
    milestone = _row(row_ordinal=3, row_type=ScheduleRowType.MILESTONE)
    rows = (summary, activity, milestone)
    assert stable_link_candidates(_result(rows)) == (activity, milestone)
    partial = _result(
        rows,
        (_issue(ScheduleIssueCode.INVALID_DATE, 1, 2, ScheduleFieldCode.START),),
        SchedulePublicationStatus.PARTIAL,
    )
    assert stable_link_candidates(partial) == (activity, milestone)
    review = _result(rows, outcome=SchedulePublicationStatus.REVIEW_REQUIRED)
    assert stable_link_candidates(review) == ()


# --- canonical bytes ----------------------------------------------------------


def test_cell_evidence_shape_is_cpm_full_cells_v1() -> None:
    obj = cell_evidence_object(_row())
    assert obj["schema"] == CELLS_SCHEMA == "cpm-full-cells-v1"
    cells = obj["cells"]
    assert isinstance(cells, dict)
    assert list(cells) == [f.value for f in ROW_CELL_FIELDS]
    assert cells["activity_id"] == {
        "state": "published_value",
        "text": "SYN-1000",
        "fragments": [
            {
                "raw": "SYN-1000",
                "bbox": ["52.570", "598.600", "80.570", "604.900"],
                "font": "Arial",
                "font_size": "7.000",
            }
        ],
    }
    assert cells["start"] == {"state": "published_blank", "text": None, "fragments": []}
    assert cell_evidence_bytes(_row()) == canonical_json_bytes(obj)


def test_canonical_bytes_are_sorted_ascii_and_stable() -> None:
    data = canonical_json_bytes({"b": 1, "a": ["é", None], "c": {"z": 1, "y": 2}})
    assert data == b'{"a":["\\u00e9",null],"b":1,"c":{"y":2,"z":1}}'
    data.decode("ascii")
    assert not data.endswith(b"\n")
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_json_bytes({"x": float("nan")})
    first = canonical_json_bytes(parse_result_object(_result((_row(),))))
    second = canonical_json_bytes(parse_result_object(_result((_row(),))))
    assert first == second
    assert parse_result_sha256(_result((_row(),))) == hashlib.sha256(first).hexdigest()


@pytest.mark.parametrize(
    ("mpt", "text"),
    [(598_600, "598.600"), (0, "0.000"), (7, "0.007"), (-500, "-0.500"), (1_224_000, "1224.000")],
)
def test_canonical_numbers_are_fixed_decimal_strings(mpt: int, text: str) -> None:
    assert format_millipoints(mpt) == text


def test_normalized_box_is_six_places_without_negative_zero() -> None:
    box = ScheduleBox(52_570, 598_600, 80_570, 792_000)
    assert normalized_box_strings(box, 1_224_000, 792_000) == [
        "0.042949",
        "0.000000",
        "0.065825",
        "0.244192",
    ]
    assert normalized_box_strings(ScheduleBox(-1, 0, 0, 0), 1_000_000_000, 792_000)[0] == (
        "0.000000"
    )


def test_result_object_keys_and_value_forms() -> None:
    obj = parse_result_object(_result((_row(),)))
    assert obj["schema"] == RESULT_SCHEMA == "cpm-full-parse-result-v1"
    assert set(obj) == {
        "schema",
        "parser_name",
        "parser_version",
        "profile_id",
        "profile_version",
        "document_sha256",
        "document_size_bytes",
        "outcome",
        "published_schedule_title",
        "data_date",
        "run_date",
        "counts",
        "rows",
        "issues",
    }
    rows = obj["rows"]
    assert isinstance(rows, list)
    row = rows[0]
    assert row["original_duration"] == {"state": "published_value", "value": "10.000"}
    assert row["finish"] == {"state": "published_value", "value": "2026-05-15", "marker": "*"}
    assert row["bbox_pdf"] == ["52.570", "598.600", "593.500", "604.900"]
    assert obj["data_date"] == "2026-05-04"
    assert "float" not in json.dumps(obj)


def test_engine_provenance_is_not_in_the_canonical_object() -> None:
    current = _result((_row(),), engine=ScheduleParseEngine("5.13.0", "153.0.7999.0"))
    floor = _result((_row(),), engine=ScheduleParseEngine("5.0.0", "143.0.7483.0"))
    assert "engine" not in parse_result_object(current)
    assert parse_result_sha256(current) == parse_result_sha256(floor)
