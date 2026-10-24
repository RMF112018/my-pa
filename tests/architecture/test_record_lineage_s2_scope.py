"""AT-026 (S2): record lineage S2 stays inside its slice (S2 contract sections 6.4, 10 and 12).

Three FAST guards over the committed tree:

* **No Record Event family.** S2 adds no Record Event family (D-15: the
  Record Event family for lineage is S3). The closed `RecordEventFamily` is
  still exactly the twenty-three families it held at the S1 basis, and the S2
  revision never touches `knowledge.record_events` or its family CHECK.
* **No lineage Record Event.** No S2 lineage module stages, drafts or names a
  Record Event. A composite's native create stages its existing `task` or
  `commitment` event inside the native service it calls (section 6.4), so the
  composite module itself reaches no Record Event either.
* **The web decoder moves in lockstep.** The `records.lineage` decoder's two
  closed sets S2 widens (section 7.4) equal the server vocabulary, read from
  the TypeScript source: `RELATION_TYPES` is `RelationType`, `ISSUE_STATES` is
  `ISSUE_STATES`, in declaration order (the vitest
  `decodes the S2 relation types and a closed Issue` pins the same literals
  from the web side).
* **The crosswalk is real.** Every test the section 10 crosswalk binds exists:
  a Python row's `test_*` names are functions defined in one of that row's
  Python modules, and a vitest row's titles are string literals in one of that
  row's TypeScript modules. A renamed test must update the table in the same
  commit (section 10).

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

from tests.architecture.test_record_lineage_s1_scope import (
    BASIS_RECORD_EVENT_FAMILIES,
    S1_MODULES,
)

from my_pa.domain.lineage.vocabulary import ISSUE_STATES, RelationType
from my_pa.domain.record_events import RecordEventFamily

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT: Final = ROOT / "docs" / "architecture" / "record-lineage-s2-contract.md"
#: Found by its slug, not its revision id, so this guard is not one more
#: head pin (`test_the_head_pin_list_is_the_files_that_actually_pin_the_head`).
(S2_REVISION,) = sorted((ROOT / "migrations" / "versions").glob("*_record_lineage_s2.py"))

#: The modules S2 added (section 9); with the S1 modules, none may reach the feed.
S2_MODULES: Final = (
    "src/my_pa/domain/lineage/closure.py",
    "src/my_pa/domain/lineage/handoff.py",
    "src/my_pa/application/issue_handoffs.py",
    "src/my_pa/application/issue_work.py",
    "src/my_pa/infrastructure/persistence/issue_handoffs.py",
)

#: Anything that stages, drafts, writes or names a Record Event.
_RECORD_EVENT_REACH: Final = re.compile(
    r"record_events|RecordEvent|record_event_family|stage_record_event"
)
#: DDL or DML against the feed, or its family CHECK, in a revision.
_FEED_DDL: Final = re.compile(r"knowledge\.record_events\b|a_record_event_family_is_known")

DECODER: Final = (
    ROOT / "web" / "src" / "lib" / "api" / "decode" / "capabilities" / "records.lineage.ts"
)
#: `export const NAME = [ "a", "b", ... ] as const;` in the decoder source.
_TS_CONST_ARRAY: Final = r"export const {name} = \[(?P<body>[^\]]*)\] as const;"
_TS_STRING: Final = re.compile(r'"([^"]*)"')

_HEADER: Final = "| AT (S2 part) | Module | Test functions | Tier |"
_BACKTICKED: Final = re.compile(r"`([^`]+)`")
_PYTHON_TEST: Final = re.compile(r"\Atest_\w+\Z")
_MODULE_PATH: Final = re.compile(r"\A(?:tests|web)/\S+\.(?:py|ts|tsx)\Z")
_TS_SUFFIXES: Final = frozenset({".ts", ".tsx"})


def test_s2_adds_no_record_event_family() -> None:
    assert {member.value for member in RecordEventFamily} == BASIS_RECORD_EVENT_FAMILIES
    revision = S2_REVISION.read_text(encoding="utf-8")
    assert _FEED_DDL.search(revision) is None, "the S2 revision reaches the Record Event feed"


def test_s2_modules_stage_no_lineage_record_event() -> None:
    for path in S2_MODULES:
        assert (ROOT / path).is_file(), path
    reaching = [
        path
        for path in (*S1_MODULES, *S2_MODULES)
        if _RECORD_EVENT_REACH.search((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert reaching == [], f"lineage modules that reach the Record Event feed: {reaching}"


def _decoder_set(name: str) -> list[str]:
    source = DECODER.read_text(encoding="utf-8")
    found = re.search(_TS_CONST_ARRAY.format(name=name), source)
    assert found is not None, f"{name} is not a const array in {DECODER.name}"
    return _TS_STRING.findall(found.group("body"))


def test_the_web_lineage_decoder_admits_exactly_the_server_vocabulary() -> None:
    assert _decoder_set("RELATION_TYPES") == [member.value for member in RelationType]
    assert set(_decoder_set("ISSUE_STATES")) == ISSUE_STATES
    assert len(_decoder_set("ISSUE_STATES")) == len(ISSUE_STATES)


@cache
def _crosswalk_rows() -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    """Each crosswalk row as (AT cell, module paths, backticked test-cell tokens).

    Section 10 holds three tables (the crosswalk, the AT-001 stage map and the
    prove-red table); only the first, the one under `_HEADER`, binds tests.
    """
    text = CONTRACT.read_text(encoding="utf-8")
    start = text.index("\n## 10. Acceptance-test crosswalk\n")
    end = text.index("\n## 11. ", start)
    lines = text[start:end].splitlines()
    first = lines.index(_HEADER)
    rows: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for line in lines[first + 2 :]:
        if not line.startswith("| "):
            break
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


def test_every_s2_crosswalk_test_exists() -> None:
    rows = _crosswalk_rows()
    assert len(rows) >= 16, "the section 10 crosswalk did not parse"
    missing: list[str] = []
    for at, modules, tokens in rows:
        assert modules, f"{at}: no module path"
        for module in modules:
            if not (ROOT / module).is_file():
                missing.append(f"{at}: module {module}")
        python = [module for module in modules if module.endswith(".py")]
        typescript = [module for module in modules if Path(module).suffix in _TS_SUFFIXES]
        names = [token for token in tokens if _PYTHON_TEST.match(token)]
        # A title is prose: a vitest row's tokens that are not identifiers.
        # Python rows carry backticked tokens with spaces too, so titles are
        # read only where a TypeScript module is.
        titles = [token for token in tokens if " " in token] if typescript else []
        assert names or titles, f"{at}: no test named"
        for name in names:
            if not any(name in _python_functions(module) for module in python):
                missing.append(f"{at}: {name} in {python}")
        for title in titles:
            if not any(_has_title(module, title) for module in typescript):
                missing.append(f"{at}: {title!r} in {typescript}")
    assert missing == [], "crosswalk tests that do not exist:\n" + "\n".join(missing)
