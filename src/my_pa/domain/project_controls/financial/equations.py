"""Financial controlled source F-1: the equations (contract section 4).

Per-Project figures over 1 effective version, the owner-budget reconciliation
identity, Program consolidation with internal-transfer elimination, and the
cross-version double-count rule. All arithmetic is exact (`money_sum`,
`add_amounts`, `subtract_amounts` under `FINANCE_CONTEXT`); nothing is rounded.
A result outside `NUMERIC(20,4)` becomes `aggregate_out_of_range`, never a clamp.
Absence of a balance measure is `measure_not_reported`, never a zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from my_pa.domain.program.vocabulary import MetricValueState
from my_pa.domain.project_controls.financial.model import (
    METRICS_BY_PERSPECTIVE,
    AccountMeasure,
    ChangeStatus,
    CostBasis,
    EacBasis,
    FinancialMetric,
    FinancialMetricValue,
    FinancialNotReportableReason,
    FinancialPerspective,
    LegSide,
    SourceVersion,
    TransferElimination,
)
from my_pa.domain.project_controls.financial.money import (
    add_amounts,
    is_storable_amount,
    money_sum,
    subtract_amounts,
)

__all__ = [
    "FinancialInvariantError",
    "ProjectComputation",
    "ScopedAmount",
    "compute_project",
    "consolidate_metric",
    "external_transfer_amounts",
    "internal_transfers",
    "not_reportable",
    "owner_budget_reconciles",
    "project_has_rows",
    "repeats_a_ref_across_versions",
    "reported_or_out_of_range",
    "revised_contract_of",
    "variance_of",
]

_R = FinancialNotReportableReason
_M = FinancialMetric

#: Section 4.1: balance metrics and the measure each sums.
_BALANCE_MEASURES: dict[FinancialMetric, AccountMeasure] = {
    _M.ORIGINAL_BUDGET: AccountMeasure.ORIGINAL_BUDGET,
    _M.CURRENT_BUDGET: AccountMeasure.CURRENT_BUDGET,
    _M.ORIGINAL_CONTRACT: AccountMeasure.ORIGINAL_CONTRACT,
    _M.ACTUAL_COST: AccountMeasure.ACTUAL_COST,
    _M.FORECAST_COST_TO_COMPLETE: AccountMeasure.FORECAST_COST_TO_COMPLETE,
    _M.COMMITTED_COST: AccountMeasure.COMMITTED_COST,
    _M.CONTINGENCY: AccountMeasure.CONTINGENCY,
    _M.ALLOWANCE: AccountMeasure.ALLOWANCE,
}


class FinancialInvariantError(RuntimeError):
    """A violated arithmetic invariant (a bug, never a reportability reason)."""


# --- metric values ------------------------------------------------------------------


def not_reportable(metric: FinancialMetric, reasons: Iterable[_R]) -> FinancialMetricValue:
    """A `null` value with its sorted, unique reasons."""
    return FinancialMetricValue(
        metric, None, MetricValueState.NOT_REPORTABLE, tuple(sorted(set(reasons)))
    )


def reported_or_out_of_range(metric: FinancialMetric, value: Decimal) -> FinancialMetricValue:
    """Reported when `value` fits `NUMERIC(20,4)`, else `aggregate_out_of_range`."""
    if not is_storable_amount(value):
        return not_reportable(metric, (_R.AGGREGATE_OUT_OF_RANGE,))
    return FinancialMetricValue(metric, value, MetricValueState.REPORTED, ())


def _is_reported(value: FinancialMetricValue) -> bool:
    return value.value_state is MetricValueState.REPORTED


# --- the pure equations ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScopedAmount:
    """An amount with the version scope it was computed in (section 4.4)."""

    period: str
    perspective: FinancialPerspective
    cost_basis: CostBasis
    currency: str
    amount: Decimal

    @property
    def scope(self) -> tuple[str, FinancialPerspective, CostBasis, str]:
        return (self.period, self.perspective, self.cost_basis, self.currency)


def revised_contract_of(original_contract: Decimal, approved_changes: Decimal) -> Decimal:
    """Section 4.2: `original_contract + approved_changes` (pending never enters)."""
    return add_amounts(original_contract, approved_changes)


def variance_of(approved_current: ScopedAmount, eac: ScopedAmount) -> Decimal:
    """Section 4.4: `approved_current - eac`, only within 1 version scope."""
    if approved_current.scope != eac.scope:
        raise ValueError("variance is defined only within 1 version scope")
    return subtract_amounts(approved_current.amount, eac.amount)


def owner_budget_reconciles(
    original_budget: Decimal,
    current_budget: Decimal,
    approved_changes: Decimal,
    transfer_net: Decimal,
) -> bool:
    """Section 4.5: `current == original + approved changes + transfer_net`, exactly."""
    return current_budget == money_sum((original_budget, approved_changes, transfer_net))


# --- per-Project figures (sections 4.1-4.5) -------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProjectComputation:
    """The figures of 1 Project in 1 effective version, before any project reason nulls them."""

    metrics: tuple[FinancialMetricValue, ...]
    eac_basis: EacBasis | None
    reconciliation_failed: bool


def project_has_rows(version: SourceVersion, external_project_id: str) -> bool:
    """Whether the version has any line, change order or leg of the external Project."""
    return (
        any(line.external_project_id == external_project_id for line in version.account_lines)
        or any(order.external_project_id == external_project_id for order in version.change_orders)
        or any(
            leg.external_project_id == external_project_id
            for transfer in version.transfers
            for leg in transfer.legs
        )
    )


def _combine(
    metric: FinancialMetric, terms: Sequence[FinancialMetricValue]
) -> FinancialMetricValue | None:
    """The union of the terms' reasons when any term is not reported, else `None`."""
    reasons = {reason for term in terms for reason in term.reasons}
    if all(_is_reported(term) for term in terms):
        return None
    return not_reportable(metric, reasons)


def _amount(value: FinancialMetricValue) -> Decimal:
    if value.value is None:
        raise FinancialInvariantError("a reported metric carries its value")
    return value.value


def compute_project(version: SourceVersion, external_project_id: str) -> ProjectComputation:
    """Every section 4.1 metric of the version's perspective for 1 external Project."""
    e = external_project_id
    lines: dict[AccountMeasure, list[Decimal]] = {}
    for line in version.account_lines:
        if line.external_project_id == e:
            lines.setdefault(line.measure, []).append(line.amount)
    orders = [order for order in version.change_orders if order.external_project_id == e]
    legs = [
        (transfer.change_status, leg)
        for transfer in version.transfers
        for leg in transfer.legs
        if leg.external_project_id == e
    ]
    approved_legs = [leg for status, leg in legs if status is ChangeStatus.APPROVED]

    raw: dict[FinancialMetric, Decimal | None] = {
        metric: (money_sum(lines[measure]) if measure in lines else None)
        for metric, measure in _BALANCE_MEASURES.items()
    }
    raw[_M.APPROVED_CHANGES] = money_sum(
        o.amount for o in orders if o.change_status is ChangeStatus.APPROVED
    )
    raw[_M.PENDING_CHANGES] = money_sum(
        o.amount for o in orders if o.change_status is ChangeStatus.PENDING
    )
    raw[_M.TRANSFER_NET] = money_sum(leg.amount for leg in approved_legs)
    raw[_M.TRANSFERS_IN] = money_sum(
        leg.amount for leg in approved_legs if leg.leg_side is LegSide.CREDIT
    )
    raw[_M.TRANSFERS_OUT] = money_sum(
        leg.amount.copy_abs() for leg in approved_legs if leg.leg_side is LegSide.DEBIT
    )
    raw[_M.PENDING_TRANSFER_NET] = money_sum(
        leg.amount for status, leg in legs if status is ChangeStatus.PENDING
    )

    values: dict[FinancialMetric, FinancialMetricValue] = {}
    for metric, amount in raw.items():
        if amount is None:
            values[metric] = not_reportable(metric, (_R.MEASURE_NOT_REPORTED,))
        else:
            values[metric] = reported_or_out_of_range(metric, amount)

    # Section 4.2: revised contract.
    terms = (values[_M.ORIGINAL_CONTRACT], values[_M.APPROVED_CHANGES])
    values[_M.REVISED_CONTRACT] = _combine(_M.REVISED_CONTRACT, terms) or (
        reported_or_out_of_range(
            _M.REVISED_CONTRACT, revised_contract_of(_amount(terms[0]), _amount(terms[1]))
        )
    )

    # Section 4.3: EAC on exclusive bases.
    present = {
        measure
        for measure in (
            AccountMeasure.ACTUAL_COST,
            AccountMeasure.FORECAST_COST_TO_COMPLETE,
            AccountMeasure.SOURCE_EAC,
        )
        if measure in lines
    }
    eac_basis: EacBasis | None = None
    if {AccountMeasure.SOURCE_EAC, AccountMeasure.FORECAST_COST_TO_COMPLETE} <= present:
        values[_M.EAC] = not_reportable(_M.EAC, (_R.EAC_BASIS_CONFLICT,))
    elif AccountMeasure.SOURCE_EAC in present:
        eac_basis = EacBasis.SOURCE
        values[_M.EAC] = reported_or_out_of_range(
            _M.EAC, money_sum(lines[AccountMeasure.SOURCE_EAC])
        )
    elif {AccountMeasure.ACTUAL_COST, AccountMeasure.FORECAST_COST_TO_COMPLETE} <= present:
        eac_basis = EacBasis.COMPUTED
        terms = (values[_M.ACTUAL_COST], values[_M.FORECAST_COST_TO_COMPLETE])
        values[_M.EAC] = _combine(_M.EAC, terms) or reported_or_out_of_range(
            _M.EAC, add_amounts(_amount(terms[0]), _amount(terms[1]))
        )
    else:
        values[_M.EAC] = not_reportable(_M.EAC, (_R.EAC_INCOMPLETE,))
    if not _is_reported(values[_M.EAC]):
        eac_basis = None

    # Section 4.4: variance within the version's 1 scope.
    current_metric = (
        _M.CURRENT_BUDGET
        if version.perspective is FinancialPerspective.OWNER_BUDGET
        else _M.REVISED_CONTRACT
    )
    terms = (values[current_metric], values[_M.EAC])
    combined = _combine(_M.VARIANCE, terms)
    if combined is None:

        def scoped(amount: Decimal) -> ScopedAmount:
            return ScopedAmount(
                version.period, version.perspective, version.cost_basis, version.currency, amount
            )

        combined = reported_or_out_of_range(
            _M.VARIANCE, variance_of(scoped(_amount(terms[0])), scoped(_amount(terms[1])))
        )
    values[_M.VARIANCE] = combined

    # Section 4.5: owner-budget reconciliation.
    reconciliation_failed = False
    original, current = raw[_M.ORIGINAL_BUDGET], raw[_M.CURRENT_BUDGET]
    approved, transfer_net = raw[_M.APPROVED_CHANGES], raw[_M.TRANSFER_NET]
    if (
        version.perspective is FinancialPerspective.OWNER_BUDGET
        and original is not None
        and current is not None
        and approved is not None
        and transfer_net is not None
    ):
        reconciliation_failed = not owner_budget_reconciles(
            original, current, approved, transfer_net
        )

    return ProjectComputation(
        metrics=tuple(values[m] for m in METRICS_BY_PERSPECTIVE[version.perspective]),
        eac_basis=eac_basis,
        reconciliation_failed=reconciliation_failed,
    )


# --- Program consolidation (sections 4.6, 4.7) -----------------------------------------------


def internal_transfers(
    version: SourceVersion,
    member_by_external_id: Mapping[str, str],
    source_content_sha256: str,
) -> tuple[TransferElimination, ...]:
    """Approved transfers whose 2 legs both map to member Projects, each listed once.

    `member_by_external_id` maps an external Project id of the version's system
    to the member Project it is the accepted mapping of. The legs of every
    internal transfer must sum to zero; a violation is a bug and raises.
    """
    eliminations = []
    internal_legs: list[Decimal] = []
    for transfer in version.transfers:
        if transfer.change_status is not ChangeStatus.APPROVED:
            continue
        target = member_by_external_id.get(transfer.credit.external_project_id)
        source = member_by_external_id.get(transfer.debit.external_project_id)
        if target is None or source is None:
            continue
        internal_legs += [transfer.credit.amount, transfer.debit.amount]
        eliminations.append(
            TransferElimination(
                transfer_ref=transfer.transfer_ref,
                source_project_id=source,
                target_project_id=target,
                cost_code=transfer.cost_code,
                wbs_package=transfer.wbs_package,
                amount=transfer.credit.amount,
                currency=version.currency,
                approved=True,
                source_content_sha256=source_content_sha256,
            )
        )
    if not money_sum(internal_legs).is_zero():
        raise FinancialInvariantError("internal transfer legs do not cancel")
    return tuple(sorted(eliminations, key=lambda e: e.transfer_ref))


def external_transfer_amounts(
    version: SourceVersion, external_project_id: str, internal_refs: frozenset[str]
) -> tuple[Decimal, Decimal]:
    """`(transfers_in, transfers_out)` of 1 Project counting only non-internal approved legs."""
    credit_amounts: list[Decimal] = []
    debit_amounts: list[Decimal] = []
    for transfer in version.transfers:
        if transfer.change_status is not ChangeStatus.APPROVED:
            continue
        if transfer.transfer_ref in internal_refs:
            continue
        for leg in transfer.legs:
            if leg.external_project_id != external_project_id:
                continue
            if leg.leg_side is LegSide.CREDIT:
                credit_amounts.append(leg.amount)
            else:
                debit_amounts.append(leg.amount.copy_abs())
    return money_sum(credit_amounts), money_sum(debit_amounts)


def consolidate_metric(
    metric: FinancialMetric,
    member_values: Sequence[FinancialMetricValue],
    program_reasons: Iterable[_R],
    contributions: Sequence[Decimal] | None = None,
) -> FinancialMetricValue:
    """Section 5.3 step 10: Σ members when all are reported and no program reason applies.

    `contributions` replaces the member values as the summands (Program
    `transfers_in` / `transfers_out` count only legs whose counterparty is
    outside the scope); the gate is always every member's own value.
    """
    reasons = set(program_reasons)
    for value in member_values:
        reasons.update(value.reasons)
    if reasons or not all(_is_reported(value) for value in member_values):
        return not_reportable(metric, reasons)
    summands = contributions if contributions is not None else [_amount(v) for v in member_values]
    return reported_or_out_of_range(metric, money_sum(summands))


def repeats_a_ref_across_versions(versions: Sequence[SourceVersion]) -> bool:
    """Section 4.7 program rule: a change-order ref or transfer ref in 2+ versions.

    The 2 ref kinds share 1 namespace, so a ref used as a change order in 1
    version and as a transfer in another is also a repeat.
    """
    seen: set[str] = set()
    for version in versions:
        refs = {order.ref for order in version.change_orders}
        refs |= {transfer.transfer_ref for transfer in version.transfers}
        if refs & seen:
            return True
        seen |= refs
    return False
