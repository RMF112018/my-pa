"""Financial controlled source F-1: the equations and the AT-020 domain half.

Contract section 4 and the section 8.2 / 8.6 values, written inline (the AT-020
database + integration half is F-2's `tests/integration/test_financial_scope_transfer.py`).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from my_pa.domain.project_controls.financial.canonical import source_content_sha256
from my_pa.domain.project_controls.financial.equations import (
    ScopedAmount,
    owner_budget_reconciles,
    repeats_a_ref_across_versions,
    revised_contract_of,
    variance_of,
)
from my_pa.domain.project_controls.financial.model import (
    ChangeStatus,
    CostBasis,
    EacBasis,
    FinancialOverview,
    FinancialSourceState,
)
from my_pa.domain.project_controls.financial.money import money_sum
from tests.fixtures.financial_domain import (
    AT020_LINES,
    AT020_TRANSFERS,
    CONTRACT,
    DESIGNATION_C,
    FIN_C,
    OWNER,
    P1,
    P2,
    P3,
    VERSIONS,
    admit,
    d,
    evaluate,
    figures,
    mapping,
    order,
    program,
    project_reasons,
    reasons,
    request,
    runs,
    scenario,
    transfer,
    version,
)

S01_P1 = {
    "original_budget": "1000000.0000",
    "current_budget": "875000.0000",
    "approved_changes": "25000.0000",
    "pending_changes": "40000.0000",
    "transfer_net": "-150000.0000",
    "transfers_in": "0.0000",
    "transfers_out": "150000.0000",
    "pending_transfer_net": "0.0000",
    "actual_cost": "400000.0000",
    "forecast_cost_to_complete": "450000.0000",
    "eac": "850000.0000",
    "variance": "25000.0000",
    "committed_cost": "600000.0000",
    "contingency": "50000.0000",
    "allowance": None,
}
S01_P2 = {
    "original_budget": "500000.0000",
    "current_budget": "650000.0000",
    "approved_changes": "0.0000",
    "pending_changes": "0.0000",
    "transfer_net": "150000.0000",
    "transfers_in": "150000.0000",
    "transfers_out": "0.0000",
    "pending_transfer_net": "0.0000",
    "actual_cost": "100000.0000",
    "forecast_cost_to_complete": "560000.0000",
    "eac": "660000.0000",
    "variance": "-10000.0000",
    "committed_cost": "300000.0000",
    "contingency": None,
    "allowance": None,
}
S01_PROGRAM = {
    "original_budget": "1500000.0000",
    "current_budget": "1525000.0000",
    "approved_changes": "25000.0000",
    "pending_changes": "40000.0000",
    "transfer_net": "0.0000",
    "transfers_in": "0.0000",
    "transfers_out": "0.0000",
    "pending_transfer_net": "0.0000",
    "actual_cost": "500000.0000",
    "forecast_cost_to_complete": "1010000.0000",
    "eac": "1510000.0000",
    "variance": "15000.0000",
    "committed_cost": "900000.0000",
    "contingency": None,
    "allowance": None,
}


def _metric_reasons(overview: FinancialOverview, project_id: str | None, metric: str) -> list[str]:
    source = (
        overview.program_metrics
        if project_id is None
        else next(p for p in overview.projects if p.project_id == project_id).metrics
    )
    (value,) = (m for m in source if m.metric.value == metric)
    return [reason.value for reason in value.reasons]


def test_revised_contract_is_original_plus_approved_changes() -> None:
    assert revised_contract_of(d("2000000"), d("42500.5")) == Decimal("2042500.5000")
    overview = scenario(2).evaluate()
    assert overview.reportability.value == "reportable"
    p1 = figures(overview, P1)
    assert p1["original_contract"] == "2000000.0000"
    assert p1["approved_changes"] == "42500.5000"
    assert p1["revised_contract"] == "2042500.5000"
    assert "original_budget" not in p1 and "current_budget" not in p1
    assert len(p1) == 15


def test_pending_changes_never_enter_approved_figures() -> None:
    s01 = figures(scenario(1).evaluate(), P1)
    assert s01["approved_changes"] == "25000.0000"  # SYN-CO-2 (pending 40000) is not in it
    assert s01["pending_changes"] == "40000.0000"
    s02 = figures(scenario(2).evaluate(), P1)
    assert s02["approved_changes"] == "42500.5000"  # SYN-CO-K3 (pending 7000) is not in it
    assert s02["revised_contract"] == "2042500.5000"
    assert s02["pending_changes"] == "7000.0000"


def test_eac_is_actual_plus_ctc_or_source_eac_never_both() -> None:
    s01 = scenario(1).evaluate()
    assert figures(s01, P1)["eac"] == "850000.0000"
    assert {p.project_id: p.eac_basis for p in s01.projects} == {
        P1: EacBasis.COMPUTED,
        P2: EacBasis.COMPUTED,
    }
    s02 = scenario(2).evaluate()
    assert figures(s02, P1)["eac"] == "1900000.0000"
    assert figures(s02, P1)["actual_cost"] == "800000.0000"  # reported on its own
    assert s02.projects[0].eac_basis is EacBasis.SOURCE
    assert figures(s02, P1)["variance"] == "142500.5000"
    s13 = scenario(13).evaluate()
    assert s13.reportability.value == "reportable"
    assert figures(s13, P1)["eac"] is None
    assert _metric_reasons(s13, P1, "eac") == ["eac_basis_conflict"]
    assert _metric_reasons(s13, P1, "variance") == ["eac_basis_conflict"]
    assert _metric_reasons(s13, P2, "eac") == ["eac_incomplete"]
    assert _metric_reasons(s13, P2, "variance") == ["eac_incomplete"]
    assert _metric_reasons(s13, None, "eac") == ["eac_basis_conflict", "eac_incomplete"]
    assert _metric_reasons(s13, None, "variance") == ["eac_basis_conflict", "eac_incomplete"]
    assert {p.project_id: p.eac_basis for p in s13.projects} == {P1: None, P2: None}


def test_variance_requires_one_version_scope() -> None:
    base = ScopedAmount("2026-10", OWNER, CostBasis.GROSS, "USD", d("875000"))
    eac = replace(base, amount=d("850000"))
    assert variance_of(base, eac) == Decimal("25000.0000")
    for changed in (
        replace(eac, period="2026-11"),
        replace(eac, perspective=CONTRACT),
        replace(eac, cost_basis=CostBasis.NET),
        replace(eac, currency="EUR"),
    ):
        with pytest.raises(ValueError, match="1 version scope"):
            variance_of(base, changed)
    s01 = scenario(1).evaluate()
    assert (figures(s01, P1)["variance"], figures(s01, P2)["variance"]) == (
        "25000.0000",
        "-10000.0000",
    )


def test_owner_budget_reconciliation_identity() -> None:
    assert owner_budget_reconciles(d("1000000"), d("875000"), d("25000"), d("-150000"))
    assert owner_budget_reconciles(d("500000"), d("650000"), d("0"), d("150000"))
    assert not owner_budget_reconciles(d("1000000"), d("900000"), d("25000"), d("-150000"))
    s14 = scenario(14).evaluate()
    assert reasons(s14) == ["source_reconciliation_failed"]
    assert project_reasons(s14, P1) == ["source_reconciliation_failed"]
    assert set(figures(s14, P1).values()) == {None}
    assert figures(s14, P2) == S01_P2


def test_at020_owning_project_figures_balance() -> None:
    overview = scenario(1).evaluate()
    assert overview.reportability.value == "reportable"
    assert figures(overview, P1) == S01_P1
    assert figures(overview, P2) == S01_P2
    assert program(overview) == S01_PROGRAM
    denominator = overview.denominator
    assert (
        denominator.member_projects,
        denominator.unresolved_members,
        denominator.projects_reportable,
        denominator.missing_source_count,
        denominator.refused_runs,
    ) == (2, 0, 2, 0, 0)
    assert dict(denominator.projects_by_source_state)[FinancialSourceState.EFFECTIVE] == 2
    # Section 8.6 reconciliation, per Project.
    assert money_sum([d("1000000"), d("25000"), d("-150000")]) == d("875000")
    assert money_sum([d("500000"), d("0"), d("150000")]) == d("650000")


def test_at020_consolidation_is_net_neutral() -> None:
    overview = scenario(1).evaluate()
    totals = program(overview)
    assert totals["transfer_net"] == "0.0000"
    members = [figures(overview, P1), figures(overview, P2)]
    assert money_sum(d(m["transfer_net"] or "") for m in members) == d("0")
    # Program identity: Σ current = Σ original + Σ approved + Σ transfer_net.
    identity = money_sum(
        d(totals[key] or "") for key in ("original_budget", "approved_changes", "transfer_net")
    )
    assert identity == d(totals["current_budget"] or "") == d("1525000")
    # A wrong consolidation adding transfers_in to current_budget double counts.
    wrong = money_sum(d(m["current_budget"] or "") for m in members) + d("150000")
    assert wrong == d("1675000") != d(totals["current_budget"] or "")


def test_at020_transfer_is_eliminated_once() -> None:
    overview = scenario(1).evaluate()
    (elimination,) = overview.transfer_eliminations
    assert (
        elimination.transfer_ref,
        elimination.source_project_id,
        elimination.target_project_id,
        elimination.cost_code,
        elimination.wbs_package,
        format(elimination.amount, "f"),
        elimination.currency,
        elimination.approved,
        elimination.source_content_sha256,
    ) == (
        "SYN-T-1",
        P1,
        P2,
        "SYN-CC-03300",
        "SYN-WBS-CONC",
        "150000.0000",
        "USD",
        True,
        source_content_sha256(VERSIONS["at020"]),
    )
    totals = program(overview)
    assert (totals["transfers_in"], totals["transfers_out"]) == ("0.0000", "0.0000")
    assert figures(overview, P2)["transfers_in"] == "150000.0000"
    assert figures(overview, P1)["transfers_out"] == "150000.0000"
    # With only P1 in scope the transfer is external: not eliminated, counted once.
    alone = evaluate(runs("at020"), request(P1))
    assert alone.transfer_eliminations == ()
    assert program(alone)["transfers_out"] == "150000.0000"


def test_at020_pending_change_is_reported_separately() -> None:
    overview = scenario(1).evaluate()
    pending = VERSIONS["at020"].change_orders[1]
    approved = VERSIONS["at020"].change_orders[0]
    assert pending.change_status is ChangeStatus.PENDING
    assert pending.wbs_package == approved.wbs_package == AT020_TRANSFERS[0].wbs_package
    assert figures(overview, P1)["pending_changes"] == "40000.0000"
    assert program(overview)["pending_changes"] == "40000.0000"
    assert program(overview)["approved_changes"] == "25000.0000"
    assert program(overview)["current_budget"] == "1525000.0000"


def test_at020_unapproved_transfer_is_excluded() -> None:
    pending_transfer = (
        transfer(
            "SYN-T-1",
            debit=("SYN-TL-1D", "SYN-P-100"),
            credit=("SYN-TL-1C", "SYN-P-200"),
            amount="150000.0000",
            status=ChangeStatus.PENDING,
        ),
    )
    lines = tuple(
        replace(line, amount={"SYN-L-002": d("1025000"), "SYN-L-008": d("500000")}[line.ref])
        if line.ref in {"SYN-L-002", "SYN-L-008"}
        else line
        for line in AT020_LINES
    )
    pending_version = version(lines=lines, transfers=pending_transfer)
    overview = evaluate([admit(pending_version, 1)], request(P1, P2))
    assert overview.reportability.value == "reportable"
    p1, p2 = figures(overview, P1), figures(overview, P2)
    assert (p1["transfer_net"], p2["transfer_net"]) == ("0.0000", "0.0000")
    assert (p1["transfers_out"], p2["transfers_in"]) == ("0.0000", "0.0000")
    assert (p1["pending_transfer_net"], p2["pending_transfer_net"]) == (
        "-150000.0000",
        "150000.0000",
    )
    assert overview.transfer_eliminations == ()
    assert program(overview)["pending_transfer_net"] == "0.0000"


def test_at020_currency_mismatch_is_not_consolidated() -> None:
    eur_c = replace(VERSIONS["p200_eur"], source_system=FIN_C)
    supplied = [*runs("at020"), admit(eur_c, 2, DESIGNATION_C)]
    mappings = (mapping("SYN-P-100", P1), mapping("SYN-P-200", P2, system=FIN_C))
    overview = evaluate(supplied, request(P1, P2), mappings=mappings)
    assert overview.reportability.value == "not_reportable"
    assert project_reasons(overview, P2) == ["currency_mismatch", "fx_missing"]
    assert project_reasons(overview, P1) == []
    assert set(program(overview).values()) == {None}
    assert figures(overview, P1)["original_budget"] == "1000000.0000"
    assert scenario(4).evaluate().reportability.value == "reportable"


def test_double_count_is_detected() -> None:
    s41 = scenario(41).evaluate()
    assert s41.reportability.value == "not_reportable"
    assert [r.value for r in s41.program_reasons] == ["double_count_detected"]
    assert reasons(s41) == ["double_count_detected"]
    assert project_reasons(s41, P1) == project_reasons(s41, P3) == []
    assert set(program(s41).values()) == {None}
    assert figures(s41, P3)["current_budget"] == "110000.0000"
    s15 = scenario(15).evaluate()
    assert project_reasons(s15, P1) == ["double_count_detected"]
    assert [r.value for r in s15.program_reasons] == ["double_count_detected"]
    # A change-order ref reused as a transfer ref across versions also repeats.
    as_transfer = version(
        "SYN-V-2026-10-T",
        source_system=FIN_C,
        lines=(),
        orders=(),
        transfers=(
            transfer(
                "SYN-CO-1",
                debit=("SYN-TL-9D", "SYN-P-100"),
                credit=("SYN-TL-9C", "SYN-P-200"),
                amount="1.0000",
            ),
        ),
    )
    assert repeats_a_ref_across_versions([VERSIONS["at020"], as_transfer])
    unrelated = replace(
        VERSIONS["second_system"],
        change_orders=(order("SYN-CO-77", "SYN-P-100", ChangeStatus.APPROVED, "25000.0000"),),
    )
    assert not repeats_a_ref_across_versions([VERSIONS["at020"], unrelated])
