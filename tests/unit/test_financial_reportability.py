"""Financial controlled source F-1: the completeness / `NOT_REPORTABLE` evaluator (section 5).

Every section 8.5 golden is evaluated here from domain inputs built in Python
(`tests/fixtures/financial_domain.py`); the fixture-file golden test
(`tests/unit/test_financial_source_fixtures.py::test_every_scenario_matches_its_golden`)
is I11-B's and re-runs the same table through the parser.
"""

from __future__ import annotations

import inspect
from dataclasses import fields, replace
from typing import Final

import pytest

from my_pa.domain.program.vocabulary import MAX_PROGRAM_PROJECTS, MetricValueState
from my_pa.domain.project_controls.financial.canonical import source_content_sha256
from my_pa.domain.project_controls.financial.model import (
    MAX_FINANCIAL_PROJECTS,
    FinancialNotReportableReason,
    FinancialOverview,
    FinancialScopeRequest,
)
from my_pa.domain.project_controls.financial.money import parse_amount, presentation_amount
from my_pa.domain.project_controls.financial.reportability import evaluate_financial_overview
from tests.fixtures.financial_domain import (
    DEFAULT_MAPPINGS,
    DESIGNATION_C,
    P1,
    P2,
    P3,
    VERSIONS,
    evaluate,
    figures,
    instant,
    program,
    project_reasons,
    reasons,
    request,
    run,
    runs,
    scenario,
)

R = FinancialNotReportableReason


def _program_reasons(overview: FinancialOverview) -> list[str]:
    return [reason.value for reason in overview.program_reasons]


def _s01_figures(overview: FinancialOverview) -> bool:
    s01 = scenario(1).evaluate()
    return all(figures(overview, p) == figures(s01, p) for p in (P1, P2)) and program(
        overview
    ) == program(s01)


def test_no_designation_is_source_not_integrated() -> None:
    overview = scenario(19).evaluate()
    assert overview.reportability.value == "source_not_integrated"
    assert reasons(overview) == ["source_not_integrated"]
    assert _program_reasons(overview) == ["source_not_integrated"]
    assert set(program(overview).values()) == {None}
    for project in overview.projects:
        assert project.source_state.value == "not_integrated"
        assert {m.value for m in project.metrics} == {None}
        assert {m.value_state for m in project.metrics} == {MetricValueState.NOT_REPORTABLE}
    assert overview.denominator.member_projects == 2
    assert overview.source_versions == overview.pending_source_versions == ()
    # A designation that does not list the request perspective does not integrate it.
    assert (
        evaluate(
            runs("at020"),
            request(P1, P2, perspective=VERSIONS["contract"].perspective),
            designations=(DESIGNATION_C,),
        ).reportability.value
        == "source_not_integrated"
    )


def test_project_level_reason_nulls_every_metric_of_that_project() -> None:
    overview = scenario(14).evaluate()
    (p1,) = (p for p in overview.projects if p.project_id == P1)
    assert len(p1.metrics) == 15
    for metric in p1.metrics:
        assert metric.value is None
        assert metric.value_state is MetricValueState.NOT_REPORTABLE
        assert [r.value for r in metric.reasons] == ["source_reconciliation_failed"]
    assert p1.eac_basis is None
    assert p1.source_state.value == "integrity_gap"


def test_program_total_is_not_reportable_when_any_member_is() -> None:
    overview = scenario(23).evaluate()
    assert overview.reportability.value == "not_reportable"
    for metric in overview.program_metrics:
        assert metric.value is None
        assert R.MAPPING_UNREVIEWED in metric.reasons
    original = next(m for m in overview.program_metrics if m.metric.value == "original_budget")
    assert [r.value for r in original.reasons] == ["mapping_unreviewed"]


def test_per_project_figures_survive_a_program_gap() -> None:
    s01 = scenario(1).evaluate()
    for number in (23, 28, 36):
        overview = scenario(number).evaluate()
        assert overview.reportability.value == "not_reportable"
        assert figures(overview, P1) == figures(s01, P1)
    assert figures(scenario(28).evaluate(), P2) == figures(s01, P2)


def test_no_zero_is_substituted() -> None:
    s01 = scenario(1).evaluate()
    for project_id in (P1, P2):
        (allowance,) = (
            m
            for p in s01.projects
            if p.project_id == project_id
            for m in p.metrics
            if m.metric.value == "allowance"
        )
        assert allowance.value is None
        assert [r.value for r in allowance.reasons] == ["measure_not_reported"]
    assert figures(s01, P2)["contingency"] is None
    assert program(s01)["contingency"] is None
    s02 = figures(scenario(2).evaluate(), P1)
    for metric in ("forecast_cost_to_complete", "committed_cost", "contingency", "allowance"):
        assert s02[metric] is None
    # An event metric of a Project present in the effective version is a verified zero.
    assert figures(s01, P2)["approved_changes"] == "0.0000"
    assert program(s01)["pending_transfer_net"] == "0.0000"


def test_denominator_counts_every_member() -> None:
    overview = scenario(27).evaluate()
    denominator = overview.denominator
    assert denominator.member_projects == 3
    assert denominator.projects_reportable == 2
    assert denominator.missing_source_count == 1
    states = {s.value: n for s, n in denominator.projects_by_source_state}
    assert states == {
        "effective": 2,
        "not_integrated": 0,
        "integrity_gap": 0,
        "mapping_gap": 0,
        "approval_gap": 0,
        "source_gap": 1,
    }
    s28 = scenario(28).evaluate().denominator
    assert (s28.member_projects, s28.unresolved_members) == (2, 1)


def test_evaluator_has_no_threshold_parameter() -> None:
    parameters = list(inspect.signature(evaluate_financial_overview).parameters)
    assert parameters == ["request", "designations", "runs", "mappings", "quarantined_run_refs"]
    names = [field.name for field in fields(FinancialScopeRequest)]
    assert names == [
        "project_ids",
        "unresolved_members",
        "membership_truncated",
        "period",
        "perspective",
        "currency",
        "cost_basis",
        "source_cutoff",
    ]
    for name in [*parameters, *names]:
        for forbidden in ("threshold", "tolerance", "materiality", "percent"):
            assert forbidden not in name


def test_currency_mismatch_reports_fx_missing() -> None:
    overview = scenario(3).evaluate()
    assert reasons(overview) == ["currency_mismatch", "fx_missing"]
    assert project_reasons(overview, P2) == ["currency_mismatch", "fx_missing"]
    assert overview.projects[0].source_state.value == "source_gap"
    assert set(figures(overview, P2).values()) == {None}


def test_refused_run_newer_than_effective_poisons_the_designation() -> None:
    s10 = scenario(10).evaluate()
    assert reasons(s10) == ["source_refused"]
    assert s10.denominator.refused_runs == 1
    s11 = scenario(11).evaluate()
    assert s11.reportability.value == "reportable"
    assert s11.denominator.refused_runs == 1


def test_membership_unresolved_blocks_program_totals_only() -> None:
    overview = scenario(28).evaluate()
    assert reasons(overview) == _program_reasons(overview) == ["membership_unresolved"]
    assert set(program(overview).values()) == {None}
    assert all(p.source_state.value == "effective" for p in overview.projects)


def test_stale_approval_is_not_reportable() -> None:
    overview = scenario(5).evaluate()
    assert reasons(overview) == ["approval_stale"]
    assert overview.projects[0].source_state.value == "approval_gap"


def test_unrecognized_approver_is_not_reportable() -> None:
    assert reasons(scenario(12).evaluate()) == ["approval_actor_unrecognized"]


def test_admitted_run_failing_hash_parity_is_hash_mismatch() -> None:
    good = run("at020", 1)
    forged = replace(good, content_sha256=source_content_sha256(VERSIONS["version_conflict"]))
    overview = evaluate([forged], request(P1, P2))
    assert overview.reportability.value == "not_reportable"
    assert reasons(overview) == ["hash_mismatch"]


def test_identical_reimport_clears_poisoning() -> None:
    s31 = scenario(31).evaluate()
    assert s31.reportability.value == "reportable"
    assert _s01_figures(s31)
    assert s31.denominator.refused_runs == 2
    s32 = scenario(32).evaluate()
    assert reasons(s32) == ["source_refused"]
    assert s32.denominator.refused_runs == 2


def test_poisoning_crosses_periods() -> None:
    assert reasons(scenario(33).evaluate()) == ["partial_export", "period_mismatch"]
    assert reasons(scenario(42).evaluate()) == ["source_refused"]
    s43 = scenario(43).evaluate()
    assert s43.reportability.value == "reportable"
    assert s43.source_cutoff_at == instant("2026-11-30T23:59:59Z")
    assert all(figures(s43, p) == figures(scenario(1).evaluate(), p) for p in (P1, P2))


def test_membership_truncated_blocks_program_totals_only() -> None:
    overview = scenario(36).evaluate()
    assert reasons(overview) == _program_reasons(overview) == ["membership_truncated"]
    assert set(program(overview).values()) == {None}
    assert all(p.source_state.value == "effective" for p in overview.projects)


def test_source_cutoff_excludes_later_versions() -> None:
    assert reasons(scenario(37).evaluate()) == ["source_version_missing"]
    at_cutoff = evaluate(runs("at020"), request(P1, P2, source_cutoff="2026-10-31T23:59:59Z"))
    assert at_cutoff.reportability.value == "reportable"
    assert at_cutoff.request.source_cutoff == instant("2026-10-31T23:59:59Z")


def test_project_cap_is_the_s4_cap() -> None:
    assert MAX_FINANCIAL_PROJECTS == MAX_PROGRAM_PROJECTS == 100
    hundred = [f"prj_SYNTHETIC{n:010d}" for n in range(1, 101)]
    assert len(request(*hundred).project_ids) == 100
    with pytest.raises(ValueError, match="1 to 100"):
        request(*hundred, "prj_SYNTHETIC9999999999")
    with pytest.raises(ValueError, match="1 to 100"):
        FinancialScopeRequest(
            (),
            0,
            False,
            "2026-10",
            VERSIONS["at020"].perspective,
            "USD",
            VERSIONS["at020"].cost_basis,
            None,
        )


def test_conflict_is_found_before_the_source_cutoff_filter() -> None:
    overview = scenario(40).evaluate()
    assert overview.reportability.value == "not_reportable"
    assert reasons(overview) == ["source_version_conflict"]


def test_quarantine_clears_a_conflict_and_is_disclosed() -> None:
    overview = scenario(38).evaluate()
    assert overview.reportability.value == "reportable"
    assert overview.quarantined_runs == ("syn-run-2",)
    assert overview.denominator.quarantined_runs == 1
    assert _s01_figures(overview)


def test_quarantined_refused_run_no_longer_poisons() -> None:
    overview = scenario(39).evaluate()
    assert overview.reportability.value == "reportable"
    assert overview.quarantined_runs == ("syn-run-2",)
    assert (overview.denominator.refused_runs, overview.denominator.quarantined_runs) == (0, 1)


def test_unknown_quarantine_ref_is_an_input_error() -> None:
    with pytest.raises(ValueError, match="names no supplied run"):
        evaluate(runs("at020"), request(P1, P2), quarantine={"syn-run-9"})
    with pytest.raises(TypeError, match="frozenset"):
        evaluate_financial_overview(request(P1), (), [], DEFAULT_MAPPINGS, {"x"})  # type: ignore[arg-type]


def test_program_reasons_exclude_project_reasons() -> None:
    s28_unmapped = replace(
        scenario(28),
        mappings=tuple(m for m in DEFAULT_MAPPINGS if m.external_project_id != "SYN-P-200"),
    )
    overview = s28_unmapped.evaluate()
    assert project_reasons(overview, P2) == ["mapping_missing"]
    assert _program_reasons(overview) == ["membership_unresolved"]
    assert reasons(overview) == ["mapping_missing", "membership_unresolved"]


# --- every section 8.5 golden, from domain inputs ---------------------------------------

#: `number: (reportability, reasons, program_reasons, {project: its reasons})`; a
#: Project not listed is `effective` with no reason.
GOLDENS: Final[dict[int, tuple[str, list[str], list[str], dict[str, list[str]]]]] = {
    1: ("reportable", [], [], {}),
    2: ("reportable", [], [], {}),
    3: (
        "not_reportable",
        ["currency_mismatch", "fx_missing"],
        [],
        {P2: ["currency_mismatch", "fx_missing"]},
    ),
    4: ("reportable", [], [], {}),
    5: ("not_reportable", ["approval_stale"], [], {P1: ["approval_stale"], P2: ["approval_stale"]}),
    6: (
        "not_reportable",
        ["approval_missing"],
        [],
        {P1: ["approval_missing"], P2: ["approval_missing"]},
    ),
    7: ("reportable", [], [], {}),
    8: (
        "not_reportable",
        ["withdrawn_source"],
        [],
        {P1: ["withdrawn_source"], P2: ["withdrawn_source"]},
    ),
    9: (
        "not_reportable",
        ["source_version_conflict"],
        [],
        {P1: ["source_version_conflict"], P2: ["source_version_conflict"]},
    ),
    10: (
        "not_reportable",
        ["source_refused"],
        [],
        {P1: ["source_refused"], P2: ["source_refused"]},
    ),
    11: ("reportable", [], [], {}),
    12: (
        "not_reportable",
        ["approval_actor_unrecognized"],
        [],
        {P1: ["approval_actor_unrecognized"], P2: ["approval_actor_unrecognized"]},
    ),
    13: ("reportable", [], [], {}),
    14: (
        "not_reportable",
        ["source_reconciliation_failed"],
        [],
        {P1: ["source_reconciliation_failed"]},
    ),
    15: (
        "not_reportable",
        ["double_count_detected"],
        ["double_count_detected"],
        {P1: ["double_count_detected"]},
    ),
    16: (
        "not_reportable",
        ["partial_export", "source_version_missing"],
        [],
        {
            P1: ["partial_export", "source_version_missing"],
            P2: ["partial_export", "source_version_missing"],
        },
    ),
    17: (
        "not_reportable",
        ["hash_mismatch", "source_version_missing"],
        [],
        {
            P1: ["hash_mismatch", "source_version_missing"],
            P2: ["hash_mismatch", "source_version_missing"],
        },
    ),
    18: (
        "not_reportable",
        ["source_refused", "source_version_missing"],
        [],
        {
            P1: ["source_refused", "source_version_missing"],
            P2: ["source_refused", "source_version_missing"],
        },
    ),
    19: (
        "source_not_integrated",
        ["source_not_integrated"],
        ["source_not_integrated"],
        {P1: ["source_not_integrated"], P2: ["source_not_integrated"]},
    ),
    20: (
        "not_reportable",
        ["period_mismatch"],
        [],
        {P1: ["period_mismatch"], P2: ["period_mismatch"]},
    ),
    21: (
        "not_reportable",
        ["perspective_mismatch"],
        [],
        {P1: ["perspective_mismatch"], P2: ["perspective_mismatch"]},
    ),
    22: (
        "not_reportable",
        ["basis_mismatch"],
        [],
        {P1: ["basis_mismatch"], P2: ["basis_mismatch"]},
    ),
    23: ("not_reportable", ["mapping_unreviewed"], [], {P2: ["mapping_unreviewed"]}),
    24: ("not_reportable", ["mapping_quarantined"], [], {P2: ["mapping_quarantined"]}),
    25: ("not_reportable", ["mapping_ambiguous"], [], {P2: ["mapping_ambiguous"]}),
    26: ("not_reportable", ["mapping_missing"], [], {P2: ["mapping_missing"]}),
    27: ("not_reportable", ["missing_project"], [], {P3: ["missing_project"]}),
    28: ("not_reportable", ["membership_unresolved"], ["membership_unresolved"], {}),
    29: ("reportable", [], [], {}),
    30: ("not_reportable", ["source_version_missing"], [], {P1: ["source_version_missing"]}),
    31: ("reportable", [], [], {}),
    32: (
        "not_reportable",
        ["source_refused"],
        [],
        {P1: ["source_refused"], P2: ["source_refused"]},
    ),
    33: (
        "not_reportable",
        ["partial_export", "period_mismatch"],
        [],
        {P1: ["partial_export", "period_mismatch"], P2: ["partial_export", "period_mismatch"]},
    ),
    34: (
        "not_reportable",
        ["source_version_ambiguous"],
        [],
        {P1: ["source_version_ambiguous"], P2: ["source_version_ambiguous"]},
    ),
    35: (
        "not_reportable",
        ["source_version_ambiguous"],
        [],
        {P1: ["source_version_ambiguous"], P2: ["source_version_ambiguous"]},
    ),
    36: ("not_reportable", ["membership_truncated"], ["membership_truncated"], {}),
    37: (
        "not_reportable",
        ["source_version_missing"],
        [],
        {P1: ["source_version_missing"], P2: ["source_version_missing"]},
    ),
    38: ("reportable", [], [], {}),
    39: ("reportable", [], [], {}),
    40: (
        "not_reportable",
        ["source_version_conflict"],
        [],
        {P1: ["source_version_conflict"], P2: ["source_version_conflict"]},
    ),
    41: ("not_reportable", ["double_count_detected"], ["double_count_detected"], {}),
    42: (
        "not_reportable",
        ["source_refused"],
        [],
        {P1: ["source_refused"], P2: ["source_refused"]},
    ),
    43: ("reportable", [], [], {}),
}

#: Scenarios whose figures are exactly the S01 figures (section 8.5).
S01_FIGURES: Final = (7, 31, 38, 39, 43)


@pytest.mark.parametrize("number", sorted(GOLDENS))
def test_every_domain_golden_matches_section_8_5(number: int) -> None:
    expected_reportability, expected_reasons, expected_program, by_project = GOLDENS[number]
    overview = scenario(number).evaluate()
    assert overview.reportability.value == expected_reportability
    assert reasons(overview) == expected_reasons
    assert _program_reasons(overview) == expected_program
    for project in overview.projects:
        assert [r.value for r in project.reasons] == by_project.get(project.project_id, [])
        if project.reasons:
            assert {m.value for m in project.metrics} == {None}
    if number in S01_FIGURES:
        assert _s01_figures(overview)
    if number in (6, 7):
        assert overview.pending_source_versions == (source_content_sha256(VERSIONS["proposed"]),)
    else:
        assert overview.pending_source_versions == ()
    refused = {10: 1, 11: 1, 16: 1, 17: 1, 18: 1, 31: 2, 32: 2, 33: 1, 42: 1, 43: 1}
    assert overview.denominator.refused_runs == refused.get(number, 0)
    assert overview.quarantined_runs == (("syn-run-2",) if number in (38, 39) else ())


def test_s04_and_s29_golden_values() -> None:
    s04 = figures(scenario(4).evaluate(), P2)
    assert (s04["original_budget"], s04["current_budget"], s04["eac"], s04["variance"]) == (
        "400000.0000",
        "400000.0000",
        "400000.0000",
        "0.0000",
    )
    s29 = scenario(29).evaluate()
    p3 = figures(s29, P3)
    assert (p3["original_budget"], p3["current_budget"], p3["contingency"]) == (
        "0.0150",
        "0.0150",
        None,
    )
    (contingency,) = (m for m in s29.program_metrics if m.metric.value == "contingency")
    assert [r.value for r in contingency.reasons] == ["aggregate_out_of_range"]
    assert presentation_amount(parse_amount("0.0150"), "USD") == "0.02"
    assert presentation_amount(parse_amount("0.0050"), "USD") == "0.00"
