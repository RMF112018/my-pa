"""OD-06 / UB-009 (F-1): the financial controlled source stays pure, synthetic and unserved.

Contract `docs/architecture/financial-source-contract.md` section 12.3. FAST
guards over the committed tree:

* **The crosswalk is real.** Every `test_*` the section 12.1 module table and the
  section 12.5 crosswalk name is a function defined in the module of its row.
* **Nothing public or persistent.** No `Capability`/`Purpose` value names
  finance, no `IdKind` uses a planned F-2 prefix, none of the 10 planned
  `financial_*` tables exists in `METADATA` or any revision or SQL file (by an
  identifier-bounded pattern whose discrimination against the legacy
  `procore_financial_*` / `second_brain_financial_*` names is shown by a
  positive control), the future switch `MY_PA_FINANCIAL_SOURCE_ENABLED` has no
  consumer, and `programs.financial` / `program_financial_read` are served by
  nothing.
* **Isolation.** The finance domain is imported only by its own slice, the
  parser by nothing outside tests; the 8 modules import only their allowed roots
  and use no float, IO, logging, printing, clock or dynamic code. `json` is allowed
  only in the domain `canonical.py` (its refusing decoder, F1-D32).
* **The evaluator signature is pinned** (section 5.3): exactly 5 required
  parameters ending with `quarantined_run_refs: frozenset[str]`; no threshold.

What it cannot prove: that the named tests pass (the tiers run them), or that a
dynamic import by string never happens beyond the forms scanned here.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.tables import METADATA

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT: Final = ROOT / "docs" / "architecture" / "financial-source-contract.md"

DOMAIN_PACKAGE: Final = "my_pa.domain.project_controls.financial"
PARSER_PACKAGE: Final = "my_pa.infrastructure.financial"
DOMAIN_DIR: Final = "src/my_pa/domain/project_controls/financial"
PARSER_DIR: Final = "src/my_pa/infrastructure/financial"

#: Section 3.1: the 6 domain modules and the 2 parser modules.
DOMAIN_MODULES: Final = tuple(
    f"{DOMAIN_DIR}/{name}.py"
    for name in ("__init__", "money", "model", "equations", "reportability", "canonical")
)
PARSER_MODULES: Final = (f"{PARSER_DIR}/__init__.py", f"{PARSER_DIR}/synthetic_csv.py")
FINANCE_MODULES: Final = DOMAIN_MODULES + PARSER_MODULES

#: Section 9.2: the 10 identifier prefixes F-2 plans (none may exist in F-1).
PLANNED_ID_PREFIXES: Final = frozenset(
    {"fdes", "fsrun", "fsver", "fmap", "fpsn", "fline", "fchg", "fxfr", "fleg", "fqr"}
)
#: Section 9.1: the 10 planned table names (none may exist in F-1).
PLANNED_TABLES: Final = (
    "financial_source_designations",
    "financial_source_runs",
    "financial_source_versions",
    "financial_project_mappings",
    "financial_period_snapshots",
    "financial_account_lines",
    "financial_change_orders",
    "financial_scope_transfers",
    "financial_transfer_legs",
    "financial_run_quarantines",
)
#: Section 12.3 (R11-F01): the planned names with identifier boundaries.
PLANNED_TABLE_PATTERN: Final = re.compile(
    r"(?<![A-Za-z0-9_])financial_(source_designations|source_runs|source_versions"
    r"|project_mappings|period_snapshots|account_lines|change_orders|scope_transfers"
    r"|transfer_legs|run_quarantines)(?![A-Za-z0-9_])"
)
#: Legacy names present at the basis that the pattern must not match (R-10, R-10a).
LEGACY_NAMES: Final = (
    "procore_financial_change_orders",
    "procore_financial_change_order_line_items",
    "procore_financial_change_events",
    "second_brain_financial_source_coverage_snapshots",
    "raw_financial_source_payload_persisted",
)

#: Section 12.3: the roots no finance consumer, route or switch may appear in.
SERVED_ROOTS: Final = ("src", "apps", "ops", "migrations", "web/src")
SWITCH_TOKENS: Final = ("MY_PA_FINANCIAL_SOURCE_ENABLED", "financial_source_enabled")
SERVED_TOKENS: Final = ("programs.financial", "program_financial_read")

#: The only names the domain may import from these 2 non-finance domain modules.
ALLOWED_FOREIGN: Final = {
    "my_pa.domain.schedule.canonical": frozenset({"canonical_json_bytes"}),
    "my_pa.domain.program.vocabulary": frozenset({"MetricValueState"}),
}
BANNED_IMPORTS: Final = frozenset(
    {
        "logging",
        "os",
        "pathlib",
        "io",
        "socket",
        "urllib",
        "http",
        "subprocess",
        "pickle",
        "xml",
        "csv",
        "json",
        "time",
    }
)
#: FR11-F06 (section 12.3 amendment): no clock -- no `time` import and no clock read.
CLOCK_ATTRIBUTES: Final = frozenset({"now", "utcnow", "today", "fromtimestamp", "utcfromtimestamp"})
#: F1-D32: the shared encoder's refusing decoder lives in `canonical.py` only.
JSON_ALLOWED_IN: Final = f"{DOMAIN_DIR}/canonical.py"
BANNED_CALLS: Final = frozenset({"print", "open", "eval", "exec", "compile", "__import__"})

_BACKTICKED: Final = re.compile(r"`([^`]+)`")
_TEST_NAME: Final = re.compile(r"\Atest_\w+\Z")
_QUALIFIED: Final = re.compile(r"\A(tests/\S+\.py)::(test_\w+)\Z")


def _section(start: str, end: str) -> str:
    text = CONTRACT.read_text(encoding="utf-8")
    first = text.index(start)
    return text[first : text.index(end, first)]


def _functions(path: str) -> frozenset[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    return frozenset(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )


def _named_tests() -> list[tuple[str, str]]:
    """`(module, test)` pairs of section 12.1 rows and section 12.5 cells."""
    pairs: list[tuple[str, str]] = []
    for line in _section("### 12.1 Test modules", "### 12.2 ").splitlines():
        if not line.startswith("| `tests/"):
            continue
        module_cell, tests_cell = (cell.strip() for cell in line.strip().strip("|").split(" | "))
        (module,) = _BACKTICKED.findall(module_cell)
        pairs += [
            (module, name) for name in _BACKTICKED.findall(tests_cell) if _TEST_NAME.match(name)
        ]
    for token in _BACKTICKED.findall(_section("### 12.5 Crosswalk", "\n## 13. ")):
        match = _QUALIFIED.match(token)
        if match is not None:
            pairs.append((match.group(1), match.group(2)))
    return pairs


def test_financial_crosswalk_names_real_tests() -> None:
    pairs = _named_tests()
    modules = {module for module, _ in pairs}
    assert len(modules) == 9, "section 12.1 names 9 test modules"
    assert len(pairs) >= 120, "the section 12.1 / 12.5 tables did not parse"
    missing: list[str] = []
    for module, name in pairs:
        if not (ROOT / module).is_file():
            missing.append(module)
        elif name not in _functions(module):
            missing.append(f"{module}::{name}")
    # The F-2 half of AT-020 is a crosswalk row, never a (skipped) F-1 test.
    assert not (ROOT / "tests" / "integration" / "test_financial_scope_transfer.py").exists()
    assert missing == []


def test_no_financial_capability_purpose_or_id_kind() -> None:
    assert [c.value for c in Capability if "financ" in c.value] == []
    assert [p.value for p in Purpose if "financ" in p.value] == []
    assert [k.value for k in IdKind if k.value in PLANNED_ID_PREFIXES] == []
    assert [k.name for k in IdKind if "FINANCIAL" in k.name] == []


def _migration_texts() -> Iterator[tuple[Path, str]]:
    for pattern in ("migrations/versions/*.py", "migrations/sql/*.sql"):
        for path in sorted(ROOT.glob(pattern)):
            yield path, path.read_text(encoding="utf-8")


def test_no_financial_table_or_migration() -> None:
    tables = [t.name for t in METADATA.tables.values() if PLANNED_TABLE_PATTERN.search(t.name)]
    assert tables == []
    texts = list(_migration_texts())
    assert len(texts) >= 128, "the revision and SQL files were not found"
    hits = [
        str(path.relative_to(ROOT)) for path, text in texts if PLANNED_TABLE_PATTERN.search(text)
    ]
    assert hits == []


def test_the_table_guard_does_not_match_legacy_names() -> None:
    for name in LEGACY_NAMES:
        assert PLANNED_TABLE_PATTERN.search(name) is None, name
        assert PLANNED_TABLE_PATTERN.search(f'"financial"."{name}"') is None, name
    for name in PLANNED_TABLES:
        for text in (name, f"knowledge.{name}", f'op.create_table("{name}",'):
            match = PLANNED_TABLE_PATTERN.search(text)
            assert match is not None and match.group(0) == name, text
    # The legacy names really are present at the basis, so the control is live.
    corpus = "\n".join(text for _, text in _migration_texts())
    assert all(name in corpus for name in LEGACY_NAMES[:4])


def _text_files(roots: tuple[str, ...]) -> Iterator[tuple[Path, str]]:
    for root in roots:
        for path in sorted((ROOT / root).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or "node_modules" in path.parts:
                continue
            data = path.read_bytes()
            if b"\0" in data:
                continue  # binary asset
            yield path, data.decode("utf-8", errors="replace")


def _env_examples() -> list[Path]:
    found = [path for path in ROOT.glob(".env*") if path.is_file()]
    for root in ("apps", "ops", "web", "deploy"):
        if (ROOT / root).is_dir():
            found += [
                path
                for path in (ROOT / root).rglob(".env*")
                if path.is_file() and "node_modules" not in path.parts
            ]
    return found


def test_financial_switch_has_no_consumer() -> None:
    envs = _env_examples()
    assert ROOT / ".env.example" in envs
    files = [*_text_files(SERVED_ROOTS), *((p, p.read_text(encoding="utf-8")) for p in envs)]
    assert len(files) > 1000, "the served roots were not scanned"
    hits = [
        str(path.relative_to(ROOT))
        for path, text in files
        if any(token in text for token in SWITCH_TOKENS)
    ]
    assert hits == []


def test_programs_financial_overview_is_not_served() -> None:
    hits = [
        str(path.relative_to(ROOT))
        for path, text in _text_files(SERVED_ROOTS)
        if any(token in text for token in SERVED_TOKENS)
    ]
    assert hits == []


def _python_files(roots: tuple[str, ...]) -> Iterator[str]:
    for root in roots:
        for path in sorted((ROOT / root).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield str(path.relative_to(ROOT))


def _imports(path: str, *, expand: bool = False) -> list[tuple[str, frozenset[str]]]:
    """`(module, imported names)` of every import; `import x` has no names.

    With `expand`, `from a.b import c` also yields `a.b.c`, so `from
    my_pa.infrastructure import financial` counts as importing the package.
    """
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    found: list[tuple[str, frozenset[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, frozenset()) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = frozenset(alias.name for alias in node.names)
            found.append((node.module, names))
            if expand:
                found += [(f"{node.module}.{name}", frozenset()) for name in names]
    return found


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def test_financial_modules_are_imported_only_by_their_own_slice() -> None:
    offenders: list[str] = []
    for path in _python_files(("src", "apps", "ops", "migrations")):
        own_domain = path.startswith(DOMAIN_DIR + "/")
        own_parser = path.startswith(PARSER_DIR + "/")
        for module, _ in _imports(path, expand=True):
            if _within(module, DOMAIN_PACKAGE) and not (own_domain or own_parser):
                offenders.append(f"{path} imports {module}")
            if _within(module, PARSER_PACKAGE) and not own_parser:
                offenders.append(f"{path} imports {module}")
    assert offenders == []


def _top(module: str) -> str:
    return module.split(".", 1)[0]


def test_financial_modules_import_only_their_allowed_roots() -> None:
    stdlib = sys.stdlib_module_names | {"__future__"}
    offenders: list[str] = []
    for path in FINANCE_MODULES:
        in_domain = path in DOMAIN_MODULES
        for module, names in _imports(path):
            if _top(module) in stdlib or _within(module, DOMAIN_PACKAGE):
                continue
            allowed = ALLOWED_FOREIGN.get(module) if in_domain else None
            if allowed is not None and names and names <= allowed:
                continue
            offenders.append(f"{path} imports {module}")
    assert offenders == []


def test_financial_modules_use_no_float_io_or_logging() -> None:
    offenders: list[str] = []
    for path in FINANCE_MODULES:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "float":
                offenders.append(f"{path}:{node.lineno} float")
            elif isinstance(node, ast.Constant) and type(node.value) in (float, complex):
                offenders.append(f"{path}:{node.lineno} float literal")
            elif isinstance(node, ast.Attribute) and node.attr in CLOCK_ATTRIBUTES:
                offenders.append(f"{path}:{node.lineno} clock .{node.attr}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in BANNED_CALLS
            ):
                offenders.append(f"{path}:{node.lineno} {node.func.id}()")
        for module, _ in _imports(path):
            top = _top(module)
            if top in BANNED_IMPORTS and not (top == "json" and path == JSON_ALLOWED_IN):
                offenders.append(f"{path} imports {module}")
    assert offenders == []


def test_evaluator_signature_is_pinned() -> None:
    path = f"{DOMAIN_DIR}/reportability.py"
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    (function,) = (
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_financial_overview"
    )
    arguments = function.args
    assert [a.arg for a in arguments.args] == [
        "request",
        "designations",
        "runs",
        "mappings",
        "quarantined_run_refs",
    ]
    # Every parameter is required: no default can stand in for a threshold or for
    # the operator's quarantine set.
    assert arguments.defaults == [] and arguments.kwonlyargs == []
    assert arguments.vararg is None and arguments.kwarg is None
    assert arguments.posonlyargs == []
    annotation = arguments.args[-1].annotation
    assert annotation is not None and ast.unparse(annotation) == "frozenset[str]"
