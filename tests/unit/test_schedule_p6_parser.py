"""S7-1 acceptance A1, A4, A5, A6: profile `p6_xer_v1` over synthetic XER fixtures (FAST).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 3, 5, 7.7,
12 and 14 (S7-1). Every fixture of `tests/fixtures/schedule_p6_xer.py` must
produce the outcome, verdict and issues its generator intends (A1, truth
written from the generator's own layout) and the golden frame digest pinned
in `schedule_p6_xer_goldens.json` (A1, A6). Encodings and line ends (A4),
each section 5.4 cap at its limit and one past it (A5).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.schedule.p6 import P6_LIMITS, frame_bytes, frame_sha256, parse_xer
from my_pa.domain.schedule.p6.catalogue import catalogue_field
from my_pa.domain.schedule.p6.frame import frame_object, render_decimal
from my_pa.domain.schedule.p6.model import (
    Bound,
    CalendarStatus,
    P6IssueCode,
    P6Outcome,
    P6ParseResult,
)
from my_pa.domain.schedule.p6.profile import verdict
from my_pa.domain.schedule.p6.reader import RawTable
from my_pa.domain.schedule.p6.values import ReadingStatus, read_value
from tests.fixtures import schedule_p6_xer as fixtures

ROOT: Final = Path(__file__).resolve().parents[2]
GOLDENS: Final = json.loads(fixtures.GOLDEN_FILE.read_text(encoding="utf-8"))
CASES: Final = tuple(fixtures.CASES)


def _parse(name: str) -> tuple[fixtures.FixtureCase, P6ParseResult]:
    case = fixtures.build(name)
    return case, parse_xer(case.data, capture=case.capture)


def _issues(result: P6ParseResult) -> list[tuple[str, str, str | None, int | None, str | None]]:
    return [
        (issue.code.value, issue.severity.value, issue.table, issue.line, issue.field)
        for issue in result.issues
    ]


@pytest.mark.parametrize("name", CASES)
def test_every_fixture_produces_its_intended_outcome_and_issues(name: str) -> None:
    case, result = _parse(name)
    assert result.outcome.value == case.truth.outcome
    assert verdict(result).value == case.truth.verdict
    assert sorted(_issues(result), key=repr) == sorted(case.truth.issues, key=repr)


@pytest.mark.parametrize("name", CASES)
def test_every_fixture_matches_its_golden(name: str) -> None:
    case, result = _parse(name)
    golden = GOLDENS["cases"][name]
    assert hashlib.sha256(case.data).hexdigest() == golden["input_sha256"]
    assert [list(issue) for issue in _issues(result)] == golden["issues"]
    assert result.outcome.value == golden["outcome"]
    assert verdict(result).value == golden["verdict"]
    assert frame_sha256(result) == golden["frame_sha256"]


def test_golden_file_holds_exactly_the_registered_cases() -> None:
    assert GOLDENS["generator_version"] == fixtures.GENERATOR_VERSION
    assert set(GOLDENS["cases"]) == set(CASES)


# --- A4 encodings and line ends ---------------------------------------------------------------


def test_cp1252_and_utf8_differ_only_in_the_recorded_encoding() -> None:
    _, cp1252 = _parse("cp1252_bytes")
    _, utf8 = _parse("utf8_bytes")
    assert cp1252.header is not None and cp1252.header.encoding == "cp1252"
    assert utf8.header is not None and utf8.header.encoding == "utf-8"
    left, right = frame_object(cp1252), frame_object(utf8)
    for frame in (left, right):
        header = frame["header"]
        assert isinstance(header, dict)
        header["encoding"] = None
        project = frame["project"]
        assert isinstance(project, dict)
        columns = project["columns"]
        assert isinstance(columns, dict)
        columns["encoding"] = None
    assert left == right
    names = [entity.get("activity_name") for entity in cp1252.activities]
    assert "Synthetic Café Task €" in names


def test_invalid_bytes_and_a_bom_fail_closed() -> None:
    _, invalid = _parse("invalid_bytes")
    assert [issue.code for issue in invalid.issues] == [P6IssueCode.ENCODING_INVALID]
    _, bom = _parse("bom_utf8")
    assert [issue.code for issue in bom.issues] == [P6IssueCode.HEADER_INVALID]


def test_crlf_and_lf_give_identical_frames() -> None:
    _, crlf = _parse("no_optional_tables")
    _, lf = _parse("lf_line_ends")
    _, trailing = _parse("trailing_blank_lines")
    assert frame_bytes(crlf) == frame_bytes(lf) == frame_bytes(trailing)


def test_an_unnamed_calendar_root_reads_like_a_named_one() -> None:
    case, unnamed = _parse("calendar_root_unnamed")
    assert case.data.count(b"(0||()(") == 2
    named = parse_xer(case.data.replace(b"(0||()(", b"(0||CalendarData()("), capture=case.capture)
    assert len(unnamed.calendars) == 2
    assert [calendar.status for calendar in unnamed.calendars] == [CalendarStatus.PARSED] * 2
    assert [(c.p6_id, c.status, c.used, c.week, c.exceptions) for c in unnamed.calendars] == [
        (c.p6_id, c.status, c.used, c.week, c.exceptions) for c in named.calendars
    ]
    assert all(calendar.week for calendar in unnamed.calendars)


# --- A5 caps ----------------------------------------------------------------------------------

FAST_BOUNDS: Final = tuple(fixtures.CONTRACT_CAPS)


def test_production_limits_are_the_contract_caps() -> None:
    limits = P6_LIMITS.as_dict()
    assert {name: limits[name] for name in fixtures.CONTRACT_CAPS} == dict(fixtures.CONTRACT_CAPS)
    assert {bound.value for bound in Bound} == set(fixtures.CONTRACT_CAPS)
    assert (
        limits["captured_fields"],
        limits["captured_values_per_entity"],
        limits["captured_values"],
        limits["captured_text_characters"],
    ) == (300, 300, 3_000_000, 4_000)


def test_limits_can_only_be_tightened() -> None:
    assert P6_LIMITS.tightened(task_records=10).task_records == 10
    with pytest.raises(ValueError, match="tightened"):
        P6_LIMITS.tightened(task_records=25_001)


def _fatal_bounds(result: P6ParseResult) -> list[Bound | None]:
    return [issue.bound for issue in result.issues if issue.fatal]


@pytest.mark.parametrize("bound", FAST_BOUNDS)
def test_each_cap_passes_at_its_limit_and_fails_one_past_it(bound: str) -> None:
    data, changes = fixtures.cap_case(bound, past=False)
    limits = P6_LIMITS.tightened(**changes)
    at_limit = parse_xer(data, limits=limits)
    assert at_limit.outcome is P6Outcome.COMPLETE, _issues(at_limit)[:3]
    data, changes = fixtures.cap_case(bound, past=True)
    past = parse_xer(data, limits=P6_LIMITS.tightened(**changes))
    assert past.outcome is P6Outcome.FAILED
    assert [issue.code for issue in past.issues if issue.fatal] == [P6IssueCode.BOUND_EXCEEDED]
    assert _fatal_bounds(past) == [Bound(bound)]


@pytest.mark.slow
@pytest.mark.parametrize("bound", sorted(fixtures.TIGHTENED_CAPS))
def test_record_caps_at_production_size(bound: str) -> None:
    data, changes = fixtures.cap_case(bound, past=False, production=True)
    assert not changes
    assert parse_xer(data).outcome is P6Outcome.COMPLETE
    data, _ = fixtures.cap_case(bound, past=True, production=True)
    assert _fatal_bounds(parse_xer(data)) == [Bound(bound)]


# --- A6 determinism ---------------------------------------------------------------------------


def test_same_bytes_give_identical_frame_bytes() -> None:
    case = fixtures.build("full_valid")
    first = frame_bytes(parse_xer(case.data))
    second = frame_bytes(parse_xer(bytes(case.data)))
    assert first == second
    assert b"." not in json.dumps(json.loads(first)["counts"]).encode()


def test_frame_digest_is_independent_of_the_hash_seed() -> None:
    script = (
        "from tests.fixtures import schedule_p6_xer as f\n"
        "from my_pa.domain.schedule.p6 import frame_sha256, parse_xer\n"
        "for name in ('full_valid', 'udf_all_types', 'unknown_field'):\n"
        "    case = f.build(name)\n"
        "    print(frame_sha256(parse_xer(case.data, capture=case.capture)))\n"
    )
    expected = [
        GOLDENS["cases"][name]["frame_sha256"]
        for name in ("full_valid", "udf_all_types", "unknown_field")
    ]
    for seed in ("0", "1", "4242"):
        environment = dict(
            os.environ, PYTHONHASHSEED=seed, PYTHONPATH=f"{ROOT / 'src'}{os.pathsep}{ROOT}"
        )
        completed = subprocess.run(  # noqa: S603 - fixed interpreter and script
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        assert completed.stdout.split() == expected


def test_decimals_render_without_exponent_or_trailing_zeros() -> None:
    assert render_decimal(Decimal("100")) == "100"
    assert render_decimal(Decimal("8.50")) == "8.5"
    assert render_decimal(Decimal("-0.000")) == "0"
    assert render_decimal(Decimal("123456789012345.123456")) == "123456789012345.123456"


# --- value forms (sections 3.3, 5.4) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "field", "raw", "status"),
    [
        ("TASK", "remain_drtn_hr_cnt", "123456789012345.123456", ReadingStatus.OK),
        ("TASK", "remain_drtn_hr_cnt", "1234567890123456", ReadingStatus.INVALID),
        ("TASK", "remain_drtn_hr_cnt", "1.1234567", ReadingStatus.INVALID),
        ("TASK", "remain_drtn_hr_cnt", "1e3", ReadingStatus.INVALID),
        ("TASK", "early_start_date", "1900-01-01 00:00", ReadingStatus.OK),
        ("TASK", "early_start_date", "2199-12-31 23:59", ReadingStatus.OK),
        ("TASK", "early_start_date", "1899-12-31 23:59", ReadingStatus.INVALID),
        ("TASK", "early_start_date", "2200-01-01 00:00", ReadingStatus.INVALID),
        ("TASK", "early_start_date", "2030-01-07 08:00:00", ReadingStatus.OK),
        ("TASK", "early_start_date", "2030-01-07 08:00:30", ReadingStatus.INVALID),
        ("TASK", "early_start_date", "2030-01-07", ReadingStatus.INVALID),
        ("TASK", "early_start_date", "2030-02-30 08:00", ReadingStatus.INVALID),
        ("TASK", "task_id", "123456789", ReadingStatus.OK),
        ("TASK", "task_id", "-1", ReadingStatus.INVALID),
        ("PROJWBS", "proj_node_flag", "Y", ReadingStatus.OK),
        ("PROJWBS", "proj_node_flag", "yes", ReadingStatus.INVALID),
        ("TASK", "task_type", "TT_Task", ReadingStatus.OK),
        ("TASK", "task_type", "TT_Other", ReadingStatus.UNKNOWN_ENUM),
        ("TASK", "task_type", "not a token", ReadingStatus.INVALID),
        ("TASK", "task_code", "x" * 40, ReadingStatus.OK),
        ("TASK", "task_code", "x" * 41, ReadingStatus.INVALID),
        ("TASK", "task_name", "a\x00b", ReadingStatus.INVALID),
        ("TASK", "task_name", "a\x7fb", ReadingStatus.INVALID),
        ("CALENDAR", "clndr_data", "a\x7fb", ReadingStatus.OK),
        ("TASK", "task_name", "", ReadingStatus.EMPTY),
    ],
)
def test_value_forms(table: str, field: str, raw: str, status: ReadingStatus) -> None:
    catalogued = catalogue_field(table, field)
    assert catalogued is not None
    assert read_value(catalogued, raw).status is status


# --- unknown-field policy (5.2), capture (7.2, 7.7) -------------------------------------------


def test_unknown_field_is_observed_reported_once_and_not_stored() -> None:
    _, result = _parse("unknown_field")
    codes = [issue.code for issue in result.issues]
    assert codes.count(P6IssueCode.UNKNOWN_FIELD) == 1
    assert codes.count(P6IssueCode.UNKNOWN_FIELD_UNNAMED) == 1
    observed = {(field.table, field.position): field for field in result.observed_fields}
    extra = next(f for f in result.observed_fields if f.field == "syn_extra_field")
    assert (extra.catalogued, extra.nonempty, extra.captured) == (False, 4, False)
    assert dict(extra.shapes) == {"text": 4}
    unnamed = [f for f in observed.values() if f.table == "TASK" and f.field is None]
    assert len(unnamed) == 1 and unnamed[0].field_key is None
    assert all(value.field_key != "xer:TASK.syn_extra_field" for value in result.field_values)
    _, selected = _parse("unknown_field_selected")
    captured = [v for v in selected.field_values if v.field_key == "xer:TASK.syn_extra_field"]
    assert [(v.value_type, v.value) for v in captured] == [("text", "Synthetic extra")] * 4


def test_unknown_table_is_observed_not_dropped() -> None:
    _, result = _parse("unknown_table")
    table = next(table for table in result.tables if table.name == "SYNEXTRA")
    assert (table.catalogued, table.records) == (False, 1)
    assert {f.field for f in result.observed_fields if f.table == "SYNEXTRA"} == {
        "syn_key",
        "syn_note",
    }


def test_capture_selection_is_validated() -> None:
    data = fixtures.build("no_optional_tables").data
    with pytest.raises(ValueError, match="malformed"):
        parse_xer(data, capture=["xer:task.lower"])
    with pytest.raises(ValueError, match="cap"):
        parse_xer(data, capture=[f"code:Synthetic {index}" for index in range(301)])
    assert parse_xer(data, capture=[]).field_values == ()


def test_capture_caps_stop_optional_capture_only() -> None:
    case = fixtures.build("full_selected_capture")
    tight = P6_LIMITS.tightened(captured_values_per_entity=2)
    result = parse_xer(case.data, capture=case.capture, limits=tight)
    assert result.outcome is P6Outcome.COMPLETE
    assert P6IssueCode.CAPTURE_CAP_REACHED in {issue.code for issue in result.issues}
    assert len(result.activities) == 4
    full = parse_xer(case.data, capture=case.capture)
    assert len(result.field_values) < len(full.field_values)
    total = parse_xer(
        case.data, capture=case.capture, limits=P6_LIMITS.tightened(captured_values=3)
    )
    assert len(total.field_values) == 3


def test_text_over_the_capture_bound_is_skipped_never_truncated() -> None:
    case = fixtures.build("full_selected_capture")
    tight = P6_LIMITS.tightened(captured_text_characters=10)
    result = parse_xer(case.data, capture=case.capture, limits=tight)
    texts = [v.value for v in result.field_values if v.value_type == "text"]
    assert all(isinstance(text, str) and len(text) <= 10 for text in texts)
    assert P6IssueCode.VALUE_INVALID in {issue.code for issue in result.issues}


def test_activities_carry_faithful_kinds_and_derived_dates() -> None:
    _, result = _parse("progress_statuses")
    by_code = {a.get("activity_id"): a for a in result.activities}
    assert [a.get("kind") for a in result.activities] == [
        "start_milestone",
        "task",
        "task",
        "finish_milestone",
    ]
    done = by_code["SYN-1010"]
    assert done.get("start_at") == done.get("actual_start")
    assert by_code["SYN-1020"].get("finish_at") == by_code["SYN-1020"].get("early_finish")
    assert by_code["SYN-1020"].get("wbs_path") == ("A", "A1")


def test_external_relationship_has_no_predecessor_activity() -> None:
    _, result = _parse("cross_project_relationship")
    external = [r for r in result.relationships if r.get("is_external")]
    assert len(external) == 1
    assert external[0].get("pred_activity_id") is None
    assert external[0].get("succ_activity_id") == "SYN-1010"


# --- hostile input in the generic (V) id columns (section 13) ---------------------------------


@pytest.mark.parametrize(
    ("table", "field", "digit"),
    [
        ("UDFTYPE", "udf_type_id", chr(0xB2)),  # superscript 2: `isdigit`, refused by `int`
        ("UDFVALUE", "fk_id", chr(0xB3)),
        ("TASKACTV", "task_id", chr(0xB9)),
        # Arabic-Indic 7101, an existing code id: `int` would silently convert it.
        ("TASKACTV", "actv_code_id", "".join(chr(0x0660 + int(d)) for d in "7101")),
    ],
)
def test_non_ascii_digits_in_an_id_column_are_invalid_never_an_error(
    table: str, field: str, digit: str
) -> None:
    model = fixtures.base_model("full")
    model.table(table).rows[0][field] = digit
    lay = fixtures.layout(model)
    encoding = "cp1252" if len(digit) == 1 else "utf-8"
    result = parse_xer(fixtures.encode(lay.lines, encoding=encoding))
    assert result.outcome is P6Outcome.COMPLETE
    line = lay.row_line[(table, 0)]
    assert any(
        issue.code is P6IssueCode.VALUE_INVALID and issue.line == line for issue in result.issues
    )
    assert all(value.record_line != line for value in result.field_values)


def test_udf_code_labels_are_indexed_once_not_scanned_per_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = 400
    model = fixtures.base_model("standard")
    model.tables.insert(
        0,
        fixtures.Table(
            "UDFTYPE",
            ["udf_type_id", "table_name", "udf_type_label", "logical_data_type"],
            [
                {
                    "udf_type_id": "9",
                    "table_name": "TASK",
                    "udf_type_label": "Synthetic Choice",
                    "logical_data_type": "FT_STATICTYPE",
                }
            ],
        ),
    )
    model.insert_after(
        "UDFTYPE",
        fixtures.Table(
            "UDFCODE",
            ["udf_code_id", "short_name"],
            [{"udf_code_id": str(100_000 + index), "short_name": "S"} for index in range(count)],
        ),
    )
    model.tables.append(
        fixtures.Table(
            "UDFVALUE",
            ["udf_type_id", "fk_id", "udf_code_id"],
            [{"udf_type_id": "9", "fk_id": "3002", "udf_code_id": "1"}] * count,
        )
    )
    data = fixtures.encode(fixtures.layout(model).lines)
    calls = 0
    original = RawTable.index

    def counting(self: RawTable, field: str) -> int | None:
        nonlocal calls
        calls += 1
        return original(self, field)

    monkeypatch.setattr(RawTable, "index", counting)
    result = parse_xer(data)
    assert result.outcome is P6Outcome.COMPLETE
    assert calls < 20 * count  # a per-value scan of UDFCODE makes count * count calls
