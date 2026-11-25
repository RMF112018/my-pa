"""`comms_identifiers_v2` (communications WP4, rulings R5, R5b (a) and R11).

The labelled synthetic set `tests/fixtures/communications_identifiers/labelled_v2.json`
is hand-labelled: each case's `expected` is the exact normalized output. v2 must
reproduce every case exactly, so its per-kind precision and recall are 1.0; the
v1 figures over the same set are recorded (`record_property`), never gated. v1's
output is a subset of v2's on every case except the precision defects v2
corrects: `Submittal 03 30 00-01`, which v1 read as `submittal:03`, and a
number that runs on into `:digit` or a letter (`RFI 10:30`, `CO 5b`; WP4-R1 F6).
The `behaviour` table pins documented outputs that are neither positives nor
true negatives; every negative expects nothing.

Unmarked: FAST. Every text is synthetic.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION_V1,
    IDENTIFIER_VERSION_V2,
    FormClass,
    IdentifierKind,
    TechnicalIdentifier,
    extract_identifiers,
    identifier_forms,
    normalize_identifier_query,
)

LABELLED: Final = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "communications_identifiers"
    / "labelled_v2.json"
)
_SET: Final[dict[str, Any]] = json.loads(LABELLED.read_text(encoding="utf-8"))
CASES: Final[list[dict[str, Any]]] = _SET["cases"]
#: Documented outputs that are neither a positive nor a true negative (a
#: cross-kind reading, a number continued past a boundary, an accepted
#: residual such as `CO: 25 ppm`): pinned exactly, never scored (WP4-R1 F6).
BEHAVIOUR: Final[list[dict[str, Any]]] = _SET["behaviour"]
KINDS: Final = tuple(kind.value for kind in IdentifierKind)
#: The one v1 output class v2 drops on purpose: a spaced submittal number
#: (`Submittal 03 30 00-01`) read as its first group (`submittal:03`).
V1_DEFECT: Final = re.compile(r"[Ss]ubmittal (?P<first>[0-4][0-9]) [0-9]{2} [0-9]{2}")


def _normalized(text: str, version: str) -> set[str]:
    return {identifier.normalized for identifier in extract_identifiers(text, version=version)}


def _kind(normalized: str) -> str:
    return normalized.split(":", 1)[0]


def _scores(version: str) -> dict[str, dict[str, int]]:
    """Per kind: true positives, false positives, false negatives over the set."""
    scores = {kind: Counter[str]() for kind in KINDS}
    for case in CASES:
        expected, found = set(case["expected"]), _normalized(case["text"], version)
        for value in expected & found:
            scores[_kind(value)]["tp"] += 1
        for value in found - expected:
            scores[_kind(value)]["fp"] += 1
        for value in expected - found:
            scores[_kind(value)]["fn"] += 1
    return {kind: dict(counter) for kind, counter in scores.items()}


def test_the_labelled_set_is_the_size_and_shape_the_ruling_asks() -> None:
    assert len(CASES) >= 340
    assert len({case["id"] for case in CASES}) == len(CASES)
    groups = Counter((case["group"], case["kind"]) for case in CASES)
    for kind in KINDS:
        assert groups["positive", kind] >= 20, kind
        assert groups["negative", kind] >= 15, kind
    assert sum(1 for case in CASES if case["group"] == "mixed") >= 30
    for case in CASES:
        assert case["expected"] == sorted(set(case["expected"])), case["id"]
        assert all(_kind(value) in KINDS for value in case["expected"]), case["id"]
        if case["group"] == "positive":
            assert any(_kind(v) == case["kind"] for v in case["expected"]), case["id"]
        if case["group"] == "negative":  # a true negative yields nothing (WP4-R1 F6)
            assert case["expected"] == [], case["id"]
    assert BEHAVIOUR
    assert not {case["id"] for case in CASES} & {case["id"] for case in BEHAVIOUR}
    assert all(case["group"] == "behaviour" and case["expected"] for case in BEHAVIOUR)


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["id"]))
def test_v2_reproduces_every_labelled_case_exactly(case: dict[str, Any]) -> None:
    assert sorted(_normalized(case["text"], IDENTIFIER_VERSION_V2)) == case["expected"]


@pytest.mark.parametrize("case", BEHAVIOUR, ids=lambda case: str(case["id"]))
def test_v2_reproduces_every_behaviour_case_exactly(case: dict[str, Any]) -> None:
    assert sorted(_normalized(case["text"], IDENTIFIER_VERSION_V2)) == case["expected"]


def test_v2_precision_and_recall_are_one_per_kind_and_v1_is_recorded(
    record_property: Callable[[str, object], None],
) -> None:
    v2 = _scores(IDENTIFIER_VERSION_V2)
    for kind, score in v2.items():
        assert score.get("fp", 0) == 0, kind
        assert score.get("fn", 0) == 0, kind
        assert score.get("tp", 0) >= 20, kind
    v1 = _scores(IDENTIFIER_VERSION_V1)
    for kind, score in v1.items():
        tp, fp, fn = score.get("tp", 0), score.get("fp", 0), score.get("fn", 0)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        record_property(f"v1_{kind}", f"precision={precision:.3f} recall={recall:.3f}")
    # Measured, not gated: v1 has no `pco` or `cor` at all.
    assert v1["pco"].get("tp", 0) == v1["cor"].get("tp", 0) == 0


def _v1_number_end_defects(text: str) -> set[str]:
    """v1 outputs whose number runs on into `:digit` or a letter (WP4-R1 F6)."""
    found = {
        f"{kind}:{int(m.group('number'))}"
        for kind in ("rfi", "cb", "co")
        for m in re.finditer(rf"(?i:{kind})\S*\s*(?P<number>[0-9]+)(?=:[0-9]|[^\W\d_])", text)
    }
    found.update(
        f"submittal:{m.group('number')}"
        for m in re.finditer(
            r"(?i:submittal)\S*\s*(?P<number>[0-9]+(?:[.\-][0-9]+)*)(?=:[0-9]|[^\W\d_])", text
        )
    )
    return found


def test_every_v1_output_is_a_v2_output_except_the_corrected_defects() -> None:
    """v2 drops only `submittal:03` and the F6 number ends (`RFI 10:30`, `CO 5b`)."""
    exceptions = []
    for case in CASES:
        lost = _normalized(case["text"], IDENTIFIER_VERSION_V1) - _normalized(
            case["text"], IDENTIFIER_VERSION_V2
        )
        if lost:
            exceptions.append((case["id"], lost))
    assert exceptions
    for case_id, lost in exceptions:
        text = next(case["text"] for case in CASES if case["id"] == case_id)
        defects = {f"submittal:{m.group('first')}" for m in V1_DEFECT.finditer(text)}
        defects |= _v1_number_end_defects(text)
        assert defects, case_id
        assert lost <= defects, (case_id, lost)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Cross-kind traps: the qualified forms never also yield a `co`.
        ("PCO 5", {"pco:5"}),
        ("COR 7", {"cor:7"}),
        ("Change Order Request 7", {"cor:7"}),
        ("Potential Change Order 12", {"pco:12"}),
        ("Proposed Change Order 12", {"pco:12"}),
        ("Change Order 5", {"co:5"}),
        ("CO2 levels", set()),
        ("Co. 5", set()),
    ],
)
def test_the_cross_kind_traps(text: str, expected: set[str]) -> None:
    assert _normalized(text, IDENTIFIER_VERSION_V2) == expected


def test_rfi_17_never_matches_rfi_174_in_v2() -> None:
    query = _normalized("RFI: 17", IDENTIFIER_VERSION_V2)
    assert query == {"rfi:17"}
    assert not query & _normalized("Request for Information 174", IDENTIFIER_VERSION_V2)
    assert not _normalized("PCO 17", IDENTIFIER_VERSION_V2) & _normalized(
        "PCO 174", IDENTIFIER_VERSION_V2
    )


@pytest.mark.parametrize("text", ["Quote 033000 and 099123 attached", "job 260411", "PO 033000"])
def test_the_six_digit_policy_is_unchanged(text: str) -> None:
    assert _normalized(text, IDENTIFIER_VERSION_V2) == set()


@pytest.mark.parametrize(
    ("text", "form"),
    [
        ("RFI 174", FormClass.RFI_ACRONYM),
        ("RFI: 174", FormClass.RFI_ACRONYM_COLON),
        ("Request for Information 174", FormClass.RFI_WORDS),
        ("CB: 2", FormClass.CB_ACRONYM_COLON),
        ("Change Bulletin 2", FormClass.CB_WORDS),
        ("CO #5", FormClass.CO_ACRONYM),
        ("CO: 5", FormClass.CO_ACRONYM_COLON),
        ("Change Order 5", FormClass.CO_WORDS),
        ("PCO 12", FormClass.PCO_ACRONYM),
        ("Potential Change Order 12", FormClass.PCO_WORDS),
        ("COR 7", FormClass.COR_ACRONYM),
        ("Change Order Request 7", FormClass.COR_WORDS),
        ("Submittal 12", FormClass.SUBMITTAL_NUMBER),
        ("Submittal: 12", FormClass.SUBMITTAL_COLON),
        ("Submittals 12", FormClass.SUBMITTAL_PLURAL),
        ("Submittal 03 30 00-01", FormClass.SUBMITTAL_SPACED_SPEC),
        ("GMP", FormClass.GMP_ACRONYM),
        ("FPL", FormClass.FPL_ACRONYM),
        ("FP&L", FormClass.FPL_AMPERSAND),
        ("F.P.L.", FormClass.FPL_DOTTED),
        ("Section 03 30 00", FormClass.SPEC_CUED),
    ],
)
def test_each_form_has_its_class(text: str, form: FormClass) -> None:
    ((_identifier, found),) = identifier_forms(text)
    assert found is form


def test_the_forms_are_exactly_the_extraction() -> None:
    for case in CASES:
        forms = {identifier for identifier, _form in identifier_forms(case["text"])}
        assert forms == set(extract_identifiers(case["text"])), case["id"]
    bare = identifier_forms("ref 03 30 00", include_uncued_spec_sections=True)
    assert bare == ((TechnicalIdentifier(IdentifierKind.SPEC_SECTION, "033000"),
                     FormClass.SPEC_BARE_SPACED),)  # fmt: skip


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ("RFI 174", "rfi:174"),
        ("  Change Order #5 ", "co:5"),
        ("PCO-12", "pco:12"),
        ("FP&L", "fpl"),
        ("rfi:174", "rfi:174"),
        ("submittal:033000-01", "submittal:033000-01"),
        ("spec:033000.13", "spec:033000.13"),
        ("cor:7", "cor:7"),
        ("gmp", "gmp"),
        ("fpl", "fpl"),
    ],
)
def test_a_query_item_names_exactly_one_identifier(item: str, expected: str) -> None:
    found = normalize_identifier_query(item)
    assert found is not None
    assert found.normalized == expected


@pytest.mark.parametrize(
    "item",
    ["174", "RFI", "RFI 1 and RFI 2", "", "rfi:0174", "rfi:abc", "xyz:1", "spec:33401", "GMP FPL"],
)
def test_a_query_item_naming_zero_or_several_is_none(item: str) -> None:
    assert normalize_identifier_query(item) is None


def test_query_normalization_follows_the_version() -> None:
    assert normalize_identifier_query("pco:12", version=IDENTIFIER_VERSION_V1) is None
    assert normalize_identifier_query("PCO 12", version=IDENTIFIER_VERSION_V1) is None
    found = normalize_identifier_query("RFI 174", version=IDENTIFIER_VERSION_V1)
    assert found == TechnicalIdentifier(IdentifierKind.RFI, "174")
