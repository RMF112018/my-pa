"""AT-026 (S1): record lineage S1 stays inside its slice (S1 contract sections 6.3 and 10).

Two FAST guards over the committed tree:

* **No Record Event family.** S1 emits no Record Event (section 6.3 step 6;
  the Record Event family for lineage is S3, section 11). The closed
  `RecordEventFamily` is still exactly the twenty-three families it held at
  the basis `ac24e3bf`, the S1 revision never touches `knowledge.record_events`
  or its family CHECK, and no S1 module stages, drafts or names a Record Event.
* **The crosswalk is real.** Every test the section 10 crosswalk binds exists:
  a Python row's `test_*` names are functions defined in one of that row's
  Python modules, and a vitest or playwright row's titles are string literals
  in one of that row's TypeScript modules. A renamed test must update the
  table in the same commit (section 10), and this is what makes that binding
  enforceable rather than a convention.

What it cannot prove: that a named test is collected and passes (the tiers
run them), or that a vitest title is the argument of `it`/`test` rather than
some other literal. Every identity here is a repository path or a token.
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path
from typing import Final

from my_pa.domain.record_events import RecordEventFamily

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT: Final = ROOT / "docs" / "architecture" / "record-lineage-s1-contract.md"
#: Found by its slug, not its revision id, so this guard is not one more
#: head pin (`test_the_head_pin_list_is_the_files_that_actually_pin_the_head`).
(S1_REVISION,) = sorted((ROOT / "migrations" / "versions").glob("*_record_lineage_s1.py"))

#: `RecordEventFamily` at the S1 basis `ac24e3bf` (twenty-three members).
BASIS_RECORD_EVENT_FAMILIES: Final = frozenset(
    {
        "task",
        "commitment",
        "project",
        "entity",
        "entity_identifier",
        "entity_alias",
        "entity_assignment",
        "entity_relationship",
        "entity_observation",
        "entity_name",
        "entity_address",
        "entity_communication_method",
        "entity_project_participation",
        "person_organization_affiliation",
        "relationship_memory",
        "constraint",
        "constraint_category",
        "project_controls_settings",
        "meeting",
        "meeting_series",
        "capture",
        "task_comment",
        "knowledge_assertion",
    }
)

#: The modules S1 added for its planes (section 9); none may reach the feed.
S1_MODULES: Final = (
    "src/my_pa/domain/lineage/__init__.py",
    "src/my_pa/domain/lineage/vocabulary.py",
    "src/my_pa/domain/lineage/canonical.py",
    "src/my_pa/domain/lineage/model.py",
    "src/my_pa/domain/situation/issue_lifecycle.py",
    "src/my_pa/application/issues.py",
    "src/my_pa/application/record_lineage.py",
    "src/my_pa/application/lineage_endpoints.py",
    "src/my_pa/application/lineage_authority.py",
    "src/my_pa/infrastructure/persistence/issues.py",
    "src/my_pa/infrastructure/persistence/record_lineage.py",
    "src/my_pa/contracts/v1/issues.py",
    "src/my_pa/contracts/v1/record_lineage.py",
)

#: Anything that stages, drafts, writes or names a Record Event.
_RECORD_EVENT_REACH: Final = re.compile(
    r"record_events|RecordEvent|record_event_family|stage_record_event"
)
#: DDL or DML against the feed, or its family CHECK, in a revision.
_FEED_DDL: Final = re.compile(r"knowledge\.record_events\b|a_record_event_family_is_known")

_BACKTICKED: Final = re.compile(r"`([^`]+)`")
_PYTHON_TEST: Final = re.compile(r"\Atest_\w+\Z")
_MODULE_PATH: Final = re.compile(r"\A(?:tests|web)/\S+\.(?:py|ts|tsx)\Z")
_TS_SUFFIXES: Final = frozenset({".ts", ".tsx"})


def test_s1_adds_no_record_event_family() -> None:
    assert {member.value for member in RecordEventFamily} == BASIS_RECORD_EVENT_FAMILIES
    revision = S1_REVISION.read_text(encoding="utf-8")
    assert _FEED_DDL.search(revision) is None, "the S1 revision reaches the Record Event feed"
    reaching = [
        path
        for path in S1_MODULES
        if _RECORD_EVENT_REACH.search((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert reaching == [], f"S1 modules that reach the Record Event feed: {reaching}"


@cache
def _crosswalk_rows() -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    """Each section 10 row as (AT cell, module paths, backticked test-cell tokens)."""
    text = CONTRACT.read_text(encoding="utf-8")
    start = text.index("\n## 10. Acceptance-test crosswalk\n")
    end = text.index("\n## 11. ", start)
    rows: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for line in text[start:end].splitlines():
        if not line.startswith("| ") or line.startswith("| AT (S1 part)") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        assert len(cells) == 4, line
        at, modules_cell, tests_cell, _tier = cells
        modules = tuple(
            token for token in _BACKTICKED.findall(modules_cell) if _MODULE_PATH.match(token)
        )
        rows.append((at, modules, tuple(_BACKTICKED.findall(tests_cell))))
    return tuple(rows)


@cache
def _python_functions(path: str) -> frozenset[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    return frozenset(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )


def _has_title(path: str, title: str) -> bool:
    source = (ROOT / path).read_text(encoding="utf-8")
    return any(f"{quote}{title}{quote}" in source for quote in ('"', "'", "`"))


def test_every_s1_crosswalk_test_exists() -> None:
    rows = _crosswalk_rows()
    assert len(rows) >= 20, "the section 10 table did not parse"
    missing: list[str] = []
    for at, modules, tokens in rows:
        assert modules, f"{at}: no module path"
        for module in modules:
            if not (ROOT / module).is_file():
                missing.append(f"{at}: module {module}")
        python = [module for module in modules if module.endswith(".py")]
        typescript = [module for module in modules if Path(module).suffix in _TS_SUFFIXES]
        names = [token for token in tokens if _PYTHON_TEST.match(token)]
        # A title is prose: a vitest/playwright row's tokens that are not
        # identifiers. Python rows carry backticked tokens with spaces too
        # (`archived: true`), so titles are read only where a TS module is.
        titles = [token for token in tokens if " " in token] if typescript else []
        assert names or titles, f"{at}: no test named"
        for name in names:
            if not any(name in _python_functions(module) for module in python):
                missing.append(f"{at}: {name} in {python}")
        for title in titles:
            if not any(_has_title(module, title) for module in typescript):
                missing.append(f"{at}: {title!r} in {typescript}")
    assert missing == [], "crosswalk tests that do not exist:\n" + "\n".join(missing)
