"""AT-026 (S4): record lineage S4 stays inside its slice (S4 contract sections 3, 8, 10 and 12).

Four FAST guards over the committed tree:

* **The crosswalk is real.** Every test the section 10 crosswalk binds exists:
  a row's `test_*` names are functions defined in one of that row's modules.
* **No Record Event family.** S4 adds no Record Event family: the closed
  `RecordEventFamily` is still exactly the 23 families of the S1 basis, and the
  S4 revision never touches `knowledge.record_events` or its family CHECK.
* **No Record Event staged by an S4 read.** All 7 S4 capabilities are reads
  (section 6.1): no S4 module, and none of the 7 handlers or the commit-time
  recompute in `ApplicationService`, reaches, stages, drafts or writes a Record
  Event.
* **No lineage vocabulary changes.** Program answers are not lineage reads
  (D-13): `domain/lineage/vocabulary.py` is byte-identical to the S3 basis, its
  completeness set gains neither `not_reportable` nor
  `source_not_integrated`, and `domain/program` imports nothing from
  `domain/lineage` but `canonical`.

What it cannot prove: that a named test is collected and passes (the tiers
run them). Every identity here is a repository path or a token.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import re
from pathlib import Path
from typing import Final

from tests.architecture.test_record_lineage_s1_scope import BASIS_RECORD_EVENT_FAMILIES
from tests.architecture.test_record_lineage_s2_scope import _python_functions

from my_pa.application.service import ApplicationService
from my_pa.domain.lineage.vocabulary import LineageCompleteness
from my_pa.domain.record_events import RecordEventFamily

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT: Final = ROOT / "docs" / "architecture" / "record-lineage-s4-program-contract.md"
#: Found by its slug, not its revision id, so this guard is not one more head pin.
(S4_REVISION,) = sorted((ROOT / "migrations" / "versions").glob("*_record_lineage_s4.py"))

#: The S4 modules (section 9).
S4_MODULES: Final = (
    "src/my_pa/domain/program/__init__.py",
    "src/my_pa/domain/program/vocabulary.py",
    "src/my_pa/domain/program/membership.py",
    "src/my_pa/domain/program/reportability.py",
    "src/my_pa/domain/program/digest.py",
    "src/my_pa/domain/intelligence/source_manifest.py",
    "src/my_pa/application/program_membership.py",
    "src/my_pa/application/program_work.py",
    "src/my_pa/application/program_constraints.py",
    "src/my_pa/application/commitments_v2.py",
    "src/my_pa/infrastructure/persistence/program_reads.py",
    "src/my_pa/infrastructure/persistence/program_membership.py",
    "src/my_pa/infrastructure/persistence/program_metrics.py",
    "src/my_pa/contracts/v1/programs.py",
    "src/my_pa/contracts/v1/commitments_v2.py",
    "src/my_pa/contracts/v1/report_manifests.py",
)
#: The S4 code inside `ApplicationService`: the 7 handlers and the recompute.
S4_HANDLERS: Final = (
    "_programs_members_resolve",
    "_programs_overview",
    "_commitments_v2_read",
    "_commitments_v2_list",
    "_commitments_v2_search",
    "_commitments_v2_waiting_on",
    "_reports_manifest",
    "_program_reference_recompute",
    "_program_plane",
    "_program_read_plane",
)

#: S3 basis digest of `domain/lineage/vocabulary.py` (unchanged since `75707a8b`).
LINEAGE_VOCABULARY_SHA256: Final = (
    "64faec74fa514118c74064e74b88b29177f0027fb964eae4aec3d3c457b3f756"
)
#: The S3 section 3 names S3 listed as "Program work"; S4 adds them nowhere (D-13).
NOT_LINEAGE: Final = frozenset({"not_reportable", "source_not_integrated"})

#: Anything that stages, drafts, writes or names a Record Event.
_RECORD_EVENT_REACH: Final = re.compile(
    r"record_events|RecordEvent|record_event_family|stage_record_event"
)
#: DDL or DML against the feed, or its family CHECK, in a revision.
_FEED_DDL: Final = re.compile(r"knowledge\.record_events\b|a_record_event_family_is_known")

_HEADER: Final = "| AT (S4 part) | Module | Test functions | Tier |"
_BACKTICKED: Final = re.compile(r"`([^`]+)`")
_PYTHON_TEST: Final = re.compile(r"\Atest_\w+\Z")
_MODULE_PATH: Final = re.compile(r"\Atests/\S+\.py\Z")


def _crosswalk_rows() -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    """Each crosswalk row as (AT cell, module paths, backticked test-cell tokens).

    Section 10 holds 2 tables (the crosswalk and the prove-red table); only the
    first, the one under `_HEADER`, binds tests.
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


def test_every_s4_crosswalk_test_exists() -> None:
    rows = _crosswalk_rows()
    assert len(rows) >= 16, "the section 10 crosswalk did not parse"
    missing: list[str] = []
    named = 0
    for at, modules, tokens in rows:
        assert modules, f"{at}: no module path"
        for module in modules:
            if not (ROOT / module).is_file():
                missing.append(f"{at}: module {module}")
        names = [token for token in tokens if _PYTHON_TEST.match(token)]
        assert names, f"{at}: no test named"
        named += len(names)
        for name in names:
            if not any(
                (ROOT / module).is_file() and name in _python_functions(module)
                for module in modules
            ):
                missing.append(f"{at}: {name} in {modules}")
    assert missing == [], "crosswalk tests that do not exist:\n" + "\n".join(missing)
    assert named >= 140, named


def test_s4_adds_no_record_event_family() -> None:
    assert {member.value for member in RecordEventFamily} == BASIS_RECORD_EVENT_FAMILIES
    revision = S4_REVISION.read_text(encoding="utf-8")
    assert _FEED_DDL.search(revision) is None, "the S4 revision reaches the Record Event feed"


def test_s4_reads_stage_no_record_event() -> None:
    for path in S4_MODULES:
        assert (ROOT / path).is_file(), path
    reaching = [
        path
        for path in S4_MODULES
        if _RECORD_EVENT_REACH.search((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert reaching == [], f"S4 modules that reach the Record Event feed: {reaching}"
    handlers = [
        name
        for name in S4_HANDLERS
        if _RECORD_EVENT_REACH.search(inspect.getsource(getattr(ApplicationService, name)))
        or "record_event" in inspect.getsource(getattr(ApplicationService, name))
    ]
    assert handlers == [], f"S4 handlers that reach the Record Event feed: {handlers}"


def _lineage_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module.startswith("my_pa.domain.lineage"):
                found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(
                alias.name for alias in node.names if alias.name.startswith("my_pa.domain.lineage")
            )
    return found


def test_s4_changes_no_lineage_vocabulary() -> None:
    vocabulary = ROOT / "src" / "my_pa" / "domain" / "lineage" / "vocabulary.py"
    assert hashlib.sha256(vocabulary.read_bytes()).hexdigest() == LINEAGE_VOCABULARY_SHA256
    assert not NOT_LINEAGE & {member.value for member in LineageCompleteness}
    program = ROOT / "src" / "my_pa" / "domain" / "program"
    modules = sorted(program.glob("*.py"))
    assert len(modules) >= 5
    for module in modules:
        assert _lineage_imports(module) <= {"my_pa.domain.lineage.canonical"}, module.name
