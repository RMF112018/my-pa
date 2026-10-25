"""Record lineage S3.1 scope guard (S3.1 contract section 10).

Worker N3 lands the web-decoder vocabulary row: after S3.1 the strict web
client's lineage decoders admit exactly the server's closed sets --
`client_identified` beside `user_confirmed`, and the timeline's `confirm`
action -- so a value outside them still refuses the whole answer. The scope
guard's crosswalk, Record Event and `user_directed` rows are worker N4's.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

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

ROOT: Final = Path(__file__).resolve().parents[2]
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
