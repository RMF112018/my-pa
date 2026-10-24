"""AT-006 + WP-02D: one Meeting, several Issues, and Series that lineage never reads.

S2 contract sections 1, 3.1, 7.2 and 12 (D-11, D-12) against PostgreSQL,
through `ApplicationService.invoke` and `records.lineage`:

* a Meeting shared by three Issues offers the three as choices and imports none
  into another: each Issue's traversal follows only its own memberships and
  its own context-scoped, passage-anchored discussions;
* a Meeting Series is native Meeting metadata: reassigning a Meeting's Series
  writes no lineage row and changes no lineage answer, a Meeting in another
  Series keeps it, and a Series sibling linked to another Issue is never
  reached; no lineage module reads `meeting_series_id`.

Every identity and every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.application.commands import CreateMeeting, ReadMeeting, ReadRecordLineage, UpdateMeeting
from tests.database.lineage_record_harness import NOTE_BODY, note_anchor
from tests.database.lineage_s2_harness import GATEWAY, S2Runtime, all_s2_counts, assertion

pytestmark = pytest.mark.database

_STARTS: Final = datetime(2026, 10, 2, 15, tzinfo=UTC)
#: Three passages of the one note, one per Issue.
_PASSAGES: Final = ("Decisions", "façade survey", "pour")
_SRC: Final = Path(__file__).resolve().parents[2] / "src" / "my_pa"
#: Every module that reads or writes lineage rows.
_LINEAGE_MODULES: Final = (
    "application/record_lineage.py",
    "application/lineage_endpoints.py",
    "application/issues.py",
    "application/issue_handoffs.py",
    "application/issue_work.py",
    "domain/lineage",
    "infrastructure/persistence/record_lineage.py",
    "infrastructure/persistence/issues.py",
    "infrastructure/persistence/issue_handoffs.py",
)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S2Runtime]:
    composed = S2Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _meeting(
    runtime: S2Runtime,
    key: str,
    *,
    series_title: str | None = None,
    series_id: str | None = None,
) -> dict[str, Any]:
    """A Meeting with one note version, optionally in a (new or existing) Series."""
    written = runtime.ok(
        CreateMeeting(
            title=f"Synthetic meeting {key}",
            start_at=_STARTS,
            timezone_name="UTC",
            idempotency_key=f"s2-ctx-mtg-{key}",
            notes_markdown=NOTE_BODY,
            series_title=series_title,
            meeting_series_id=series_id,
        )
    )
    view = written["meeting"]
    return {
        "meeting_id": str(view["meeting_id"]),
        "note_id": str(view["notes"]["note_version_id"]),
        "series_id": view["meeting_series_id"],
    }


def _lineage(
    runtime: S2Runtime, family: str, record_id: str, issue_id: str | None = None
) -> dict[str, Any]:
    return runtime.ok(
        ReadRecordLineage(origin={"family": family, "record_id": record_id}, issue_id=issue_id)
    )


def _cutless(answer: dict[str, Any]) -> dict[str, Any]:
    """The answer without its read-time native cut (S3 section 3.4)."""
    return {key: value for key, value in answer.items() if key != "native_cut_at"}


def _nodes(answer: dict[str, Any]) -> set[tuple[str, str]]:
    return {(node["family"], node["record_id"]) for node in answer["nodes"]}


def _edges(answer: dict[str, Any]) -> set[str]:
    return {edge["link_id"] for edge in answer["typed_edges"]}


def _discusses(
    runtime: S2Runtime,
    mtg: dict[str, Any],
    target: tuple[str, str],
    key: str,
    *,
    passage: str = "façade survey",
    context: str | None = None,
) -> str:
    anchor = note_anchor(
        mtg["meeting_id"], mtg["note_id"], NOTE_BODY, role="discussion", passage=passage
    )
    written = runtime.ok(
        assertion(
            "discusses",
            ("meeting_note_version", mtg["note_id"]),
            target,
            key,
            (anchor,),
            context=context,
        ),
        surface=GATEWAY,
    )
    return str(written["association"]["link_id"])


def _three_issue_meeting(runtime: S2Runtime, key: str) -> dict[str, Any]:
    """M (one note N) a `discussion` member of I1, I2, I3; Ti a `work` member of Ii only.

    N discusses each Ti on its own passage, scoped to Ii.
    """
    mtg = _meeting(runtime, key)
    issues = [runtime.issue(f"{key}-i{index}") for index in (1, 2, 3)]
    tasks = [runtime.task(f"{key}-t{index}") for index in (1, 2, 3)]
    discussions = []
    for index, (issue, task_id, passage) in enumerate(
        zip(issues, tasks, _PASSAGES, strict=True), start=1
    ):
        runtime.member(issue, "meeting", mtg["meeting_id"], f"{key}-m{index}", "discussion")
        runtime.member(issue, "task", task_id, f"{key}-t{index}", "work")
        discussions.append(
            _discusses(
                runtime,
                mtg,
                ("task", task_id),
                f"{key}-d{index}",
                passage=passage,
                context=issue,
            )
        )
    return {**mtg, "issues": issues, "tasks": tasks, "discussions": discussions}


def test_a_meeting_with_three_issues_offers_three_choices(runtime: S2Runtime) -> None:
    scene = _three_issue_meeting(runtime, "ctx-choices")
    for family, record_id in (
        ("meeting", scene["meeting_id"]),
        ("meeting_note_version", scene["note_id"]),
    ):
        answer = _lineage(runtime, family, record_id)
        assert answer["selected_issue_id"] is None
        assert answer["complete_state"] == "unresolved_ambiguity"
        assert sorted(match["issue_id"] for match in answer["issues_matching_root"]) == sorted(
            scene["issues"]
        )
        # No Issue is chosen for the caller, so no Issue's members are imported.
        assert not _nodes(answer) & {("task", task_id) for task_id in scene["tasks"]}
        for issue in scene["issues"]:
            chosen = _lineage(runtime, family, record_id, issue)
            assert (chosen["selected_issue_id"], chosen["complete_state"]) == (issue, "complete")


def test_each_issue_returns_only_its_own_passage_links(runtime: S2Runtime) -> None:
    scene = _three_issue_meeting(runtime, "ctx-passages")
    for index, issue in enumerate(scene["issues"]):
        answer = _lineage(runtime, "meeting_note_version", scene["note_id"], issue)
        discussions = [
            edge for edge in answer["typed_edges"] if edge["relation_type"] == "discusses"
        ]
        assert [edge["link_id"] for edge in discussions] == [scene["discussions"][index]]
        (passage,) = discussions[0]["evidence"]
        start = NOTE_BODY.index(_PASSAGES[index])
        assert (passage["passage_start_cp"], passage["passage_end_cp"]) == (
            start,
            start + len(_PASSAGES[index]),
        )
        others = {("task", task_id) for task_id in scene["tasks"]} - {
            ("task", scene["tasks"][index])
        }
        assert ("task", scene["tasks"][index]) in _nodes(answer)
        assert not _nodes(answer) & others
        assert not _nodes(answer) & {
            ("situation", other) for other in scene["issues"] if other != issue
        }


def test_one_shared_meeting_imports_no_other_issue_member(runtime: S2Runtime) -> None:
    mtg = _meeting(runtime, "ctx-shared")
    first, second = runtime.issue("ctx-shared-i1"), runtime.issue("ctx-shared-i2")
    t1, t2 = runtime.task("ctx-shared-t1"), runtime.task("ctx-shared-t2")
    c2 = runtime.commitment("ctx-shared-c2")
    for issue, key in ((first, "m1"), (second, "m2")):
        runtime.member(issue, "meeting", mtg["meeting_id"], f"ctx-shared-{key}", "discussion")
    runtime.member(first, "task", t1, "ctx-shared-t1", "work")
    runtime.member(second, "task", t2, "ctx-shared-t2", "work")
    runtime.member(second, "commitment", c2, "ctx-shared-c2", "work")
    # A context-free discussion of T2 from the shared note: it is the second
    # Issue's member, so the first Issue's traversal does not follow it.
    _discusses(runtime, mtg, ("task", t2), "ctx-shared-d2")
    foreign = {("task", t2), ("commitment", c2), ("situation", second)}
    for family, record_id in (
        ("task", t1),
        ("situation", first),
        ("meeting", mtg["meeting_id"]),
        ("meeting_note_version", mtg["note_id"]),
    ):
        answer = _lineage(runtime, family, record_id, first)
        assert answer["selected_issue_id"] == first
        assert ("meeting", mtg["meeting_id"]) in _nodes(answer)
        assert not _nodes(answer) & foreign, (family, record_id)
    # T1's own read selects its only Issue without being told.
    assert _lineage(runtime, "task", t1)["selected_issue_id"] == first


def test_series_reassignment_changes_no_lineage_row_or_answer(runtime: S2Runtime) -> None:
    series_a = _meeting(runtime, "ctx-series-a0", series_title="Synthetic Series A")["series_id"]
    series_b = _meeting(runtime, "ctx-series-b0", series_title="Synthetic Series B")["series_id"]
    assert series_a and series_b and series_a != series_b
    mtg = _meeting(runtime, "ctx-series-m1", series_id=series_a)
    issue = runtime.issue("ctx-series")
    task_id = runtime.task("ctx-series")
    runtime.member(issue, "meeting", mtg["meeting_id"], "ctx-series-m1", "discussion")
    runtime.member(issue, "task", task_id, "ctx-series-t1", "work")
    _discusses(runtime, mtg, ("task", task_id), "ctx-series-d1", context=issue)
    roots = (
        ("situation", issue),
        ("meeting", mtg["meeting_id"]),
        ("meeting_note_version", mtg["note_id"]),
        ("task", task_id),
    )
    answers = {root: _lineage(runtime, *root) for root in roots}
    counts = all_s2_counts(runtime.engine)
    for key, target in (("to-b", series_b), ("detach", None), ("back-to-a", series_a)):
        current = runtime.ok(ReadMeeting(meeting_id=mtg["meeting_id"]))["meeting"]
        moved = runtime.ok(
            UpdateMeeting(
                meeting_id=mtg["meeting_id"],
                expected_version=int(current["version"]),
                idempotency_key=f"s2-ctx-series-{key}",
                meeting_series_id=target,
            )
        )["meeting"]
        assert moved["meeting_series_id"] == target
        assert all_s2_counts(runtime.engine) == counts, key
        # S3 section 3.4 lockstep: a current read reports its own read time as
        # `native_cut_at`; every other key of the answer is unchanged.
        assert {root: _cutless(_lineage(runtime, *root)) for root in roots} == {
            root: _cutless(answer) for root, answer in answers.items()
        }, key
    # Lineage has no Series vocabulary to read: the Series is native metadata.
    for module in _LINEAGE_MODULES:
        path = _SRC / module
        for source in sorted(path.rglob("*.py")) if path.is_dir() else [path]:
            assert "meeting_series" not in source.read_text(encoding="utf-8"), source


def test_a_cross_series_meeting_keeps_its_series_and_imports_no_sibling(
    runtime: S2Runtime,
) -> None:
    m1 = _meeting(runtime, "ctx-cross-m1", series_title="Synthetic Series A")
    m3 = _meeting(runtime, "ctx-cross-m3", series_title="Synthetic Series B")
    sibling = _meeting(runtime, "ctx-cross-m5", series_id=m3["series_id"])
    issue, other = runtime.issue("ctx-cross-i"), runtime.issue("ctx-cross-j")
    task_id, other_task = runtime.task("ctx-cross-t1"), runtime.task("ctx-cross-tj")
    runtime.member(issue, "task", task_id, "ctx-cross-t1", "work")
    for mtg, key in ((m1, "m1"), (m3, "m3")):
        runtime.member(issue, "meeting", mtg["meeting_id"], f"ctx-cross-{key}", "discussion")
    _discusses(runtime, m3, ("task", task_id), "ctx-cross-d3", context=issue)
    # The Series B sibling belongs to another Issue with its own work.
    runtime.member(other, "meeting", sibling["meeting_id"], "ctx-cross-m5", "discussion")
    runtime.member(other, "task", other_task, "ctx-cross-tj", "work")
    _discusses(runtime, sibling, ("task", other_task), "ctx-cross-d5", context=other)
    unreachable = {
        ("meeting", sibling["meeting_id"]),
        ("meeting_note_version", sibling["note_id"]),
        ("situation", other),
        ("task", other_task),
    }
    for family, record_id in (
        ("situation", issue),
        ("meeting", m3["meeting_id"]),
        ("meeting_note_version", m3["note_id"]),
        ("task", task_id),
    ):
        answer = _lineage(runtime, family, record_id, issue)
        assert {("meeting", m1["meeting_id"]), ("meeting", m3["meeting_id"])} <= _nodes(answer)
        assert not _nodes(answer) & unreachable, (family, record_id)
    # M3 keeps its own Series: no lineage write moved it.
    for mtg in (m1, m3, sibling):
        view = runtime.ok(ReadMeeting(meeting_id=mtg["meeting_id"]))["meeting"]
        assert view["meeting_series_id"] == mtg["series_id"]
    assert m1["series_id"] != m3["series_id"] == sibling["series_id"]
