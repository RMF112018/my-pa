"""The S2 residual `related_context` (S3 contract section 3.1) against PostgreSQL.

`related_context` is a symmetric semantic relation between two distinct
records of the six families (Meeting, note version, Task, Commitment,
Constraint, Capture version), always scoped to an Issue:

* it is stored once, in canonical order -- the endpoint with the smaller
  `(family token, record_id)` by code point is `from` -- so both request orders
  are one identity and, under one key, one request;
* `context_issue_id` is required, and both endpoints must be inside that
  Issue at assert time (the Issue, an active member, or a member of an active
  member's pair set);
* it needs an exact `corroborates` anchor; a self-link is refused;
* the reverse read follows it like any context-scoped link, so it never
  bridges Issues.

Every identity and every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from my_pa.application.commands import ReadRecordLineage
from tests.database.lineage_record_harness import capture, legacy_anchor, note_anchor
from tests.database.lineage_s3_harness import (
    GATEWAY,
    NOTE_BODY,
    S3Runtime,
    all_s3_counts,
    corroborates,
    direct_task,
    related,
)

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3Runtime]:
    composed = S3Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _ok(runtime: S3Runtime, command: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    return runtime.ok(command, **kwargs)


def _refused(runtime: S3Runtime, command: Any, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    error = runtime.refused(command, **kwargs)
    return str(error["code"]), list(error.get("safe_details") or [])


def _scene(runtime: S3Runtime, key: str) -> dict[str, Any]:
    """An Issue with a Meeting (one note) and a Task as `reference` members, and an anchor."""
    issue = runtime.issue(key)
    meeting_id, note_id = runtime.note(key)
    task_id = runtime.task(key)
    runtime.member(issue, "meeting", meeting_id, f"{key}-m", "reference")
    runtime.member(issue, "task", task_id, f"{key}-t", "reference")
    return {
        "issue": issue,
        "meeting": meeting_id,
        "note": note_id,
        "task": task_id,
        "anchor": corroborates(meeting_id, note_id),
    }


def _stored(runtime: S3Runtime, link_id: str) -> tuple[str, str, str, str]:
    with runtime.engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT from_family, from_id, to_family, to_id FROM knowledge.record_links "
                "WHERE link_id = :link"
            ),
            {"link": link_id},
        ).one()
    return (row.from_family, row.from_id, row.to_family, row.to_id)


def test_related_context_is_stored_once_in_canonical_order(runtime: S3Runtime) -> None:
    scene = _scene(runtime, "canonical")
    meeting = ("meeting", scene["meeting"])
    task = ("task", scene["task"])
    # Named task -> meeting; `meeting` < `task` by family token, so it is stored the other way.
    first = _ok(
        runtime, related(task, meeting, "canonical", (scene["anchor"],), context=scene["issue"])
    )
    view = first["association"]
    assert first["created"] is True
    assert (view["from"], view["to"]) == (
        {"family": "meeting", "record_id": scene["meeting"]},
        {"family": "task", "record_id": scene["task"]},
    )
    assert _stored(runtime, view["link_id"]) == ("meeting", scene["meeting"], "task", scene["task"])
    # The other order under the same key is the same request: a replay.
    replay = _ok(
        runtime, related(meeting, task, "canonical", (scene["anchor"],), context=scene["issue"])
    )
    assert replay["replayed"] is True
    assert replay["association"] == view
    # Under a new key it is the same identity: the existing link answers.
    again = _ok(
        runtime,
        related(meeting, task, "canonical-again", (scene["anchor"],), context=scene["issue"]),
    )
    assert (again["created"], again["association"]["link_id"]) == (False, view["link_id"])
    with runtime.engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.record_links "
                    "WHERE relation_type = 'related_context'"
                )
            ).scalar_one()
            == 1
        )


def test_related_context_needs_a_context_and_both_endpoints_inside(runtime: S3Runtime) -> None:
    scene = _scene(runtime, "inside")
    outsider = runtime.task("inside-outsider")
    other_meeting, other_note = runtime.note("inside-outsider")
    meeting = ("meeting", scene["meeting"])
    task = ("task", scene["task"])
    before = all_s3_counts(runtime.engine)
    # No context: refused before anything is locked.
    assert _refused(
        runtime, related(meeting, task, "no-context", (scene["anchor"],), context=None)
    ) == (
        "invalid_request",
        ["context_issue_id"],
    )
    # `from` (the canonical smaller endpoint) outside the Issue.
    assert _refused(
        runtime,
        related(
            ("meeting", other_meeting),
            task,
            "from-outside",
            (scene["anchor"],),
            context=scene["issue"],
        ),
    ) == ("invalid_request", ["from"])
    # `to` outside the Issue.
    assert _refused(
        runtime,
        related(
            meeting, ("task", outsider), "to-outside", (scene["anchor"],), context=scene["issue"]
        ),
    ) == ("invalid_request", ["to"])
    assert all_s3_counts(runtime.engine) == before
    # A note version of a member Meeting is inside through the pair set; so is the Issue.
    inside = _ok(
        runtime,
        related(
            ("meeting_note_version", scene["note"]),
            task,
            "pair-set",
            (scene["anchor"],),
            context=scene["issue"],
        ),
    )
    assert inside["created"] is True
    del other_note


def test_related_context_needs_corroborating_exact_evidence(runtime: S3Runtime) -> None:
    scene = _scene(runtime, "evidence")
    capture_id, _, _ = capture(runtime, "evidence-legacy")
    meeting = ("meeting", scene["meeting"])
    task = ("task", scene["task"])
    before = all_s3_counts(runtime.engine)
    for name, anchor in (
        ("origin", note_anchor(scene["meeting"], scene["note"], NOTE_BODY, role="origin")),
        ("legacy", legacy_anchor(capture_id, role="corroborates")),
    ):
        assert _refused(
            runtime, related(meeting, task, name, (anchor,), context=scene["issue"])
        ) == ("invalid_request", ["evidence_anchors"]), name
    assert all_s3_counts(runtime.engine) == before
    written = _ok(
        runtime, related(meeting, task, "good", (scene["anchor"],), context=scene["issue"])
    )
    assert [anchor["role"] for anchor in written["association"]["evidence"]] == ["corroborates"]


def test_a_related_context_self_link_is_refused(runtime: S3Runtime) -> None:
    scene = _scene(runtime, "self")
    before = all_s3_counts(runtime.engine)
    task = ("task", scene["task"])
    assert _refused(
        runtime, related(task, task, "self", (scene["anchor"],), context=scene["issue"])
    ) == (
        "invalid_request",
        ["to"],
    )
    assert all_s3_counts(runtime.engine) == before


def test_related_context_is_never_followed_across_issues(runtime: S3Runtime) -> None:
    scene = _scene(runtime, "across")
    second = runtime.issue("across-second")
    runtime.member(second, "meeting", scene["meeting"], "across-second-m", "reference")
    other_task = runtime.task("across-second")
    runtime.member(second, "task", other_task, "across-second-t", "reference")
    link = _ok(
        runtime,
        related(
            ("meeting", scene["meeting"]),
            ("task", scene["task"]),
            "across",
            (scene["anchor"],),
            context=scene["issue"],
        ),
    )["association"]["link_id"]

    def read(issue_id: str) -> dict[str, Any]:
        return runtime.ok(
            ReadRecordLineage(
                origin={"family": "meeting", "record_id": scene["meeting"]}, issue_id=issue_id
            )
        )

    in_first = read(scene["issue"])
    assert link in {edge["link_id"] for edge in in_first["typed_edges"]}
    in_second = read(second)
    assert link not in {edge["link_id"] for edge in in_second["typed_edges"]}
    assert ("task", scene["task"]) not in {
        (node["family"], node["record_id"]) for node in in_second["nodes"]
    }


def test_mixed_case_endpoints_are_ordered_by_code_point(runtime: S3Runtime) -> None:
    issue = runtime.issue("mixed")
    # Code point: "B" (66) < "a" (97); a case-insensitive collation orders them the other way.
    upper = direct_task(runtime.engine, "tsk_Bmixedcase000001")
    lower = direct_task(runtime.engine, "tsk_amixedcase000001")
    runtime.member(issue, "task", upper, "mixed-upper", "reference")
    runtime.member(issue, "task", lower, "mixed-lower", "reference")
    meeting_id, note_id = runtime.note("mixed")
    written = _ok(
        runtime,
        related(
            ("task", lower),
            ("task", upper),
            "mixed",
            (corroborates(meeting_id, note_id),),
            context=issue,
        ),
    )["association"]
    assert (written["from"]["record_id"], written["to"]["record_id"]) == (upper, lower)
    assert _stored(runtime, written["link_id"]) == ("task", upper, "task", lower)
