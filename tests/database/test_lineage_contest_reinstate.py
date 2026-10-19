"""AT-007 (S3) and the S2 residual: contest, reinstate and the contested closure gate.

S3 contract sections 3.1, 3.2, 6.2 and 7.4, through `ApplicationService.invoke`
against PostgreSQL:

* `records.associations.contest` moves an active semantic link to `contested`
  with an exact `contradicts` anchor; `.reinstate` moves it back to `active`
  re-applying the relation's own evidence rule; `ended` stays terminal and a
  membership is never contested;
* a contested link keeps its identity: an assert of it is `conflict` /
  `state`, and a contested `blocks` link still closes no cycle;
* a contested link **in the Issue's context** -- scoped to it, naming it as an
  endpoint, or a null-context link with both endpoints inside it -- holds the
  close (`conflict` / `closure_gate`) and is listed by
  `issues.closure_readiness`;
* a closed Issue refuses a contest of any link in its context, including a
  null-context link inside it (`conflict` / `state`);
* the S1 reverse read shows a contested link as contested.

Every write takes one commit mark (section 6.2 step 1b), stamped on its
revision and its request row. Every identity and every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from my_pa.application.commands import EndRecordAssociation, ReadRecordLineage
from tests.database.lineage_record_harness import capture, legacy_anchor, note_anchor
from tests.database.lineage_s2_harness import assertion, close, reopen
from tests.database.lineage_s3_harness import (
    GATEWAY,
    NOTE_BODY,
    S3Runtime,
    all_s3_counts,
    blocks_scene,
    contest,
    corroborates,
    mark_count,
    mark_taken_first,
    reinstate,
    statements,
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


def _closure_set(runtime: S3Runtime, key: str) -> tuple[dict[str, object], ...]:
    _, _, anchor = runtime.evidence_source(f"{key}-closure")
    return (anchor,)


def _revision_marks(runtime: S3Runtime, link_id: str) -> list[tuple[int, str, int | None]]:
    with runtime.engine.connect() as connection:
        return [
            (int(row.revision_no), str(row.action), row.commit_seq)
            for row in connection.execute(
                text(
                    "SELECT revision_no, action, commit_seq FROM knowledge.record_link_revisions "
                    "WHERE link_id = :link ORDER BY revision_no"
                ),
                {"link": link_id},
            )
        ]


def _request_mark(runtime: S3Runtime, capability: str, key: str) -> int | None:
    with runtime.engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT commit_seq FROM knowledge.lineage_write_requests "
                "WHERE capability = :capability AND idempotency_key = :key"
            ),
            {"capability": capability, "key": key},
        ).scalar_one()
    return None if value is None else int(value)


# ---- the evidence and transition rules --------------------------------------------------


def test_contest_needs_a_contradicting_exact_anchor(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "contest-evidence")
    capture_id, _, _ = capture(runtime, "contest-evidence-legacy")
    before = all_s3_counts(runtime.engine)
    for name, anchors in (
        # Exact, but no `contradicts` role.
        ("bad-role", (scene["corroborates"],)),
        # A `contradicts` anchor on a legacy Capture root is not exact.
        ("bad-legacy", (legacy_anchor(capture_id, role="contradicts"),)),
    ):
        assert _refused(runtime, contest(scene["link"], 1, name, anchors)) == (
            "invalid_request",
            ["evidence_anchors"],
        ), name
    assert all_s3_counts(runtime.engine) == before
    # Any other role is admitted beside the contradicting one.
    contested = _ok(
        runtime,
        contest(
            scene["link"],
            1,
            "good",
            (
                scene["contradicts"],
                note_anchor(
                    scene["meeting"],
                    scene["note"],
                    NOTE_BODY,
                    role="corroborates",
                    passage="Ana will send",
                ),
            ),
        ),
    )["association"]
    assert contested["lifecycle_state"] == "contested"
    assert sorted(anchor["role"] for anchor in contested["evidence"]) == [
        "contradicts",
        "corroborates",
    ]


def test_contest_then_reinstate_restores_active(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "round-trip")
    marks = mark_count(runtime.engine)
    with statements(runtime.engine) as contest_statements:
        contested = _ok(runtime, contest(scene["link"], 1, "round-trip", (scene["contradicts"],)))
    assert contested["replayed"] is False
    # Section 6.2 step 1b: the mark right after the reservation, before any lock.
    assert mark_taken_first(contest_statements)
    assert contested["association"]["revision_no"] == 2
    assert contested["association"]["lifecycle_state"] == "contested"
    with statements(runtime.engine) as reinstate_statements:
        reinstated = _ok(
            runtime, reinstate(scene["link"], 2, "round-trip", (scene["corroborates"],))
        )
    assert mark_taken_first(reinstate_statements)
    view = reinstated["association"]
    assert (view["link_id"], view["revision_no"], view["lifecycle_state"]) == (
        scene["link"],
        3,
        "active",
    )
    assert [anchor["role"] for anchor in view["evidence"]] == ["corroborates"]
    # Each write took exactly one mark, stamped on its revision and its request.
    assert mark_count(runtime.engine) == marks + 2
    revisions = _revision_marks(runtime, scene["link"])
    assert [(number, action) for number, action, _ in revisions] == [
        (1, "assert"),
        (2, "contest"),
        (3, "reinstate"),
    ]
    assert revisions[1][2] == _request_mark(
        runtime, "records.associations.contest", "s3-contest-round-trip"
    )
    assert revisions[2][2] == _request_mark(
        runtime, "records.associations.reinstate", "s3-reinstate-round-trip"
    )
    assert revisions[1][2] is not None and revisions[2][2] == revisions[1][2] + 1
    # A replay answers the stored revision and takes no mark.
    replayed = _ok(runtime, contest(scene["link"], 1, "round-trip", (scene["contradicts"],)))
    assert replayed["replayed"] is True
    assert replayed["association"] == contested["association"]
    assert mark_count(runtime.engine) == marks + 2
    # Reinstated, the link can be contested again and correctly ended from there.
    _ok(runtime, contest(scene["link"], 3, "round-trip-again", (scene["contradicts"],)))
    ended = _ok(
        runtime,
        EndRecordAssociation(
            link_id=scene["link"],
            expected_revision=4,
            idempotency_key="s3-end-contested",
            reason="Withdrawn.",
        ),
    )["association"]
    assert (ended["revision_no"], ended["lifecycle_state"]) == (5, "ended")


def test_reinstate_reapplies_the_relation_evidence_rule(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "reinstate-rule")
    _ok(runtime, contest(scene["link"], 1, "reinstate-rule", (scene["contradicts"],)))
    before = all_s3_counts(runtime.engine)
    # `blocks` needs an exact `corroborates` anchor; a contradicting set does not do.
    assert _refused(
        runtime, reinstate(scene["link"], 2, "reinstate-rule-bad", (scene["contradicts"],))
    ) == ("invalid_request", ["evidence_anchors"])
    passage = note_anchor(scene["meeting"], scene["note"], NOTE_BODY, role="origin")
    assert _refused(runtime, reinstate(scene["link"], 2, "reinstate-rule-origin", (passage,))) == (
        "invalid_request",
        ["evidence_anchors"],
    )
    assert all_s3_counts(runtime.engine) == before
    reinstated = _ok(
        runtime, reinstate(scene["link"], 2, "reinstate-rule-good", (scene["corroborates"],))
    )
    assert reinstated["association"]["lifecycle_state"] == "active"


def test_a_contested_identity_cannot_be_asserted_again(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "identity")
    again = assertion(
        "blocks",
        ("task", scene["first"]),
        ("task", scene["second"]),
        "identity-again",
        (scene["corroborates"],),
        context=scene["issue"],
    )
    # While active, the same meaning answers the existing link.
    repeated = _ok(runtime, again)
    assert (repeated["created"], repeated["association"]["link_id"]) == (False, scene["link"])
    _ok(runtime, contest(scene["link"], 1, "identity", (scene["contradicts"],)))
    before = all_s3_counts(runtime.engine)
    later = assertion(
        "blocks",
        ("task", scene["first"]),
        ("task", scene["second"]),
        "identity-later",
        (scene["corroborates"],),
        context=scene["issue"],
    )
    # Never `created: false`: that would hand back a disputed claim as success.
    assert _refused(runtime, later) == ("conflict", ["state"])
    assert all_s3_counts(runtime.engine) == before


def test_an_ended_link_cannot_be_reinstated(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "ended")
    _ok(runtime, contest(scene["link"], 1, "ended", (scene["contradicts"],)))
    _ok(
        runtime,
        EndRecordAssociation(
            link_id=scene["link"],
            expected_revision=2,
            idempotency_key="s3-ended-end",
            reason="The claim was wrong.",
        ),
    )
    before = all_s3_counts(runtime.engine)
    assert _refused(runtime, reinstate(scene["link"], 3, "ended", (scene["corroborates"],))) == (
        "conflict",
        ["state"],
    )
    assert _refused(runtime, contest(scene["link"], 3, "ended-again", (scene["contradicts"],))) == (
        "conflict",
        ["state"],
    )
    # An active link is not reinstated either; a stale revision stays `stale_version`.
    assert all_s3_counts(runtime.engine) == before
    other = blocks_scene(runtime, "ended-other")
    before = all_s3_counts(runtime.engine)
    assert _refused(
        runtime, reinstate(other["link"], 1, "ended-other", (other["corroborates"],))
    ) == ("conflict", ["state"])
    assert _refused(runtime, contest(other["link"], 2, "ended-other", (other["contradicts"],))) == (
        "conflict",
        ["stale_version"],
    )
    assert all_s3_counts(runtime.engine) == before


def test_a_membership_cannot_be_contested(runtime: S3Runtime) -> None:
    issue = runtime.issue("membership")
    task_id = runtime.task("membership")
    link = runtime.member(issue, "task", task_id, "membership", "reference")
    meeting_id, note_id = runtime.note("membership-source")
    before = all_s3_counts(runtime.engine)
    anchor = note_anchor(meeting_id, note_id, NOTE_BODY, role="contradicts", passage=None)
    assert _refused(runtime, contest(link, 1, "membership", (anchor,))) == (
        "invalid_request",
        ["link_id"],
    )
    assert _refused(
        runtime, reinstate(link, 1, "membership", (corroborates(meeting_id, note_id),))
    ) == ("invalid_request", ["link_id"])
    assert all_s3_counts(runtime.engine) == before


# ---- the closure gate -------------------------------------------------------------------


def test_a_contested_link_in_the_issue_context_blocks_closure(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "gate")
    issue = scene["issue"]
    _ok(runtime, contest(scene["link"], 1, "gate", (scene["contradicts"],)))
    before = all_s3_counts(runtime.engine)
    assert _refused(runtime, close(issue, 1, "gate", _closure_set(runtime, "gate"))) == (
        "conflict",
        ["closure_gate"],
    )
    assert all_s3_counts(runtime.engine) == before
    # Reinstating resolves the dispute; the close then succeeds.
    _ok(runtime, reinstate(scene["link"], 2, "gate", (scene["corroborates"],)))
    closed = _ok(runtime, close(issue, 1, "gate-after", _closure_set(runtime, "gate-after")))
    assert closed["issue"]["state"] == "closed"
    # A link contested in another Issue's context does not hold this one.
    elsewhere = blocks_scene(runtime, "gate-elsewhere")
    _ok(runtime, contest(elsewhere["link"], 1, "gate-elsewhere", (elsewhere["contradicts"],)))
    unrelated = runtime.issue("gate-unrelated")
    assert (
        _ok(runtime, close(unrelated, 1, "gate-unrelated", _closure_set(runtime, "gu")))["issue"][
            "state"
        ]
        == "closed"
    )


def test_closure_readiness_lists_contested_links(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "readiness")
    issue = scene["issue"]
    assert runtime.readiness(issue)["ready"] is True
    assert runtime.readiness(issue)["contested_links"] == []
    _ok(runtime, contest(scene["link"], 1, "readiness", (scene["contradicts"],)))
    readiness = runtime.readiness(issue)
    assert readiness["ready"] is False
    assert readiness["blockers"] == []
    assert readiness["contested_links"] == [{"link_id": scene["link"], "relation_type": "blocks"}]
    assert readiness["contested_links_truncated"] is False
    _ok(runtime, reinstate(scene["link"], 2, "readiness", (scene["corroborates"],)))
    readiness = runtime.readiness(issue)
    assert (readiness["ready"], readiness["contested_links"]) == (True, [])


def test_contest_in_a_closed_issue_context_is_refused(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "frozen")
    issue = scene["issue"]
    _ok(runtime, close(issue, 1, "frozen", _closure_set(runtime, "frozen")))
    before = all_s3_counts(runtime.engine)
    assert _refused(runtime, contest(scene["link"], 1, "frozen", (scene["contradicts"],))) == (
        "conflict",
        ["state"],
    )
    assert all_s3_counts(runtime.engine) == before
    # Reopened, the Issue admits the contest again.
    _ok(runtime, reopen(issue, 2, "frozen"))
    assert (
        _ok(runtime, contest(scene["link"], 1, "frozen-reopened", (scene["contradicts"],)))[
            "association"
        ]["lifecycle_state"]
        == "contested"
    )
    # The dispute now holds the close, so a closed Issue never carries one.
    assert _refused(runtime, close(issue, 3, "frozen-held", _closure_set(runtime, "fh"))) == (
        "conflict",
        ["closure_gate"],
    )


def test_a_contested_blocks_link_still_refuses_a_cycle(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "cycle", context=False)
    _ok(runtime, contest(scene["link"], 1, "cycle", (scene["contradicts"],)))
    before = all_s3_counts(runtime.engine)
    reverse = assertion(
        "blocks",
        ("task", scene["second"]),
        ("task", scene["first"]),
        "cycle-reverse",
        (scene["corroborates"],),
    )
    assert _refused(runtime, reverse) == ("invalid_request", ["blocks_cycle"])
    assert all_s3_counts(runtime.engine) == before
    # Once ended, the contested edge leaves the search.
    _ok(
        runtime,
        EndRecordAssociation(
            link_id=scene["link"],
            expected_revision=2,
            idempotency_key="s3-cycle-end",
            reason="The dispute held.",
        ),
    )
    assert _ok(runtime, reverse)["created"] is True


def test_a_contested_link_reads_as_contested_in_lineage(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "read", members=True)
    _ok(runtime, contest(scene["link"], 1, "read", (scene["contradicts"],)))
    answer = runtime.ok(
        ReadRecordLineage(
            origin={"family": "task", "record_id": scene["first"]}, issue_id=scene["issue"]
        )
    )
    edges = {edge["link_id"]: edge for edge in answer["typed_edges"]}
    assert edges[scene["link"]]["lifecycle_state"] == "contested"
    assert edges[scene["link"]]["revision_no"] == 2
    assert {(node["family"], node["record_id"]) for node in answer["nodes"]} >= {
        ("task", scene["first"]),
        ("task", scene["second"]),
    }


def test_a_contested_link_naming_the_issue_as_endpoint_blocks_closure(
    runtime: S3Runtime,
) -> None:
    issue = runtime.issue("endpoint")
    meeting_id, note_id = runtime.note("endpoint")
    discussion = note_anchor(meeting_id, note_id, NOTE_BODY, role="discussion")
    written = _ok(
        runtime,
        assertion(
            "discusses",
            ("meeting_note_version", note_id),
            ("situation", issue),
            "endpoint",
            (discussion,),
        ),
    )["association"]
    # A null-context link: in the Issue's context only because it names the Issue.
    assert written["context_issue_id"] is None
    _ok(
        runtime,
        contest(
            written["link_id"],
            1,
            "endpoint",
            (note_anchor(meeting_id, note_id, NOTE_BODY, role="contradicts", passage=None),),
        ),
    )
    readiness = runtime.readiness(issue)
    assert readiness["contested_links"] == [
        {"link_id": written["link_id"], "relation_type": "discusses"}
    ]
    assert _refused(runtime, close(issue, 1, "endpoint", _closure_set(runtime, "endpoint"))) == (
        "conflict",
        ["closure_gate"],
    )


def test_a_contested_null_context_link_inside_the_issue_blocks_closure(
    runtime: S3Runtime,
) -> None:
    scene = blocks_scene(runtime, "inside", context=False, members=True)
    issue = scene["issue"]
    _ok(runtime, contest(scene["link"], 1, "inside", (scene["contradicts"],)))
    assert runtime.readiness(issue)["contested_links"] == [
        {"link_id": scene["link"], "relation_type": "blocks"}
    ]
    assert _refused(runtime, close(issue, 1, "inside", _closure_set(runtime, "inside"))) == (
        "conflict",
        ["closure_gate"],
    )
    # The same link outside every Issue (no member endpoints) holds no close.
    outside = blocks_scene(runtime, "outside", context=False)
    _ok(runtime, contest(outside["link"], 1, "outside", (outside["contradicts"],)))
    assert runtime.readiness(outside["issue"])["contested_links"] == []
    assert (
        _ok(runtime, close(outside["issue"], 1, "outside", _closure_set(runtime, "outside")))[
            "issue"
        ]["state"]
        == "closed"
    )


def test_a_closed_issue_refuses_contest_of_a_null_context_link_inside_it(
    runtime: S3Runtime,
) -> None:
    scene = blocks_scene(runtime, "inside-frozen", context=False, members=True)
    issue = scene["issue"]
    _ok(runtime, close(issue, 1, "inside-frozen", _closure_set(runtime, "inside-frozen")))
    before = all_s3_counts(runtime.engine)
    assert _refused(
        runtime, contest(scene["link"], 1, "inside-frozen", (scene["contradicts"],))
    ) == ("conflict", ["state"])
    assert all_s3_counts(runtime.engine) == before
    # The same rule for an end: a closed Issue neither acquires nor loses a link's state.
    assert _refused(
        runtime,
        EndRecordAssociation(
            link_id=scene["link"],
            expected_revision=1,
            idempotency_key="s3-inside-frozen-end",
            reason="Withdrawn.",
        ),
    ) == ("conflict", ["state"])
    assert all_s3_counts(runtime.engine) == before
    # A null-context link inside several Issues is refused while any is closed.
    _ok(runtime, reopen(issue, 2, "inside-frozen"))
    second = runtime.issue("inside-frozen-second")
    runtime.member(second, "task", scene["first"], "inside-frozen-second-a", "reference")
    runtime.member(second, "task", scene["second"], "inside-frozen-second-b", "reference")
    _ok(runtime, close(second, 1, "inside-frozen-second", _closure_set(runtime, "ifs")))
    assert _refused(
        runtime, contest(scene["link"], 1, "inside-frozen-both", (scene["contradicts"],))
    ) == ("conflict", ["state"])
