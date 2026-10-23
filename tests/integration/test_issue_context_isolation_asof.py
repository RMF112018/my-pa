"""AT-006 (S3 part): a shared Meeting never carries another Issue's context, at any cut or page.

S3 contract section 7.2 step 3 against PostgreSQL through `ApplicationService.invoke`:
every breadth-first state carries the one selected Issue, so a Meeting that is
a member of several Issues expands only into the selected Issue's links -- as
of a `known_at`, and on every page of a paged read.

Every identity and every body is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.database.lineage_record_harness import NOTE_BODY, note_anchor
from tests.database.lineage_s2_harness import assertion
from tests.database.lineage_s3_harness import GATEWAY
from tests.database.lineage_s3_read_harness import S3ReadRuntime, horizon, node_set, union

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _shared(runtime: S3ReadRuntime, key: str, sizes: tuple[int, ...]) -> dict[str, Any]:
    """One Meeting with one note, a member of one Issue per size.

    Issue *i* has `sizes[i]` Task members, each discussed from the shared note
    in that Issue's context.
    """
    meeting_id, note_id = runtime.note(f"{key}-m")
    issues: list[dict[str, Any]] = []
    for index, size in enumerate(sizes):
        issue = runtime.issue(f"{key}-{index}")
        runtime.member(issue, "meeting", meeting_id, f"{key}-{index}-m", "discussion")
        tasks = []
        for number in range(size):
            task = runtime.task(f"{key}-{index}-{number:02d}")
            runtime.member(issue, "task", task, f"{key}-{index}-{number:02d}", "reference")
            runtime.ok(
                assertion(
                    "discusses",
                    ("meeting_note_version", note_id),
                    ("task", task),
                    f"{key}-{index}-{number:02d}",
                    (note_anchor(meeting_id, note_id, NOTE_BODY, role="discussion"),),
                    context=issue,
                ),
                surface=GATEWAY,
            )
            tasks.append(task)
        issues.append({"issue": issue, "tasks": tasks})
    return {"meeting": meeting_id, "note": note_id, "issues": issues}


def _foreign(scene: dict[str, Any], chosen: int) -> set[str]:
    """Every identifier of the other Issues and their own records."""
    found: set[str] = set()
    for index, issue in enumerate(scene["issues"]):
        if index != chosen:
            found.add(issue["issue"])
            found.update(issue["tasks"])
    return found


def _own(scene: dict[str, Any], chosen: int) -> set[tuple[str, str]]:
    issue = scene["issues"][chosen]
    return {
        ("situation", issue["issue"]),
        ("meeting", scene["meeting"]),
        ("meeting_note_version", scene["note"]),
        *(("task", task) for task in issue["tasks"]),
    }


def test_a_three_issue_meeting_pages_only_its_issue_at_known_at(runtime: S3ReadRuntime) -> None:
    scene = _shared(runtime, "iso-three", (2, 6, 2))
    known = horizon(runtime.engine)
    root = ("meeting", scene["meeting"])
    candidates = runtime.lineage(root, known_at=known)
    assert candidates["complete_state"] == "unresolved_ambiguity"
    assert {match["issue_id"] for match in candidates["issues_matching_root"]} == {
        issue["issue"] for issue in scene["issues"]
    }
    assert node_set(candidates) == {root}
    for chosen in range(3):
        issue_id = scene["issues"][chosen]["issue"]
        pages = runtime.pages(root, issue_id=issue_id, known_at=known, page_size=10)
        merged = union(pages)
        assert node_set({"nodes": merged["nodes"]}) == _own(scene, chosen), chosen
        rendered = json.dumps(merged)
        for identifier in _foreign(scene, chosen):
            assert identifier not in rendered, chosen
        for page in pages:
            assert page["selected_issue_id"] == issue_id
            assert page["known_at"] == known


def test_a_shared_meeting_never_carries_another_issue_context_across_pages(
    runtime: S3ReadRuntime,
) -> None:
    scene = _shared(runtime, "iso-pages", (12, 3))
    known = horizon(runtime.engine)
    # From the second Issue, through the shared Meeting and its note.
    for root in (
        ("situation", scene["issues"][1]["issue"]),
        ("meeting", scene["meeting"]),
        ("meeting_note_version", scene["note"]),
    ):
        pages = runtime.pages(
            root, issue_id=scene["issues"][1]["issue"], known_at=known, page_size=10
        )
        merged = union(pages)
        assert node_set({"nodes": merged["nodes"]}) == _own(scene, 1), root
        # The candidates name every Issue the root matches; nothing else does.
        rendered = json.dumps(merged)
        for identifier in _foreign(scene, 1):
            assert identifier not in rendered, root
        assert all(
            edge["context_issue_id"] in (None, scene["issues"][1]["issue"])
            for edge in merged["typed_edges"]
        ), root


def test_an_issue_chosen_from_the_meeting_view_reads_only_its_records(
    runtime: S3ReadRuntime,
) -> None:
    scene = _shared(runtime, "iso-chosen", (2, 2, 2))
    root = ("meeting", scene["meeting"])
    offered = runtime.lineage(root)["issues_matching_root"]
    assert len(offered) == 3
    for match in offered:
        chosen = next(
            index
            for index, issue in enumerate(scene["issues"])
            if issue["issue"] == match["issue_id"]
        )
        answer = runtime.lineage(root, issue_id=match["issue_id"])
        assert answer["selected_issue_id"] == match["issue_id"]
        assert node_set(answer) == _own(scene, chosen)
        assert [m["issue_id"] for m in answer["issues_matching_root"]] == [
            m["issue_id"] for m in offered
        ]
        edges = json.dumps(answer["typed_edges"]) + json.dumps(answer["nodes"])
        for identifier in _foreign(scene, chosen):
            assert identifier not in edges
