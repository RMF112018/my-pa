"""AT-026 (S3): record lineage S3 stays inside its slice (S3 contract sections 7.3, 10 and 12).

Four FAST guards over the committed tree:

* **No Record Event family.** S3 adds no Record Event family (D-06: commit
  marks are the lineage receipts). The closed `RecordEventFamily` is still
  exactly the twenty-three families it held at the S1 basis, and the S3
  revision never touches `knowledge.record_events` or its family CHECK.
* **No lineage Record Event.** No S3 lineage module stages, drafts or names a
  Record Event — except the three `issues.timeline` modules and the two that
  name the timeline's watermark, which *read* the feed (section 7.3: the
  native plane through the Record Event reader's own predicate) and are held
  to the narrower rule that they stage, draft and write none. The S1 and S2
  modules stay under the strict rule.
* **The web decoders move in lockstep.** Every closed set the web lineage
  decoders admit (`records.lineage.ts` and `issues.timeline.ts`, section 7.6)
  equals the server vocabulary, read from the TypeScript source in
  declaration order.
* **The crosswalk is real.** Every test the section 10 crosswalk binds exists:
  a Python row's `test_*` names are functions defined in one of that row's
  Python modules, and a vitest or Playwright row's titles are string literals
  in one of that row's TypeScript modules.

What it cannot prove: that a named test is collected and passes (the tiers
run them). Every identity here is a repository path or a token.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from tests.architecture.test_record_lineage_s1_scope import (
    BASIS_RECORD_EVENT_FAMILIES,
    S1_MODULES,
)
from tests.architecture.test_record_lineage_s2_scope import (
    S2_MODULES,
    _has_title,
    _python_functions,
)

from my_pa.domain.lineage.vocabulary import (
    ISSUE_STATES,
    EvidenceAvailability,
    HandoffCorrectionAction,
    LineageCompleteness,
    LinkLifecycleState,
    RelationType,
    TimelineEntryKind,
)
from my_pa.domain.record_events import RecordEventFamily

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT: Final = ROOT / "docs" / "architecture" / "record-lineage-s3-contract.md"
#: Found by its slug, not its revision id, so this guard is not one more head pin.
(S3_REVISION,) = sorted((ROOT / "migrations" / "versions").glob("*_record_lineage_s3.py"))

#: The S3 modules (section 9) that neither read nor write the feed.
S3_MODULES: Final = (
    "src/my_pa/domain/lineage/asof.py",
    "src/my_pa/domain/lineage/backfill.py",
    "src/my_pa/domain/lineage_backfill/__init__.py",
    "src/my_pa/domain/lineage_backfill/vocabulary.py",
    "src/my_pa/application/lineage_backfill.py",
    "src/my_pa/infrastructure/persistence/lineage_backfill.py",
    "src/my_pa/contracts/v1/lineage_backfill.py",
)
#: The S3 modules admitted to read the feed (or name its watermark): they may
#: name a Record Event, never stage, draft or write one (section 7.3, L4).
S3_FEED_READERS: Final = (
    "src/my_pa/application/issue_timeline.py",
    "src/my_pa/contracts/v1/issue_timeline.py",
    "src/my_pa/infrastructure/persistence/issue_timeline.py",
    "src/my_pa/domain/lineage/cursor.py",
    "src/my_pa/application/lineage_visibility.py",
)

#: Anything that stages, drafts, writes or names a Record Event.
_RECORD_EVENT_REACH: Final = re.compile(
    r"record_events|RecordEvent|record_event_family|stage_record_event"
)
#: Anything that stages, drafts or writes one: the stager (`uow.record_events`),
#: its draft and `stage`, or SQL that inserts into the feed.
_RECORD_EVENT_WRITE: Final = re.compile(
    r"RecordEventDraft|RecordEventStager|stage_record_event|\.record_events\.|\.stage\("
    r"|insert\s+into\s+knowledge\.record_events",
    re.IGNORECASE,
)
#: DDL or DML against the feed, or its family CHECK, in a revision.
_FEED_DDL: Final = re.compile(r"knowledge\.record_events\b|a_record_event_family_is_known")

DECODERS: Final = ROOT / "web" / "src" / "lib" / "api" / "decode" / "capabilities"
#: `export const NAME = [ "a", "b", ... ] as const;` in a decoder source.
_TS_CONST_ARRAY: Final = r"export const {name} = \[(?P<body>[^\]]*)\] as const;"
_TS_STRING: Final = re.compile(r'"([^"]*)"')

_HEADER: Final = "| AT (S3 part) | Module | Test functions | Tier |"
_BACKTICKED: Final = re.compile(r"`([^`]+)`")
_PYTHON_TEST: Final = re.compile(r"\Atest_\w+\Z")
_MODULE_PATH: Final = re.compile(r"\A(?:tests|web)/\S+\.(?:py|ts|tsx)\Z")
_TS_SUFFIXES: Final = frozenset({".ts", ".tsx"})


def test_s3_adds_no_record_event_family() -> None:
    assert {member.value for member in RecordEventFamily} == BASIS_RECORD_EVENT_FAMILIES
    revision = S3_REVISION.read_text(encoding="utf-8")
    assert _FEED_DDL.search(revision) is None, "the S3 revision reaches the Record Event feed"


def test_s3_modules_stage_no_lineage_record_event() -> None:
    for path in (*S3_MODULES, *S3_FEED_READERS):
        assert (ROOT / path).is_file(), path
    reaching = [
        path
        for path in (*S1_MODULES, *S2_MODULES, *S3_MODULES)
        if _RECORD_EVENT_REACH.search((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert reaching == [], f"lineage modules that reach the Record Event feed: {reaching}"
    writing = [
        path
        for path in S3_FEED_READERS
        if _RECORD_EVENT_WRITE.search((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert writing == [], f"timeline modules that stage or write a Record Event: {writing}"


def _decoder_set(module: str, name: str) -> list[str]:
    path = DECODERS / module
    found = re.search(_TS_CONST_ARRAY.format(name=name), path.read_text(encoding="utf-8"))
    assert found is not None, f"{name} is not a const array in {path.name}"
    return _TS_STRING.findall(found.group("body"))


def test_the_web_lineage_decoders_admit_exactly_the_server_vocabulary() -> None:
    lineage = "records.lineage.ts"
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
    states = _decoder_set(lineage, "ISSUE_STATES")
    assert set(states) == ISSUE_STATES
    assert len(states) == len(ISSUE_STATES)
    timeline = "issues.timeline.ts"
    assert _decoder_set(timeline, "TIMELINE_ENTRY_KINDS") == [
        member.value for member in TimelineEntryKind
    ]
    assert _decoder_set(timeline, "HANDOFF_CORRECTION_ACTIONS") == [
        member.value for member in HandoffCorrectionAction
    ]


def _crosswalk_rows() -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    """Each crosswalk row as (AT cell, module paths, backticked test-cell tokens).

    Section 10 holds three tables (the crosswalk, the AT-001 stage list and the
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


def test_every_s3_crosswalk_test_exists() -> None:
    rows = _crosswalk_rows()
    assert len(rows) >= 28, "the section 10 crosswalk did not parse"
    missing: list[str] = []
    for at, modules, tokens in rows:
        assert modules, f"{at}: no module path"
        for module in modules:
            if not (ROOT / module).is_file():
                missing.append(f"{at}: module {module}")
        python = [module for module in modules if module.endswith(".py")]
        typescript = [module for module in modules if Path(module).suffix in _TS_SUFFIXES]
        names = [token for token in tokens if _PYTHON_TEST.match(token)]
        # A title is prose: a vitest or Playwright row's tokens that are not
        # identifiers. Python rows carry backticked prose too, so titles are
        # read only where a TypeScript module is.
        titles = [token for token in tokens if " " in token] if typescript else []
        assert names or titles, f"{at}: no test named"
        for name in names:
            if not any(
                (ROOT / module).is_file() and name in _python_functions(module) for module in python
            ):
                missing.append(f"{at}: {name} in {python}")
        for title in titles:
            if not any(
                (ROOT / module).is_file() and _has_title(module, title) for module in typescript
            ):
                missing.append(f"{at}: {title!r} in {typescript}")
    assert missing == [], "crosswalk tests that do not exist:\n" + "\n".join(missing)
