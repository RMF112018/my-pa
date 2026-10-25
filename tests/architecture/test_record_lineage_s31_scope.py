"""Record lineage S3.1 scope guard (S3.1 contract section 10).

Four FAST guards over the committed tree:

* **The crosswalk is real** (worker N4). Every test the section 10 crosswalk
  binds exists -- a row's `test_*` names are functions defined in one of that
  row's modules -- and so does every function the section 10.1 conversion
  tables name.
* **No Record Event family** (N4). S3.1 adds no Record Event family: the closed
  `RecordEventFamily` is still exactly the 23 families of the S1 basis, and the
  S3.1 revision never touches `knowledge.record_events` or its family CHECK.
* **No gate reads the `user_directed` claim** (N4, R31-F06). The tokens
  `user_directed_claim` and `user_directed` appear nowhere in the close-gate
  domain module, the S4 reportability module and the rate check, nor -- by AST
  -- in the bodies of `IssueApplication.close_issue`, of
  `IssueApplication.closure_readiness` (but for its `UnreviewedLinkView`
  construction, which displays the claim) and of the lineage verification
  comparator `source_manifest.lineage_verification_state`. The claim is read
  only to store it (`lineage_write_provenance`) and to count it in a manifest
  (`lineage_server_counts`), each exempt by name.
* **The web decoders admit exactly the server vocabulary** (worker N3): after
  S3.1 the strict web client's lineage decoders admit exactly the server's
  closed sets -- `client_identified` beside `user_confirmed`, and the
  timeline's `confirm` action -- so a value outside them still refuses the
  whole answer.

What it cannot prove: that a named test is collected and passes (the tiers run
them), or that a gate does not reach the claim through a helper outside the
named bodies (the invariance test `test_the_user_directed_claim_changes_no_outcome`
pins the outcomes).
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Final

from tests.architecture.test_record_lineage_s1_scope import BASIS_RECORD_EVENT_FAMILIES
from tests.architecture.test_record_lineage_s2_scope import _python_functions

from my_pa.application.commands import MAX_RELATED_DEPTH
from my_pa.application.issues import IssueApplication
from my_pa.application.lineage_authority import lineage_write_provenance
from my_pa.domain.intelligence import source_manifest
from my_pa.domain.lineage.vocabulary import (
    AcceptanceBasis,
    EvidenceAvailability,
    HandoffCorrectionAction,
    IssueProjectMembershipAction,
    LineageCompleteness,
    LinkLifecycleState,
    LinkRevisionAction,
    RelationType,
    TimelineEntryKind,
)
from my_pa.domain.record_events import RecordEventFamily

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT: Final = ROOT / "docs" / "architecture" / "record-lineage-s31-open-writes-contract.md"
#: Found by its slug, not its revision id, so this guard is not one more head pin.
(S31_REVISION,) = sorted((ROOT / "migrations" / "versions").glob("*_record_lineage_s31.py"))
DECODERS: Final = ROOT / "web" / "src" / "lib" / "api" / "decode" / "capabilities"
TIMELINE_VIEW: Final = ROOT / "web" / "src" / "components" / "issues" / "issue-timeline.tsx"
_TS_CONST_ARRAY: Final = r"export const {name} = \[(?P<body>[^\]]*)\] as const;"
_TS_STRING: Final = re.compile(r'"([^"]*)"')
_TS_RECORD: Final = r"const {name}: Readonly<Record<string, string>> = \{{(?P<body>[^}}]*)\}};"
_TS_KEY: Final = re.compile(r"^\s*([a-z_]+):", re.M)


def _decoder_set(module: str, name: str) -> list[str]:
    path = DECODERS / module
    found = re.search(_TS_CONST_ARRAY.format(name=name), path.read_text(encoding="utf-8"))
    assert found is not None, f"{name} is not a const array in {path.name}"
    return _TS_STRING.findall(found.group("body"))


def _record_keys(name: str) -> set[str]:
    found = re.search(_TS_RECORD.format(name=name), TIMELINE_VIEW.read_text(encoding="utf-8"))
    assert found is not None, f"{name} is not a string record in {TIMELINE_VIEW.name}"
    return set(_TS_KEY.findall(found.group("body")))


def test_the_web_lineage_decoders_admit_exactly_the_server_vocabulary_after_s31() -> None:
    lineage = "records.lineage.ts"
    # S3.1 sections 4.1 and 8: the one widened closed set, in vocabulary order.
    assert _decoder_set(lineage, "ACCEPTANCE_BASES") == [member.value for member in AcceptanceBasis]
    # Every S3 closed set is unchanged.
    assert _decoder_set(lineage, "RELATION_TYPES") == [member.value for member in RelationType]
    assert _decoder_set(lineage, "LINK_LIFECYCLE_STATES") == [
        member.value for member in LinkLifecycleState
    ]
    assert _decoder_set(lineage, "EVIDENCE_AVAILABILITIES") == [
        member.value for member in EvidenceAvailability
    ]
    assert _decoder_set(lineage, "LINEAGE_COMPLETENESS") == [
        member.value for member in LineageCompleteness
    ]
    timeline = "issues.timeline.ts"
    assert _decoder_set(timeline, "TIMELINE_ENTRY_KINDS") == [
        member.value for member in TimelineEntryKind
    ]
    assert _decoder_set(timeline, "HANDOFF_CORRECTION_ACTIONS") == [
        member.value for member in HandoffCorrectionAction
    ]
    # The decoders that show a fact's basis share the one closed set.
    for module in ("issues.read.ts", "issues.timeline.ts"):
        text = (DECODERS / module).read_text(encoding="utf-8")
        assert "enumeration(ACCEPTANCE_BASES)" in text, module
        assert 'enumeration(["user_confirmed"])' not in text, module
    # The timeline names every link and Project-link action, `confirm` included.
    assert _record_keys("LINK_ACTIONS") == {member.value for member in LinkRevisionAction}
    assert _record_keys("PROJECT_ACTIONS") == {
        member.value for member in IssueProjectMembershipAction
    }


# ---- the crosswalk, the Record Event feed and the claim (worker N4) ----------------

_HEADER: Final = "| Concern | Module | Test functions | Tier |"
_CONVERSION_HEADER: Final = "| Module::name | Old assertion | New assertion | Owner |"
_BACKTICKED: Final = re.compile(r"`([^`]+)`")
_PYTHON_TEST: Final = re.compile(r"\Atest_\w+\Z")
_MODULE_PATH: Final = re.compile(r"\Atests/\S+\.py\Z")
_CONVERSION: Final = re.compile(r"\A(tests/\S+\.py)::(test_\w+)\Z")
#: DDL or DML against the feed, or its family CHECK, in a revision.
_FEED_DDL: Final = re.compile(r"knowledge\.record_events\b|a_record_event_family_is_known")
#: R31-F06: the claim's tokens (`user_directed` is a prefix of `user_directed_claim`).
_CLAIM: Final = "user_directed"
#: Modules that may never name the claim at all.
_CLAIM_FREE_MODULES: Final = (
    "src/my_pa/domain/lineage/closure.py",
    "src/my_pa/domain/program/reportability.py",
    "src/my_pa/application/lineage_rate.py",
)
#: The one construction inside the readiness read that displays the claim.
_DISPLAY_EXEMPTION: Final = "UnreviewedLinkView"


def _section_10() -> list[str]:
    text = CONTRACT.read_text(encoding="utf-8")
    start = text.index("\n## 10. Acceptance-test crosswalk\n")
    end = text.index("\n## 11. ", start)
    return text[start:end].splitlines()


def _crosswalk_rows() -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    """Each section 10 crosswalk row as (concern, module paths, backticked test-cell tokens)."""
    lines = _section_10()
    first = lines.index(_HEADER)
    rows: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for line in lines[first + 2 :]:
        if not line.startswith("| "):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        assert len(cells) == 4, line
        concern, modules_cell, tests_cell, _tier = cells
        modules = tuple(
            token for token in _BACKTICKED.findall(modules_cell) if _MODULE_PATH.match(token)
        )
        rows.append((concern, modules, tuple(_BACKTICKED.findall(tests_cell))))
    return tuple(rows)


def _conversions() -> list[tuple[str, str]]:
    """Every `module::name` the section 10.1 conversion tables bind."""
    found: list[tuple[str, str]] = []
    for line in _section_10():
        if not line.startswith("| `tests/"):
            continue
        first_cell = line.strip().strip("|").split(" | ")[0]
        for token in _BACKTICKED.findall(first_cell):
            matched = _CONVERSION.match(token)
            if matched is not None:
                found.append((matched.group(1), matched.group(2)))
    return found


def test_every_s31_crosswalk_test_exists() -> None:
    rows = _crosswalk_rows()
    assert len(rows) >= 20, "the section 10 crosswalk did not parse"
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
            if not any(
                (ROOT / module).is_file() and name in _python_functions(module)
                for module in modules
            ):
                missing.append(f"{concern}: {name} in {modules}")
    conversions = _conversions()
    assert len(conversions) >= 12, "the section 10.1 conversion tables did not parse"
    for module, name in conversions:
        if not (ROOT / module).is_file() or name not in _python_functions(module):
            missing.append(f"section 10.1: {module}::{name}")
    assert missing == [], "crosswalk tests that do not exist:\n" + "\n".join(missing)
    assert named >= 150, named


def test_s31_adds_no_record_event_family() -> None:
    assert {member.value for member in RecordEventFamily} == BASIS_RECORD_EVENT_FAMILIES
    revision = S31_REVISION.read_text(encoding="utf-8")
    assert _FEED_DDL.search(revision) is None, "the S3.1 revision reaches the Record Event feed"


def _function_node(function: Callable[..., object]) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    (node,) = tree.body
    assert isinstance(node, ast.FunctionDef), function.__qualname__
    return node


def _claim_reads(node: ast.AST, *, exempt: str | None = None) -> list[str]:
    """Every name, attribute, keyword or string under `node` that names the claim.

    A call of `exempt` (a display constructor) is skipped whole.
    """
    found: list[str] = []
    for child in ast.iter_child_nodes(node):
        if (
            exempt is not None
            and isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == exempt
        ):
            continue
        token: str | None = None
        if isinstance(child, ast.Name):
            token = child.id
        elif isinstance(child, ast.Attribute):
            token = child.attr
        elif isinstance(child, ast.keyword):
            token = child.arg
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            token = child.value
        if token is not None and _CLAIM in token:
            found.append(f"{type(child).__name__} {token} (line {getattr(child, 'lineno', '?')})")
        found.extend(_claim_reads(child, exempt=exempt))
    return found


def test_no_gate_reads_the_user_directed_claim() -> None:
    for path in _CLAIM_FREE_MODULES:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert _CLAIM not in text, f"{path} names the user_directed claim"
    assert _claim_reads(_function_node(IssueApplication.close_issue)) == []
    readiness = _function_node(IssueApplication.closure_readiness)
    assert _claim_reads(readiness, exempt=_DISPLAY_EXEMPTION) == []
    # The exemption is real: the readiness read does display the claim.
    assert _claim_reads(readiness) != []
    comparator = _function_node(source_manifest.lineage_verification_state)
    assert _claim_reads(comparator) == []
    # The claim is stored and counted, by name, and nowhere upgrades a class.
    assert _claim_reads(_function_node(lineage_write_provenance)) != []
    assert _claim_reads(_function_node(source_manifest.lineage_server_counts)) != []
    # The block's depth bound is the related read's own (section 7.9).
    assert source_manifest._MAX_RELATED_DEPTH == MAX_RELATED_DEPTH
