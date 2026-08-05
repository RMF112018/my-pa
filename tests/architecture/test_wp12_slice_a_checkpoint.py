"""WP-12A freezes authority, acceptance ownership, and the native v1 boundary."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOAL = ROOT / ".ai" / "goals" / "wp-12-apple-mcc"
MATRIX = GOAL / "gap-matrix.yaml"
ARCHITECTURE_PLAN = GOAL / "wp-12-architecture-acceptance-plan.md"
CHECKPOINT = GOAL / "slice-a-implementation-checkpoint.json"
MCV_PLAN = ROOT / "docs" / "plans" / "mcv-completion-plan.md"
NATIVE_PACKAGE = ROOT / "native" / "apple-source-host"


def _matrix_owners() -> dict[int, str]:
    """Read the two scalar fields this test owns without adding a YAML dependency."""
    text = MATRIX.read_text(encoding="utf-8")
    blocks = re.findall(
        r"(?ms)^  - id: NAPDCB-AC-(?P<number>\d{3})\n(?P<body>.*?)(?=^  - id:|^summary:)",
        text,
    )
    owners: dict[int, str] = {}
    for number_text, body in blocks:
        slice_match = re.search(r"(?m)^    slice: ([A-H])$", body)
        assert slice_match is not None, f"AC-{number_text} has no readable final slice"
        owners[int(number_text)] = slice_match.group(1)
    return owners


def _expand_final_criteria() -> list[tuple[int, str]]:
    plan = ARCHITECTURE_PLAN.read_text(encoding="utf-8")
    owner: str | None = None
    assignments: list[tuple[int, str]] = []
    for line in plan.splitlines():
        heading = re.match(r"### ([A-H]) —", line)
        if heading:
            owner = heading.group(1)
        criteria = re.search(r"Final criteria:\s*([^.]*)\.", line)
        if criteria is None:
            continue
        assert owner is not None, "Final criteria appeared before a slice heading"
        for token in (part.strip() for part in criteria.group(1).split(",")):
            span = re.fullmatch(r"(\d{3})(?:-|\N{EN DASH})(\d{3})", token)
            numbers = range(int(span.group(1)), int(span.group(2)) + 1) if span else [int(token)]
            assignments.extend((number, owner) for number in numbers)
    return assignments


def test_all_48_criteria_have_one_exact_final_owner() -> None:
    matrix = _matrix_owners()
    narrative = _expand_final_criteria()
    counts = Counter(number for number, _owner in narrative)

    assert list(matrix) == list(range(1, 49))
    assert len(narrative) == 48
    assert counts == Counter(dict.fromkeys(range(1, 49), 1))
    assert dict(narrative) == matrix
    assert dict(narrative)[37] == "C"


def test_slice_a_records_current_authority_without_starting_mvp() -> None:
    plan = MCV_PLAN.read_text(encoding="utf-8")
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))

    assert "AUTH-WP12-20260804-OPERATOR-001" in plan
    assert "D-106" in plan and "WP-12 active before MCV completion" in plan
    assert "D-107" in plan and "condition not yet met; no current MVP execution authority" in plan
    assert "WP-10 remains deferred" in plan
    assert "WP-11 remains dependency-blocked" in plan
    assert checkpoint["authorization"]["wp10_deferred"] is True
    assert checkpoint["authorization"]["wp11_deferred"] is True
    assert checkpoint["authorization"]["mvp_started"] is False
    assert checkpoint["acceptance"]["final_criteria_discharged"] == []


def test_native_v1_target_has_no_live_or_mutating_surface() -> None:
    package = (NATIVE_PACKAGE / "Package.swift").read_text(encoding="utf-8")
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((NATIVE_PACKAGE / "Sources").rglob("*.swift"))
    )

    assert ".package(" not in package
    assert NativeSourceProtocolIdentifier.value in sources
    for fragment in NativeSourceProtocolIdentifier.forbidden_fragments:
        assert fragment not in sources


class NativeSourceProtocolIdentifier:
    value = "my-pa.native-source.v1"
    forbidden_fragments = (
        "import EventKit",
        "import Contacts",
        "import MailKit",
        "EKEventStore",
        "CNContactStore",
        "requestAccess",
        "NSXPC",
        "LaunchAgent",
        "URLSession",
        "NWListener",
        "Postgres",
        "SQLite",
        "DATABASE_URL",
        "func create",
        "func update",
        "func delete",
        "func write",
        "func mutate",
        "func activate",
    )
