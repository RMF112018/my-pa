"""CPM Workbench S5a: the Full-Schedule parser plane stays inside its slice.

Contract `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 1.2, 3.1, 7, 9 and 10.1. FAST guards over the committed tree:

* **Generic extraction is unchanged.** `SUPPORTED_MEDIA_TYPES` is still exactly
  Markdown and plain text; `application/pdf` stays unsupported there (R2-AC-005).
* **Neutral naming.** No schedule source module, the fixture generator, any
  generated fixture or golden file carries a denylisted research-corpus token.
  The denylist is held as SHA-256 digests of lowercased word tokens, so this
  guard carries no proprietary string itself.
* **Import allowlist.** `domain/schedule` is standard-library only plus itself;
  `infrastructure/schedule` reaches the domain package, itself and (through
  `pdf.py` alone, enforced by `test_scope_and_hygiene.py`) `pypdfium2`; neither
  imports persistence, application, adapters, bootstrap or contracts.
* **No logging, printing, file or environment access** in either package.
* **The fixture generator is standard-library only** at module level (no
  `math`, no `random`, no clock), and **only the generator names
  `write_goldens`**, so no test can silently regenerate a golden.

What it cannot prove: that a named test is collected and passes (the tiers
run them). The crosswalk guard of contract section 10.4 is added by the WP-02
parser change together with the tests it binds.
"""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from tests.fixtures import schedule_full_pdf

from my_pa.domain.extraction.text import SUPPORTED_MEDIA_TYPES

ROOT: Final = Path(__file__).resolve().parents[2]
DOMAIN: Final = ROOT / "src" / "my_pa" / "domain" / "schedule"
INFRASTRUCTURE: Final = ROOT / "src" / "my_pa" / "infrastructure" / "schedule"
GENERATOR: Final = ROOT / "tests" / "fixtures" / "schedule_full_pdf.py"
GOLDENS: Final = ROOT / "tests" / "fixtures" / "schedule_full_goldens"

#: SHA-256 of lowercased `[A-Za-z0-9]+` tokens that must never appear (contract 10.1).
DENYLIST_SHA256: Final = frozenset(
    {
        "26049e25810bd7c6d59e3a8192e93d98c7b398f37061b36b64b58f795fc3d555",
        "7d8a34ddb21729dc73215f8125fcd0d58e32dc938e91978c5f6f6bdb1f88831d",
        "08bf7134d662b64c5241c42be9e9deb9a7644b35af95cce700e71503403a0e35",
        "d037ceb3377a6d6d9f9dbb49f1fa467f9ca87dfae3579542304a02b38280bf62",
    }
)
_TOKEN: Final = re.compile(rb"[A-Za-z0-9]+")

#: Package roots neither schedule package may import (contract 3.1).
FORBIDDEN_PREFIXES: Final = (
    "my_pa.infrastructure.persistence",
    "my_pa.application",
    "my_pa.adapters",
    "my_pa.bootstrap",
    "my_pa.contracts",
)


def _modules(package: Path) -> list[Path]:
    return sorted(package.rglob("*.py"))


def _imported_modules(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def _denylisted(data: bytes) -> set[str]:
    return {
        token.decode("ascii")
        for token in set(_TOKEN.findall(data))
        if hashlib.sha256(token.lower()).hexdigest() in DENYLIST_SHA256
    }


def _neutrality_targets() -> list[Path]:
    targets = [*_modules(DOMAIN), *_modules(INFRASTRUCTURE), GENERATOR]
    if GOLDENS.exists():
        targets += sorted(path for path in GOLDENS.rglob("*") if path.is_file())
    return targets


def test_generic_extraction_still_excludes_pdf() -> None:
    assert frozenset({"text/markdown", "text/plain"}) == SUPPORTED_MEDIA_TYPES
    assert "application/pdf" not in SUPPORTED_MEDIA_TYPES


def test_schedule_files_carry_no_denylisted_token() -> None:
    offending = {
        str(path.relative_to(ROOT)): sorted(found)
        for path in _neutrality_targets()
        if (found := _denylisted(path.read_bytes()))
    }
    assert DOMAIN.is_dir()
    assert INFRASTRUCTURE.is_dir()
    assert not offending, f"denylisted research-corpus tokens: {offending}"


def test_generated_fixtures_carry_no_denylisted_token() -> None:
    offending = {
        f"{family}__{variant}": sorted(found)
        for family, variant in schedule_full_pdf.CASES
        if (found := _denylisted(schedule_full_pdf.build(family, variant).pdf))
    }
    assert not offending, f"denylisted research-corpus tokens: {offending}"


def test_schedule_import_allowlist() -> None:
    stdlib = sys.stdlib_module_names
    wrong: list[str] = []
    for package, allowed in (
        (DOMAIN, ("my_pa.domain.schedule",)),
        (INFRASTRUCTURE, ("my_pa.domain.schedule", "my_pa.infrastructure.schedule", "pypdfium2")),
    ):
        for path in _modules(package):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in _imported_modules(tree):
                root = name.split(".")[0]
                if root in stdlib or root == "__future__":
                    continue
                if not any(name == a or name.startswith(f"{a}.") for a in allowed):
                    wrong.append(f"{path.relative_to(ROOT)} imports {name}")
                if name.startswith(FORBIDDEN_PREFIXES):
                    wrong.append(f"{path.relative_to(ROOT)} imports forbidden {name}")
    assert not wrong, wrong


def test_schedule_modules_neither_log_nor_print() -> None:
    wrong: list[str] = []
    for path in [*_modules(DOMAIN), *_modules(INFRASTRUCTURE)]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _imported_modules(tree):
            if name.split(".")[0] in {"logging", "os", "pathlib", "io", "shutil", "tempfile"}:
                wrong.append(f"{path.relative_to(ROOT)} imports {name}")
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"print", "open", "input", "breakpoint"}
            ):
                wrong.append(f"{path.relative_to(ROOT)}:{node.lineno} calls {node.func.id}")
    assert not wrong, wrong


def test_fixture_generator_is_standard_library_only() -> None:
    tree = ast.parse(GENERATOR.read_text(encoding="utf-8"), filename=str(GENERATOR))
    top_level = [
        name
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported_modules(node)
    ]
    assert top_level, "the generator imports nothing at module level?"
    for name in top_level:
        root = name.split(".")[0]
        assert root in sys.stdlib_module_names or root == "__future__", name
        assert root not in {"math", "random", "time", "secrets", "uuid"}, name
    # The only non-stdlib reach is the lazy parser import inside the golden writer.
    lazy = [
        (node.lineno, name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node not in tree.body
        for name in _imported_modules(node)
    ]
    assert {name for _, name in lazy} <= {
        "my_pa.domain.schedule",
        "my_pa.infrastructure.schedule.full_profile",
    }


def test_only_the_generator_references_write_goldens() -> None:
    wrong: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path == GENERATOR:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            named = (isinstance(node, ast.Name) and node.id == "write_goldens") or (
                isinstance(node, ast.Attribute) and node.attr == "write_goldens"
            )
            imported = isinstance(node, ast.ImportFrom) and any(
                alias.name == "write_goldens" for alias in node.names
            )
            if named or imported:
                wrong.append(f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}")
    assert not wrong, wrong
