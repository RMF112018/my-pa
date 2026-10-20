"""AT-011: a lineage cursor cannot outlive the reader's grants (S3 contract sections 5, 6.4, 7.2).

Against PostgreSQL through `ApplicationService.invoke`. The `records.lineage`
rows (worker L3):

* pages under one cursor reconstruct the one-page answer, and a lineage write
  between pages changes no later page (the cut is frozen in the token);
* a revoked family grant answers `scope_changed_restart_required` and nothing
  beyond the origin; a revoked `records.lineage` grant is `unsupported`;
* another Principal's cursor, changed filters and an edited cut are
  `conflict` / `cursor`; a malformed token or position and a cut beyond the
  horizon are `invalid_request` / `cursor`; a well-formed position that is not
  an item of the recomputed result -- unknown or vanished -- answers
  `scope_changed_restart_required`;
* a current read pages after the lineage horizon (its native cut is its read
  time, never compared with `k`);
* restricted nodes are neither counted nor identifiable;
* the S1/S2 Issue reads apply section 6.4 to remote readers.

The `issues.timeline` rows of this crosswalk entry are worker L4's. Every
identity and every body is synthetic.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import text
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL
from tests.database.lineage_record_harness import (
    capture,
    legacy_anchor,
    membership,
    restricted_capture_version,
)
from tests.database.lineage_s2_harness import close, handoff
from tests.database.lineage_s3_harness import GATEWAY, shortly_after
from tests.database.lineage_s3_read_harness import (
    S3ReadRuntime,
    decoded,
    grant,
    horizon,
    lineage_request,
    node_set,
    reencoded,
    union,
)

from my_pa.application.commands import (
    ListIssueHandoffs,
    ListIssues,
    ReadIssue,
    ReadIssueClosureReadiness,
    ReadIssueHistory,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.record_lineage import LineageReadRequest, lineage_request_document
from my_pa.domain.lineage.cursor import cursor_binding, parse_instant_token
from my_pa.domain.lineage.model import RecordRef
from my_pa.domain.lineage.vocabulary import RecordFamily

pytestmark = pytest.mark.database

#: Every family read and the lineage read itself.
_ALL: Final = (
    "records.lineage",
    "issues.read",
    "meetings.read",
    "tasks.read",
    "commitments.read",
    "constraints.read",
    "capture.read",
)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _scene(runtime: S3ReadRuntime, key: str, *, tasks: int = 12) -> dict[str, Any]:
    """An Issue with a Meeting and `tasks` Task members: more than one page of items.

    Nodes sort `(depth, family, record_id)`, so the Meeting precedes every
    Task and the first page of 10 ends on a Task node.
    """
    issue = runtime.issue(key)
    meeting_id, note_id = runtime.note(f"{key}-m")
    runtime.member(issue, "meeting", meeting_id, f"{key}-m", "discussion")
    task_ids = []
    for number in range(tasks):
        task_id = runtime.task(f"{key}-{number:02d}")
        runtime.member(issue, "task", task_id, f"{key}-{number:02d}", "work")
        task_ids.append(task_id)
    return {"issue": issue, "meeting": meeting_id, "note": note_id, "tasks": task_ids}


def _code(error: dict[str, Any]) -> tuple[str, list[str]]:
    return str(error["code"]), list(error.get("safe_details") or [])


def _first(runtime: S3ReadRuntime, root: tuple[str, str], **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    page = runtime.lineage(root, page_size=10, **kwargs)
    assert page["next_cursor"] is not None
    return page


def _assert_restart(page: dict[str, Any], root: tuple[str, str]) -> None:
    assert page["complete_state"] == "scope_changed_restart_required"
    assert page["qualifiers"] == ["scope_changed_restart_required"]
    assert page["root"] == {"family": root[0], "record_id": root[1]}
    assert (page["selected_issue_id"], page["next_cursor"]) == (None, None)
    assert page["issues_matching_root"] == []
    assert page["nodes"] == page["typed_edges"] == page["virtual_native_edges"] == []


def _rebound(token: str, runtime_request: dict[str, Any], principal_id: str, **cuts: object) -> str:
    """The token with its cuts changed *and* `b` recomputed for them (unsigned, D-02)."""
    document = decoded(token)
    document.update(cuts)
    document["b"] = cursor_binding(
        capability="records.lineage",
        principal_id=principal_id,
        request=runtime_request,
        known_at=parse_instant_token(document["k"]),
        lineage_valid_at=parse_instant_token(document["t"]),
        native_cut_at=parse_instant_token(document["n"]),
        record_event_watermark=document["r"],
    )
    return reencoded(document)


def _request_document(root: tuple[str, str], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return lineage_request_document(
        LineageReadRequest(
            origin=RecordRef(family=RecordFamily(root[0]), record_id=root[1]),
            issue_id=fields.get("issue_id"),
            max_depth=fields.get("max_depth", 4),
            page_size=fields.get("page_size"),
        )
    )


# ---- paging under one cursor ------------------------------------------------------------


def test_pages_under_one_cursor_reconstruct_the_one_page_answer(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-whole")
    root = ("situation", scene["issue"])
    whole = runtime.lineage(root)
    pages = runtime.pages(root, page_size=10)
    assert len(pages) >= 3
    merged = union(pages)
    for key in ("nodes", "typed_edges", "virtual_native_edges"):
        assert merged[key] == whole[key], key
    for page in pages:
        for key in ("root", "selected_issue_id", "issues_matching_root", "complete_state"):
            assert page[key] == whole[key], key
        assert (page["known_at"], page["lineage_valid_at"]) == (
            whole["known_at"],
            whole["lineage_valid_at"],
        )
    # Every page but the last carries a cursor, the last none.
    assert [page["next_cursor"] is None for page in pages] == [False] * (len(pages) - 1) + [True]


def test_a_write_between_pages_changes_no_later_page(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-write")
    root = ("situation", scene["issue"])
    whole = runtime.lineage(root)
    first = _first(runtime, root)
    # A lineage write after the first page: a new member, and the horizon moves.
    late = runtime.task("cur-write-late")
    runtime.member(scene["issue"], "task", late, "cur-write-late", "work")
    assert horizon(runtime.engine) > first["known_at"]
    rest = []
    cursor = first["next_cursor"]
    while cursor is not None:
        page = runtime.lineage(root, page_size=10, cursor=cursor)
        assert page["known_at"] == first["known_at"]
        rest.append(page)
        cursor = page["next_cursor"]
    merged = union([first, *rest])
    for key in ("nodes", "typed_edges", "virtual_native_edges"):
        assert merged[key] == whole[key], key
    assert ("task", late) not in node_set({"nodes": merged["nodes"]})
    # A fresh read sees it.
    assert ("task", late) in node_set(runtime.lineage(root))


# ---- grants -------------------------------------------------------------------------------


def test_a_revoked_family_grant_answers_restart_required_without_identifiers(
    runtime: S3ReadRuntime,
) -> None:
    scene = _scene(runtime, "cur-revoke")
    root = ("situation", scene["issue"])
    first = _first(runtime, root, grants=grant(*_ALL))
    last = first["nodes"][-1]
    assert last["family"] == "task"
    # The Meeting read is revoked; the position (a Task node) still exists.
    narrowed = grant(*(name for name in _ALL if name != "meetings.read"))
    page = runtime.lineage(root, page_size=10, cursor=first["next_cursor"], grants=narrowed)
    _assert_restart(page, root)
    rendered = json.dumps(page)
    for identifier in (scene["meeting"], scene["note"], *scene["tasks"]):
        assert identifier not in rendered
    # Restarting under the new grants reads again from the start.
    again = runtime.pages(root, page_size=10, grants=narrowed)
    assert all(node["family"] != "meeting" for node in union(again)["nodes"])
    assert again[0]["complete_state"] == "restricted_evidence"


def test_a_revoked_read_grant_is_unsupported(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-unsup")
    root = ("situation", scene["issue"])
    first = _first(runtime, root, grants=grant(*_ALL))
    without = grant(*(name for name in _ALL if name != "records.lineage"))
    for command in (
        lineage_request(root, {})[0],
        lineage_request(root, {"page_size": 10, "cursor": first["next_cursor"]})[0],
    ):
        assert _code(runtime.refused(command, grants=without)) == ("unsupported", [])
    # A grant for a purpose `records.lineage` does not admit is no grant either.
    assert _code(runtime.refused(lineage_request(root, {})[0], grants=frozenset())) == (
        "unsupported",
        [],
    )


# ---- binding ------------------------------------------------------------------------------


def test_a_cursor_of_another_principal_is_conflict(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-other")
    root = ("situation", scene["issue"])
    first = _first(runtime, root)
    # The other Principal has a horizon of its own, so only the binding differs.
    runtime.issue("cur-other-b", principal_id=OTHER_PRINCIPAL)
    error = runtime.refused(
        lineage_request(root, {"page_size": 10, "cursor": first["next_cursor"]})[0],
        principal_id=OTHER_PRINCIPAL,
    )
    assert _code(error) == ("conflict", ["cursor"])


def test_a_cursor_with_changed_filters_is_conflict(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-filter")
    root = ("situation", scene["issue"])
    first = _first(runtime, root)
    cursor = first["next_cursor"]
    for changed in (
        {"issue_id": scene["issue"]},
        {"max_depth": 3},
        {"page_size": 11},
        {"known_at": first["known_at"]},
        {"valid_at": first["known_at"]},
    ):
        fields = {"page_size": 10, "cursor": cursor, **changed}
        error = runtime.refused(lineage_request(root, fields)[0])
        assert _code(error) == ("conflict", ["cursor"]), changed
    other_root = ("task", scene["tasks"][0])
    error = runtime.refused(lineage_request(other_root, {"page_size": 10, "cursor": cursor})[0])
    assert _code(error) == ("conflict", ["cursor"])


def test_a_cursor_with_a_tampered_cut_is_conflict(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-tamper")
    root = ("situation", scene["issue"])
    first = _first(runtime, root)
    document = decoded(first["next_cursor"])
    earlier = (datetime.fromisoformat(document["k"]) - timedelta(seconds=1)).astimezone(UTC)
    earlier_token = earlier.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for key in ("k", "t"):
        edited = reencoded({**document, key: earlier_token})
        error = runtime.refused(lineage_request(root, {"page_size": 10, "cursor": edited})[0])
        assert _code(error) == ("conflict", ["cursor"]), key


def test_a_malformed_cursor_is_invalid_request(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-malformed")
    root = ("situation", scene["issue"])
    first = _first(runtime, root)
    document = decoded(first["next_cursor"])
    malformed = [
        "not-a-json-token",
        reencoded({**document, "v": 2}),
        reencoded({key: value for key, value in document.items() if key != "s"}),
        reencoded({**document, "p": "x:task:" + scene["tasks"][0]}),
        reencoded({**document, "p": "n:task:cmt_aaaaaaaa11111111"}),
        reencoded({**document, "p": "e:sit_aaaaaaaa11111111"}),
        reencoded({**document, "p": ["2026-10-19T12:00:00.000000Z", 0, 0, "irs_aaaaaaaa1111"]}),
        reencoded({**document, "r": "rcev_aaaaaaaa11111111"}),
    ]
    for token in malformed:
        error = runtime.refused(lineage_request(root, {"page_size": 10, "cursor": token})[0])
        assert _code(error) == ("invalid_request", ["cursor"]), token
    # A cursor without a page size is refused when the request is parsed.
    with pytest.raises(InvalidRequestError) as refused:
        lineage_request(root, {"cursor": first["next_cursor"]})
    assert refused.value.safe_details == (SafeDetail.CURSOR,)


def test_an_unknown_well_formed_position_answers_restart_required(
    runtime: S3ReadRuntime,
) -> None:
    scene = _scene(runtime, "cur-unknown")
    root = ("situation", scene["issue"])
    first = _first(runtime, root)
    document = decoded(first["next_cursor"])
    # A position the client edited: `p` is covered by neither `b` nor `s`.
    for position in (
        "n:task:tsk_neverexisted000001",
        "e:irl_neverexisted000001",
        "v:mnote_neverexisted000001",
    ):
        token = reencoded({**document, "p": position})
        page = runtime.lineage(root, page_size=10, cursor=token)
        _assert_restart(page, root)


def test_a_cursor_beyond_the_horizon_is_invalid_request(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-future")
    root = ("situation", scene["issue"])
    first = _first(runtime, root)
    request = _request_document(root, page_size=10)
    future = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    # `k` re-bound to a future instant: the binding matches, the horizon refuses.
    token = _rebound(first["next_cursor"], request, PRINCIPAL, k=future, t=future)
    error = runtime.refused(lineage_request(root, {"page_size": 10, "cursor": token})[0])
    assert _code(error) == ("invalid_request", ["cursor"])
    # A `t` after its `k`, and an `n` after now, refuse alike.
    document = decoded(first["next_cursor"])
    for cuts in ({"t": future}, {"n": future}):
        token = _rebound(first["next_cursor"], request, PRINCIPAL, **cuts)
        error = runtime.refused(lineage_request(root, {"page_size": 10, "cursor": token})[0])
        assert _code(error) == ("invalid_request", ["cursor"]), cuts
    assert document["k"] == first["known_at"]


def test_a_vanished_emitted_item_answers_restart_required(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-vanish")
    root = ("situation", scene["issue"])
    first = _first(runtime, root)
    last = first["nodes"][-1]
    assert last["family"] == "task"
    # The emitted Task stops resolving natively (a synthetic database only:
    # replica mode bypasses the link guard trigger and the foreign keys).
    with runtime.engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("DELETE FROM knowledge.tasks WHERE task_id = :task"), {"task": last["record_id"]}
        )
    page = runtime.lineage(root, page_size=10, cursor=first["next_cursor"])
    _assert_restart(page, root)


def test_a_current_read_pages_after_the_lineage_horizon(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-current")
    root = ("situation", scene["issue"])
    time.sleep(0.05)
    pages = runtime.pages(root, page_size=10)
    assert len(pages) >= 2
    first = pages[0]
    assert first["native_cut_at"] > first["known_at"] == horizon(runtime.engine)
    assert decoded(first["next_cursor"])["n"] == first["native_cut_at"]
    whole = runtime.lineage(root)
    assert union(pages)["nodes"] == whole["nodes"]


def test_restricted_nodes_are_neither_counted_nor_identifiable(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime, "cur-hidden", tasks=3)
    root = ("situation", scene["issue"])
    hidden_grants = grant(*(name for name in _ALL if name != "tasks.read"))
    for answer in (
        runtime.lineage(root, grants=hidden_grants),
        *runtime.pages(root, page_size=10, grants=hidden_grants),
    ):
        rendered = json.dumps(answer)
        for task_id in scene["tasks"]:
            assert task_id not in rendered
        assert {family for family, _ in node_set(answer)} <= {"situation", "meeting"}
        assert answer["complete_state"] == "restricted_evidence"
        assert not {key for key in _keys(answer) if "count" in key or "hidden" in key}
    whole = runtime.lineage(root, grants=hidden_grants)
    assert node_set(whole) == {("situation", scene["issue"]), ("meeting", scene["meeting"])}
    assert len(whole["typed_edges"]) == 1


# ---- the S1/S2 Issue reads (section 6.4, R3-F13) -------------------------------------------


def test_s1_and_s2_issue_reads_apply_family_visibility_for_remote_readers(
    runtime: S3ReadRuntime,
) -> None:
    scene = _scene(runtime, "cur-issue", tasks=2)
    issue = scene["issue"]
    commitment = runtime.commitment("cur-issue")
    runtime.member(issue, "commitment", commitment, "cur-issue-c", "discussion")
    created = str(runtime.commitment_view(commitment)["created_at"])
    runtime.ok(
        handoff(
            issue,
            commitment,
            "counterparty",
            shortly_after(created, 1000),
            "cur-issue",
            runtime.handoff_anchor("cur-issue-h"),
        ),
        surface=GATEWAY,
    )
    issue_reads = grant(
        "issues.read", "issues.list", "issues.handoffs.list", "issues.closure_readiness"
    )
    everything = issue_reads | grant(*_ALL)
    # issues.read: members the reader may not see are withheld.
    narrow = runtime.ok(ReadIssue(issue_id=issue, include_members=True), grants=issue_reads)
    assert narrow["memberships"] == [] and narrow["restricted"] is True
    full = runtime.ok(ReadIssue(issue_id=issue, include_members=True), grants=everything)
    assert len(full["memberships"]) == 4 and full["restricted"] is False
    local = runtime.ok(ReadIssue(issue_id=issue, include_members=True))
    assert local["memberships"] == full["memberships"] and local["restricted"] is False
    # issues.list: Issues are served while the Issue family is visible.
    listed = runtime.ok(ListIssues(), grants=issue_reads)
    assert issue in {entry["issue_id"] for entry in listed["issues"]}
    assert listed["restricted"] is False
    # issues.handoffs.list needs Commitment visibility.
    hidden = runtime.ok(ListIssueHandoffs(issue_id=issue), grants=issue_reads)
    assert (hidden["handoffs"], hidden["restricted"]) == ([], True)
    error = runtime.refused(
        ListIssueHandoffs(issue_id=issue, commitment_id=commitment), grants=issue_reads
    )
    assert _code(error) == ("not_found", ["commitment_id"])
    shown = runtime.ok(ListIssueHandoffs(issue_id=issue), grants=everything)
    assert len(shown["handoffs"]) == 1 and shown["restricted"] is False
    # issues.closure_readiness: the blocking Tasks are withheld, `ready` stays false.
    readiness = runtime.ok(ReadIssueClosureReadiness(issue_id=issue), grants=issue_reads)
    assert (readiness["ready"], readiness["blockers"], readiness["restricted"]) == (
        False,
        [],
        True,
    )
    whole = runtime.ok(ReadIssueClosureReadiness(issue_id=issue), grants=everything)
    assert len(whole["blockers"]) == 2 and whole["restricted"] is False
    # The grant re-check: each read without its own grant is hidden (`unsupported`).
    for command, name in (
        (ReadIssue(issue_id=issue), "issues.read"),
        (ListIssues(), "issues.list"),
        (ListIssueHandoffs(issue_id=issue), "issues.handoffs.list"),
        (ReadIssueClosureReadiness(issue_id=issue), "issues.closure_readiness"),
    ):
        without = frozenset(pair for pair in everything if pair[0].value != name)
        assert _code(runtime.refused(command, grants=without)) == ("unsupported", []), name


def _keys(document: object) -> set[str]:
    found: set[str] = set()
    if isinstance(document, dict):
        for key, value in document.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(document, list):
        for item in document:
            found |= _keys(item)
    return found


# ---- anchors on the S1/S2 Issue reads (section 6.4; L3 corrective) ------------------------


def test_a_handoff_whose_anchor_is_invisible_is_withheld_from_a_remote_reader(
    runtime: S3ReadRuntime,
) -> None:
    issue = runtime.issue("cur-handoff-anchor")
    commitment = runtime.commitment("cur-handoff-anchor")
    runtime.member(issue, "commitment", commitment, "cur-handoff-anchor", "discussion")
    created = str(runtime.commitment_view(commitment)["created_at"])
    # The handoff's one required anchor is a Meeting note.
    runtime.ok(
        handoff(
            issue,
            commitment,
            "counterparty",
            shortly_after(created, 1000),
            "cur-handoff-anchor",
            runtime.handoff_anchor("cur-handoff-anchor-h"),
        ),
        surface=GATEWAY,
    )
    without_meetings = grant("issues.handoffs.list", "issues.read", "commitments.read")
    hidden = runtime.ok(ListIssueHandoffs(issue_id=issue), grants=without_meetings)
    assert (hidden["handoffs"], hidden["next_cursor"], hidden["restricted"]) == ([], None, True)
    rendered = json.dumps(hidden)
    assert "mtg_" not in rendered and "mnote_" not in rendered
    named = runtime.ok(
        ListIssueHandoffs(issue_id=issue, commitment_id=commitment), grants=without_meetings
    )
    assert (named["handoffs"], named["restricted"]) == ([], True)
    shown = runtime.ok(
        ListIssueHandoffs(issue_id=issue), grants=without_meetings | grant("meetings.read")
    )
    assert len(shown["handoffs"]) == 1 and shown["restricted"] is False
    assert shown["handoffs"][0]["evidence"]["family"] == "meeting_note_version"


def _closed_with_note_evidence(runtime: S3ReadRuntime, key: str) -> dict[str, Any]:
    """An Issue with a Task member cited on a note, closed on a note's resolution anchor."""
    issue = runtime.issue(key)
    task = runtime.task(f"{key}-t")
    meeting_id, note_id, anchor = runtime.evidence_source(f"{key}-member")
    runtime.ok(
        membership(issue, "task", task, f"{key}-t", role="reference", anchors=(anchor,)),
        surface=GATEWAY,
    )
    _, _, closing = runtime.evidence_source(f"{key}-closure")
    runtime.ok(close(issue, 1, key, (closing,)), surface=GATEWAY)
    return {"issue": issue, "task": task, "meeting": meeting_id, "note": note_id}


def test_issue_reads_withhold_invisible_closure_membership_and_history_anchors(
    runtime: S3ReadRuntime,
) -> None:
    scene = _closed_with_note_evidence(runtime, "cur-issue-anchor")
    issue = scene["issue"]
    without_meetings = grant("issues.read", "issues.history", "tasks.read")
    with_meetings = without_meetings | grant("meetings.read")
    read = ReadIssue(issue_id=issue, include_members=True)
    hidden = runtime.ok(read, grants=without_meetings)
    assert hidden["issue"]["closure"]["evidence"] == []
    (member,) = hidden["memberships"]
    assert member["evidence"] == [] and hidden["restricted"] is True
    assert "mnote_" not in json.dumps(hidden)
    history = runtime.ok(ReadIssueHistory(issue_id=issue), grants=without_meetings)
    assert [revision["evidence"] for revision in history["revisions"]] == [[], []]
    assert "mnote_" not in json.dumps(history)
    shown = runtime.ok(read, grants=with_meetings)
    assert len(shown["issue"]["closure"]["evidence"]) == 1
    assert len(shown["memberships"][0]["evidence"]) == 1 and shown["restricted"] is False
    local = runtime.ok(read)
    assert local["issue"]["closure"] == shown["issue"]["closure"]
    shown_history = runtime.ok(ReadIssueHistory(issue_id=issue), grants=with_meetings)
    assert [len(revision["evidence"]) for revision in shown_history["revisions"]] == [0, 1]


def test_a_restricted_legacy_anchor_is_labelled_locally_and_withheld_remotely(
    runtime: S3ReadRuntime,
) -> None:
    issue = runtime.issue("cur-legacy")
    task = runtime.task("cur-legacy-t")
    capture_id, version_id, _ = capture(runtime, "cur-legacy-c")
    runtime.ok(
        membership(
            issue,
            "task",
            task,
            "cur-legacy-t",
            role="reference",
            anchors=(legacy_anchor(capture_id),),
        ),
        surface=GATEWAY,
    )
    read = ReadIssue(issue_id=issue, include_members=True)
    everything = grant("issues.read", "tasks.read", "capture.read")
    before = runtime.ok(read)["memberships"][0]["evidence"]
    assert [anchor["availability"] for anchor in before] == ["legacy_unversioned"]
    assert len(runtime.ok(read, grants=everything)["memberships"][0]["evidence"]) == 1
    # The Capture root now holds a `restricted_local` version (S1 F24's forward rule).
    restricted_capture_version(runtime.engine, version_id)
    local = runtime.ok(read)
    assert [a["availability"] for a in local["memberships"][0]["evidence"]] == ["restricted"]
    assert local["restricted"] is False
    remote = runtime.ok(read, grants=everything)
    assert remote["memberships"][0]["evidence"] == [] and remote["restricted"] is True
    assert capture_id not in json.dumps(remote)
