"""Financial controlled source F-1: records, admission, version and mapping resolution.

Contract sections 3.4-3.10. Versions are built in Python
(`tests/fixtures/financial_domain.py`); the fixture files are I11-B's.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from my_pa.domain.project_controls.financial.canonical import (
    period_snapshot,
    source_content_sha256,
)
from my_pa.domain.project_controls.financial.model import (
    AccountLine,
    AccountMeasure,
    AdmissionRefusalCode,
    ChangeOrder,
    ChangeStatus,
    FinanceParseOutcome,
    FinancialNotReportableReason,
    LegSide,
    MappingState,
    MatchBasis,
    PeriodSnapshot,
    RunOutcome,
    ScopeTransfer,
    SourceDesignation,
    TransferLeg,
)
from my_pa.domain.project_controls.financial.reportability import (
    VersionResolution,
    admit_source_run,
    current_mapping_revisions,
    resolve_project_mapping,
    resolve_source_version,
)
from tests.fixtures.financial_domain import (
    DEFAULT_MAPPINGS,
    DESIGNATION_A,
    FIN_A,
    OWNER,
    P1,
    P2,
    VERSIONS,
    d,
    evaluate,
    instant,
    mapping,
    outcome,
    reasons,
    request,
    run,
    runs,
    scenario,
)

R = FinancialNotReportableReason


def _resolve(*names: str) -> VersionResolution:
    return resolve_source_version(DESIGNATION_A, runs(*names), request(P1, P2))


def test_records_refuse_float_and_unquantized_amounts() -> None:
    args = ("SYN-L-1", "SYN-P-1", None, "SYN-CC", "SYN-WBS", AccountMeasure.ACTUAL_COST)
    with pytest.raises(TypeError):
        AccountLine(*args, 1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        AccountLine(*args, 1)  # type: ignore[arg-type]
    for unquantized in (Decimal("1.5"), Decimal("1"), Decimal("1.00000"), Decimal("-0.0000")):
        with pytest.raises(ValueError, match="storable"):
            AccountLine(*args, unquantized)
    with pytest.raises(ValueError, match="never negative"):
        AccountLine(*args, d("-1"))
    with pytest.raises(ValueError, match="never zero"):
        ChangeOrder("SYN-CO", "SYN-P-1", None, "SYN-CC", "SYN-WBS", ChangeStatus.APPROVED, d("0"))
    with pytest.raises(ValueError, match="debit"):
        TransferLeg("SYN-TL", "SYN-P-1", LegSide.DEBIT, d("1"))
    with pytest.raises(ValueError, match="credit"):
        TransferLeg("SYN-TL", "SYN-P-1", LegSide.CREDIT, d("-1"))
    credit = TransferLeg("SYN-TL-C", "SYN-P-2", LegSide.CREDIT, d("2"))
    debit = TransferLeg("SYN-TL-D", "SYN-P-1", LegSide.DEBIT, d("-1"))
    with pytest.raises(ValueError, match="sum to zero"):
        ScopeTransfer("SYN-T", "SYN-CC", "SYN-WBS", ChangeStatus.APPROVED, (credit, debit))
    balanced = replace(debit, amount=d("-2"))
    with pytest.raises(ValueError, match="credit then"):
        ScopeTransfer("SYN-T", "SYN-CC", "SYN-WBS", ChangeStatus.APPROVED, (balanced, credit))
    with pytest.raises(ValueError, match="different Projects"):
        ScopeTransfer(
            "SYN-T",
            "SYN-CC",
            "SYN-WBS",
            ChangeStatus.APPROVED,
            (credit, replace(balanced, external_project_id="SYN-P-2")),
        )
    with pytest.raises(ValueError, match="measure"):
        replace(VERSIONS["at020"], perspective=VERSIONS["contract"].perspective)
    with pytest.raises(ValueError, match="identity"):
        replace(
            VERSIONS["at020"],
            account_lines=(
                *VERSIONS["at020"].account_lines,
                replace(VERSIONS["at020"].account_lines[0], ref="SYN-L-099"),
            ),
        )


def test_mapping_match_basis_is_operator_review_only() -> None:
    assert [basis.value for basis in MatchBasis] == ["operator_review"]
    for fuzzy in ("fuzzy", "name", "alias", "similarity", "automatic"):
        with pytest.raises(ValueError):
            MatchBasis(fuzzy)
    with pytest.raises(TypeError):
        replace(DEFAULT_MAPPINGS[0], match_basis="operator_review")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="names no Project"):
        mapping("SYN-P-100", P1, state=MappingState.REJECTED)


def test_current_mapping_is_the_highest_revision() -> None:
    history = [
        mapping("SYN-P-200", P2, revision=1),
        mapping("SYN-P-200", None, revision=2, state=MappingState.REJECTED),
    ]
    current = current_mapping_revisions(history)
    assert current[(FIN_A, "SYN-P-200")].revision == 2
    resolved = resolve_project_mapping(P2, [FIN_A], current)
    assert resolved.reasons == frozenset({R.MAPPING_MISSING})
    history.append(mapping("SYN-P-200", P2, revision=3))
    resolved = resolve_project_mapping(P2, [FIN_A], current_mapping_revisions(history))
    assert (resolved.source_system, resolved.external_project_id) == (FIN_A, "SYN-P-200")
    assert resolved.reasons == frozenset()


def test_effective_version_ignores_proposed_supersession() -> None:
    resolution = _resolve("at020", "proposed")
    assert resolution.effective == VERSIONS["at020"]
    assert resolution.reasons == frozenset()
    assert resolution.pending_source_versions == (source_content_sha256(VERSIONS["proposed"]),)
    overview = scenario(7).evaluate()
    assert overview.reportability.value == "reportable"
    assert overview.pending_source_versions == (source_content_sha256(VERSIONS["proposed"]),)


def test_withdrawal_withdraws_the_superseded_version() -> None:
    resolution = _resolve("at020", "withdrawal")
    assert resolution.effective is None
    assert resolution.reasons == frozenset({R.WITHDRAWN_SOURCE})
    assert reasons(scenario(8).evaluate()) == ["withdrawn_source"]


def test_two_approved_heads_are_ambiguous() -> None:
    resolution = _resolve("at020", "stale")
    assert resolution.effective is None
    assert resolution.reasons == frozenset({R.SOURCE_VERSION_AMBIGUOUS})


def test_same_ref_different_content_is_a_version_conflict() -> None:
    assert VERSIONS["at020"].source_version_ref == VERSIONS["version_conflict"].source_version_ref
    resolution = _resolve("at020", "version_conflict")
    assert resolution.effective is None
    assert resolution.reasons == frozenset({R.SOURCE_VERSION_CONFLICT})
    assert reasons(scenario(9).evaluate()) == ["source_version_conflict"]
    # An identical re-import (same content) is not a conflict.
    assert _resolve("at020", "at020").effective == VERSIONS["at020"]


def test_run_from_an_undesignated_system_is_refused() -> None:
    spoofed = run("spoofed", 1)
    assert spoofed.outcome is RunOutcome.REFUSED
    assert spoofed.refusal_code is AdmissionRefusalCode.SOURCE_SYSTEM_MISMATCH
    assert spoofed.version is None
    assert spoofed.designated_source_system == FIN_A
    owner_only = SourceDesignation(FIN_A, frozenset({OWNER}), frozenset({"syn-approver-1"}))
    undesignated_perspective = run("contract", 1, owner_only)
    assert undesignated_perspective.refusal_code is AdmissionRefusalCode.PERSPECTIVE_NOT_DESIGNATED
    admitted = run("at020", 1)
    assert admitted.outcome is RunOutcome.ADMITTED
    assert admitted.content_sha256 == source_content_sha256(VERSIONS["at020"])


def test_period_snapshot_slices_by_external_project() -> None:
    at020 = VERSIONS["at020"]
    p100 = period_snapshot(at020, "SYN-P-100")
    p200 = period_snapshot(at020, "SYN-P-200")
    p300 = period_snapshot(at020, "SYN-P-300")
    assert type(p100) is PeriodSnapshot
    assert (p100.account_line_count, p100.change_order_count, p100.transfer_leg_count) == (6, 2, 1)
    assert (p200.account_line_count, p200.change_order_count, p200.transfer_leg_count) == (5, 0, 1)
    assert (p300.account_line_count, p300.change_order_count, p300.transfer_leg_count) == (0, 0, 0)
    assert p100.source_content_sha256 == source_content_sha256(at020)
    assert len({p100.slice_sha256, p200.slice_sha256, p300.slice_sha256}) == 3


def test_supersession_cycle_is_ambiguous() -> None:
    resolution = _resolve("cycle_a", "cycle_b")
    assert resolution.effective is None
    assert resolution.reasons == frozenset({R.SOURCE_VERSION_AMBIGUOUS})
    assert reasons(scenario(34).evaluate()) == ["source_version_ambiguous"]


def test_approved_and_withdrawn_heads_are_ambiguous() -> None:
    resolution = _resolve("at020", "withdrawal_dangling")
    assert resolution.reasons == frozenset({R.SOURCE_VERSION_AMBIGUOUS})
    assert reasons(scenario(35).evaluate()) == ["source_version_ambiguous"]


def test_several_withdrawn_heads_are_withdrawn_source() -> None:
    # Neither withdrawal names a version of the scope key: 2 withdrawn heads, 0 approved.
    resolution = _resolve("withdrawal", "withdrawal_dangling")
    assert resolution.effective is None
    assert resolution.reasons == frozenset({R.WITHDRAWN_SOURCE})


def test_dangling_withdrawal_stays_a_withdrawn_head() -> None:
    resolution = _resolve("withdrawal_dangling")
    assert resolution.reasons == frozenset({R.WITHDRAWN_SOURCE})
    # A dangling approved version stands on its own.
    dangling = replace(VERSIONS["stale"], approved_at=instant("2026-11-05T15:00:00Z"))
    dangling = replace(dangling, supersedes_ref="SYN-V-2026-10-NONE")
    parsed = FinanceParseOutcome(dangling, None, None, outcome("stale").file_sha256)
    alone = admit_source_run("syn-run-1", 1, DESIGNATION_A, parsed.file_sha256, parsed)
    lone = resolve_source_version(DESIGNATION_A, [alone], request(P1, P2))
    assert lone.effective == dangling


def test_conflict_is_system_wide_and_terminal() -> None:
    overview = scenario(9).evaluate()
    assert reasons(overview) == ["source_version_conflict"]  # never also ambiguous
    assert overview.source_versions == ()
    # A conflict in another period still blocks this period's answer.
    edited = replace(
        VERSIONS["period_2026_11"],
        account_lines=VERSIONS["version_conflict"].account_lines,
    )
    parsed = FinanceParseOutcome(edited, None, None, "0" * 64)
    supplied = [
        *runs("at020", "period_2026_11"),
        admit_source_run("syn-run-3", 3, DESIGNATION_A, "0" * 64, parsed),
    ]
    overview = evaluate(supplied, request(P1, P2))
    assert reasons(overview) == ["source_version_conflict"]


def test_admitting_run_is_the_latest_carrying_the_content() -> None:
    assert scenario(31).evaluate().reportability.value == "reportable"
    assert reasons(scenario(32).evaluate()) == ["source_refused"]


def test_mapping_revision_gap_is_an_input_error() -> None:
    gap = (mapping("SYN-P-100", P1, revision=1), mapping("SYN-P-100", P1, revision=3))
    with pytest.raises(ValueError, match="without gap"):
        evaluate(runs("at020"), request(P1), mappings=gap)
    duplicate = (mapping("SYN-P-100", P1), mapping("SYN-P-100", P2))
    with pytest.raises(ValueError, match="without gap"):
        evaluate(runs("at020"), request(P1), mappings=duplicate)
    with pytest.raises(ValueError, match="without gap"):
        evaluate(runs("at020"), request(P1), mappings=(mapping("SYN-P-100", P1, revision=2),))


def test_duplicate_designation_is_an_input_error() -> None:
    twin = SourceDesignation(FIN_A, frozenset({OWNER}), frozenset({"syn-approver-2"}))
    with pytest.raises(ValueError, match="1 active designation"):
        evaluate(runs("at020"), request(P1), designations=(DESIGNATION_A, twin))


def test_run_sequence_must_be_unique_per_system() -> None:
    first = run("at020", 1)
    again = replace(run("stale", 1), run_ref="syn-run-9")
    with pytest.raises(ValueError, match="unique per source system"):
        evaluate([first, again], request(P1))
    # The same sequence under another system is allowed.
    other = replace(run("second_system", 1), run_ref="syn-run-c1")
    assert evaluate([first, other], request(P1)).reportability.value == "reportable"
