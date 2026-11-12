"""Financial controlled source F-1: the synthetic interchange parser (contract section 7).

Every committed fixture is parsed: each admitted file must reproduce the content
digest of the version the I11-A domain builder constructs (hash parity across
the 2 packages, F1-D30), and each refused file must refuse with the code in its
name at the line the manifest records. Limits no committed fixture reaches
(`too_large`, `too_many_rows`, `line_too_long`) are generated in-test under
injected limits, and the file half of the seeded body-mutation property
(F1-D31) runs here. Together they reach every one of the 50 refusal codes.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import random
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.project_controls.financial.canonical import (
    loads_canonical,
    source_content_sha256,
    source_version_object,
)
from my_pa.domain.project_controls.financial.model import (
    FinanceParseOutcome,
    FinanceParseRefusalCode,
    LegSide,
)
from my_pa.infrastructure.financial import synthetic_csv
from my_pa.infrastructure.financial.synthetic_csv import (
    HEADER_COLUMNS,
    PRODUCTION_LIMITS,
    FinanceParseLimits,
    parse_synthetic_finance,
)
from tests.fixtures.financial_domain import VERSIONS

FIXTURES: Final = Path(__file__).resolve().parents[1] / "fixtures" / "financial_source"
#: Section 8.2 base file; its content digest is pinned by I11-A (F1-D30).
BASE: Final = "syn_at020_owner_budget.csv"
AT020_CONTENT_SHA256: Final = "ae7b8de3bc2551718b6bf40d3e99457cec6e28e4b8661d4af68529a545a73e07"
#: Codes no committed fixture can carry; each is reached by a test below.
IN_TEST_CODES: Final = frozenset({"too_large", "too_many_rows", "line_too_long"})
SEEDS: Final = range(200)

_C = FinanceParseRefusalCode


def _manifest() -> dict[str, dict[str, object]]:
    manifest = loads_canonical((FIXTURES / "manifest.json").read_bytes())
    assert isinstance(manifest, dict)
    files = manifest["files"]
    assert isinstance(files, dict)
    return files


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _parse(name: str) -> FinanceParseOutcome:
    return parse_synthetic_finance(_read(name))


def _refusal(outcome: FinanceParseOutcome) -> tuple[str | None, int | None]:
    assert outcome.admitted is None
    assert outcome.refusal_code is not None
    return outcome.refusal_code.value, outcome.refusal_line


# --- in-test mutation helpers (the writer is never called by a test) ------------------


def _lines(data: bytes) -> list[str]:
    text = data.decode("ascii")
    assert text.endswith("\n")
    return text[:-1].split("\n")


def _assemble(lines: list[str]) -> bytes:
    """Recompute both row counts and `body_sha256` over the given lines."""
    lines = list(lines)
    count = str(len(lines) - 4)
    end = lines[-1].split(",")
    end[HEADER_COLUMNS.index("row_count")] = count
    lines[-1] = ",".join(end)
    body = ("\n".join(lines[3:]) + "\n").encode("ascii")
    header = lines[2].split(",")
    header[HEADER_COLUMNS.index("row_count")] = count
    header[HEADER_COLUMNS.index("body_sha256")] = hashlib.sha256(body).hexdigest()
    lines[2] = ",".join(header)
    return ("\n".join(lines) + "\n").encode("ascii")


def _with_cells(data: bytes, number: int, **cells: str) -> list[str]:
    lines = _lines(data)
    row = lines[number - 1].split(",")
    for column, value in cells.items():
        row[HEADER_COLUMNS.index(column)] = value
    lines[number - 1] = ",".join(row)
    return lines


def _mutated(number: int, **cells: str) -> bytes:
    """The base file with cells of line `number` changed, counts and hash recomputed."""
    return _assemble(_with_cells(_read(BASE), number, **cells))


# --- section 12.1 tests ---------------------------------------------------------------


def test_valid_fixture_parses_to_its_golden_version() -> None:
    admitted = {
        name: entry for name, entry in _manifest().items() if entry["outcome"] == "admitted"
    }
    assert len(admitted) == 20
    for name, entry in admitted.items():
        data = _read(name)
        outcome = parse_synthetic_finance(data)
        assert outcome.refusal_code is None and outcome.refusal_line is None, name
        assert outcome.admitted is not None
        assert outcome.file_sha256 == hashlib.sha256(data).hexdigest() == entry["file_sha256"]
        golden = VERSIONS[str(entry["domain_key"])]
        assert source_version_object(outcome.admitted) == source_version_object(golden), name
        assert source_content_sha256(outcome.admitted) == entry["content_sha256"], name
        assert source_content_sha256(golden) == entry["content_sha256"], name
    base = _parse(BASE).admitted
    assert base is not None
    assert source_content_sha256(base) == AT020_CONTENT_SHA256
    assert base == VERSIONS["at020"]


def test_each_malformed_fixture_refuses_with_its_code() -> None:
    refused = {name: entry for name, entry in _manifest().items() if entry["outcome"] == "refused"}
    malformed = sorted(name for name in refused if name.startswith("malformed/"))
    assert len(malformed) == 52 and len(refused) == 55
    reached: set[str] = set()
    mismatches: list[str] = []
    for name in sorted(refused):
        entry = refused[name]
        expected = (entry["refusal_code"], entry["refusal_line"])
        if name in malformed:
            assert entry["refusal_code"] == Path(name).name.split("__", 1)[0], name
        actual = _refusal(_parse(name))
        if actual != expected:
            mismatches.append(f"{name}: {actual} != {expected}")
        reached.add(str(actual[0]))
    assert mismatches == []
    assert reached | IN_TEST_CODES == {code.value for code in FinanceParseRefusalCode}
    assert len(FinanceParseRefusalCode) == 50


def test_refusal_carries_code_and_line_only() -> None:
    assert [f.name for f in fields(FinanceParseOutcome)] == [
        "admitted",
        "refusal_code",
        "refusal_line",
        "file_sha256",
    ]
    for name, secret in (
        ("malformed/formula_injection__equals.csv", "=SYN-CC-1"),
        ("malformed/amount_scale__base.csv", "1000000.00001"),
        ("malformed/identifier_grammar__space.csv", "SYN CC"),
        ("syn_duplicate_identity.csv", "SYN-L-099"),
    ):
        outcome = _parse(name)
        assert outcome.admitted is None
        assert isinstance(outcome.refusal_code, FinanceParseRefusalCode)
        assert type(outcome.refusal_line) is int
        assert secret not in repr(outcome)
        assert "SYN" not in repr(outcome)
    # No exception raised while handling another chains it (`raise ... from None`).
    tree = ast.parse(inspect.getsource(synthetic_csv))
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
    assert len(handlers) == 3
    for handler in handlers:
        for node in ast.walk(handler):
            if isinstance(node, ast.Raise):
                assert isinstance(node.cause, ast.Constant) and node.cause.value is None


def test_oversized_input_is_refused_before_decoding() -> None:
    limit = PRODUCTION_LIMITS.max_bytes
    assert limit == 4194304
    oversized = b"\xc3\x96" + b"a" * (limit - 1)
    assert len(oversized) == limit + 1
    assert _refusal(parse_synthetic_finance(oversized)) == ("too_large", None)
    base = _read(BASE)
    tight = FinanceParseLimits(len(base) - 1, 20000, 1024, 64)
    assert _refusal(parse_synthetic_finance(base, limits=tight)) == ("too_large", None)
    exact = FinanceParseLimits(len(base), 20000, 1024, 64)
    assert parse_synthetic_finance(base, limits=exact).admitted is not None
    assert _refusal(parse_synthetic_finance(b"")) == ("empty_input", None)


def test_too_many_rows_under_an_injected_limit() -> None:
    assert FinanceParseLimits(4194304, 20000, 1024, 64) == PRODUCTION_LIMITS
    base = _read(BASE)
    records = len(_lines(base)) - 2  # the source_version, 15 records and the end line
    assert records == 17
    over = FinanceParseLimits(PRODUCTION_LIMITS.max_bytes, records - 1, 1024, 64)
    assert _refusal(parse_synthetic_finance(base, limits=over)) == ("too_many_rows", None)
    at = FinanceParseLimits(PRODUCTION_LIMITS.max_bytes, records, 1024, 64)
    assert parse_synthetic_finance(base, limits=at).admitted is not None
    lengths = [len(line) for line in _lines(base)]
    longest = max(lengths)
    short = FinanceParseLimits(PRODUCTION_LIMITS.max_bytes, 20000, longest - 1, 64)
    expected_line = lengths.index(longest) + 1
    assert _refusal(parse_synthetic_finance(base, limits=short)) == (
        "line_too_long",
        expected_line,
    )
    fits = FinanceParseLimits(PRODUCTION_LIMITS.max_bytes, 20000, longest, 64)
    assert parse_synthetic_finance(base, limits=fits).admitted is not None
    # A production-size line bomb on line 4 (no fixture reaches the 1024-byte bound).
    bomb = _lines(base)
    bomb[3] = bomb[3] + "A" * 1024
    assert _refusal(parse_synthetic_finance(_assemble(bomb))) == ("line_too_long", 4)
    with pytest.raises(ValueError):
        FinanceParseLimits(0, 1, 1, 1)
    with pytest.raises(TypeError):
        FinanceParseLimits(True, 1, 1, 1)


def test_formula_injection_is_refused_in_text_cells_only() -> None:
    for prefix in ("equals", "plus", "minus", "at"):
        name = f"malformed/formula_injection__{prefix}.csv"
        assert _refusal(_parse(name)) == ("formula_injection", 4)
    # Every non-amount text column refuses a formula, on line 3 as on a record line.
    assert _refusal(parse_synthetic_finance(_mutated(3, approved_by="@syn-approver-1"))) == (
        "formula_injection",
        3,
    )
    assert _refusal(parse_synthetic_finance(_mutated(17, transfer_ref="+SYN-T-1"))) == (
        "formula_injection",
        17,
    )
    assert _refusal(parse_synthetic_finance(_mutated(4, external_project_id="=SYN-P-100"))) == (
        "formula_injection",
        4,
    )
    # The amount column is grammar-only: a formula there is an amount_grammar refusal.
    for text in ("=1+1", "+5", "@SUM(A1)", "=1000000"):
        assert _refusal(parse_synthetic_finance(_mutated(4, amount=text))) == (
            "amount_grammar",
            4,
        )
    assert _refusal(_parse("malformed/amount_grammar__formula.csv")) == ("amount_grammar", 4)


def test_a_negative_amount_is_not_a_formula() -> None:
    version = _parse(BASE).admitted
    assert version is not None
    (transfer,) = version.transfers
    assert transfer.debit.leg_side is LegSide.DEBIT
    assert transfer.debit.amount == Decimal("-150000.0000")
    # A deductive change order is a legitimate negative amount too.
    deductive = parse_synthetic_finance(_mutated(15, amount="-25000.0000")).admitted
    assert deductive is not None
    (order,) = (o for o in deductive.change_orders if o.ref == "SYN-CO-1")
    assert order.amount == Decimal("-25000.0000")


def test_partial_export_is_rejected_whole() -> None:
    assert _refusal(_parse("malformed/partial_export__count.csv")) == ("partial_export", 3)
    assert _refusal(_parse("malformed/partial_export__no_final_lf.csv")) == ("partial_export", 19)
    assert _refusal(_parse("syn_partial_export.csv")) == ("partial_export", 18)
    base = _lines(_read(BASE))
    # An early `end` record: everything before it is still refused.
    early = [*base[:10], base[-1], *base[10:]]
    assert _refusal(parse_synthetic_finance(_assemble(early))) == ("partial_export", 11)
    # The end line's own count disagrees with the actual count.
    wrong_end = [*base[:-1], base[-1].replace(",15,", ",14,")]
    assert _refusal(parse_synthetic_finance(("\n".join(wrong_end) + "\n").encode())) == (
        "partial_export",
        19,
    )
    # A file cut after its header or after line 3.
    for cut in (1, 2, 3):
        data = ("\n".join(base[:cut]) + "\n").encode()
        assert _refusal(parse_synthetic_finance(data)) == ("partial_export", cut)


def test_tampered_body_is_a_hash_mismatch() -> None:
    tampered = _read("syn_tampered_body.csv")
    base = _read(BASE)
    assert len(tampered) == len(base)
    assert [i for i, (a, b) in enumerate(zip(tampered, base, strict=True)) if a != b] == [
        base.index(b"400000.0000,,,,,") + 10
    ]
    assert _refusal(parse_synthetic_finance(tampered)) == ("hash_mismatch", 3)


def test_parser_raises_only_type_error_for_non_bytes() -> None:
    data = _read(BASE)
    for value in (data.decode("ascii"), bytearray(data), memoryview(data), None, 0):
        with pytest.raises(TypeError):
            parse_synthetic_finance(value)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        parse_synthetic_finance(data, limits=(1, 2, 3, 4))  # type: ignore[arg-type]


def test_period_is_data_never_ingest_time() -> None:
    first = _parse(BASE)
    assert first.admitted is not None and first.admitted.period == "2026-10"
    later = _parse("syn_period_2026_11.csv").admitted
    assert later is not None and later.period == "2026-11"
    assert parse_synthetic_finance(_read(BASE)) == first  # a pure function of the bytes
    # No clock is read anywhere in the parser.
    tree = ast.parse(inspect.getsource(synthetic_csv))
    clock = {"now", "utcnow", "today", "time", "monotonic", "perf_counter"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in clock, node.attr
        if isinstance(node, ast.Import | ast.ImportFrom):
            modules = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
            assert "time" not in modules


def test_end_line_cells_are_validated() -> None:
    base = _lines(_read(BASE))

    def end_with(**cells: str) -> bytes:
        row = base[-1].split(",")
        for column, value in cells.items():
            row[HEADER_COLUMNS.index(column)] = value
        return ("\n".join([*base[:-1], ",".join(row)]) + "\n").encode()

    assert _refusal(parse_synthetic_finance(end_with(ref="SYN-L-END"))) == ("cell_not_empty", 19)
    assert _refusal(parse_synthetic_finance(end_with(amount="=1+1"))) == ("cell_not_empty", 19)
    assert _refusal(parse_synthetic_finance(end_with(currency="USD"))) == ("cell_not_empty", 19)
    # An end count outside the count grammar cannot equal the actual count.
    assert _refusal(parse_synthetic_finance(end_with(row_count="015"))) == ("partial_export", 19)
    assert _refusal(parse_synthetic_finance(end_with(row_count=""))) == ("partial_export", 19)


def test_transfer_leg_sign_is_not_masked_by_amount_sign() -> None:
    assert _refusal(_parse("malformed/transfer_leg_sign__base.csv")) == ("transfer_leg_sign", 18)
    assert _refusal(_parse("malformed/amount_sign__base.csv")) == ("amount_sign", 6)
    # A debit leg's negative amount is valid; only account lines carry amount_sign.
    assert _parse(BASE).admitted is not None


# --- F1-D31: the file half of the seeded body-mutation property ------------------------


def test_seeded_file_body_mutations_are_refused() -> None:
    base = _read(BASE)
    body_start = base.index(b"\n", base.index(b"\n", base.index(b"\n") + 1) + 1) + 1
    codes: set[str] = set()
    for seed in SEEDS:
        rng = random.Random(seed)  # noqa: S311 - deterministic test data, not a secret
        position = rng.randrange(body_start, len(base))
        replacement = rng.choice([b for b in range(256) if b != base[position]])
        mutated = base[:position] + bytes([replacement]) + base[position + 1 :]
        outcome = parse_synthetic_finance(mutated)
        assert outcome.admitted is None, seed  # never admitted under the declared hash
        assert outcome.refusal_code is not None
        codes.add(outcome.refusal_code.value)
    assert "hash_mismatch" in codes
