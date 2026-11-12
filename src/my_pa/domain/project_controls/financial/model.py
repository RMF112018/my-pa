"""Financial controlled source F-1: closed vocabularies and immutable records (sections 3, 5).

Every record is a frozen, slotted dataclass whose `__post_init__` enforces the
contract invariants; a failure raises `ValueError` (or `TypeError` for a wrong
type, including any non-`Decimal` amount) with a fixed message that carries no
field value. Money is `Decimal` with exponent -4 (`money.is_storable_amount`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType
from typing import Final

from my_pa.domain.program.vocabulary import MetricValueState
from my_pa.domain.project_controls.financial.money import currency_error, is_storable_amount

__all__ = [
    "CALCULATION_VERSION",
    "IDENTIFIER_PATTERN",
    "MAX_FINANCIAL_PROJECTS",
    "MEASURES_BY_PERSPECTIVE",
    "METRICS_BY_PERSPECTIVE",
    "PROJECT_ID_PATTERN",
    "SOURCE_STATE_PRECEDENCE",
    "AccountLine",
    "AccountMeasure",
    "AdmissionRefusalCode",
    "ChangeOrder",
    "ChangeStatus",
    "CostBasis",
    "EacBasis",
    "FinanceParseOutcome",
    "FinanceParseRefusalCode",
    "FinancialDenominator",
    "FinancialMetric",
    "FinancialMetricValue",
    "FinancialNotReportableReason",
    "FinancialOverview",
    "FinancialPerspective",
    "FinancialReportability",
    "FinancialScopeRequest",
    "FinancialSourceState",
    "LegSide",
    "MappingState",
    "MatchBasis",
    "PeriodSnapshot",
    "ProjectFinancialFigures",
    "ProjectMappingRevision",
    "RunOutcome",
    "ScopeTransfer",
    "SourceDesignation",
    "SourceRun",
    "SourceVersion",
    "SourceVersionStatus",
    "TransferElimination",
    "TransferLeg",
    "is_identifier",
    "period_start",
    "require_instant",
]


# --- closed vocabularies (section 3.2) -----------------------------------------------


class FinancialPerspective(StrEnum):
    OWNER_BUDGET = "owner_budget"
    CONSTRUCTION_CONTRACT = "construction_contract"


class CostBasis(StrEnum):
    GROSS = "gross"
    NET = "net"


class SourceVersionStatus(StrEnum):
    APPROVED = "approved"
    PROPOSED = "proposed"
    WITHDRAWN = "withdrawn"


class AccountMeasure(StrEnum):
    ORIGINAL_BUDGET = "original_budget"
    CURRENT_BUDGET = "current_budget"
    ORIGINAL_CONTRACT = "original_contract"
    ACTUAL_COST = "actual_cost"
    FORECAST_COST_TO_COMPLETE = "forecast_cost_to_complete"
    SOURCE_EAC = "source_eac"
    COMMITTED_COST = "committed_cost"
    CONTINGENCY = "contingency"
    ALLOWANCE = "allowance"


class ChangeStatus(StrEnum):
    APPROVED = "approved"
    PENDING = "pending"


class LegSide(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class MappingState(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class MatchBasis(StrEnum):
    """Section 3.8: the only basis is operator review -- never fuzzy, name or alias."""

    OPERATOR_REVIEW = "operator_review"


class RunOutcome(StrEnum):
    ADMITTED = "admitted"
    REFUSED = "refused"


class AdmissionRefusalCode(StrEnum):
    SOURCE_SYSTEM_MISMATCH = "source_system_mismatch"
    PERSPECTIVE_NOT_DESIGNATED = "perspective_not_designated"


class FinancialReportability(StrEnum):
    """The 07 `reportability` enum, verbatim."""

    REPORTABLE = "reportable"
    NOT_REPORTABLE = "not_reportable"
    SOURCE_NOT_INTEGRATED = "source_not_integrated"


class FinancialSourceState(StrEnum):
    """Section 5.2, in declaration order (the denominator's key order)."""

    EFFECTIVE = "effective"
    NOT_INTEGRATED = "not_integrated"
    INTEGRITY_GAP = "integrity_gap"
    MAPPING_GAP = "mapping_gap"
    APPROVAL_GAP = "approval_gap"
    SOURCE_GAP = "source_gap"


class FinancialMetric(StrEnum):
    """Section 4.1; declaration order is the canonical output order."""

    ORIGINAL_BUDGET = "original_budget"
    CURRENT_BUDGET = "current_budget"
    ORIGINAL_CONTRACT = "original_contract"
    APPROVED_CHANGES = "approved_changes"
    PENDING_CHANGES = "pending_changes"
    REVISED_CONTRACT = "revised_contract"
    TRANSFER_NET = "transfer_net"
    TRANSFERS_IN = "transfers_in"
    TRANSFERS_OUT = "transfers_out"
    PENDING_TRANSFER_NET = "pending_transfer_net"
    ACTUAL_COST = "actual_cost"
    FORECAST_COST_TO_COMPLETE = "forecast_cost_to_complete"
    EAC = "eac"
    VARIANCE = "variance"
    COMMITTED_COST = "committed_cost"
    CONTINGENCY = "contingency"
    ALLOWANCE = "allowance"


class FinancialNotReportableReason(StrEnum):
    """Section 5.1 (29 members); outputs always carry them sorted."""

    SOURCE_NOT_INTEGRATED = "source_not_integrated"
    MEMBERSHIP_UNRESOLVED = "membership_unresolved"
    MEMBERSHIP_TRUNCATED = "membership_truncated"
    MAPPING_MISSING = "mapping_missing"
    MAPPING_UNREVIEWED = "mapping_unreviewed"
    MAPPING_QUARANTINED = "mapping_quarantined"
    MAPPING_AMBIGUOUS = "mapping_ambiguous"
    SOURCE_VERSION_MISSING = "source_version_missing"
    MISSING_PROJECT = "missing_project"
    PERIOD_MISMATCH = "period_mismatch"
    PERSPECTIVE_MISMATCH = "perspective_mismatch"
    BASIS_MISMATCH = "basis_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    FX_MISSING = "fx_missing"
    APPROVAL_MISSING = "approval_missing"
    APPROVAL_STALE = "approval_stale"
    APPROVAL_ACTOR_UNRECOGNIZED = "approval_actor_unrecognized"
    WITHDRAWN_SOURCE = "withdrawn_source"
    SOURCE_VERSION_AMBIGUOUS = "source_version_ambiguous"
    SOURCE_VERSION_CONFLICT = "source_version_conflict"
    HASH_MISMATCH = "hash_mismatch"
    PARTIAL_EXPORT = "partial_export"
    SOURCE_REFUSED = "source_refused"
    SOURCE_RECONCILIATION_FAILED = "source_reconciliation_failed"
    DOUBLE_COUNT_DETECTED = "double_count_detected"
    MEASURE_NOT_REPORTED = "measure_not_reported"
    EAC_BASIS_CONFLICT = "eac_basis_conflict"
    EAC_INCOMPLETE = "eac_incomplete"
    AGGREGATE_OUT_OF_RANGE = "aggregate_out_of_range"


class FinanceParseRefusalCode(StrEnum):
    """Section 7.8 (50 members, closed): the synthetic parser's refusal taxonomy."""

    EMPTY_INPUT = "empty_input"
    TOO_LARGE = "too_large"
    BOM_PRESENT = "bom_present"
    NON_ASCII = "non_ascii"
    CARRIAGE_RETURN = "carriage_return"
    CONTROL_CHARACTER = "control_character"
    QUOTE_CHARACTER = "quote_character"
    PARTIAL_EXPORT = "partial_export"
    TOO_MANY_ROWS = "too_many_rows"
    LINE_TOO_LONG = "line_too_long"
    FORMAT_UNRECOGNIZED = "format_unrecognized"
    DUPLICATE_COLUMN = "duplicate_column"
    HEADER_MISMATCH = "header_mismatch"
    FIELD_COUNT = "field_count"
    CELL_TOO_LONG = "cell_too_long"
    SOURCE_VERSION_NOT_FIRST = "source_version_not_first"
    SOURCE_VERSION_DUPLICATE = "source_version_duplicate"
    RECORD_TYPE_UNKNOWN = "record_type_unknown"
    CELL_MISSING = "cell_missing"
    CELL_NOT_EMPTY = "cell_not_empty"
    FORMULA_INJECTION = "formula_injection"
    IDENTIFIER_GRAMMAR = "identifier_grammar"
    AMOUNT_GRAMMAR = "amount_grammar"
    AMOUNT_SCALE = "amount_scale"
    AMOUNT_RANGE = "amount_range"
    AMOUNT_NEGATIVE_ZERO = "amount_negative_zero"
    AMOUNT_SIGN = "amount_sign"
    PERIOD_GRAMMAR = "period_grammar"
    TIMESTAMP_GRAMMAR = "timestamp_grammar"
    ENUM_VALUE = "enum_value"
    CURRENCY_GRAMMAR = "currency_grammar"
    CURRENCY_UNKNOWN = "currency_unknown"
    COUNT_GRAMMAR = "count_grammar"
    DIGEST_GRAMMAR = "digest_grammar"
    HASH_MISMATCH = "hash_mismatch"
    LINE_CURRENCY_MISMATCH = "line_currency_mismatch"
    CUTOFF_BEFORE_PERIOD = "cutoff_before_period"
    MEASURE_PERSPECTIVE_MISMATCH = "measure_perspective_mismatch"
    DUPLICATE_REF = "duplicate_ref"
    DUPLICATE_IDENTITY = "duplicate_identity"
    TRANSFER_LEG_COUNT = "transfer_leg_count"
    TRANSFER_LEG_SIDES = "transfer_leg_sides"
    TRANSFER_LEG_SIGN = "transfer_leg_sign"
    TRANSFER_SCOPE_MISMATCH = "transfer_scope_mismatch"
    TRANSFER_SAME_PROJECT = "transfer_same_project"
    TRANSFER_STATUS_MISMATCH = "transfer_status_mismatch"
    TRANSFER_UNBALANCED = "transfer_unbalanced"
    CHANGE_ORDER_ZERO = "change_order_zero"
    WITHDRAWAL_HAS_ROWS = "withdrawal_has_rows"
    SUPERSEDES_SELF = "supersedes_self"


class EacBasis(StrEnum):
    """Section 4.3: the EAC basis disclosed per Project (`None` when no EAC)."""

    COMPUTED = "computed"
    SOURCE = "source"


# --- constants ---------------------------------------------------------------------

#: Section 5.4: the overview calculation version.
CALCULATION_VERSION: Final = "my-pa-finance-calc-v1"
#: Section 5.3: the S4 `MAX_PROGRAM_PROJECTS` cap (a test pins the equality).
MAX_FINANCIAL_PROJECTS: Final = 100
#: Section 7.5: every identifier cell.
IDENTIFIER_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
#: Section 3.8: a native Project id.
PROJECT_ID_PATTERN: Final = re.compile(r"prj_[A-Za-z0-9]{8,64}")
#: Section 7.5 (FR11-F01): the year is 1000-9999, so year 0000 is a grammar refusal.
_PERIOD: Final = re.compile(r"[1-9][0-9]{3}-(0[1-9]|1[0-2])")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")

_BOTH: Final = frozenset(FinancialPerspective)
_OWNER: Final = frozenset({FinancialPerspective.OWNER_BUDGET})
_CONTRACT: Final = frozenset({FinancialPerspective.CONSTRUCTION_CONTRACT})

#: Section 3.2: the perspectives each measure is valid for.
MEASURES_BY_PERSPECTIVE: Final[Mapping[AccountMeasure, frozenset[FinancialPerspective]]] = (
    MappingProxyType(
        {
            AccountMeasure.ORIGINAL_BUDGET: _OWNER,
            AccountMeasure.CURRENT_BUDGET: _OWNER,
            AccountMeasure.ORIGINAL_CONTRACT: _CONTRACT,
            AccountMeasure.ACTUAL_COST: _BOTH,
            AccountMeasure.FORECAST_COST_TO_COMPLETE: _BOTH,
            AccountMeasure.SOURCE_EAC: _BOTH,
            AccountMeasure.COMMITTED_COST: _BOTH,
            AccountMeasure.CONTINGENCY: _BOTH,
            AccountMeasure.ALLOWANCE: _BOTH,
        }
    )
)

_OWNER_ONLY_METRICS: Final = frozenset(
    {FinancialMetric.ORIGINAL_BUDGET, FinancialMetric.CURRENT_BUDGET}
)
_CONTRACT_ONLY_METRICS: Final = frozenset(
    {FinancialMetric.ORIGINAL_CONTRACT, FinancialMetric.REVISED_CONTRACT}
)

#: Section 4.1: the 15 metrics of each perspective, in catalogue order.
METRICS_BY_PERSPECTIVE: Final[Mapping[FinancialPerspective, tuple[FinancialMetric, ...]]] = (
    MappingProxyType(
        {
            FinancialPerspective.OWNER_BUDGET: tuple(
                m for m in FinancialMetric if m not in _CONTRACT_ONLY_METRICS
            ),
            FinancialPerspective.CONSTRUCTION_CONTRACT: tuple(
                m for m in FinancialMetric if m not in _OWNER_ONLY_METRICS
            ),
        }
    )
)

_R = FinancialNotReportableReason

#: Section 5.2: the first matching state wins; `effective` when no project reason.
SOURCE_STATE_PRECEDENCE: Final[tuple[tuple[FinancialSourceState, frozenset[_R]], ...]] = (
    (FinancialSourceState.NOT_INTEGRATED, frozenset({_R.SOURCE_NOT_INTEGRATED})),
    (
        FinancialSourceState.INTEGRITY_GAP,
        frozenset(
            {
                _R.HASH_MISMATCH,
                _R.PARTIAL_EXPORT,
                _R.SOURCE_REFUSED,
                _R.SOURCE_VERSION_CONFLICT,
                _R.SOURCE_VERSION_AMBIGUOUS,
                _R.SOURCE_RECONCILIATION_FAILED,
                _R.DOUBLE_COUNT_DETECTED,
            }
        ),
    ),
    (
        FinancialSourceState.MAPPING_GAP,
        frozenset(
            {
                _R.MAPPING_MISSING,
                _R.MAPPING_UNREVIEWED,
                _R.MAPPING_QUARANTINED,
                _R.MAPPING_AMBIGUOUS,
            }
        ),
    ),
    (
        FinancialSourceState.APPROVAL_GAP,
        frozenset({_R.APPROVAL_MISSING, _R.APPROVAL_STALE, _R.APPROVAL_ACTOR_UNRECOGNIZED}),
    ),
    (
        FinancialSourceState.SOURCE_GAP,
        frozenset(
            {
                _R.SOURCE_VERSION_MISSING,
                _R.MISSING_PROJECT,
                _R.PERIOD_MISMATCH,
                _R.PERSPECTIVE_MISMATCH,
                _R.BASIS_MISMATCH,
                _R.CURRENCY_MISMATCH,
                _R.FX_MISSING,
                _R.WITHDRAWN_SOURCE,
            }
        ),
    ),
)


# --- field checks --------------------------------------------------------------------


def is_identifier(value: object) -> bool:
    """Section 7.5 identifier grammar."""
    return type(value) is str and IDENTIFIER_PATTERN.fullmatch(value) is not None


def _identifier(value: object) -> None:
    if type(value) is not str:
        raise TypeError("identifier must be a string")
    if IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError("identifier outside the grammar")


def _optional_identifier(value: object) -> None:
    if value is not None:
        _identifier(value)


def _project_id(value: object) -> None:
    if type(value) is not str:
        raise TypeError("project id must be a string")
    if PROJECT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("project id outside the grammar")


def _sha256(value: object) -> None:
    if type(value) is not str:
        raise TypeError("digest must be a string")
    if _SHA256.fullmatch(value) is None:
        raise ValueError("digest is not lowercase hex SHA-256")


def _enum(value: object, kind: type[StrEnum]) -> None:
    if not isinstance(value, kind):
        raise TypeError("value is not a member of its closed vocabulary")


def _count(value: object, *, minimum: int = 0) -> None:
    if type(value) is not int:
        raise TypeError("count must be an int")
    if value < minimum:
        raise ValueError("count below its minimum")


def _amount(value: object) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError("amount must be a Decimal")
    if not is_storable_amount(value):
        raise ValueError("amount is not a storable NUMERIC(20,4) value")
    return value


def _period(value: object) -> None:
    if type(value) is not str:
        raise TypeError("period must be a string")
    if _PERIOD.fullmatch(value) is None:
        raise ValueError("period outside the grammar")


def _currency(value: object) -> None:
    if type(value) is not str:
        raise TypeError("currency must be a string")
    if currency_error(value) is not None:
        raise ValueError("currency is not a known ISO 4217 code")


def require_instant(value: object) -> datetime:
    """An aware UTC instant with whole seconds (the canonical timestamp precision)."""
    if type(value) is not datetime:
        raise TypeError("instant must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("instant must be aware UTC")
    if value.microsecond != 0:
        raise ValueError("instant must have whole seconds")
    if value.year < 1000:
        raise ValueError("instant year must have 4 digits")
    return value


def period_start(period: str) -> datetime:
    """The first instant (UTC) of a `YYYY-MM` period."""
    year, month = period.split("-")
    return datetime(int(year), int(month), 1, tzinfo=UTC)


def _sorted_unique(values: tuple[str, ...]) -> bool:
    return all(a < b for a, b in pairwise(values))


def _tuple_of(value: object, kind: type) -> tuple[object, ...]:
    if not isinstance(value, tuple) or type(value) is not tuple:
        raise TypeError("collection must be a tuple")
    for item in value:
        if type(item) is not kind:
            raise TypeError("collection item has the wrong type")
    return value


def _reasons(value: object) -> None:
    _tuple_of(value, FinancialNotReportableReason)
    if not _sorted_unique(value):  # type: ignore[arg-type]
        raise ValueError("reasons must be sorted and unique")


# --- source designation (section 3.4) -----------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceDesignation:
    """The operator's statement that `source_system` is authoritative (test input in F-1)."""

    source_system: str
    perspectives: frozenset[FinancialPerspective]
    approvers: frozenset[str]

    def __post_init__(self) -> None:
        _identifier(self.source_system)
        if type(self.perspectives) is not frozenset or type(self.approvers) is not frozenset:
            raise TypeError("perspectives and approvers must be frozensets")
        if not self.perspectives or not self.approvers:
            raise ValueError("a designation names at least 1 perspective and 1 approver")
        for perspective in self.perspectives:
            _enum(perspective, FinancialPerspective)
        for approver in self.approvers:
            _identifier(approver)


# --- lines, change orders, transfers (section 3.6) ------------------------------------


@dataclass(frozen=True, slots=True)
class AccountLine:
    ref: str
    external_project_id: str
    external_contract_id: str | None
    cost_code: str
    wbs_package: str
    measure: AccountMeasure
    amount: Decimal

    def __post_init__(self) -> None:
        for value in (self.ref, self.external_project_id, self.cost_code, self.wbs_package):
            _identifier(value)
        _optional_identifier(self.external_contract_id)
        _enum(self.measure, AccountMeasure)
        if _amount(self.amount) < 0:
            raise ValueError("an account line amount is never negative")

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        """Section 3.6: the account-line identity within a version."""
        return (
            self.external_project_id,
            self.external_contract_id or "",
            self.cost_code,
            self.wbs_package,
            self.measure.value,
        )


@dataclass(frozen=True, slots=True)
class ChangeOrder:
    ref: str
    external_project_id: str
    external_contract_id: str | None
    cost_code: str
    wbs_package: str
    change_status: ChangeStatus
    amount: Decimal

    def __post_init__(self) -> None:
        for value in (self.ref, self.external_project_id, self.cost_code, self.wbs_package):
            _identifier(value)
        _optional_identifier(self.external_contract_id)
        _enum(self.change_status, ChangeStatus)
        if _amount(self.amount).is_zero():
            raise ValueError("a change order amount is never zero")


@dataclass(frozen=True, slots=True)
class TransferLeg:
    ref: str
    external_project_id: str
    leg_side: LegSide
    amount: Decimal

    def __post_init__(self) -> None:
        _identifier(self.ref)
        _identifier(self.external_project_id)
        _enum(self.leg_side, LegSide)
        amount = _amount(self.amount)
        if self.leg_side is LegSide.DEBIT and not amount < 0:
            raise ValueError("a debit leg is negative")
        if self.leg_side is LegSide.CREDIT and not amount > 0:
            raise ValueError("a credit leg is positive")


@dataclass(frozen=True, slots=True)
class ScopeTransfer:
    """Exactly 2 legs ordered (credit, debit), different Projects, summing to zero."""

    transfer_ref: str
    cost_code: str
    wbs_package: str
    change_status: ChangeStatus
    legs: tuple[TransferLeg, TransferLeg]

    def __post_init__(self) -> None:
        for value in (self.transfer_ref, self.cost_code, self.wbs_package):
            _identifier(value)
        _enum(self.change_status, ChangeStatus)
        _tuple_of(self.legs, TransferLeg)
        if len(self.legs) != 2:
            raise ValueError("a transfer has exactly 2 legs")
        credit, debit = self.legs
        if credit.leg_side is not LegSide.CREDIT or debit.leg_side is not LegSide.DEBIT:
            raise ValueError("transfer legs are 1 credit then 1 debit")
        if credit.external_project_id == debit.external_project_id:
            raise ValueError("transfer legs name different Projects")
        if credit.amount.copy_abs() != debit.amount.copy_abs():
            raise ValueError("transfer legs sum to zero exactly")

    @property
    def credit(self) -> TransferLeg:
        return self.legs[0]

    @property
    def debit(self) -> TransferLeg:
        return self.legs[1]


# --- source version and run (section 3.5) ----------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceVersion:
    source_system: str
    source_version_ref: str
    period: str
    cutoff_at: datetime
    status: SourceVersionStatus
    approved_by: str | None
    approved_at: datetime | None
    supersedes_ref: str | None
    perspective: FinancialPerspective
    currency: str
    cost_basis: CostBasis
    account_lines: tuple[AccountLine, ...]
    change_orders: tuple[ChangeOrder, ...]
    transfers: tuple[ScopeTransfer, ...]

    def __post_init__(self) -> None:
        _identifier(self.source_system)
        _identifier(self.source_version_ref)
        _period(self.period)
        require_instant(self.cutoff_at)
        _enum(self.status, SourceVersionStatus)
        _optional_identifier(self.approved_by)
        if self.approved_at is not None:
            require_instant(self.approved_at)
        _optional_identifier(self.supersedes_ref)
        _enum(self.perspective, FinancialPerspective)
        _currency(self.currency)
        _enum(self.cost_basis, CostBasis)
        _tuple_of(self.account_lines, AccountLine)
        _tuple_of(self.change_orders, ChangeOrder)
        _tuple_of(self.transfers, ScopeTransfer)
        approval = (self.approved_by is not None, self.approved_at is not None)
        if self.status is SourceVersionStatus.PROPOSED:
            if approval != (False, False):
                raise ValueError("a proposed version carries no approval")
        elif approval != (True, True):
            raise ValueError("an approved or withdrawn version carries both approval fields")
        if self.status is SourceVersionStatus.WITHDRAWN:
            if self.supersedes_ref is None:
                raise ValueError("a withdrawal names the version it withdraws")
            if self.account_lines or self.change_orders or self.transfers:
                raise ValueError("a withdrawal carries no rows")
        if self.supersedes_ref == self.source_version_ref:
            raise ValueError("a version cannot supersede itself")
        if self.cutoff_at < period_start(self.period):
            raise ValueError("cutoff precedes the period")
        for line in self.account_lines:
            if self.perspective not in MEASURES_BY_PERSPECTIVE[line.measure]:
                raise ValueError("measure is not valid for the perspective")
        refs = [line.ref for line in self.account_lines]
        refs += [order.ref for order in self.change_orders]
        for transfer in self.transfers:
            refs += [transfer.transfer_ref, *(leg.ref for leg in transfer.legs)]
        if len(refs) != len(set(refs)):
            raise ValueError("refs are unique within a version")
        identities = [line.identity for line in self.account_lines]
        if len(identities) != len(set(identities)):
            raise ValueError("account-line identity is unique within a version")

    @property
    def scope_key(self) -> tuple[str, str, FinancialPerspective, str, CostBasis]:
        """Section 3.7: `(source_system, period, perspective, currency, cost_basis)`."""
        return (self.source_system, self.period, self.perspective, self.currency, self.cost_basis)


@dataclass(frozen=True, slots=True)
class SourceRun:
    run_ref: str
    run_sequence: int
    designated_source_system: str
    file_sha256: str
    outcome: RunOutcome
    refusal_code: FinanceParseRefusalCode | AdmissionRefusalCode | None
    refusal_line: int | None
    version: SourceVersion | None
    content_sha256: str | None

    def __post_init__(self) -> None:
        _identifier(self.run_ref)
        _count(self.run_sequence, minimum=1)
        _identifier(self.designated_source_system)
        _sha256(self.file_sha256)
        _enum(self.outcome, RunOutcome)
        if self.refusal_line is not None:
            _count(self.refusal_line, minimum=1)
        if self.outcome is RunOutcome.ADMITTED:
            if self.version is None or self.content_sha256 is None:
                raise ValueError("an admitted run carries its version and content digest")
            if self.refusal_code is not None or self.refusal_line is not None:
                raise ValueError("an admitted run carries no refusal")
            if type(self.version) is not SourceVersion:
                raise TypeError("version must be a SourceVersion")
            _sha256(self.content_sha256)
            if self.version.source_system != self.designated_source_system:
                raise ValueError("an admitted version belongs to the designated system")
        else:
            if self.refusal_code is None:
                raise ValueError("a refused run carries its refusal code")
            if not isinstance(self.refusal_code, FinanceParseRefusalCode | AdmissionRefusalCode):
                raise TypeError("refusal code is not a member of its closed vocabulary")
            if self.version is not None or self.content_sha256 is not None:
                raise ValueError("a refused run carries no version")


@dataclass(frozen=True, slots=True)
class FinanceParseOutcome:
    """Section 7.9: exactly 1 of an admitted version or a refusal code (+ line)."""

    admitted: SourceVersion | None
    refusal_code: FinanceParseRefusalCode | None
    refusal_line: int | None
    file_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.file_sha256)
        if (self.admitted is None) == (self.refusal_code is None):
            raise ValueError("a parse outcome is exactly 1 of admitted or refused")
        if self.admitted is not None:
            if type(self.admitted) is not SourceVersion:
                raise TypeError("admitted must be a SourceVersion")
            if self.refusal_line is not None:
                raise ValueError("an admitted outcome carries no refusal line")
        else:
            _enum(self.refusal_code, FinanceParseRefusalCode)
        if self.refusal_line is not None:
            _count(self.refusal_line, minimum=1)


# --- mapping (section 3.8) -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProjectMappingRevision:
    source_system: str
    external_project_id: str
    revision: int
    state: MappingState
    project_id: str | None
    match_basis: MatchBasis
    reviewed_by: str
    reviewed_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.source_system)
        _identifier(self.external_project_id)
        _count(self.revision, minimum=1)
        _enum(self.state, MappingState)
        _enum(self.match_basis, MatchBasis)
        _identifier(self.reviewed_by)
        require_instant(self.reviewed_at)
        if self.state is MappingState.REJECTED:
            if self.project_id is not None:
                raise ValueError("a rejected mapping names no Project")
        elif self.project_id is None:
            raise ValueError("a proposed, accepted or quarantined mapping names its Project")
        else:
            _project_id(self.project_id)

    @property
    def key(self) -> tuple[str, str]:
        return (self.source_system, self.external_project_id)


# --- period snapshot (section 3.9) ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class PeriodSnapshot:
    """Derived (never authored): one version's slice for one external Project."""

    source_content_sha256: str
    external_project_id: str
    account_line_count: int
    change_order_count: int
    transfer_leg_count: int
    slice_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.source_content_sha256)
        _identifier(self.external_project_id)
        _count(self.account_line_count)
        _count(self.change_order_count)
        _count(self.transfer_leg_count)
        _sha256(self.slice_sha256)


# --- the request and the overview (section 5) ----------------------------------------------


@dataclass(frozen=True, slots=True)
class FinancialScopeRequest:
    """Section 5.3: no threshold, tolerance or materiality field exists."""

    project_ids: tuple[str, ...]
    unresolved_members: int
    membership_truncated: bool
    period: str
    perspective: FinancialPerspective
    currency: str
    cost_basis: CostBasis
    source_cutoff: datetime | None

    def __post_init__(self) -> None:
        _tuple_of(self.project_ids, str)
        for project_id in self.project_ids:
            _project_id(project_id)
        if not 1 <= len(self.project_ids) <= MAX_FINANCIAL_PROJECTS:
            raise ValueError("a request names 1 to 100 Projects")
        if not _sorted_unique(self.project_ids):
            raise ValueError("request Projects are sorted and unique")
        _count(self.unresolved_members)
        if type(self.membership_truncated) is not bool:
            raise TypeError("membership_truncated must be a bool")
        _period(self.period)
        _enum(self.perspective, FinancialPerspective)
        _currency(self.currency)
        _enum(self.cost_basis, CostBasis)
        if self.source_cutoff is not None:
            require_instant(self.source_cutoff)


@dataclass(frozen=True, slots=True)
class FinancialMetricValue:
    """A reported value has no reason; a not-reportable value is `None` with reasons."""

    metric: FinancialMetric
    value: Decimal | None
    value_state: MetricValueState
    reasons: tuple[FinancialNotReportableReason, ...]

    def __post_init__(self) -> None:
        _enum(self.metric, FinancialMetric)
        _enum(self.value_state, MetricValueState)
        _reasons(self.reasons)
        if self.value_state is MetricValueState.REPORTED:
            _amount(self.value)
            if self.reasons:
                raise ValueError("a reported value carries no reason")
        else:
            if self.value is not None:
                raise ValueError("an unreported value is null, never a substitute")
            if self.value_state is MetricValueState.NOT_REPORTABLE and not self.reasons:
                raise ValueError("a not-reportable value names its reasons")


@dataclass(frozen=True, slots=True)
class ProjectFinancialFigures:
    project_id: str
    source_state: FinancialSourceState
    reasons: tuple[FinancialNotReportableReason, ...]
    source_content_sha256: str | None
    external_project_id: str | None
    eac_basis: EacBasis | None
    metrics: tuple[FinancialMetricValue, ...]

    def __post_init__(self) -> None:
        _project_id(self.project_id)
        _enum(self.source_state, FinancialSourceState)
        _reasons(self.reasons)
        if self.source_content_sha256 is not None:
            _sha256(self.source_content_sha256)
        _optional_identifier(self.external_project_id)
        if self.eac_basis is not None:
            _enum(self.eac_basis, EacBasis)
        _tuple_of(self.metrics, FinancialMetricValue)
        if (self.source_state is FinancialSourceState.EFFECTIVE) != (not self.reasons):
            raise ValueError("a Project is effective exactly when it has no project reason")


@dataclass(frozen=True, slots=True)
class TransferElimination:
    """Section 4.6: an internal approved transfer, listed once (F1-D12 fields)."""

    transfer_ref: str
    source_project_id: str
    target_project_id: str
    cost_code: str
    wbs_package: str
    amount: Decimal
    currency: str
    approved: bool
    source_content_sha256: str

    def __post_init__(self) -> None:
        for value in (self.transfer_ref, self.cost_code, self.wbs_package):
            _identifier(value)
        _project_id(self.source_project_id)
        _project_id(self.target_project_id)
        if not _amount(self.amount) > 0:
            raise ValueError("an elimination amount is the positive credit amount")
        _currency(self.currency)
        if self.approved is not True:
            raise ValueError("only an approved transfer is eliminated")
        _sha256(self.source_content_sha256)


@dataclass(frozen=True, slots=True)
class FinancialDenominator:
    member_projects: int
    unresolved_members: int
    projects_reportable: int
    missing_source_count: int
    refused_runs: int
    quarantined_runs: int
    projects_by_source_state: tuple[tuple[FinancialSourceState, int], ...]

    def __post_init__(self) -> None:
        for value in (
            self.member_projects,
            self.unresolved_members,
            self.projects_reportable,
            self.missing_source_count,
            self.refused_runs,
            self.quarantined_runs,
        ):
            _count(value)
        if tuple(state for state, _ in self.projects_by_source_state) != tuple(
            FinancialSourceState
        ):
            raise ValueError("the denominator counts every source state in declaration order")
        for _, count in self.projects_by_source_state:
            _count(count)
        if sum(count for _, count in self.projects_by_source_state) != self.member_projects:
            raise ValueError("every member Project is counted in exactly 1 source state")


@dataclass(frozen=True, slots=True)
class FinancialOverview:
    """Section 5.4."""

    calculation_version: str
    request: FinancialScopeRequest
    reportability: FinancialReportability
    reasons: tuple[FinancialNotReportableReason, ...]
    program_reasons: tuple[FinancialNotReportableReason, ...]
    quarantined_runs: tuple[str, ...]
    program_metrics: tuple[FinancialMetricValue, ...]
    projects: tuple[ProjectFinancialFigures, ...]
    transfer_eliminations: tuple[TransferElimination, ...]
    source_versions: tuple[str, ...]
    pending_source_versions: tuple[str, ...]
    source_cutoff_at: datetime | None
    denominator: FinancialDenominator

    def __post_init__(self) -> None:
        if self.calculation_version != CALCULATION_VERSION:
            raise ValueError("unknown calculation version")
        _enum(self.reportability, FinancialReportability)
        _reasons(self.reasons)
        _reasons(self.program_reasons)
        if not set(self.program_reasons) <= set(self.reasons):
            raise ValueError("program reasons are part of the reasons")
        for values in (self.quarantined_runs, self.source_versions, self.pending_source_versions):
            _tuple_of(values, str)
            if not _sorted_unique(values):
                raise ValueError("disclosure lists are sorted and unique")
        _tuple_of(self.program_metrics, FinancialMetricValue)
        _tuple_of(self.projects, ProjectFinancialFigures)
        if tuple(p.project_id for p in self.projects) != self.request.project_ids:
            raise ValueError("one figure set per requested Project, in request order")
        _tuple_of(self.transfer_eliminations, TransferElimination)
        refs = tuple(e.transfer_ref for e in self.transfer_eliminations)
        if not _sorted_unique(refs):
            raise ValueError("eliminations are sorted by transfer_ref and listed once")
        if self.source_cutoff_at is not None:
            require_instant(self.source_cutoff_at)
