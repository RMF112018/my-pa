"""No test pins the current Alembic head as a literal; it reads `tests.pins`.

Replaces the 56-file `HEAD_PIN_FILES` registry and its three guards in
`tests/schema/test_constraint_authoring_capability_migration.py`. The head is
pinned once, in the reviewed `tests/pins.json`, so a new migration moves one
field instead of sixty files. A new migration PR runs
`python -m tests.pins regen`; the new head's own test declares `REVISION` and
is the one file allowed to spell it.

Unmarked: FAST. Reads `tests/**/*.py` only; writes nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from tests.pins import ALEMBIC_HEAD

ROOT: Final = Path(__file__).resolve().parents[2]
TESTS: Final = ROOT / "tests"
_HEAD: Final = re.escape(ALEMBIC_HEAD)

#: The shapes that *pin* the head: a module-level constant holding it, an
#: equality with it, or a one-element list holding it. Edge assertions
#: (`get_revision(...)`), dict keys, paths, messages and prose are not pins.
PIN_SHAPES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(rf"^[A-Z_][A-Z0-9_]*\s*(:\s*[^=]+)?=\s*[\"']{_HEAD}[\"']"),
    re.compile(rf"==\s*[\"']{_HEAD}[\"']"),
    re.compile(rf"[\"']{_HEAD}[\"']\s*=="),
    re.compile(rf"\[\s*[\"']{_HEAD}[\"']\s*\]"),
)
#: The head revision's own test declares its identity: the one allowed pin.
OWN_REVISION: Final = re.compile(rf"^REVISION\s*(:\s*[^=]+)?=\s*[\"']{_HEAD}[\"']")
#: `get_heads()` compared with a collection holding any string literal.
GET_HEADS_LITERAL: Final = re.compile(
    r"get_heads\(\)\)?\s*==\s*[\[\(\{][^\]\)\}]*[\"']"
    r"|[\"'][^\"']*[\"']\s*[\]\)\}]\s*==\s*(list\()?\s*\w+\.get_heads\(\)"
)


def _sources() -> list[tuple[str, list[str]]]:
    me = Path(__file__).resolve()
    return [
        (path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8").splitlines())
        for path in sorted(TESTS.rglob("*.py"))
        if path.resolve() != me
    ]


def _pins(line: str) -> bool:
    return any(shape.search(line) for shape in PIN_SHAPES)


def test_no_test_spells_the_current_head() -> None:
    own = [
        (relative, number)
        for relative, lines in _sources()
        for number, line in enumerate(lines, 1)
        if OWN_REVISION.match(line)
    ]
    assert len({relative for relative, _ in own}) <= 1, f"two files declare the head: {own}"
    exempt = set(own[:1])
    offenders = [
        f"{relative}:{number}"
        for relative, lines in _sources()
        for number, line in enumerate(lines, 1)
        if _pins(line) and (relative, number) not in exempt
    ]
    assert offenders == [], (
        f"these lines pin the current head as a literal; import ALEMBIC_HEAD from tests.pins: "
        f"{offenders}"
    )


def test_no_get_heads_comparison_spells_a_revision() -> None:
    offenders = [
        f"{relative}:{number}"
        for relative, lines in _sources()
        for number, line in enumerate(lines, 1)
        if GET_HEADS_LITERAL.search(line)
    ]
    assert offenders == [], (
        "these `get_heads()` comparisons spell a revision; compare with [ALEMBIC_HEAD] "
        f"(import ALEMBIC_HEAD from tests.pins) or assert len(...) == 1: {offenders}"
    )


def test_the_patterns_match_pins_and_spare_the_allowed_shapes() -> None:
    head = ALEMBIC_HEAD
    for pin in (
        f'HEAD: Final = "{head}"',
        f'CURRENT_HEAD_REVISION = "{head}"',
        f'    assert x == "{head}"',
        f'    assert script.get_heads() == ["{head}"]',
    ):
        assert _pins(pin), pin
    for allowed in (
        f'    assert script.get_revision("{head}").down_revision == "x"',
        f'    "{head}": frozenset(',
        f'    MIGRATIONS / "20261122_{head}_x.py"',
    ):
        assert not _pins(allowed), allowed
    assert OWN_REVISION.match(f'REVISION: Final = "{head}"')
    for spelled in (
        f'    assert script.get_heads() == ["{head}"]',
        '    assert list(script.get_heads()) == ("abc123",)',
    ):
        assert GET_HEADS_LITERAL.search(spelled), spelled
    for allowed in (
        "    assert script.get_heads() == [ALEMBIC_HEAD]",
        "    assert len(list(script.get_heads())) == 1",
    ):
        assert not GET_HEADS_LITERAL.search(allowed), allowed
