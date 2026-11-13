"""Financial controlled source F-1: canonical objects and SHA-256 digests (contract section 6).

The one encoder is the schedule package's `canonical_json_bytes` (sorted keys,
compact separators, ASCII, no NaN); every digest is
`sha256(schema + "\\n" + canonical)`. No canonical object holds a number for
money: amounts are `format_amount` strings, timestamps `YYYY-MM-DDTHH:MM:SSZ`,
enums their values, and lists are in a defined order, never insertion order.

`source_version_from_object` is the strict inverse of `source_version_object`:
exact key sets, closed values, amounts through `parse_amount`, every record
rebuilt through its constructor. Any refusal is `FinanceDecodeError`, whose
message carries nothing of the object. `loads_canonical` is the only JSON
decoding path: it refuses every JSON number with a fraction or exponent and
`NaN`/`Infinity`, so money can never arrive as a binary floating-point value.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final, NoReturn

from my_pa.domain.project_controls.financial.model import (
    AccountLine,
    AccountMeasure,
    ChangeOrder,
    ChangeStatus,
    CostBasis,
    FinancialMetricValue,
    FinancialOverview,
    FinancialPerspective,
    LegSide,
    PeriodSnapshot,
    ProjectFinancialFigures,
    ScopeTransfer,
    SourceVersion,
    SourceVersionStatus,
    TransferElimination,
    TransferLeg,
)
from my_pa.domain.project_controls.financial.money import AmountError, format_amount, parse_amount
from my_pa.domain.schedule.canonical import canonical_json_bytes

__all__ = [
    "OVERVIEW_SCHEMA",
    "SLICE_SCHEMA",
    "SOURCE_SCHEMA",
    "FinanceDecodeError",
    "format_timestamp",
    "loads_canonical",
    "overview_object",
    "overview_sha256",
    "period_snapshot",
    "slice_object",
    "source_content_sha256",
    "source_version_from_object",
    "source_version_object",
]

SOURCE_SCHEMA: Final = "my-pa-finance-source-v1"
SLICE_SCHEMA: Final = "my-pa-finance-slice-v1"
OVERVIEW_SCHEMA: Final = "my-pa-finance-overview-v1"

_TIMESTAMP: Final = re.compile(r"[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"

_VERSION_KEYS: Final = frozenset(
    {
        "source_system",
        "source_version_ref",
        "period",
        "cutoff_at",
        "status",
        "approved_by",
        "approved_at",
        "supersedes_ref",
        "perspective",
        "currency",
        "cost_basis",
        "account_lines",
        "change_orders",
        "transfers",
    }
)
_LINE_KEYS: Final = frozenset(
    {
        "ref",
        "external_project_id",
        "external_contract_id",
        "cost_code",
        "wbs_package",
        "measure",
        "amount",
    }
)
_ORDER_KEYS: Final = frozenset(
    {
        "ref",
        "external_project_id",
        "external_contract_id",
        "cost_code",
        "wbs_package",
        "change_status",
        "amount",
    }
)
_TRANSFER_KEYS: Final = frozenset(
    {"transfer_ref", "cost_code", "wbs_package", "change_status", "legs"}
)
_LEG_KEYS: Final = frozenset({"ref", "external_project_id", "leg_side", "amount"})


class FinanceDecodeError(ValueError):
    """The object is not a valid canonical finance object. No content in the message."""


def _digest(schema: str, payload: bytes) -> str:
    return hashlib.sha256(schema.encode("ascii") + b"\n" + payload).hexdigest()


def format_timestamp(value: datetime) -> str:
    """`YYYY-MM-DDTHH:MM:SSZ` of an aware UTC instant."""
    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def _optional_timestamp(value: datetime | None) -> str | None:
    return None if value is None else format_timestamp(value)


# --- source version (section 6.2) ---------------------------------------------------


def _line_object(line: AccountLine) -> dict[str, object]:
    return {
        "ref": line.ref,
        "external_project_id": line.external_project_id,
        "external_contract_id": line.external_contract_id,
        "cost_code": line.cost_code,
        "wbs_package": line.wbs_package,
        "measure": line.measure.value,
        "amount": format_amount(line.amount),
    }


def _order_object(order: ChangeOrder) -> dict[str, object]:
    return {
        "ref": order.ref,
        "external_project_id": order.external_project_id,
        "external_contract_id": order.external_contract_id,
        "cost_code": order.cost_code,
        "wbs_package": order.wbs_package,
        "change_status": order.change_status.value,
        "amount": format_amount(order.amount),
    }


def _leg_object(leg: TransferLeg) -> dict[str, object]:
    return {
        "ref": leg.ref,
        "external_project_id": leg.external_project_id,
        "leg_side": leg.leg_side.value,
        "amount": format_amount(leg.amount),
    }


def _transfer_object(transfer: ScopeTransfer) -> dict[str, object]:
    return {
        "transfer_ref": transfer.transfer_ref,
        "cost_code": transfer.cost_code,
        "wbs_package": transfer.wbs_package,
        "change_status": transfer.change_status.value,
        "legs": [_leg_object(leg) for leg in transfer.legs],
    }


def source_version_object(version: SourceVersion) -> dict[str, object]:
    """Section 6.2: exactly these keys; lines and orders by `ref`, transfers by `transfer_ref`."""
    return {
        "source_system": version.source_system,
        "source_version_ref": version.source_version_ref,
        "period": version.period,
        "cutoff_at": format_timestamp(version.cutoff_at),
        "status": version.status.value,
        "approved_by": version.approved_by,
        "approved_at": _optional_timestamp(version.approved_at),
        "supersedes_ref": version.supersedes_ref,
        "perspective": version.perspective.value,
        "currency": version.currency,
        "cost_basis": version.cost_basis.value,
        "account_lines": [
            _line_object(line) for line in sorted(version.account_lines, key=lambda x: x.ref)
        ],
        "change_orders": [
            _order_object(order) for order in sorted(version.change_orders, key=lambda x: x.ref)
        ],
        "transfers": [
            _transfer_object(transfer)
            for transfer in sorted(version.transfers, key=lambda x: x.transfer_ref)
        ],
    }


def source_content_sha256(version: SourceVersion) -> str:
    """The version's `content_sha256` (schema `my-pa-finance-source-v1`)."""
    return _digest(SOURCE_SCHEMA, canonical_json_bytes(source_version_object(version)))


# --- strict decoding ------------------------------------------------------------------


def _refuse() -> NoReturn:
    raise FinanceDecodeError("not a canonical finance object") from None


def _refuse_number(_text: str) -> NoReturn:
    raise FinanceDecodeError("a fractional or exponent JSON number is refused") from None


def _refuse_constant(_text: str) -> NoReturn:
    raise FinanceDecodeError("NaN and Infinity are refused") from None


def loads_canonical(data: bytes) -> object:
    """Section 6.2 / R11-N06: JSON decoding with refusing number-with-fraction and constants."""
    if type(data) is not bytes:
        raise TypeError("canonical JSON is decoded from bytes")
    try:
        text = data.decode("ascii")
        return json.loads(text, parse_float=_refuse_number, parse_constant=_refuse_constant)
    except FinanceDecodeError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        _refuse()


def _mapping(value: object, keys: frozenset[str]) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != keys:
        _refuse()
    return value


def _str(value: object) -> str:
    if type(value) is not str:
        _refuse()
    return value


def _optional_str(value: object) -> str | None:
    return None if value is None else _str(value)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        _refuse()
    return value


def _member[E: StrEnum](value: object, kind: type[E]) -> E:
    text = _str(value)
    try:
        return kind(text)
    except ValueError:
        _refuse()


def _timestamp(value: object) -> datetime:
    text = _str(value)
    if _TIMESTAMP.fullmatch(text) is None:
        _refuse()
    try:
        return datetime.strptime(text, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        _refuse()


def _optional_timestamp_of(value: object) -> datetime | None:
    return None if value is None else _timestamp(value)


def _amount_of(value: object) -> Decimal:
    try:
        return parse_amount(_str(value))
    except AmountError:
        _refuse()


def _line_of(value: object) -> AccountLine:
    obj = _mapping(value, _LINE_KEYS)
    return AccountLine(
        ref=_str(obj["ref"]),
        external_project_id=_str(obj["external_project_id"]),
        external_contract_id=_optional_str(obj["external_contract_id"]),
        cost_code=_str(obj["cost_code"]),
        wbs_package=_str(obj["wbs_package"]),
        measure=_member(obj["measure"], AccountMeasure),
        amount=_amount_of(obj["amount"]),
    )


def _order_of(value: object) -> ChangeOrder:
    obj = _mapping(value, _ORDER_KEYS)
    return ChangeOrder(
        ref=_str(obj["ref"]),
        external_project_id=_str(obj["external_project_id"]),
        external_contract_id=_optional_str(obj["external_contract_id"]),
        cost_code=_str(obj["cost_code"]),
        wbs_package=_str(obj["wbs_package"]),
        change_status=_member(obj["change_status"], ChangeStatus),
        amount=_amount_of(obj["amount"]),
    )


def _leg_of(value: object) -> TransferLeg:
    obj = _mapping(value, _LEG_KEYS)
    return TransferLeg(
        ref=_str(obj["ref"]),
        external_project_id=_str(obj["external_project_id"]),
        leg_side=_member(obj["leg_side"], LegSide),
        amount=_amount_of(obj["amount"]),
    )


def _transfer_of(value: object) -> ScopeTransfer:
    obj = _mapping(value, _TRANSFER_KEYS)
    legs = tuple(_leg_of(leg) for leg in _list(obj["legs"]))
    if len(legs) != 2:
        _refuse()
    return ScopeTransfer(
        transfer_ref=_str(obj["transfer_ref"]),
        cost_code=_str(obj["cost_code"]),
        wbs_package=_str(obj["wbs_package"]),
        change_status=_member(obj["change_status"], ChangeStatus),
        legs=(legs[0], legs[1]),
    )


def source_version_from_object(obj: object) -> SourceVersion:
    """The strict inverse of `source_version_object`; any deviation is `FinanceDecodeError`."""
    try:
        fields = _mapping(obj, _VERSION_KEYS)
        version = SourceVersion(
            source_system=_str(fields["source_system"]),
            source_version_ref=_str(fields["source_version_ref"]),
            period=_str(fields["period"]),
            cutoff_at=_timestamp(fields["cutoff_at"]),
            status=_member(fields["status"], SourceVersionStatus),
            approved_by=_optional_str(fields["approved_by"]),
            approved_at=_optional_timestamp_of(fields["approved_at"]),
            supersedes_ref=_optional_str(fields["supersedes_ref"]),
            perspective=_member(fields["perspective"], FinancialPerspective),
            currency=_str(fields["currency"]),
            cost_basis=_member(fields["cost_basis"], CostBasis),
            account_lines=tuple(_line_of(x) for x in _list(fields["account_lines"])),
            change_orders=tuple(_order_of(x) for x in _list(fields["change_orders"])),
            transfers=tuple(_transfer_of(x) for x in _list(fields["transfers"])),
        )
    except FinanceDecodeError:
        raise
    except (TypeError, ValueError):
        _refuse()
    if source_version_object(version) != obj:
        _refuse()  # non-canonical list order
    return version


# --- slice (section 6.3) -------------------------------------------------------------


def slice_object(version: SourceVersion, external_project_id: str) -> dict[str, object]:
    """Section 6.3: the section 6.2 record shapes filtered to 1 external Project."""
    legs = [
        (transfer, leg)
        for transfer in version.transfers
        for leg in transfer.legs
        if leg.external_project_id == external_project_id
    ]
    legs.sort(key=lambda pair: (pair[0].transfer_ref, pair[1].leg_side.value))
    return {
        "source_content_sha256": source_content_sha256(version),
        "external_project_id": external_project_id,
        "account_lines": [
            _line_object(line)
            for line in sorted(version.account_lines, key=lambda x: x.ref)
            if line.external_project_id == external_project_id
        ],
        "change_orders": [
            _order_object(order)
            for order in sorted(version.change_orders, key=lambda x: x.ref)
            if order.external_project_id == external_project_id
        ],
        "transfer_legs": [
            {
                "transfer_ref": transfer.transfer_ref,
                "change_status": transfer.change_status.value,
                "cost_code": transfer.cost_code,
                "wbs_package": transfer.wbs_package,
                "ref": leg.ref,
                "leg_side": leg.leg_side.value,
                "amount": format_amount(leg.amount),
            }
            for transfer, leg in legs
        ],
    }


def period_snapshot(version: SourceVersion, external_project_id: str) -> PeriodSnapshot:
    """Section 3.9: derive the snapshot of 1 version for 1 external Project."""
    obj = slice_object(version, external_project_id)
    return PeriodSnapshot(
        source_content_sha256=source_content_sha256(version),
        external_project_id=external_project_id,
        account_line_count=len(_list(obj["account_lines"])),
        change_order_count=len(_list(obj["change_orders"])),
        transfer_leg_count=len(_list(obj["transfer_legs"])),
        slice_sha256=_digest(SLICE_SCHEMA, canonical_json_bytes(obj)),
    )


# --- overview (section 6.4) ------------------------------------------------------------


def _metric_object(value: FinancialMetricValue) -> dict[str, object]:
    return {
        "metric": value.metric.value,
        "value": None if value.value is None else format_amount(value.value),
        "value_state": value.value_state.value,
        "reasons": [reason.value for reason in value.reasons],
    }


def _project_object(project: ProjectFinancialFigures) -> dict[str, object]:
    return {
        "project_id": project.project_id,
        "source_state": project.source_state.value,
        "reasons": [reason.value for reason in project.reasons],
        "source_content_sha256": project.source_content_sha256,
        "external_project_id": project.external_project_id,
        "eac_basis": None if project.eac_basis is None else project.eac_basis.value,
        "metrics": [_metric_object(metric) for metric in project.metrics],
    }


def _elimination_object(elimination: TransferElimination) -> dict[str, object]:
    return {
        "transfer_ref": elimination.transfer_ref,
        "source_project_id": elimination.source_project_id,
        "target_project_id": elimination.target_project_id,
        "cost_code": elimination.cost_code,
        "wbs_package": elimination.wbs_package,
        "amount": format_amount(elimination.amount),
        "currency": elimination.currency,
        "approved": elimination.approved,
        "source_content_sha256": elimination.source_content_sha256,
    }


def overview_object(overview: FinancialOverview) -> dict[str, object]:
    """Section 6.4: every section 5.4 field; values strings or `null`, lists ordered."""
    request = overview.request
    denominator = overview.denominator
    return {
        "calculation_version": overview.calculation_version,
        "request": {
            "project_ids": list(request.project_ids),
            "unresolved_members": request.unresolved_members,
            "membership_truncated": request.membership_truncated,
            "period": request.period,
            "perspective": request.perspective.value,
            "currency": request.currency,
            "cost_basis": request.cost_basis.value,
            "source_cutoff": _optional_timestamp(request.source_cutoff),
        },
        "reportability": overview.reportability.value,
        "reasons": [reason.value for reason in overview.reasons],
        "program_reasons": [reason.value for reason in overview.program_reasons],
        "quarantined_runs": list(overview.quarantined_runs),
        "program_metrics": [_metric_object(metric) for metric in overview.program_metrics],
        "projects": [_project_object(project) for project in overview.projects],
        "transfer_eliminations": [
            _elimination_object(elimination) for elimination in overview.transfer_eliminations
        ],
        "source_versions": list(overview.source_versions),
        "pending_source_versions": list(overview.pending_source_versions),
        "source_cutoff_at": _optional_timestamp(overview.source_cutoff_at),
        "denominator": {
            "member_projects": denominator.member_projects,
            "unresolved_members": denominator.unresolved_members,
            "projects_reportable": denominator.projects_reportable,
            "missing_source_count": denominator.missing_source_count,
            "refused_runs": denominator.refused_runs,
            "quarantined_runs": denominator.quarantined_runs,
            "projects_by_source_state": {
                state.value: count for state, count in denominator.projects_by_source_state
            },
        },
    }


def overview_sha256(overview: FinancialOverview) -> str:
    """The overview digest (schema `my-pa-finance-overview-v1`)."""
    return _digest(OVERVIEW_SCHEMA, canonical_json_bytes(overview_object(overview)))
