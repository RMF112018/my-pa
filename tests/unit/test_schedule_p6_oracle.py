"""P6 XER S7-5: the engine-vs-P6 oracle and the evaluation adapters (FAST).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 11.5 (the
oracle and `unmodelled_settings`), 11.4 (the delta) and 14 (S7-5). The fixtures'
P6 numbers are written by hand from the engine's rules
(`tests/fixtures/schedule_p6_oracle.py`), so a 100% share is a real agreement
and the planted mismatch must be found. Every value is synthetic.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import pytest

from my_pa.domain.schedule.p6 import P6ParseResult, parse_xer
from my_pa.domain.schedule.p6.oracle import (
    BUCKETS,
    ORACLE_CAPTURE,
    QUANTITIES,
    bucket,
    delta_counts,
    oracle_report,
    same_project,
)
from tests.fixtures import schedule_p6_oracle as cases
from tests.fixtures import schedule_p6_xer as fx


def _parse(data: bytes) -> P6ParseResult:
    return parse_xer(data, capture=ORACLE_CAPTURE)


def _report(data: bytes) -> dict[str, Any]:
    return oracle_report(_parse(data))


def _delta(earlier: P6ParseResult, later: P6ParseResult, seen: frozenset[str]) -> dict[str, Any]:
    return delta_counts(earlier, later, seen)


def _oracle(name: str) -> dict[str, Any]:
    return _report(cases.build(name))


def _encoded(model: fx.Model) -> bytes:
    return fx.encode(fx.layout(model).lines)


def _all_equal(report: dict[str, Any], activities: int) -> None:
    assert report["status"] == "compared"
    assert report["activities"] == activities
    for quantity in QUANTITIES:
        tally = report["quantities"][quantity]
        assert tally["equal"] == tally["compared"], quantity
        assert tally["equal_share"] == "1.0000", quantity
        assert tally["differences_minutes"]["0"] == tally["compared"], quantity
        assert tally["max_abs_difference_minutes"] == 0, quantity


# ---- the fixtures constructed to agree -----------------------------------------------------


def test_exact_agrees_on_every_quantity_and_the_critical_set() -> None:
    report = _oracle("exact")
    _all_equal(report, 4)
    assert report["content_schema"] == "schedule-scenario-content-v1"
    assert report["engine_version"] == "my-pa-cpm-v1"
    assert report["unmodelled_settings"] == []
    assert report["nature"] == "check, not a claim of equivalence"
    for quantity in QUANTITIES:
        assert report["quantities"][quantity]["compared"] == 4
    # Threshold 24 h: the task with 20 h of float is critical in both.
    assert report["critical"] == {
        "agreeing": 4,
        "agreement_share": "1.0000",
        "both": 4,
        "compared": 4,
        "engine": 4,
        "engine_only": 0,
        "not_compared": 0,
        "p6": 4,
        "p6_only": 0,
        "sets_equal": True,
    }


def test_milestones_agree_on_the_v2_engine() -> None:
    report = _oracle("milestones")
    _all_equal(report, 4)
    assert report["content_schema"] == "schedule-scenario-content-v2"
    assert report["engine_version"] == "my-pa-cpm-v2"


def test_rcal_project_lags_on_the_project_calendar_agree() -> None:
    report = _oracle("rcal_project")
    _all_equal(report, 2)
    assert report["content_schema"] == "schedule-scenario-content-v2"
    # The lag measured on the 5-day project calendar gives the first task 8 h of float.
    assert report["critical"]["both"] == 1
    assert report["critical"]["sets_equal"] is True
    assert report["critical"]["engine"] == 1


def test_progress_counts_missing_values_apart_from_mismatches() -> None:
    report = _oracle("progress")
    _all_equal(report, 3)
    quantities = report["quantities"]
    assert report["activities_by_state"] == {"complete": 1, "in_progress": 1, "not_started": 1}
    # P6 leaves the complete activity's late dates and remaining start empty.
    for quantity in ("late_start", "late_finish", "remaining_early_start"):
        assert quantities[quantity]["p6_missing"] == 1, quantity
        assert quantities[quantity]["compared"] == 2, quantity
    # P6 gives it a float the engine never computes for complete work.
    assert quantities["total_float"]["engine_missing"] == 1
    assert quantities["total_float"]["compared"] == 2
    assert quantities["early_start"]["by_state"] == {
        "complete": {"compared": 1, "equal": 1},
        "in_progress": {"compared": 1, "equal": 1},
        "not_started": {"compared": 1, "equal": 1},
    }
    assert report["critical"]["not_compared"] == 1
    assert report["critical"]["sets_equal"] is True
    assert report["unmodelled_settings"] == []


# ---- what the oracle must find -------------------------------------------------------------


def test_the_planted_mismatch_is_reported_with_its_difference() -> None:
    report = _oracle("mismatch")
    early_finish = report["quantities"]["early_finish"]
    assert early_finish["compared"] == 4
    assert early_finish["equal"] == 3
    assert early_finish["equal_share"] == "0.7500"
    assert early_finish["differences_minutes"]["1..60"] == 1
    assert early_finish["max_abs_difference_minutes"] == 60
    for quantity in QUANTITIES:
        if quantity != "early_finish":
            assert report["quantities"][quantity]["equal_share"] == "1.0000", quantity


def test_a_float_in_hours_is_compared_in_minutes_and_quantized_half_even() -> None:
    model = cases.CASES["exact"]()
    for row in model.table("TASK").rows:
        if row["task_code"] == "SYN-2030":
            row["total_float_hr_cnt"] = "20.004"  # 1,200.24 minutes -> 1,200
        if row["task_code"] == "SYN-2020":
            row["total_float_hr_cnt"] = "0.5"  # 30 minutes, P6 says; the engine says 0
    total_float = _report(_encoded(model))["quantities"]["total_float"]
    assert total_float["equal"] == 3
    assert total_float["p6_quantized"] == 1
    assert total_float["differences_minutes"]["-60..-1"] == 1
    assert total_float["max_abs_difference_minutes"] == 30


def test_the_critical_comparison_uses_the_project_threshold() -> None:
    model = cases.CASES["exact"]()
    model.table("PROJECT").rows[0]["critical_drtn_hr_cnt"] = "0"
    critical = _report(_encoded(model))["critical"]
    assert critical["both"] == 3
    assert critical["agreeing"] == 4
    assert critical["sets_equal"] is True
    # A P6 float that says critical where the engine says not.
    model = cases.CASES["exact"]()
    for row in model.table("TASK").rows:
        if row["task_code"] == "SYN-2030":
            row["total_float_hr_cnt"] = "30"
    critical = _report(_encoded(model))["critical"]
    assert critical["engine_only"] == 1
    assert critical["sets_equal"] is False
    assert critical["agreement_share"] == "0.7500"


def test_a_p6_date_off_the_engine_axis_is_counted_not_compared() -> None:
    model = cases.CASES["exact"]()
    model.table("TASK").rows[0]["late_start_date"] = "1999-12-31 08:00"
    late_start = _report(_encoded(model))["quantities"]["late_start"]
    assert late_start["p6_off_axis"] == 1
    assert late_start["compared"] == 3
    assert late_start["equal_share"] == "1.0000"


@pytest.mark.parametrize(
    ("difference", "name"),
    [
        (-100_000, "-inf..-2401"),
        (-2401, "-inf..-2401"),
        (-2400, "-2400..-481"),
        (-481, "-2400..-481"),
        (-480, "-480..-61"),
        (-61, "-480..-61"),
        (-60, "-60..-1"),
        (-1, "-60..-1"),
        (0, "0"),
        (1, "1..60"),
        (60, "1..60"),
        (61, "61..480"),
        (480, "61..480"),
        (481, "481..2400"),
        (2400, "481..2400"),
        (2401, "2401..inf"),
        (100_000, "2401..inf"),
    ],
)
def test_bucket_edges(difference: int, name: str) -> None:
    assert bucket(difference) == name


def test_buckets_are_contiguous_and_symmetric() -> None:
    names = [name for name, _, _ in BUCKETS]
    assert len(names) == len(set(names)) == 9
    for (_, _, high), (_, low, _) in pairwise(BUCKETS):
        assert high is not None and low == high + 1


def test_unmodelled_settings_are_listed_in_order() -> None:
    model = cases.model(
        cases._exact_tasks(),
        cases._exact_preds(),
        level="full",
        sched_lag_early_start_flag="Y",
        sched_use_expect_end_flag="Y",
        sched_float_type="FT_SmallestFloat",
        sched_open_critical_flag="Y",
        sched_use_project_end_date_for_float="Y",
        sched_retained_logic="N",
        enable_multiple_longest_path_calc="Y",
    )
    model.table("PROJECT").rows[0]["critical_path_type"] = "CT_DrivPath"
    report = _report(_encoded(model))
    assert report["unmodelled_settings"] == [
        "ss_lag_from_early_start",
        "use_expected_finish",
        "total_float_type",
        "open_ends_critical",
        "float_from_project_finish",
        "critical_path_longest_path",
        "multiple_float_paths",
        "progress_actual_dates",
    ]


def test_a_parallel_relationship_is_an_unmodelled_cause() -> None:
    # An FF beside the FS between the same ordered pair: P6 honours both, the content keeps
    # the first, so the oracle names the cause (counted by the snapshot).
    preds = [*cases._exact_preds(), fx.pred_row("4004", "3001", "3002", "PR_FF")]
    model = cases.model(cases._exact_tasks(), preds, threshold="24")
    report = _report(_encoded(model))
    assert report["status"] == "compared"
    assert report["unmodelled_settings"] == ["parallel_relationships"]
    assert _oracle("exact")["unmodelled_settings"] == []


def _progress_with(kind: str, successor: dict[str, str] | None = None) -> fx.Model:
    model = cases.CASES["progress"]()
    for row in model.table("TASKPRED").rows:
        if row["pred_task_id"] == "3002":
            row["pred_type"] = kind
    if successor is not None:
        for row in model.table("TASK").rows:
            if row["task_code"] == "SYN-5030":
                row.update(successor)
    return model


def test_an_in_progress_start_link_is_an_unmodelled_cause() -> None:
    # SYN-5020 is in progress; its SS/SF link to the not-started SYN-5030 is skipped by the
    # engine's backward pass (S6 section 3.6) and applied by P6.
    for kind in ("PR_SS", "PR_SF"):
        report = _report(_encoded(_progress_with(kind)))
        assert report["status"] == "compared", kind
        assert report["unmodelled_settings"] == ["in_progress_start_links"], kind
    # An FS or FF link from it is applied by both: no cause.
    for kind in ("PR_FS", "PR_FF"):
        assert _report(_encoded(_progress_with(kind)))["unmodelled_settings"] == [], kind
    # A complete successor is not considered by the backward pass: no cause.
    done = {
        "status_code": "TK_Complete",
        "remain_drtn_hr_cnt": "0",
        "act_start_date": "2030-01-08 08:00",
        "act_end_date": "2030-01-08 17:00",
    }
    report = _report(_encoded(_progress_with("PR_SS", done)))
    assert report["status"] == "compared"
    assert report["unmodelled_settings"] == []
    # Under progress override an in-progress successor is not considered either.
    started = {"status_code": "TK_Active", "act_start_date": "2030-01-08 13:00"}
    model = _progress_with("PR_SS", started)
    model.table("SCHEDOPTIONS").rows[0].update(
        sched_retained_logic="N", sched_progress_override="Y"
    )
    assert "in_progress_start_links" not in _report(_encoded(model))["unmodelled_settings"]
    model.table("SCHEDOPTIONS").rows[0].update(sched_progress_override="N")
    assert "in_progress_start_links" in _report(_encoded(model))["unmodelled_settings"]


def test_a_failed_parse_and_a_refused_snapshot_are_reported_not_compared() -> None:
    assert _report(fx.build("missing_required_field").data)["status"] == ("parse_failed")
    model = cases.CASES["exact"]()
    model.table("TASK").rows[0].update(status_code="TK_Complete", act_start_date="")
    report = _report(_encoded(model))
    assert report["status"] == "snapshot_refused"
    assert report["refusal"] == "rows"


def test_the_oracle_is_deterministic() -> None:
    data = cases.build("mismatch")
    assert oracle_report(_parse(data)) == oracle_report(_parse(data))


# ---- the delta between consecutive exports --------------------------------------------------


def _with_extra_task(model: fx.Model) -> fx.Model:
    model.table("TASK").rows.append(
        cases.task("3005", "SYN-2050", "8", ("2030-01-11 08:00", "2030-01-11 17:00"))
    )
    return model


def test_the_delta_is_earlier_to_later() -> None:
    earlier = parse_xer(cases.build("exact"))
    later = parse_xer(_encoded(_with_extra_task(cases.CASES["exact"]())))
    forward = _delta(earlier, later, frozenset())["counts_by_kind"]
    assert forward["added"] == 1
    assert forward["removed"] == 0
    backward = _delta(later, earlier, frozenset())["counts_by_kind"]
    assert backward["removed"] == 1
    assert backward["added"] == 0


def test_an_identical_re_export_has_no_change() -> None:
    data = cases.build("exact")
    counts = _delta(parse_xer(data), parse_xer(data), frozenset())
    assert counts["changes"] == 0


def test_a_returning_activity_is_reintroduced() -> None:
    with_it = parse_xer(_encoded(_with_extra_task(cases.CASES["exact"]())))
    without = parse_xer(cases.build("exact"))
    counts = _delta(without, with_it, frozenset({"SYN-2050"}))["counts_by_kind"]
    assert counts["reintroduced"] == 1
    assert counts["added"] == 0


def test_same_project_by_short_name_or_guid() -> None:
    base = parse_xer(cases.build("exact"))
    renamed = cases.CASES["exact"]()
    renamed.table("PROJECT").rows[0]["proj_short_name"] = "SYN-OTHER"
    assert same_project(base, parse_xer(_encoded(renamed)))
    renamed.table("PROJECT").rows[0]["guid"] = fx.guid("SynOther")
    assert not same_project(base, parse_xer(_encoded(renamed)))
