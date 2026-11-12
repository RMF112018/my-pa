"""Financial controlled source F-1: seeded property tests (contract section 12.2).

`hypothesis` is not a dependency; as in the S6-1 CPM oracle, every property runs
over `random.Random(seed)` for seeds `range(200)`. Generators build valid
synthetic versions from the section 8 vocabulary: 2-6 Projects, 0-20 lines each,
0-5 transfers. Line amounts are integers of ten-thousandths drawn below 10^20
(so up to the `NUMERIC(20,4)` limit); transfer amounts are drawn below 10^19
ten-thousandths so 5 of them cannot leave the range and the balance property is
observable. Sampling, not proof (F1-U07).

`test_seeded_body_mutations_are_refused` is the domain half of the section 12.2
property: a single random byte change in the canonical bytes of a valid version
is either refused by the strict decoder or yields a different `content_sha256`,
and the evaluator then reports `hash_mismatch`. The file-body half (a byte change
in a parsed file under its declared `body_sha256`) needs the I11-B parser.
"""

from __future__ import annotations

import random
from dataclasses import replace
from decimal import Decimal
from typing import Final

from my_pa.domain.project_controls.financial.canonical import (
    FinanceDecodeError,
    loads_canonical,
    overview_sha256,
    source_content_sha256,
    source_version_from_object,
    source_version_object,
)
from my_pa.domain.project_controls.financial.equations import compute_project, project_has_rows
from my_pa.domain.project_controls.financial.model import (
    AccountLine,
    AccountMeasure,
    ChangeOrder,
    ChangeStatus,
    ScopeTransfer,
    SourceVersion,
)
from my_pa.domain.project_controls.financial.money import (
    format_amount,
    money_sum,
    parse_amount,
    presentation_amount,
)
from my_pa.domain.project_controls.financial.reportability import evaluate_financial_overview
from my_pa.domain.schedule.canonical import canonical_json_bytes
from tests.fixtures.financial_domain import (
    DESIGNATION_A,
    admit,
    evaluate,
    mapping,
    order,
    program,
    request,
    scenario,
    transfer,
    version,
)

SEEDS: Final = range(200)
LIMIT: Final = 10**20  # ten-thousandths: NUMERIC(20,4)
OWNER_MEASURES: Final = tuple(
    m for m in AccountMeasure if m is not AccountMeasure.ORIGINAL_CONTRACT
)
PENDING_METRICS: Final = frozenset({"pending_changes", "pending_transfer_net"})


def _rng(seed: int) -> random.Random:
    """A seeded, test-only generator (section 12.2); never security material."""
    return random.Random(seed)  # noqa: S311 - deterministic test data, not a secret


def _text(units: int) -> str:
    """An integer of ten-thousandths as its 4-place amount text."""
    sign = "-" if units < 0 else ""
    whole, fraction = divmod(abs(units), 10_000)
    return f"{sign}{whole}.{fraction:04d}"


def _projects(rng: random.Random) -> list[str]:
    return [f"SYN-P-{n}" for n in range(1, rng.randint(2, 6) + 1)]


def _lines(rng: random.Random, projects: list[str]) -> list[AccountLine]:
    lines = []
    for project in projects:
        for index in range(rng.randint(0, 20)):
            lines.append(
                AccountLine(
                    f"SYN-L-{project}-{index}",
                    project,
                    None,
                    f"SYN-CC-{index}",
                    "SYN-WBS",
                    rng.choice(OWNER_MEASURES),
                    parse_amount(_text(rng.randrange(0, LIMIT))),
                )
            )
    return lines


def _transfers(
    rng: random.Random, projects: list[str], status: ChangeStatus, prefix: str
) -> list[ScopeTransfer]:
    found = []
    for index in range(rng.randint(0, 5)):
        source, target = rng.sample(projects, 2)
        found.append(
            transfer(
                f"SYN-{prefix}-{index}",
                debit=(f"SYN-{prefix}-{index}-D", source),
                credit=(f"SYN-{prefix}-{index}-C", target),
                amount=_text(rng.randrange(1, LIMIT // 10)),
                status=status,
            )
        )
    return found


def _version(rng: random.Random) -> tuple[SourceVersion, list[str]]:
    projects = _projects(rng)
    lines = [
        line for line in _lines(rng, projects) if line.measure is not AccountMeasure.CURRENT_BUDGET
    ]
    chosen = version(
        lines=lines,
        orders=(),
        transfers=_transfers(rng, projects, ChangeStatus.APPROVED, "T"),
    )
    return chosen, projects


def test_seeded_balanced_transfers_consolidate_to_zero() -> None:
    for seed in SEEDS:
        rng = _rng(seed)
        chosen, projects = _version(rng)
        present = [p for p in projects if project_has_rows(chosen, p)]
        if len(present) < 2:
            continue
        native = {p: f"prj_SYNTHETIC{n:010d}" for n, p in enumerate(present, start=1)}
        overview = evaluate(
            [admit(chosen, 1)],
            request(*native.values()),
            mappings=tuple(mapping(p, native[p]) for p in present),
        )
        totals = program(overview)
        assert totals["transfer_net"] == "0.0000", seed
        assert totals["transfers_in"] == totals["transfers_out"] == "0.0000", seed
        refs = [e.transfer_ref for e in overview.transfer_eliminations]
        assert refs == sorted(t.transfer_ref for t in chosen.transfers), seed
        member_nets = [
            m.value
            for p in overview.projects
            for m in p.metrics
            if m.metric.value == "transfer_net"
        ]
        assert money_sum(v for v in member_nets if v is not None) == Decimal("0.0000"), seed


def test_seeded_pending_rows_never_move_approved_metrics() -> None:
    for seed in SEEDS:
        rng = _rng(seed)
        chosen, projects = _version(rng)
        pending_orders: list[ChangeOrder] = [
            order(
                f"SYN-CO-P{i}",
                rng.choice(projects),
                ChangeStatus.PENDING,
                _text(rng.randrange(1, LIMIT // 10)),
            )
            for i in range(rng.randint(1, 4))
        ]
        with_pending = replace(
            chosen,
            change_orders=(*chosen.change_orders, *pending_orders),
            transfers=(
                *chosen.transfers,
                *_transfers(rng, projects, ChangeStatus.PENDING, "PT"),
            ),
        )
        for project in projects:
            before = compute_project(chosen, project).metrics
            after = compute_project(with_pending, project).metrics
            for b, a in zip(before, after, strict=True):
                if b.metric.value not in PENDING_METRICS:
                    assert a == b, (seed, project, b.metric)


def test_seeded_amount_strings_round_trip() -> None:
    for seed in SEEDS:
        rng = _rng(seed)
        for _ in range(20):
            units = rng.randrange(-LIMIT + 1, LIMIT)
            canonical = _text(units)
            if canonical.startswith("-") and units == 0:
                continue
            short = canonical.rstrip("0").rstrip(".") if "." in canonical else canonical
            if short in ("", "-"):
                short = "0"
            for text in (canonical, short):
                if text == "-0":
                    continue
                value = parse_amount(text)
                assert format_amount(value) == canonical, (seed, text)
                assert format_amount(parse_amount(format_amount(value))) == canonical


def test_seeded_body_mutations_are_refused() -> None:
    base = scenario(1).runs[0]
    assert base.version is not None
    original = base.version
    encoded = canonical_json_bytes(source_version_object(original))
    content = source_content_sha256(original)
    for seed in SEEDS:
        rng = _rng(seed)
        position = rng.randrange(len(encoded))
        replacement = rng.choice([b for b in range(0x20, 0x7F) if b != encoded[position]])
        mutated = encoded[:position] + bytes([replacement]) + encoded[position + 1 :]
        try:
            decoded = source_version_from_object(loads_canonical(mutated))
        except (FinanceDecodeError, ValueError, TypeError):
            continue  # refused: never admitted with a different content
        assert source_content_sha256(decoded) != content, seed
        forged = replace(base, version=replace(decoded, source_system=original.source_system))
        if forged.version == original:
            continue
        overview = evaluate([forged], request("prj_SYNTHETIC0000000001", "prj_SYNTHETIC0000000002"))
        assert "hash_mismatch" in [r.value for r in overview.reasons], seed


def test_seeded_input_order_never_changes_the_overview() -> None:
    for seed in SEEDS:
        rng = _rng(seed)
        chosen = scenario(rng.randint(1, 43))
        expected = overview_sha256(chosen.evaluate())
        designations = list(chosen.designations)
        supplied = list(chosen.runs)
        mappings = list(chosen.mappings)
        rng.shuffle(designations)
        rng.shuffle(supplied)
        rng.shuffle(mappings)
        overview = evaluate_financial_overview(
            chosen.request, designations, supplied, mappings, chosen.quarantine
        )
        assert overview_sha256(overview) == expected, seed


def _half_even_reference(units: int, minor: int) -> str:
    """Integer-only half-even rounding of ten-thousandths to `minor` places."""
    step = 10 ** (4 - minor)
    quotient, remainder = divmod(abs(units), step)
    if remainder * 2 > step or (remainder * 2 == step and quotient % 2 == 1):
        quotient += 1
    sign = "-" if units < 0 and quotient != 0 else ""
    if minor == 0:
        return f"{sign}{quotient}"
    whole, fraction = divmod(quotient, 10**minor)
    return f"{sign}{whole}.{fraction:0{minor}d}"


def test_seeded_presentation_rounding_matches_integer_reference() -> None:
    for seed in SEEDS:
        rng = _rng(seed)
        for _ in range(20):
            units = rng.choice([rng.randrange(-LIMIT + 1, LIMIT), rng.randrange(-100_000, 100_000)])
            if units == 0 and rng.random() < 0.5:
                units = 50
            value = parse_amount(_text(units)) if units != 0 else parse_amount("0")
            for currency, minor in (("USD", 2), ("EUR", 2), ("JPY", 0)):
                assert presentation_amount(value, currency) == _half_even_reference(units, minor), (
                    seed,
                    units,
                    currency,
                )
    assert DESIGNATION_A.source_system == "syn-fin-a"
