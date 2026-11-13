"""Financial controlled source F-1: writer of the synthetic fixtures and their manifest (I11-B).

Contract `docs/architecture/financial-source-contract.md` section 8. Regeneration
is explicit only::

    PYTHONPATH=src python -m tests.fixtures.financial_source_writer write

It writes every file under `tests/fixtures/financial_source/` and the manifest,
and prints each path with its digest. **No test calls the writer**
(`tests/unit/test_financial_source_fixtures.py` pins the files byte for byte and
asserts by `ast` that no other module under `tests/` imports this one).

Every admitted file is the `my-pa-synthetic-finance-v1` rendering of the
section 8.3 version the I11-A domain builder (`tests/fixtures/financial_domain.py`)
already constructs, so the parser must reproduce the domain content digests.
Each refused or malformed case is the section 8.2 base with exactly 1 named
mutation; `body_sha256` and `row_count` are recomputed after it unless the
mutation targets them, or unless it is a byte-level mutation of the assembled
file. The expected refusal line of every case is written here from the
mutation's position (not computed by the parser) and recorded in the manifest.
The manifest's scenario goldens come from the domain evaluation of section 8.5
(`financial_domain.scenario`), so they are independent of the parser too.

Everything is synthetic: every identifier starts with `syn-` / `SYN-`; the
format imitates no real export.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from my_pa.domain.project_controls.financial.canonical import (
    format_timestamp,
    overview_sha256,
    source_content_sha256,
)
from my_pa.domain.project_controls.financial.model import (
    LegSide,
    SourceVersion,
)
from my_pa.domain.project_controls.financial.money import format_amount
from my_pa.infrastructure.financial.synthetic_csv import BOM, FORMAT_NAME, HEADER_COLUMNS
from tests.fixtures.financial_domain import VERSIONS, scenario

ROOT: Final = Path(__file__).resolve().parent / "financial_source"
MANIFEST: Final = ROOT / "manifest.json"

#: Section 8.3: domain builder key -> fixture file name (admitted by the parser).
ADMITTED_FILES: Final[dict[str, str]] = {
    "at020": "syn_at020_owner_budget.csv",
    "contract": "syn_contract_perspective.csv",
    "p200_eur": "syn_p200_eur.csv",
    "stale": "syn_stale_approval.csv",
    "proposed": "syn_proposed.csv",
    "withdrawal": "syn_withdrawal.csv",
    "version_conflict": "syn_version_conflict.csv",
    "spoofed": "syn_spoofed_system.csv",
    "unknown_actor": "syn_unknown_actor.csv",
    "eac_conflict": "syn_eac_conflict.csv",
    "reconciliation_failure": "syn_reconciliation_failure.csv",
    "second_system": "syn_second_system.csv",
    "rounding_edges": "syn_rounding_edges.csv",
    "spoofed_b": "syn_spoofed_system_b.csv",
    "cycle_a": "syn_cycle_a.csv",
    "cycle_b": "syn_cycle_b.csv",
    "withdrawal_dangling": "syn_withdrawal_dangling.csv",
    "version_conflict_late": "syn_version_conflict_late.csv",
    "p300_second_system": "syn_p300_second_system.csv",
    "period_2026_11": "syn_period_2026_11.csv",
}
#: Section 8.3: domain builder key -> fixture file name (refused by the parser).
REFUSED_FILES: Final[dict[str, str]] = {
    "partial_export": "syn_partial_export.csv",
    "tampered_body": "syn_tampered_body.csv",
    "duplicate_identity": "syn_duplicate_identity.csv",
}

Row = dict[str, str]


def _blank(record_type: str) -> Row:
    row = dict.fromkeys(HEADER_COLUMNS, "")
    row["record_type"] = record_type
    return row


def _header_row(version: SourceVersion) -> Row:
    row = _blank("source_version")
    row.update(
        source_system=version.source_system,
        source_version_ref=version.source_version_ref,
        period=version.period,
        cutoff_at=format_timestamp(version.cutoff_at),
        status=version.status.value,
        approved_by=version.approved_by or "",
        approved_at="" if version.approved_at is None else format_timestamp(version.approved_at),
        supersedes_ref=version.supersedes_ref or "",
        perspective=version.perspective.value,
        currency=version.currency,
        cost_basis=version.cost_basis.value,
    )
    return row


def _body_rows(version: SourceVersion) -> list[Row]:
    """Account lines, change orders, then each transfer's debit and credit leg."""
    rows: list[Row] = []
    for line in version.account_lines:
        row = _blank("account_line")
        row.update(
            ref=line.ref,
            currency=version.currency,
            external_project_id=line.external_project_id,
            external_contract_id=line.external_contract_id or "",
            cost_code=line.cost_code,
            wbs_package=line.wbs_package,
            measure=line.measure.value,
            amount=format_amount(line.amount),
        )
        rows.append(row)
    for order in version.change_orders:
        row = _blank("change_order")
        row.update(
            ref=order.ref,
            currency=version.currency,
            external_project_id=order.external_project_id,
            external_contract_id=order.external_contract_id or "",
            cost_code=order.cost_code,
            wbs_package=order.wbs_package,
            amount=format_amount(order.amount),
            change_status=order.change_status.value,
        )
        rows.append(row)
    for transfer in version.transfers:
        for leg in (transfer.debit, transfer.credit):
            row = _blank("transfer_leg")
            row.update(
                ref=leg.ref,
                currency=version.currency,
                external_project_id=leg.external_project_id,
                cost_code=transfer.cost_code,
                wbs_package=transfer.wbs_package,
                amount=format_amount(leg.amount),
                change_status=transfer.change_status.value,
                transfer_ref=transfer.transfer_ref,
                leg_side=leg.leg_side.value,
            )
            rows.append(row)
    return rows


@dataclass
class Draft:
    """A file before assembly: every cell is text and may be mutated."""

    format_line: str
    header: list[str]
    version_row: Row
    body: list[Row]
    #: When set, line 3 keeps this `row_count` instead of the recomputed one.
    row_count: str | None = None
    #: Applied to line 3's `body_sha256` after it is computed.
    digest_text: Callable[[str], str] | None = None


def draft(version: SourceVersion) -> Draft:
    return Draft(FORMAT_NAME, list(HEADER_COLUMNS), _header_row(version), _body_rows(version))


def _line(row: Row) -> str:
    return ",".join(row[column] for column in HEADER_COLUMNS)


def assemble(item: Draft) -> bytes:
    """Render a draft; `row_count` and `body_sha256` are computed over the final body."""
    end = _blank("end")
    end["row_count"] = str(len(item.body))
    body = "".join(_line(row) + "\n" for row in [*item.body, end]).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    header = dict(item.version_row)
    header["row_count"] = item.row_count if item.row_count is not None else str(len(item.body))
    header["body_sha256"] = digest if item.digest_text is None else item.digest_text(digest)
    preamble = f"{item.format_line}\n{','.join(item.header)}\n{_line(header)}\n"
    return preamble.encode("utf-8") + body


def base() -> Draft:
    """Section 8.2: the AT-020 base file as a draft."""
    return draft(VERSIONS["at020"])


def _row(item: Draft, ref: str) -> Row:
    (row,) = (row for row in item.body if row["ref"] == ref)
    return row


def _lines(data: bytes) -> list[bytes]:
    return data.split(b"\n")


def _join(lines: list[bytes]) -> bytes:
    return b"\n".join(lines)


# --- section 8.3 refused named files ------------------------------------------------


def _partial_export() -> bytes:
    lines = _lines(assemble(base()))  # [..., end, b""]
    del lines[-2]
    return _join(lines)


def _tampered_body() -> bytes:
    data = assemble(base())
    old = b",SYN-L-003,"
    lines = _lines(data)
    (index,) = (i for i, line in enumerate(lines) if old in line)
    lines[index] = lines[index].replace(b",400000.0000,", b",400000.0001,")
    return _join(lines)


def _duplicate_identity() -> bytes:
    item = base()
    extra = dict(_row(item, "SYN-L-001"))
    extra.update(ref="SYN-L-099", amount="1.0000")
    item.body.append(extra)
    return assemble(item)


#: `file name -> (bytes, code, line)` for the 3 refused named files.
def refused_files() -> dict[str, tuple[bytes, str, int | None]]:
    return {
        REFUSED_FILES["partial_export"]: (_partial_export(), "partial_export", 18),
        REFUSED_FILES["tampered_body"]: (_tampered_body(), "hash_mismatch", 3),
        REFUSED_FILES["duplicate_identity"]: (_duplicate_identity(), "duplicate_identity", 19),
    }


# --- section 8.4 malformed cases ----------------------------------------------------

Mutation = Callable[[Draft], None]


def _cell(target: str, /, **cells: str) -> Mutation:
    def mutate(item: Draft) -> None:
        _row(item, target).update(cells)

    return mutate


def _version(**cells: str) -> Mutation:
    def mutate(item: Draft) -> None:
        item.version_row.update(cells)

    return mutate


def _all_currencies(code: str) -> Mutation:
    def mutate(item: Draft) -> None:
        item.version_row["currency"] = code
        for row in item.body:
            row["currency"] = code

    return mutate


def _cell_case(mutation: Mutation) -> bytes:
    item = base()
    mutation(item)
    return assemble(item)


def _format_v2(item: Draft) -> None:
    item.format_line = "my-pa-synthetic-finance-v2"


def _duplicate_column(item: Draft) -> None:
    item.header[1] = "record_type"


def _swap_header(item: Draft) -> None:
    item.header[1], item.header[2] = item.header[2], item.header[1]


def _count_14(item: Draft) -> None:
    item.row_count = "14"


def _count_015(item: Draft) -> None:
    item.row_count = "015"


def _digest_upper(item: Draft) -> None:
    item.digest_text = str.upper


def _source_version_copy(item: Draft) -> None:
    item.body.insert(0, dict(item.version_row))


def _drop_credit_leg(item: Draft) -> None:
    item.body.remove(_row(item, "SYN-TL-1C"))


def _crlf() -> bytes:
    return assemble(base()).replace(b"\n", b"\r\n")


def _no_final_lf() -> bytes:
    return assemble(base())[:-1]


def _swap_lines_3_4() -> bytes:
    lines = _lines(assemble(base()))
    lines[2], lines[3] = lines[3], lines[2]
    return _join(lines)


_CELL_CASES: Final[dict[str, tuple[Mutation, int]]] = {
    "non_ascii__cell": (_cell("SYN-L-001", wbs_package="SYN-WBS-CÖNC"), 4),
    "control_character__tab": (_cell("SYN-L-001", ref="\tSYN-L-001"), 4),
    "quote_character__quoted": (_cell("SYN-L-001", ref='"SYN-L-001"'), 4),
    "partial_export__count": (_count_14, 3),
    "format_unrecognized__base": (_format_v2, 1),
    "duplicate_column__base": (_duplicate_column, 2),
    "header_mismatch__order": (_swap_header, 2),
    "field_count__thousands": (_cell("SYN-L-001", amount="1,000,000.0000"), 4),
    "cell_too_long__base": (_cell("SYN-L-001", wbs_package="SYN-" + "A" * 61), 4),
    "source_version_duplicate__base": (_source_version_copy, 4),
    "record_type_unknown__base": (_cell("SYN-L-001", record_type="account_lines"), 4),
    "cell_missing__cost_code": (_cell("SYN-L-001", cost_code=""), 4),
    "cell_not_empty__measure": (_cell("SYN-CO-1", measure="actual_cost"), 15),
    "formula_injection__equals": (_cell("SYN-L-001", cost_code="=SYN-CC-1"), 4),
    "formula_injection__plus": (_cell("SYN-L-001", cost_code="+SYN-CC-1"), 4),
    "formula_injection__minus": (_cell("SYN-L-001", cost_code="-SYN-CC-1"), 4),
    "formula_injection__at": (_cell("SYN-L-001", cost_code="@SYN-CC-1"), 4),
    "identifier_grammar__space": (_cell("SYN-L-001", cost_code="SYN CC"), 4),
    "amount_grammar__exponent": (_cell("SYN-L-001", amount="1e6"), 4),
    "amount_grammar__plus": (_cell("SYN-L-001", amount="+1000000.0000"), 4),
    "amount_grammar__leading_zero": (_cell("SYN-L-001", amount="01000000.0000"), 4),
    "amount_grammar__formula": (_cell("SYN-L-001", amount="=1000000"), 4),
    "amount_negative_zero__base": (_cell("SYN-CO-1", amount="-0.0000"), 15),
    "amount_scale__base": (_cell("SYN-L-001", amount="1000000.00001"), 4),
    "amount_range__base": (_cell("SYN-L-001", amount="10000000000000000.0000"), 4),
    "amount_sign__base": (_cell("SYN-L-003", amount="-400000.0000"), 6),
    "period_grammar__base": (_version(period="2026-13"), 3),
    "timestamp_grammar__offset": (_version(cutoff_at="2026-10-31T23:59:59+00:00"), 3),
    "enum_value__perspective": (_version(perspective="owner-budget"), 3),
    "currency_grammar__lowercase": (_version(currency="usd"), 3),
    "currency_unknown__base": (_all_currencies("XTS"), 3),
    "count_grammar__base": (_count_015, 3),
    "digest_grammar__base": (_digest_upper, 3),
    "line_currency_mismatch__base": (_cell("SYN-L-001", currency="EUR"), 4),
    "cutoff_before_period__base": (_version(cutoff_at="2026-09-30T23:59:59Z"), 3),
    "measure_perspective_mismatch__base": (_cell("SYN-L-001", measure="original_contract"), 4),
    "duplicate_ref__base": (_cell("SYN-L-002", ref="SYN-L-001"), 5),
    "transfer_leg_count__base": (_drop_credit_leg, 17),
    "transfer_leg_sides__base": (_cell("SYN-TL-1C", leg_side=LegSide.DEBIT.value), 18),
    "transfer_scope_mismatch__base": (_cell("SYN-TL-1C", wbs_package="SYN-WBS-STEEL"), 18),
    "transfer_same_project__base": (_cell("SYN-TL-1C", external_project_id="SYN-P-100"), 18),
    "transfer_status_mismatch__base": (_cell("SYN-TL-1C", change_status="pending"), 18),
    "transfer_unbalanced__base": (_cell("SYN-TL-1C", amount="149999.9999"), 18),
    "change_order_zero__base": (_cell("SYN-CO-2", amount="0.0000"), 16),
    "withdrawal_has_rows__base": (
        _version(status="withdrawn", supersedes_ref="SYN-V-2026-10-0"),
        3,
    ),
    "supersedes_self__base": (_version(supersedes_ref="SYN-V-2026-10-A"), 3),
}


def _leg_sign(item: Draft) -> None:
    _row(item, "SYN-TL-1D")["amount"] = "150000.0000"
    _row(item, "SYN-TL-1C")["amount"] = "-150000.0000"


def malformed_files() -> dict[str, tuple[bytes, str, int | None]]:
    """`malformed/<code>__<variant>.csv -> (bytes, code, line)`: the 52 section 8.4 cases."""
    cases: dict[str, tuple[bytes, int | None]] = {
        "empty_input__base": (b"", None),
        "bom_present__base": (BOM + assemble(base()), 1),
        "carriage_return__crlf": (_crlf(), 1),
        "partial_export__no_final_lf": (_no_final_lf(), 19),
        "source_version_not_first__base": (_swap_lines_3_4(), 3),
        "transfer_leg_sign__base": (_cell_case(_leg_sign), 18),
    }
    for name, (mutation, line) in _CELL_CASES.items():
        cases[name] = (_cell_case(mutation), line)
    return {
        f"malformed/{name}.csv": (data, name.split("__", 1)[0], line)
        for name, (data, line) in sorted(cases.items())
    }


# --- manifest ---------------------------------------------------------------------


def admitted_files() -> dict[str, bytes]:
    return {name: assemble(draft(VERSIONS[key])) for key, name in ADMITTED_FILES.items()}


def _scenario_goldens() -> dict[str, dict[str, object]]:
    goldens: dict[str, dict[str, object]] = {}
    for number in range(1, 44):
        overview = scenario(number).evaluate()
        goldens[f"S{number:02d}"] = {
            "overview_sha256": overview_sha256(overview),
            "program_reasons": [reason.value for reason in overview.program_reasons],
            "reasons": [reason.value for reason in overview.reasons],
            "reportability": overview.reportability.value,
        }
    return goldens


def _entry(data: bytes) -> dict[str, object]:
    return {"file_sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def fixture_files() -> dict[str, bytes]:
    """Every fixture file (relative path -> bytes), the manifest excluded."""
    files = dict(admitted_files())
    files.update({name: data for name, (data, _, _) in refused_files().items()})
    files.update({name: data for name, (data, _, _) in malformed_files().items()})
    return files


def manifest_bytes() -> bytes:
    entries: dict[str, dict[str, object]] = {}
    for key, name in ADMITTED_FILES.items():
        data = assemble(draft(VERSIONS[key]))
        entries[name] = {
            **_entry(data),
            "content_sha256": source_content_sha256(VERSIONS[key]),
            "domain_key": key,
            "outcome": "admitted",
        }
    domain_keys = {name: key for key, name in REFUSED_FILES.items()}
    for name, (data, code, line) in {**refused_files(), **malformed_files()}.items():
        entries[name] = {
            **_entry(data),
            **({"domain_key": domain_keys[name]} if name in domain_keys else {}),
            "outcome": "refused",
            "refusal_code": code,
            "refusal_line": line,
        }
    manifest = {
        "files": entries,
        "format": FORMAT_NAME,
        "scenarios": _scenario_goldens(),
        "synthetic": "every identifier is syn-/SYN-; no real finance source (OD-06)",
    }
    return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "ascii"
    )


def write() -> None:
    """Write every fixture file and the manifest; print each path and its digest."""
    (ROOT / "malformed").mkdir(parents=True, exist_ok=True)
    outputs = {**fixture_files(), "manifest.json": manifest_bytes()}
    for name, data in sorted(outputs.items()):
        path = ROOT / name
        path.write_bytes(data)
        sys.stdout.write(f"{path.relative_to(ROOT.parent)} {hashlib.sha256(data).hexdigest()}\n")


def main(argv: list[str]) -> int:
    if argv != ["write"]:
        sys.stderr.write("usage: python -m tests.fixtures.financial_source_writer write\n")
        return 2
    write()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
