"""AT-011 (section 6.4 on every remote read): what a remote reader may not see stays unseen.

S3 contract sections 6.4, 7.1 and 7.3 against PostgreSQL through
`ApplicationService.invoke`, pinning the remote-reader guards the final review
FR3 found unpinned or broken (FR3-F01..F04):

* `issues.handoffs.list` fills its pages from the visible handoffs only: no
  withheld handoff's identifier ever appears -- not as an entry, not as a
  cursor -- and the page sequence does not depend on how many are withheld;
  `issues.read`'s `memberships_truncated` counts visible members only;
* a timeline reader without Commitment visibility sees no handoff or
  correction entry and is told `restricted_evidence`;
* readiness withholds a contested link to a record the reader may not see;
* a link history with an invisible endpoint, or naming an Issue the reader may
  not see, and an Issue history without Issue visibility, answer exactly as
  absent ones;
* both history reads say `restricted` when evidence was withheld.

Every identity and every body is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from tests.database.lineage_record_harness import NOTE_BODY, capture, capture_anchor
from tests.database.lineage_s2_harness import close, handoff
from tests.database.lineage_s3_harness import (
    GATEWAY,
    blocks_scene,
    contest,
    contradicts,
    correct_handoff,
    shortly_after,
)
from tests.database.lineage_s3_read_harness import S3ReadRuntime, grant

from my_pa.application import record_lineage as lineage_module
from my_pa.application import service as service_module
from my_pa.application.commands import (
    ListIssueHandoffs,
    ReadIssue,
    ReadIssueClosureReadiness,
    ReadIssueHistory,
    ReadIssueTimeline,
    ReadRecordAssociationHistory,
)
from my_pa.application.issue_handoffs import IssueHandoffApplication
from my_pa.infrastructure.persistence import issues as issues_persistence
from my_pa.infrastructure.persistence.issue_handoffs import SqlIssueHandoffRepository
from my_pa.infrastructure.persistence.record_lineage import SqlRecordLineageRepository

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _code(error: dict[str, Any]) -> tuple[str, list[str]]:
    return str(error["code"]), list(error.get("safe_details") or [])


# ---- FR3-F01: issues.handoffs.list and memberships_truncated ---------------------------------


def _handoff_issue(runtime: S3ReadRuntime, key: str, sources: str) -> dict[str, Any]:
    """One Issue; per letter of `sources` a Commitment with one handoff, in order.

    `v` cites a Capture version (visible with `capture.read`), `h` a Meeting
    note (hidden from a reader without a Meeting read).
    """
    issue = runtime.issue(key)
    shown: list[str] = []
    hidden: list[str] = []
    for number, source in enumerate(sources):
        name = f"{key}-{number}"
        commitment = runtime.commitment(name)
        runtime.member(issue, "commitment", commitment, name, "discussion")
        created = str(runtime.commitment_view(commitment)["created_at"])
        if source == "v":
            capture_id, version_id, _ = capture(runtime, f"{name}-c")
            anchor = capture_anchor(capture_id, version_id, NOTE_BODY, role="handoff")
        else:
            anchor = runtime.handoff_anchor(f"{name}-m")
        written = runtime.ok(
            handoff(issue, commitment, "counterparty", shortly_after(created, 1000), name, anchor),
            surface=GATEWAY,
        )["handoff"]
        (shown if source == "v" else hidden).append(str(written["handoff_id"]))
    return {"issue": issue, "shown": shown, "hidden": hidden}


def _handoff_pages(runtime: S3ReadRuntime, issue: str, grants: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    pages: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        page = runtime.ok(
            ListIssueHandoffs(issue_id=issue, page_size=1, after=after), grants=grants
        )
        pages.append(page)
        after = page["next_cursor"]
        if after is None:
            return pages
        assert len(pages) < 50


def test_handoff_pages_never_name_a_withheld_handoff(runtime: S3ReadRuntime) -> None:
    reader = grant("issues.handoffs.list", "issues.read", "commitments.read", "capture.read")
    shapes = []
    # Two visible handoffs, with two and then three withheld ones around them.
    for key, sources in (("rv-h2", "hvhv"), ("rv-h3", "hvhvh")):
        scene = _handoff_issue(runtime, key, sources)
        assert len(scene["hidden"]) >= 2
        pages = _handoff_pages(runtime, scene["issue"], reader)
        rendered = json.dumps(pages)
        for identifier in scene["hidden"]:
            assert identifier not in rendered, key
        assert [h["handoff_id"] for page in pages for h in page["handoffs"]] == scene["shown"]
        # Every cursor is a shown entry's identifier.
        assert {page["next_cursor"] for page in pages} - {None} <= set(scene["shown"])
        shapes.append([(len(page["handoffs"]), page["next_cursor"] is None) for page in pages])
        # The local reader sees every handoff.
        local = runtime.ok(ListIssueHandoffs(issue_id=scene["issue"], page_size=100))
        assert len(local["handoffs"]) == len(sources) and local["restricted"] is False
    # The page sequence is the same whatever the number withheld.
    assert shapes[0] == shapes[1] == [(1, False), (1, True)]


def test_memberships_truncated_counts_only_visible_members(runtime: S3ReadRuntime) -> None:
    issue = runtime.issue("rv-members")
    meeting_id, _ = runtime.note("rv-members-m")
    runtime.member(issue, "meeting", meeting_id, "rv-members-m", "discussion")
    for number in range(100):
        task = runtime.task(f"rv-members-{number:03d}")
        runtime.member(issue, "task", task, f"rv-members-{number:03d}", "reference")
    read = ReadIssue(issue_id=issue, include_members=True)
    local = runtime.ok(read)
    assert (len(local["memberships"]), local["memberships_truncated"]) == (100, True)
    # Without the Task read: one visible member, nothing truncated among what it may see.
    remote = runtime.ok(read, grants=grant("issues.read", "meetings.read"))
    assert len(remote["memberships"]) == 1
    assert (remote["memberships_truncated"], remote["restricted"]) == (False, True)


# ---- FR3-F02: four remote-reader guards ------------------------------------------------------


def test_a_timeline_without_commitment_visibility_shows_no_handoff_or_correction(
    runtime: S3ReadRuntime,
) -> None:
    scene = _handoff_issue(runtime, "rv-timeline", "vv")
    first, second = scene["shown"]
    meeting_id, note_id = runtime.note("rv-timeline-void")
    corrected = runtime.ok(
        correct_handoff(second, "void", "rv-timeline", contradicts(meeting_id, note_id)),
        surface=GATEWAY,
    )["correction"]["correction_id"]
    command = ReadIssueTimeline(issue_id=scene["issue"])
    hidden = runtime.ok(command, grants=grant("issues.timeline", "issues.read", "meetings.read"))
    kinds = {entry["kind"] for entry in hidden["entries"]}
    assert not kinds & {"handoff", "handoff_correction"}
    rendered = json.dumps(hidden)
    for identifier in (first, second, corrected):
        assert identifier not in rendered
    assert "restricted_evidence" in hidden["qualifiers"]
    shown = runtime.ok(
        command,
        grants=grant("issues.timeline", "issues.read", "meetings.read", "commitments.read"),
    )
    assert {"handoff", "handoff_correction"} <= {entry["kind"] for entry in shown["entries"]}


def test_readiness_withholds_a_contested_link_to_an_invisible_record(
    runtime: S3ReadRuntime,
) -> None:
    scene = blocks_scene(runtime, "rv-ready")
    runtime.ok(contest(scene["link"], 1, "rv-ready", (scene["contradicts"],)), surface=GATEWAY)
    command = ReadIssueClosureReadiness(issue_id=scene["issue"])
    hidden = runtime.ok(command, grants=grant("issues.closure_readiness", "issues.read"))
    assert (hidden["ready"], hidden["contested_links"], hidden["restricted"]) == (False, [], True)
    assert scene["link"] not in json.dumps(hidden)
    shown = runtime.ok(
        command, grants=grant("issues.closure_readiness", "issues.read", "tasks.read")
    )
    assert [link["link_id"] for link in shown["contested_links"]] == [scene["link"]]
    assert shown["restricted"] is False


def test_association_history_with_an_invisible_endpoint_is_not_found(
    runtime: S3ReadRuntime,
) -> None:
    scene = blocks_scene(runtime, "rv-assoc", context=False)
    reader = grant("records.associations.history", "issues.read")
    hidden = runtime.refused(ReadRecordAssociationHistory(link_id=scene["link"]), grants=reader)
    absent = runtime.refused(
        ReadRecordAssociationHistory(link_id="irl_lineages3absent0001"), grants=reader
    )
    assert _code(hidden) == _code(absent) == ("not_found", ["link_id"])
    seen = runtime.ok(
        ReadRecordAssociationHistory(link_id=scene["link"]), grants=reader | grant("tasks.read")
    )
    assert seen["link"]["link_id"] == scene["link"]


def test_issue_history_without_issue_visibility_is_not_found(runtime: S3ReadRuntime) -> None:
    issue = runtime.issue("rv-issue-history")
    reader = grant("issues.history")
    hidden = runtime.refused(ReadIssueHistory(issue_id=issue), grants=reader)
    absent = runtime.refused(ReadIssueHistory(issue_id="sit_lineages3absent0001"), grants=reader)
    assert _code(hidden) == _code(absent) == ("not_found", ["issue_id"])
    seen = runtime.ok(ReadIssueHistory(issue_id=issue), grants=reader | grant("issues.read"))
    assert [revision["version"] for revision in seen["revisions"]] == [1]


# ---- FR3-F03 and FR3-F04: the two history reads -----------------------------------------------


def test_association_history_of_an_issue_scoped_link_needs_issue_visibility(
    runtime: S3ReadRuntime,
) -> None:
    scene = blocks_scene(runtime, "rv-scoped")
    reader = grant("records.associations.history", "tasks.read")
    hidden = runtime.refused(ReadRecordAssociationHistory(link_id=scene["link"]), grants=reader)
    absent = runtime.refused(
        ReadRecordAssociationHistory(link_id="irl_lineages3absent0001"), grants=reader
    )
    assert _code(hidden) == _code(absent) == ("not_found", ["link_id"])
    assert scene["issue"] not in json.dumps(hidden)
    seen = runtime.ok(
        ReadRecordAssociationHistory(link_id=scene["link"]), grants=reader | grant("issues.read")
    )
    assert seen["link"]["context_issue_id"] == scene["issue"]


def test_history_reads_say_restricted_when_evidence_is_withheld(runtime: S3ReadRuntime) -> None:
    scene = blocks_scene(runtime, "rv-restricted")
    _, _, closing = runtime.evidence_source("rv-restricted-closure")
    runtime.ok(close(scene["issue"], 1, "rv-restricted", (closing,)), surface=GATEWAY)
    without_meetings = grant(
        "issues.history", "records.associations.history", "issues.read", "tasks.read"
    )
    with_meetings = without_meetings | grant("meetings.read")
    for command in (
        ReadIssueHistory(issue_id=scene["issue"]),
        ReadRecordAssociationHistory(link_id=scene["link"]),
    ):
        name = command.capability.value
        hidden = runtime.ok(command, grants=without_meetings)
        assert hidden["restricted"] is True, name
        assert all(revision["evidence"] == [] for revision in hidden["revisions"]), name
        shown = runtime.ok(command, grants=with_meetings)
        assert shown["restricted"] is False, name
        assert any(revision["evidence"] for revision in shown["revisions"]), name
        assert runtime.ok(command)["restricted"] is False, name


# ---- FR3-F08: bounded scans --------------------------------------------------------------------


def test_a_handoff_scan_stops_at_its_bound_without_naming_a_withheld_handoff(
    runtime: S3ReadRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bound and batch moved down so 8 withheld handoffs exceed the bound.
    monkeypatch.setattr(service_module, "_HANDOFF_SCAN_BATCH", 2)
    monkeypatch.setattr(service_module, "_HANDOFF_SCAN_BOUND", 4)
    scene = _handoff_issue(runtime, "rv-bound", "v" + "h" * 8 + "v")
    calls: list[int] = []
    original = IssueHandoffApplication.list_handoffs

    def counted(self: IssueHandoffApplication, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(IssueHandoffApplication, "list_handoffs", counted)
    reader = grant("issues.handoffs.list", "issues.read", "commitments.read", "capture.read")
    envelopes = []
    after: str | None = None
    requests = []
    while True:
        calls.clear()
        envelope = runtime.invoke(
            ListIssueHandoffs(issue_id=scene["issue"], page_size=1, after=after), grants=reader
        ).to_canonical_dict()
        requests.append(len(calls))
        envelopes.append(envelope)
        after = envelope["result"]["next_cursor"]
        if after is None:
            break
        assert len(envelopes) < 10, "paging did not end"
    rendered = json.dumps(envelopes)
    for identifier in scene["hidden"]:
        assert identifier not in rendered
    # Bounded work: at most bound / batch repository reads per request.
    assert max(requests) <= 2
    first, last = envelopes[0], envelopes[-1]
    assert [h["handoff_id"] for h in first["result"]["handoffs"]] == scene["shown"][:1]
    assert first["result"]["next_cursor"] == scene["shown"][0]
    assert first["disclosure"]["truncation"]["is_truncated"] is True
    assert first["disclosure"]["truncation"]["reason"] == "visibility_scan_bound"
    # Paging ends in a stated, non-identifying truncation.
    assert last["result"]["handoffs"] == [] and last["result"]["restricted"] is True
    assert last["disclosure"]["truncation"]["is_truncated"] is True
    assert last["disclosure"]["truncation"]["next_cursor"] is None


def test_a_membership_scan_stops_at_its_bound(
    runtime: S3ReadRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = runtime.issue("rv-mbound")
    meeting_id, _ = runtime.note("rv-mbound-m")
    runtime.member(issue, "meeting", meeting_id, "rv-mbound-m", "discussion")
    for number in range(6):
        task = runtime.task(f"rv-mbound-{number}")
        runtime.member(issue, "task", task, f"rv-mbound-{number}", "reference")
    monkeypatch.setattr(lineage_module, "MEMBERSHIP_SCAN_BATCH", 2)
    monkeypatch.setattr(lineage_module, "MAX_VISIBILITY_SCAN", 4)
    calls: list[int] = []
    original = SqlRecordLineageRepository.issue_memberships

    def counted(self: SqlRecordLineageRepository, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SqlRecordLineageRepository, "issue_memberships", counted)
    read = ReadIssue(issue_id=issue, include_members=True)
    remote = runtime.ok(read, grants=grant("issues.read", "meetings.read"))
    assert len(calls) == 2
    assert [m["to"]["record_id"] for m in remote["memberships"]] == [meeting_id]
    # Stopped at the bound: more may exist, and something was withheld.
    assert (remote["memberships_truncated"], remote["restricted"]) == (True, True)
    # Keyset batches: a local reader pages through all 7 in 4 reads.
    calls.clear()
    local = runtime.ok(read)
    assert len(local["memberships"]) == 4 and local["memberships_truncated"] is True
    monkeypatch.setattr(lineage_module, "MAX_VISIBILITY_SCAN", 400)
    calls.clear()
    whole = runtime.ok(read)
    assert len(whole["memberships"]) == 7 and whole["memberships_truncated"] is False
    assert len(calls) == 4


def test_a_handoff_list_statement_timeout_answers_unavailable(
    runtime: S3ReadRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = _handoff_issue(runtime, "rv-hto", "v")
    original = SqlIssueHandoffRepository.known_events

    def slow(self: SqlIssueHandoffRepository, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        # Through the ledger's own statement runner, as its reads run.
        issues_persistence._run(lambda: self._connection.execute(text("SELECT pg_sleep(0.5)")))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(service_module, "LINEAGE_STATEMENT_TIMEOUT_MS", 50)
    monkeypatch.setattr(SqlIssueHandoffRepository, "known_events", slow)
    error = runtime.refused(ListIssueHandoffs(issue_id=scene["issue"]))
    assert _code(error) == ("unavailable", [])


def test_an_issue_read_statement_timeout_answers_unavailable(
    runtime: S3ReadRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = runtime.issue("rv-ito")
    original = issues_persistence.SqlIssueRepository.read_issue

    def slow(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        # Through the Issue repository's own statement runner, as its reads run.
        issues_persistence._run(lambda: self._connection.execute(text("SELECT pg_sleep(0.5)")))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(service_module, "LINEAGE_STATEMENT_TIMEOUT_MS", 50)
    monkeypatch.setattr(issues_persistence.SqlIssueRepository, "read_issue", slow)
    error = runtime.refused(ReadIssue(issue_id=issue, include_members=True))
    assert _code(error) == ("unavailable", [])
