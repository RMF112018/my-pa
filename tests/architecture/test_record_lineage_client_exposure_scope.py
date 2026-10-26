"""Record lineage P1 scope guard (client exposure contract section 10).

Two FAST guards over the committed tree, in the shape of the S3.1 scope guard:

* **The crosswalk is real.** Every test the section 10 crosswalk binds exists:
  each row names at least one module path that is a file, and each `test_*`
  name in its test cell is a function defined in one of that row's modules.
* **The conversions are real.** Every `module::name` the section 10.1
  conversion table names is a function defined in that module, so a converted
  S1-S3.1 test cannot be renamed or deleted without this table changing too.

What it cannot prove: that a named test is collected and passes (the tiers run
them), or that a conversion changed exactly the assertion its row states (the
design review and the conversion diff do).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from tests.architecture.test_record_lineage_s2_scope import _python_functions

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT: Final = ROOT / "docs" / "architecture" / "record-lineage-client-exposure-contract.md"
_HEADER: Final = "| Concern | Module | Test functions | Tier |"
_CONVERSION_HEADER: Final = "| Module::name | Old assertion | New assertion |"
_BACKTICKED: Final = re.compile(r"`([^`]+)`")
_PYTHON_TEST: Final = re.compile(r"\Atest_\w+\Z")
_MODULE_PATH: Final = re.compile(r"\Atests/\S+\.py\Z")
_CONVERSION: Final = re.compile(r"\A(tests/\S+\.py)::(test_\w+)\Z")


def _section_10() -> list[str]:
    text = CONTRACT.read_text(encoding="utf-8")
    start = text.index("\n## 10. Acceptance-test crosswalk\n")
    end = text.index("\n## 11. ", start)
    return text[start:end].splitlines()


def _table_rows(header: str) -> list[list[str]]:
    lines = _section_10()
    assert lines.count(header) == 1, f"expected exactly 1 table headed {header!r}"
    first = lines.index(header)
    rows: list[list[str]] = []
    for line in lines[first + 2 :]:
        if not line.startswith("| "):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split(" | ")])
    return rows


def _crosswalk_rows() -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    """Each crosswalk row as (concern, module paths, backticked test-cell tokens)."""
    rows: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for cells in _table_rows(_HEADER):
        assert len(cells) == 4, cells
        concern, modules_cell, tests_cell, _tier = cells
        modules = tuple(
            token for token in _BACKTICKED.findall(modules_cell) if _MODULE_PATH.match(token)
        )
        rows.append((concern, modules, tuple(_BACKTICKED.findall(tests_cell))))
    return tuple(rows)


def _conversions() -> list[tuple[str, str]]:
    """Every `module::name` the section 10.1 conversion table binds."""
    found: list[tuple[str, str]] = []
    for cells in _table_rows(_CONVERSION_HEADER):
        assert len(cells) == 3, cells
        (token,) = _BACKTICKED.findall(cells[0])
        matched = _CONVERSION.match(token)
        assert matched is not None, token
        found.append((matched.group(1), matched.group(2)))
    return found


def _defines(module: str, name: str) -> bool:
    return (ROOT / module).is_file() and name in _python_functions(module)


def test_every_client_exposure_crosswalk_test_exists() -> None:
    rows = _crosswalk_rows()
    assert len(rows) >= 6, "the section 10 crosswalk did not parse"
    missing: list[str] = []
    named = 0
    for concern, modules, tokens in rows:
        assert modules, f"{concern}: no module path"
        for module in modules:
            if not (ROOT / module).is_file():
                missing.append(f"{concern}: module {module}")
        names = [token for token in tokens if _PYTHON_TEST.match(token)]
        assert names, f"{concern}: no test named"
        named += len(names)
        for name in names:
            if not any(_defines(module, name) for module in modules):
                missing.append(f"{concern}: {name} in {modules}")
    assert missing == [], "crosswalk tests that do not exist:\n" + "\n".join(missing)
    assert named >= 36, named


def test_every_client_exposure_conversion_exists() -> None:
    conversions = _conversions()
    assert len(conversions) >= 9, "the section 10.1 conversion table did not parse"
    missing = [
        f"section 10.1: {module}::{name}"
        for module, name in conversions
        if not _defines(module, name)
    ]
    assert missing == [], "converted tests that do not exist:\n" + "\n".join(missing)
