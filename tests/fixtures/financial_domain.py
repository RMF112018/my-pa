"""Financial controlled source F-1: synthetic domain inputs built in Python (I11-A).

Contract `docs/architecture/financial-source-contract.md` section 8. The I11-A
package tests the pure domain without fixture files: every section 8.3 version
is rebuilt here as a `SourceVersion` from the values the contract writes down,
and every run is admitted through `admit_source_run`. Nothing here is real;
every identifier starts with `syn-` / `SYN-` and every native id is
`prj_SYNTHETIC...`. The byte-exact fixture files, their parser and their
manifest belong to I11-B; digests here are computed, never pinned.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from my_pa.domain.project_controls.financial.model import (
    AccountLine,
    AccountMeasure,
    ChangeOrder,
    ChangeStatus,
    CostBasis,
    FinanceParseOutcome,
    FinanceParseRefusalCode,
    FinancialOverview,
    FinancialPerspective,
    FinancialScopeRequest,
    LegSide,
    MappingState,
    MatchBasis,
    ProjectMappingRevision,
    ScopeTransfer,
    SourceDesignation,
    SourceRun,
    SourceVersion,
    SourceVersionStatus,
    TransferLeg,
)
from my_pa.domain.project_controls.financial.money import parse_amount
from my_pa.domain.project_controls.financial.reportability import (
    admit_source_run,
    evaluate_financial_overview,
)

P1: Final = "prj_SYNTHETIC0000000001"
P2: Final = "prj_SYNTHETIC0000000002"
P3: Final = "prj_SYNTHETIC0000000003"

FIN_A: Final = "syn-fin-a"
FIN_B: Final = "syn-fin-b"
FIN_C: Final = "syn-fin-c"
APPROVER: Final = "syn-approver-1"
CC: Final = "SYN-CC-03300"
WBS: Final = "SYN-WBS-CONC"

OWNER: Final = FinancialPerspective.OWNER_BUDGET
CONTRACT: Final = FinancialPerspective.CONSTRUCTION_CONTRACT
M = AccountMeasure


def instant(text: str) -> datetime:
    """`YYYY-MM-DDTHH:MM:SSZ` to an aware UTC instant."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def d(text: str) -> Decimal:
    """A storable amount from its contract text."""
    return parse_amount(text)


DESIGNATION_A: Final = SourceDesignation(FIN_A, frozenset({OWNER, CONTRACT}), frozenset({APPROVER}))
DESIGNATION_C: Final = SourceDesignation(FIN_C, frozenset({OWNER}), frozenset({APPROVER}))


def line(
    ref: str,
    project: str,
    measure: AccountMeasure,
    amount: str,
    *,
    contract: str | None = None,
    cost_code: str = CC,
    wbs: str = WBS,
) -> AccountLine:
    return AccountLine(ref, project, contract, cost_code, wbs, measure, d(amount))


def order(
    ref: str,
    project: str,
    status: ChangeStatus,
    amount: str,
    *,
    contract: str | None = None,
    cost_code: str = CC,
    wbs: str = WBS,
) -> ChangeOrder:
    return ChangeOrder(ref, project, contract, cost_code, wbs, status, d(amount))


def transfer(
    transfer_ref: str,
    *,
    debit: tuple[str, str],
    credit: tuple[str, str],
    amount: str,
    status: ChangeStatus = ChangeStatus.APPROVED,
    cost_code: str = CC,
    wbs: str = WBS,
) -> ScopeTransfer:
    """`debit` / `credit` are `(leg ref, external project)`; `amount` is the credit amount."""
    credit_leg = TransferLeg(credit[0], credit[1], LegSide.CREDIT, d(amount))
    debit_leg = TransferLeg(debit[0], debit[1], LegSide.DEBIT, d("-" + amount))
    return ScopeTransfer(transfer_ref, cost_code, wbs, status, (credit_leg, debit_leg))


AT020_LINES: Final = (
    line("SYN-L-001", "SYN-P-100", M.ORIGINAL_BUDGET, "1000000.0000"),
    line("SYN-L-002", "SYN-P-100", M.CURRENT_BUDGET, "875000.0000"),
    line("SYN-L-003", "SYN-P-100", M.ACTUAL_COST, "400000.0000"),
    line("SYN-L-004", "SYN-P-100", M.FORECAST_COST_TO_COMPLETE, "450000.0000"),
    line("SYN-L-005", "SYN-P-100", M.COMMITTED_COST, "600000.0000"),
    line("SYN-L-006", "SYN-P-100", M.CONTINGENCY, "50000.0000"),
    line("SYN-L-007", "SYN-P-200", M.ORIGINAL_BUDGET, "500000.0000"),
    line("SYN-L-008", "SYN-P-200", M.CURRENT_BUDGET, "650000.0000"),
    line("SYN-L-009", "SYN-P-200", M.ACTUAL_COST, "100000.0000"),
    line("SYN-L-010", "SYN-P-200", M.FORECAST_COST_TO_COMPLETE, "560000.0000"),
    line("SYN-L-011", "SYN-P-200", M.COMMITTED_COST, "300000.0000"),
)
AT020_ORDERS: Final = (
    order("SYN-CO-1", "SYN-P-100", ChangeStatus.APPROVED, "25000.0000"),
    order("SYN-CO-2", "SYN-P-100", ChangeStatus.PENDING, "40000.0000"),
)
AT020_TRANSFERS: Final = (
    transfer(
        "SYN-T-1",
        debit=("SYN-TL-1D", "SYN-P-100"),
        credit=("SYN-TL-1C", "SYN-P-200"),
        amount="150000.0000",
    ),
)


def version(
    ref: str = "SYN-V-2026-10-A",
    *,
    source_system: str = FIN_A,
    period: str = "2026-10",
    cutoff_at: str = "2026-10-31T23:59:59Z",
    status: SourceVersionStatus = SourceVersionStatus.APPROVED,
    approved_by: str | None = APPROVER,
    approved_at: str | None = "2026-11-05T15:00:00Z",
    supersedes_ref: str | None = None,
    perspective: FinancialPerspective = OWNER,
    currency: str = "USD",
    cost_basis: CostBasis = CostBasis.GROSS,
    lines: Sequence[AccountLine] = AT020_LINES,
    orders: Sequence[ChangeOrder] = AT020_ORDERS,
    transfers: Sequence[ScopeTransfer] = AT020_TRANSFERS,
) -> SourceVersion:
    """A section 8 version; the defaults are the section 8.2 base file."""
    return SourceVersion(
        source_system=source_system,
        source_version_ref=ref,
        period=period,
        cutoff_at=instant(cutoff_at),
        status=status,
        approved_by=approved_by,
        approved_at=None if approved_at is None else instant(approved_at),
        supersedes_ref=supersedes_ref,
        perspective=perspective,
        currency=currency,
        cost_basis=cost_basis,
        account_lines=tuple(lines),
        change_orders=tuple(orders),
        transfers=tuple(transfers),
    )


def _replace_line(ref: str, amount: str) -> tuple[AccountLine, ...]:
    return tuple(
        replace(item, amount=d(amount)) if item.ref == ref else item for item in AT020_LINES
    )


#: Section 8.3, every admitted file rebuilt as a domain version (keys are file stems).
VERSIONS: Final[dict[str, SourceVersion]] = {
    "at020": version(),
    "contract": version(
        "SYN-V-2026-10-K",
        perspective=CONTRACT,
        lines=(
            line("SYN-L-K01", "SYN-P-100", M.ORIGINAL_CONTRACT, "2000000.0000", contract="SYN-K-1"),
            line("SYN-L-K02", "SYN-P-100", M.ACTUAL_COST, "800000.0000", contract="SYN-K-1"),
            line("SYN-L-K03", "SYN-P-100", M.SOURCE_EAC, "1900000.0000", contract="SYN-K-1"),
        ),
        orders=(
            order(
                "SYN-CO-K1", "SYN-P-100", ChangeStatus.APPROVED, "30000.0000", contract="SYN-K-1"
            ),
            order(
                "SYN-CO-K2", "SYN-P-100", ChangeStatus.APPROVED, "12500.5000", contract="SYN-K-1"
            ),
            order("SYN-CO-K3", "SYN-P-100", ChangeStatus.PENDING, "7000.0000", contract="SYN-K-1"),
        ),
        transfers=(),
    ),
    "p200_eur": version(
        "SYN-V-2026-10-E",
        currency="EUR",
        lines=(
            line("SYN-L-E01", "SYN-P-200", M.ORIGINAL_BUDGET, "400000.0000"),
            line("SYN-L-E02", "SYN-P-200", M.CURRENT_BUDGET, "400000.0000"),
            line("SYN-L-E03", "SYN-P-200", M.ACTUAL_COST, "50000.0000"),
            line("SYN-L-E04", "SYN-P-200", M.FORECAST_COST_TO_COMPLETE, "350000.0000"),
        ),
        orders=(),
        transfers=(),
    ),
    "stale": version("SYN-V-2026-10-S", approved_at="2026-10-30T12:00:00Z"),
    "proposed": version(
        "SYN-V-2026-10-P",
        status=SourceVersionStatus.PROPOSED,
        approved_by=None,
        approved_at=None,
        supersedes_ref="SYN-V-2026-10-A",
    ),
    "withdrawal": version(
        "SYN-V-2026-10-W",
        status=SourceVersionStatus.WITHDRAWN,
        supersedes_ref="SYN-V-2026-10-A",
        approved_at="2026-11-07T09:00:00Z",
        lines=(),
        orders=(),
        transfers=(),
    ),
    "version_conflict": version(lines=_replace_line("SYN-L-003", "400001.0000")),
    "spoofed": version("SYN-V-2026-10-X", source_system=FIN_B),
    "unknown_actor": version("SYN-V-2026-10-U", approved_by="syn-approver-9"),
    "eac_conflict": version(
        "SYN-V-2026-10-Q",
        lines=(
            line("SYN-L-Q01", "SYN-P-100", M.ORIGINAL_BUDGET, "1000000.0000"),
            line("SYN-L-Q02", "SYN-P-100", M.CURRENT_BUDGET, "1000000.0000"),
            line("SYN-L-Q03", "SYN-P-100", M.ACTUAL_COST, "400000.0000"),
            line("SYN-L-Q04", "SYN-P-100", M.FORECAST_COST_TO_COMPLETE, "450000.0000"),
            line("SYN-L-Q05", "SYN-P-100", M.SOURCE_EAC, "860000.0000"),
            line("SYN-L-Q06", "SYN-P-200", M.ORIGINAL_BUDGET, "500000.0000"),
            line("SYN-L-Q07", "SYN-P-200", M.CURRENT_BUDGET, "500000.0000"),
            line("SYN-L-Q08", "SYN-P-200", M.ACTUAL_COST, "100000.0000"),
        ),
        orders=(),
        transfers=(),
    ),
    "reconciliation_failure": version(
        "SYN-V-2026-10-R", lines=_replace_line("SYN-L-002", "900000.0000")
    ),
    "second_system": version(
        "SYN-V-2026-10-C",
        source_system=FIN_C,
        lines=(
            line("SYN-L-C01", "SYN-P-100", M.ORIGINAL_BUDGET, "1000000.0000"),
            line("SYN-L-C02", "SYN-P-100", M.CURRENT_BUDGET, "1025000.0000"),
        ),
        orders=(order("SYN-CO-1", "SYN-P-100", ChangeStatus.APPROVED, "25000.0000"),),
        transfers=(),
    ),
    "rounding_edges": version(
        "SYN-V-2026-10-Z",
        lines=(
            line("SYN-L-Z01", "SYN-P-300", M.ORIGINAL_BUDGET, "0.0050", cost_code="SYN-CC-01001"),
            line("SYN-L-Z02", "SYN-P-300", M.ORIGINAL_BUDGET, "0.0050", cost_code="SYN-CC-01002"),
            line("SYN-L-Z03", "SYN-P-300", M.ORIGINAL_BUDGET, "0.0050", cost_code="SYN-CC-01003"),
            line("SYN-L-Z04", "SYN-P-300", M.CURRENT_BUDGET, "0.0050", cost_code="SYN-CC-01001"),
            line("SYN-L-Z05", "SYN-P-300", M.CURRENT_BUDGET, "0.0050", cost_code="SYN-CC-01002"),
            line("SYN-L-Z06", "SYN-P-300", M.CURRENT_BUDGET, "0.0050", cost_code="SYN-CC-01003"),
            line(
                "SYN-L-Z07",
                "SYN-P-300",
                M.CONTINGENCY,
                "9999999999999999.9999",
                cost_code="SYN-CC-01001",
            ),
            line("SYN-L-Z08", "SYN-P-300", M.CONTINGENCY, "0.0001", cost_code="SYN-CC-01002"),
        ),
        orders=(),
        transfers=(),
    ),
    "spoofed_b": version("SYN-V-2026-10-Y", source_system=FIN_B),
    "cycle_a": version("SYN-V-2026-10-C1", supersedes_ref="SYN-V-2026-10-C2"),
    "cycle_b": version("SYN-V-2026-10-C2", supersedes_ref="SYN-V-2026-10-C1"),
    "withdrawal_dangling": version(
        "SYN-V-2026-10-W2",
        status=SourceVersionStatus.WITHDRAWN,
        supersedes_ref="SYN-V-2026-10-NONE",
        approved_at="2026-11-07T09:00:00Z",
        lines=(),
        orders=(),
        transfers=(),
    ),
    "version_conflict_late": version(
        cutoff_at="2026-11-30T23:59:59Z",
        approved_at="2026-12-05T15:00:00Z",
        lines=_replace_line("SYN-L-003", "400001.0000"),
    ),
    "p300_second_system": version(
        "SYN-V-2026-10-D",
        source_system=FIN_C,
        lines=(
            line("SYN-L-D01", "SYN-P-300", M.ORIGINAL_BUDGET, "100000.0000"),
            line("SYN-L-D02", "SYN-P-300", M.CURRENT_BUDGET, "110000.0000"),
        ),
        orders=(order("SYN-CO-1", "SYN-P-300", ChangeStatus.APPROVED, "10000.0000"),),
        transfers=(),
    ),
    "period_2026_11": version(
        "SYN-V-2026-11-A",
        period="2026-11",
        cutoff_at="2026-11-30T23:59:59Z",
        approved_at="2026-12-05T15:00:00Z",
    ),
}

#: Section 8.3, the files the parser refuses: `(code, line)`.
REFUSALS: Final[dict[str, tuple[FinanceParseRefusalCode, int]]] = {
    "partial_export": (FinanceParseRefusalCode.PARTIAL_EXPORT, 18),
    "tampered_body": (FinanceParseRefusalCode.HASH_MISMATCH, 3),
    "duplicate_identity": (FinanceParseRefusalCode.DUPLICATE_IDENTITY, 19),
}

#: Section 8.1: which designated system each file is imported under.
_IMPORTED_UNDER: Final[dict[str, SourceDesignation]] = {
    "second_system": DESIGNATION_C,
    "p300_second_system": DESIGNATION_C,
}


def file_sha256(name: str) -> str:
    """A stand-in file digest (the real one is the I11-B fixture's)."""
    return hashlib.sha256(f"synthetic file {name}".encode("ascii")).hexdigest()


def outcome(name: str) -> FinanceParseOutcome:
    """The parser outcome a section 8.3 file produces."""
    if name in REFUSALS:
        code, line_number = REFUSALS[name]
        return FinanceParseOutcome(None, code, line_number, file_sha256(name))
    return FinanceParseOutcome(VERSIONS[name], None, None, file_sha256(name))


def run(
    name: str,
    sequence: int,
    designation: SourceDesignation | None = None,
) -> SourceRun:
    """The run `syn-run-<sequence>` admitting (or refusing) file `name`."""
    chosen = designation or _IMPORTED_UNDER.get(name, DESIGNATION_A)
    return admit_source_run(
        f"syn-run-{sequence}", sequence, chosen, file_sha256(name), outcome(name)
    )


def admit(
    chosen: SourceVersion, sequence: int, designation: SourceDesignation = DESIGNATION_A
) -> SourceRun:
    """Admit an ad-hoc version (not a section 8.3 file) as run `syn-run-<sequence>`."""
    digest = file_sha256(f"ad hoc {chosen.source_system} {chosen.source_version_ref} {sequence}")
    parsed = FinanceParseOutcome(chosen, None, None, digest)
    return admit_source_run(f"syn-run-{sequence}", sequence, designation, digest, parsed)


def runs(*names: str) -> list[SourceRun]:
    """Runs in sequence order 1, 2, ... (section 8.5)."""
    return [run(name, index) for index, name in enumerate(names, start=1)]


def mapping(
    external: str,
    project: str | None,
    *,
    system: str = FIN_A,
    revision: int = 1,
    state: MappingState = MappingState.ACCEPTED,
) -> ProjectMappingRevision:
    return ProjectMappingRevision(
        system,
        external,
        revision,
        state,
        project,
        MatchBasis.OPERATOR_REVIEW,
        "syn-operator",
        instant("2026-11-01T00:00:00Z"),
    )


DEFAULT_MAPPINGS: Final = (
    mapping("SYN-P-100", P1),
    mapping("SYN-P-200", P2),
    mapping("SYN-P-300", P3),
)


def request(
    *projects: str,
    period: str = "2026-10",
    perspective: FinancialPerspective = OWNER,
    currency: str = "USD",
    cost_basis: CostBasis = CostBasis.GROSS,
    unresolved_members: int = 0,
    membership_truncated: bool = False,
    source_cutoff: str | None = None,
) -> FinancialScopeRequest:
    return FinancialScopeRequest(
        project_ids=tuple(sorted(projects)),
        unresolved_members=unresolved_members,
        membership_truncated=membership_truncated,
        period=period,
        perspective=perspective,
        currency=currency,
        cost_basis=cost_basis,
        source_cutoff=None if source_cutoff is None else instant(source_cutoff),
    )


def evaluate(
    supplied_runs: Iterable[SourceRun],
    scope: FinancialScopeRequest,
    *,
    designations: Sequence[SourceDesignation] = (DESIGNATION_A, DESIGNATION_C),
    mappings: Sequence[ProjectMappingRevision] = DEFAULT_MAPPINGS,
    quarantine: Iterable[str] = (),
) -> FinancialOverview:
    return evaluate_financial_overview(
        scope, designations, list(supplied_runs), mappings, frozenset(quarantine)
    )


def figures(overview: FinancialOverview, project_id: str) -> dict[str, str | None]:
    """A Project's metric values as `{metric: amount text or None}`."""
    (project,) = (p for p in overview.projects if p.project_id == project_id)
    return {
        m.metric.value: None if m.value is None else format(m.value, "f") for m in project.metrics
    }


def program(overview: FinancialOverview) -> dict[str, str | None]:
    """The Program metric values as `{metric: amount text or None}`."""
    return {
        m.metric.value: None if m.value is None else format(m.value, "f")
        for m in overview.program_metrics
    }


def reasons(overview: FinancialOverview) -> list[str]:
    return [reason.value for reason in overview.reasons]


def project_reasons(overview: FinancialOverview, project_id: str) -> list[str]:
    (project,) = (p for p in overview.projects if p.project_id == project_id)
    return [reason.value for reason in project.reasons]


# --- section 8.5 scenarios, built from domain inputs ----------------------------------


@dataclass(frozen=True)
class Scenario:
    """The evaluator inputs of 1 section 8.5 golden scenario."""

    runs: tuple[SourceRun, ...]
    request: FinancialScopeRequest
    designations: tuple[SourceDesignation, ...] = (DESIGNATION_A, DESIGNATION_C)
    mappings: tuple[ProjectMappingRevision, ...] = DEFAULT_MAPPINGS
    quarantine: frozenset[str] = frozenset()

    def evaluate(self) -> FinancialOverview:
        return evaluate_financial_overview(
            self.request, self.designations, self.runs, self.mappings, self.quarantine
        )


def _without(external: str) -> tuple[ProjectMappingRevision, ...]:
    return tuple(m for m in DEFAULT_MAPPINGS if m.external_project_id != external)


def scenario(number: int) -> Scenario:
    """Section 8.5 scenario `S<number>` (request `2026-10`, owner budget, USD, gross)."""
    p12 = request(P1, P2)
    table: dict[int, Scenario] = {
        1: Scenario(tuple(runs("at020")), p12),
        2: Scenario(tuple(runs("contract")), request(P1, perspective=CONTRACT)),
        3: Scenario(tuple(runs("p200_eur")), request(P2)),
        4: Scenario(tuple(runs("p200_eur")), request(P2, currency="EUR")),
        5: Scenario(tuple(runs("stale")), p12),
        6: Scenario(tuple(runs("proposed")), p12),
        7: Scenario(tuple(runs("at020", "proposed")), p12),
        8: Scenario(tuple(runs("at020", "withdrawal")), p12),
        9: Scenario(tuple(runs("at020", "version_conflict")), p12),
        10: Scenario(tuple(runs("at020", "spoofed")), p12),
        11: Scenario(tuple(runs("spoofed", "at020")), p12),
        12: Scenario(tuple(runs("unknown_actor")), p12),
        13: Scenario(tuple(runs("eac_conflict")), p12),
        14: Scenario(tuple(runs("reconciliation_failure")), p12),
        15: Scenario(
            tuple(runs("at020", "second_system")),
            p12,
            mappings=(*DEFAULT_MAPPINGS, mapping("SYN-P-100", P1, system=FIN_C)),
        ),
        16: Scenario(tuple(runs("partial_export")), p12),
        17: Scenario(tuple(runs("tampered_body")), p12),
        18: Scenario(tuple(runs("duplicate_identity")), p12),
        19: Scenario(tuple(runs("at020")), p12, designations=()),
        20: Scenario(tuple(runs("at020")), request(P1, P2, period="2026-09")),
        21: Scenario(tuple(runs("at020")), request(P1, P2, perspective=CONTRACT)),
        22: Scenario(tuple(runs("at020")), request(P1, P2, cost_basis=CostBasis.NET)),
        23: Scenario(
            tuple(runs("at020")),
            p12,
            mappings=(
                *_without("SYN-P-200"),
                mapping("SYN-P-200", P2, state=MappingState.PROPOSED),
            ),
        ),
        24: Scenario(
            tuple(runs("at020")),
            p12,
            mappings=(
                *DEFAULT_MAPPINGS,
                mapping("SYN-P-200", P2, revision=2, state=MappingState.QUARANTINED),
            ),
        ),
        25: Scenario(
            tuple(runs("at020")), p12, mappings=(*DEFAULT_MAPPINGS, mapping("SYN-P-201", P2))
        ),
        26: Scenario(tuple(runs("at020")), p12, mappings=_without("SYN-P-200")),
        27: Scenario(tuple(runs("at020")), request(P1, P2, P3)),
        28: Scenario(tuple(runs("at020")), request(P1, P2, unresolved_members=1)),
        29: Scenario(tuple(runs("rounding_edges")), request(P3)),
        30: Scenario((), request(P1)),
        31: Scenario(tuple(runs("spoofed", "at020", "spoofed_b", "at020")), p12),
        32: Scenario(tuple(runs("spoofed", "at020", "spoofed_b")), p12),
        33: Scenario(tuple(runs("at020", "partial_export")), request(P1, P2, period="2026-09")),
        34: Scenario(tuple(runs("cycle_a", "cycle_b")), p12),
        35: Scenario(tuple(runs("at020", "withdrawal_dangling")), p12),
        36: Scenario(tuple(runs("at020")), request(P1, P2, membership_truncated=True)),
        37: Scenario(tuple(runs("at020")), request(P1, P2, source_cutoff="2026-10-30T00:00:00Z")),
        38: Scenario(
            tuple(runs("at020", "version_conflict")), p12, quarantine=frozenset({"syn-run-2"})
        ),
        39: Scenario(tuple(runs("at020", "spoofed")), p12, quarantine=frozenset({"syn-run-2"})),
        40: Scenario(
            tuple(runs("at020", "version_conflict_late")),
            request(P1, P2, source_cutoff="2026-11-15T00:00:00Z"),
        ),
        41: Scenario(
            tuple(runs("at020", "p300_second_system")),
            request(P1, P3),
            mappings=(mapping("SYN-P-100", P1), mapping("SYN-P-300", P3, system=FIN_C)),
        ),
        42: Scenario(tuple(runs("at020", "spoofed", "period_2026_11")), p12),
        43: Scenario(
            tuple(runs("at020", "spoofed", "period_2026_11")), request(P1, P2, period="2026-11")
        ),
    }
    return table[number]
