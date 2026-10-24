"""AT-001 (S1 stages 1 to 3 and the reverse roots): the record lineage S1 vertical.

S1 contract sections 1 and 7.2, through `ApplicationService.invoke` against
PostgreSQL: a synthetic Meeting M1 with note version N1, a Commitment C1
asserted `originated_from` an exact N1 passage inside Issue I, a later note
version N1b that does not retarget C1, and the bounded reverse read from M1,
N1, C1 and I. Every write is a stamped local-operator write; every identity
and body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from my_pa.application.commands import ReadRecordLineage
from my_pa.domain.meeting.model import MeetingNotesMode
from tests.database.lineage_issue_harness import LineageRuntime
from tests.database.lineage_record_harness import (
    GATEWAY,
    NOTE_BODY,
    all_lineage_counts,
    commitment,
    meeting,
    membership,
    note,
    note_anchor,
    originated_from,
    revise_notes,
)

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[LineageRuntime]:
    composed = LineageRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _lineage(runtime: LineageRuntime, family: str, record_id: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    return runtime.ok(
        ReadRecordLineage(origin={"family": family, "record_id": record_id}, **kwargs)
    )


def _graph(answer: dict[str, Any]) -> tuple[set[tuple[str, str]], set[str]]:
    nodes = {(node["family"], node["record_id"]) for node in answer["nodes"]}
    edges = {edge["link_id"] for edge in answer["typed_edges"]}
    return nodes, edges


def _fixture(runtime: LineageRuntime, key: str, *, meeting_member: bool = True) -> dict[str, str]:
    """The section 7.2 AT-001 fixture: I, M1/N1(/N1b), C1, memberships, C1 <- N1."""
    issue = runtime.issue(key)
    m1, n1 = meeting(runtime, key)
    c1 = commitment(runtime, key)
    if meeting_member:
        runtime.ok(
            membership(issue, "meeting", m1, f"{key}-m1", role="discussion"), surface=GATEWAY
        )
    runtime.ok(membership(issue, "commitment", c1, f"{key}-c1", role="work"), surface=GATEWAY)
    origin = runtime.ok(
        originated_from(
            "commitment",
            c1,
            "meeting_note_version",
            n1,
            f"{key}-origin",
            (note_anchor(m1, n1, NOTE_BODY),),
            context_issue_id=issue,
        ),
        surface=GATEWAY,
    )
    return {
        "issue": issue,
        "m1": m1,
        "n1": n1,
        "c1": c1,
        "origin": origin["association"]["link_id"],
    }


def test_m1_alone_creates_no_link(runtime: LineageRuntime) -> None:
    before = all_lineage_counts(runtime.engine)
    m1, n1 = meeting(runtime, "alone")
    assert all_lineage_counts(runtime.engine) == before
    answer = _lineage(runtime, "meeting", m1)
    assert answer["typed_edges"] == []
    assert answer["selected_issue_id"] is None
    assert answer["issues_matching_root"] == []
    assert answer["complete_state"] == "complete"
    assert [node["record_id"] for node in answer["nodes"]] == [m1]
    assert [edge["from"]["record_id"] for edge in answer["virtual_native_edges"]] == [n1]


def test_c1_originates_from_an_exact_n1_passage(runtime: LineageRuntime) -> None:
    ids = _fixture(runtime, "exact")
    stored = note(runtime, ids["m1"], ids["n1"])
    answer = _lineage(runtime, "commitment", ids["c1"], issue_id=ids["issue"])
    origin = next(edge for edge in answer["typed_edges"] if edge["link_id"] == ids["origin"])
    assert origin["relation_type"] == "originated_from"
    assert origin["from"] == {"family": "commitment", "record_id": ids["c1"]}
    assert origin["to"] == {"family": "meeting_note_version", "record_id": ids["n1"]}
    assert origin["context_issue_id"] == ids["issue"]
    (anchor,) = origin["evidence"]
    start = NOTE_BODY.index("façade survey")
    assert (anchor["passage_start_cp"], anchor["passage_end_cp"]) == (start, start + 13)
    assert anchor["version_id"] == ids["n1"] and anchor["source_version_no"] == 1
    assert anchor["role"] == "origin" and anchor["availability"] == "available"
    assert stored["body_markdown"][start : start + 13] == "façade survey"


def test_reverse_read_from_m1_n1_c1_and_issue_yields_one_graph(runtime: LineageRuntime) -> None:
    ids = _fixture(runtime, "graph")
    n1b = revise_notes(runtime, ids["m1"], "graph-n1b", body=NOTE_BODY + " Updated.")
    expected_nodes = {
        ("situation", ids["issue"]),
        ("meeting", ids["m1"]),
        ("meeting_note_version", ids["n1"]),
        ("commitment", ids["c1"]),
    }
    graphs = []
    for family, record_id in (
        ("meeting", ids["m1"]),
        ("meeting_note_version", ids["n1"]),
        ("commitment", ids["c1"]),
        ("situation", ids["issue"]),
    ):
        answer = _lineage(runtime, family, record_id)
        assert answer["selected_issue_id"] == ids["issue"], family
        assert answer["complete_state"] == "complete", family
        nodes, edges = _graph(answer)
        assert nodes == expected_nodes, family
        # N1b is reachable only as a virtual note edge of M1.
        virtual = {edge["from"]["record_id"] for edge in answer["virtual_native_edges"]}
        assert virtual == {ids["n1"], n1b}, family
        graphs.append(edges)
    assert all(edges == graphs[0] for edges in graphs)
    assert len(graphs[0]) == 3


def test_m1_reaches_c1_through_the_pair_set_without_an_m1_membership(
    runtime: LineageRuntime,
) -> None:
    ids = _fixture(runtime, "pair", meeting_member=False)
    answer = _lineage(runtime, "meeting", ids["m1"])
    assert answer["selected_issue_id"] == ids["issue"]
    nodes, edges = _graph(answer)
    assert ("commitment", ids["c1"]) in nodes
    assert ("meeting_note_version", ids["n1"]) in nodes
    assert ids["origin"] in edges


def test_a_link_scoped_to_another_issue_is_not_followed_from_the_pair(
    runtime: LineageRuntime,
) -> None:
    ids = _fixture(runtime, "scoped")
    other = runtime.issue("scoped-j")
    c2 = commitment(runtime, "scoped-c2")
    runtime.ok(
        originated_from(
            "commitment",
            c2,
            "meeting_note_version",
            ids["n1"],
            "scoped-j-origin",
            (note_anchor(ids["m1"], ids["n1"], NOTE_BODY, passage="Next: pour"),),
            context_issue_id=other,
        ),
        surface=GATEWAY,
    )
    answer = _lineage(runtime, "meeting", ids["m1"], issue_id=ids["issue"])
    assert answer["selected_issue_id"] == ids["issue"]
    nodes, _ = _graph(answer)
    assert ("situation", other) not in nodes
    assert ("commitment", c2) not in nodes
    # Without a choice the meeting is ambiguous between I and J.
    ambiguous = _lineage(runtime, "meeting", ids["m1"])
    assert ambiguous["complete_state"] == "unresolved_ambiguity"


def test_n1b_does_not_retarget_c1(runtime: LineageRuntime) -> None:
    ids = _fixture(runtime, "retarget")
    for key, mode, body in (
        ("replace", MeetingNotesMode.REPLACE, "A wholly different note."),
        ("append", MeetingNotesMode.APPEND, "And another line."),
    ):
        revise_notes(runtime, ids["m1"], f"retarget-{key}", body=body, mode=mode)
    answer = _lineage(runtime, "commitment", ids["c1"], issue_id=ids["issue"])
    origin = next(edge for edge in answer["typed_edges"] if edge["link_id"] == ids["origin"])
    assert origin["to"]["record_id"] == ids["n1"]
    assert origin["revision_no"] == 1
    assert {anchor["version_id"] for anchor in origin["evidence"]} == {ids["n1"]}
    stored = note(runtime, ids["m1"], ids["n1"])
    assert stored["body_markdown"] == NOTE_BODY and stored["is_current"] is False


def test_a_meeting_in_two_issues_requires_an_issue_choice(runtime: LineageRuntime) -> None:
    first = runtime.issue("two-a")
    second = runtime.issue("two-b")
    m1, _ = meeting(runtime, "two")
    for issue, key in ((first, "a"), (second, "b")):
        runtime.ok(
            membership(issue, "meeting", m1, f"two-{key}", role="discussion"), surface=GATEWAY
        )
    answer = _lineage(runtime, "meeting", m1)
    assert answer["complete_state"] == "unresolved_ambiguity"
    assert answer["selected_issue_id"] is None
    assert [match["issue_id"] for match in answer["issues_matching_root"]] == sorted(
        [first, second]
    )
    assert answer["typed_edges"] == []
    chosen = _lineage(runtime, "meeting", m1, issue_id=second)
    assert chosen["selected_issue_id"] == second
    assert chosen["complete_state"] == "complete"
