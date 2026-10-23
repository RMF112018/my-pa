"""WP-02C: the S2 relation matrix rules against PostgreSQL (S2 contract section 3.1).

Through `ApplicationService.invoke`. The creation relations
(`delegated_from`, `created_to_resolve`) are written only by the composites
and refused by `records.associations.assert`; each composite admits only its
own intent relations and pairs; the assert-time rules (membership, Task
state, Commitment direction, the composite's own Issue) are checked when the
link is created and only then: a correction re-applies only the relation's
evidence rule (R2-F07).

`records.associations.assert` admits `escalated_from` (Issue-scoped, an
exact `origin` anchor, a published Constraint not older than its Task, a
Project linked to the Issue, a Task member of it) and `blocks` (an exact
`corroborates` anchor, never a self-loop, never a cycle over the Principal's
active `blocks` links, a search bounded at 1000 records that refuses rather
than admits when it cannot finish); a correction re-applies only their
evidence rules, and no lineage write moves a Constraint's ball-in-court. Every
identity is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text

from my_pa.application.commands import (
    CorrectRecordAssociation,
    CreateConstraintDraft,
    EndIssueMembership,
    EndIssueProjectLink,
    EndRecordAssociation,
    ReadConstraint,
    ReadIssue,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.application.record_lineage import MAX_BLOCKS_SEARCH
from my_pa.domain.task.lifecycle import TaskLifecycleState
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    capture,
    legacy_anchor,
    meeting,
    note_anchor,
)
from tests.database.lineage_s2_harness import (
    GATEWAY,
    REVIEW_DECISION,
    S2Runtime,
    all_s2_counts,
    assertion,
    correct,
    work_commitment,
    work_task,
)
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity
from tests.database.test_lineage_integrity_guards import (
    CHECK,
    _link_values,
    _task,
    _write_link,
)
from tests.database.test_lineage_integrity_guards import (
    _refused as _refused_sql,
)

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S2Runtime]:
    composed = S2Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _ok(runtime: S2Runtime, command: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    return runtime.ok(command, **kwargs)


def _refused(runtime: S2Runtime, command: Any, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    error = runtime.refused(command, **kwargs)
    return str(error["code"]), list(error.get("safe_details") or [])


def _commitment(
    runtime: S2Runtime, key: str, *, direction: str = "owed_to_principal"
) -> dict[str, object]:
    origin, _, _ = capture(runtime, f"{key}-native-origin")
    return {
        "counterparty_entity_id": seed_counterparty_entity(runtime.engine, PRINCIPAL),
        "direction": direction,
        "summary": f"Synthetic commitment {key}",
        "origin_evidence_ref": origin,
        "accepted_by_review_decision_id": REVIEW_DECISION,
    }


def _intent(
    relation: str, family: str, record_id: str, *anchors: dict[str, object]
) -> dict[str, object]:
    intent: dict[str, object] = {
        "relation_type": relation,
        "to_record": {"family": family, "record_id": record_id},
        "evidence_anchors": list(anchors),
    }
    if relation == "created_to_resolve":
        intent["purpose"] = "Resolve it."
    return intent


def _shape_refusal(build: Any) -> list[str]:  # noqa: ANN401
    with pytest.raises(InvalidRequestError) as caught:
        build()
    return [detail.value for detail in caught.value.safe_details]


def test_s2_relations_are_admitted_only_in_the_matrix(runtime: S2Runtime) -> None:
    issue = runtime.issue("matrix")
    member_task = _ok(runtime, work_task(issue, "matrix-t1"))["record"]["record_id"]
    meeting_id, note_id = meeting(runtime, "matrix-n1")
    origin = note_anchor(meeting_id, note_id, NOTE_BODY)
    corroborates = note_anchor(meeting_id, note_id, NOTE_BODY, role="corroborates")
    project = runtime.project_with_constraints("matrix")
    constraint = runtime.constraint(project, "matrix-x1")
    native = _commitment(runtime, "matrix-native")
    # Shapes refused by the request alone: a relation the composite does not
    # write, a pair outside the matrix, a repeated meaning, more than four.
    for build in (
        lambda: work_task(
            issue, "m-1", intents=(_intent("delegated_from", "task", member_task, origin),)
        ),
        lambda: work_task(
            issue, "m-2", intents=(_intent("escalated_from", "task", member_task, origin),)
        ),
        lambda: work_task(issue, "m-3", intents=(_intent("blocks", "task", member_task, origin),)),
        lambda: work_task(
            issue, "m-4", intents=(_intent("issue_member", "task", member_task, origin),)
        ),
        lambda: work_commitment(
            issue,
            "m-5",
            native,
            intents=(_intent("originated_from", "task", member_task, origin),),
        ),
        lambda: work_task(
            issue, "m-6", intents=(_intent("created_to_resolve", "meeting", meeting_id),)
        ),
        lambda: work_task(
            issue,
            "m-7",
            intents=(
                _intent("created_to_resolve", "situation", issue),
                _intent("created_to_resolve", "situation", issue),
            ),
        ),
        lambda: work_task(
            issue,
            "m-8",
            intents=tuple(_intent("created_to_resolve", "situation", issue) for _ in range(5)),
        ),
        lambda: work_task(issue, "m-9", intents=({"relation_type": "created_to_resolve"},)),
    ):
        assert _shape_refusal(build) == ["association_intents"]
    other_issue = runtime.issue("matrix-other")
    outsider = runtime.task("matrix-outsider")
    # The assert-time rules, each with its own detail, and nothing written.
    refusals = [
        # `delegated_from` needs an exact origin anchor ...
        (
            work_commitment(
                issue,
                "r-1",
                _commitment(runtime, "r-1"),
                intents=(_intent("delegated_from", "task", member_task, corroborates),),
            ),
            ("invalid_request", ["evidence_anchors"]),
        ),
        # ... a Task that is an active member of the Issue ...
        (
            work_commitment(
                issue,
                "r-2",
                _commitment(runtime, "r-2"),
                intents=(_intent("delegated_from", "task", outsider, origin),),
            ),
            ("invalid_request", ["to"]),
        ),
        # ... and an owed-to-Principal Commitment.
        (
            work_commitment(
                issue,
                "r-3",
                _commitment(runtime, "r-3", direction="owed_by_principal"),
                intents=(_intent("delegated_from", "task", member_task, origin),),
            ),
            ("invalid_request", ["direction"]),
        ),
        # `created_to_resolve` targets the composite's own Issue ...
        (
            work_task(
                issue, "r-4", intents=(_intent("created_to_resolve", "situation", other_issue),)
            ),
            ("invalid_request", ["to"]),
        ),
        # ... or a Constraint that is an active member of it.
        (
            work_task(
                issue, "r-5", intents=(_intent("created_to_resolve", "constraint", constraint),)
            ),
            ("invalid_request", ["to"]),
        ),
        # `originated_from` keeps its S1 rule: an exact origin on the version.
        (
            work_task(
                issue,
                "r-6",
                intents=(
                    _intent("originated_from", "meeting_note_version", note_id, corroborates),
                ),
            ),
            ("invalid_request", ["evidence_anchors"]),
        ),
    ]
    counts = all_s2_counts(runtime.engine)
    for command, answer in refusals:
        assert _refused(runtime, command) == answer, command.idempotency_key
    assert all_s2_counts(runtime.engine) == counts
    # A terminal Task is not delegated from.
    done = _ok(runtime, work_task(issue, "matrix-done"))["record"]["record_id"]
    runtime.transition(done, TaskLifecycleState.COMPLETED, "matrix-done")
    assert _refused(
        runtime,
        work_commitment(
            issue,
            "r-7",
            _commitment(runtime, "r-7"),
            intents=(_intent("delegated_from", "task", done, origin),),
        ),
    ) == ("invalid_request", ["endpoint"])
    # Each admitted row is admitted.
    runtime.member(issue, "constraint", constraint, "matrix-x1", "constraint")
    written = _ok(
        runtime,
        work_commitment(
            issue,
            "a-1",
            _commitment(runtime, "a-1"),
            intents=(
                _intent("delegated_from", "task", member_task, origin),
                _intent("created_to_resolve", "constraint", constraint),
                _intent("created_to_resolve", "situation", issue),
                _intent("originated_from", "meeting_note_version", note_id, origin),
            ),
        ),
    )
    assert [view["relation_type"] for view in written["associations"]] == [
        "delegated_from",
        "created_to_resolve",
        "created_to_resolve",
        "originated_from",
    ]
    # The database admits a creation pair only in the matrix, as the application does.
    with runtime.engine.connect() as connection:
        definition = connection.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'a_record_link_pair_is_admitted'"
            )
        ).scalar_one()
    assert "delegated_from" in definition and "created_to_resolve" in definition
    # `records.associations.assert` admits `escalated_from` and `blocks` only in
    # their own pairs, refused by the request alone otherwise.
    corroborating = note_anchor(meeting_id, note_id, NOTE_BODY, role="corroborates")
    for build in (
        lambda: assertion(
            "escalated_from",
            ("task", member_task),
            ("constraint", constraint),
            "m-10",
            (origin,),
            context=issue,
        ),
        lambda: assertion(
            "escalated_from", ("constraint", constraint), ("situation", issue), "m-11", (origin,)
        ),
        lambda: assertion(
            "blocks",
            ("commitment", "cmt_lineages2absent0001"),
            ("task", member_task),
            "m-12",
            (corroborating,),
        ),
        lambda: assertion(
            "blocks", ("task", member_task), ("situation", issue), "m-13", (corroborating,)
        ),
    ):
        assert _shape_refusal(build) == ["relation_type"]
    scene = _escalation(runtime, "matrix-esc")
    counts = all_s2_counts(runtime.engine)
    # An escalation names a Task that is an active member of its Issue.
    outside = assertion(
        "escalated_from",
        ("constraint", scene.constraint),
        ("task", scene.outsider),
        "matrix-esc-outsider",
        (scene.origin,),
        context=scene.issue,
    )
    assert _refused(runtime, outside) == ("invalid_request", ["to"])
    assert all_s2_counts(runtime.engine) == counts
    escalated = _ok(runtime, _escalate(scene, "matrix-esc"))["association"]
    blocking = _ok(
        runtime,
        _blocks(
            ("constraint", scene.constraint), ("task", scene.task), "matrix-blk", scene.corroborates
        ),
    )["association"]
    assert (escalated["relation_type"], blocking["relation_type"]) == ("escalated_from", "blocks")


def test_a_correction_reapplies_only_the_evidence_rules(runtime: S2Runtime) -> None:
    issue = runtime.issue("correct")
    t1 = _ok(runtime, work_task(issue, "correct-t1"))["record"]["record_id"]
    meeting_id, note_id = meeting(runtime, "correct-n1")
    origin = note_anchor(meeting_id, note_id, NOTE_BODY)
    delegated = _ok(
        runtime,
        work_commitment(
            issue,
            "correct-c2",
            _commitment(runtime, "correct-c2"),
            intents=(
                _intent("delegated_from", "task", t1, origin),
                _intent("created_to_resolve", "situation", issue),
            ),
        ),
    )
    delegation, resolving = delegated["associations"]
    # T1 completes (stage 11): the Task is terminal, which the assert-time rule
    # would refuse; the correction does not re-run it.
    runtime.transition(t1, TaskLifecycleState.COMPLETED, "correct-t1")
    other_meeting, other_note = meeting(runtime, "correct-n2")
    second_origin = note_anchor(other_meeting, other_note, NOTE_BODY)
    corrected = _ok(
        runtime,
        CorrectRecordAssociation(
            link_id=delegation["link_id"],
            expected_revision=1,
            idempotency_key="s2-correct-delegation",
            reason="The delegation was recorded in a later note.",
            evidence_anchors=(second_origin,),
        ),
    )["association"]
    assert (corrected["revision_no"], corrected["relation_type"]) == (2, "delegated_from")
    # The evidence rule is re-applied: a set without an exact origin is refused.
    assert _refused(
        runtime,
        CorrectRecordAssociation(
            link_id=delegation["link_id"],
            expected_revision=2,
            idempotency_key="s2-correct-delegation-bad",
            reason="Only a corroboration.",
            evidence_anchors=(
                note_anchor(other_meeting, other_note, NOTE_BODY, role="corroborates"),
            ),
        ),
    ) == ("invalid_request", ["evidence_anchors"])
    # `created_to_resolve` admits any evidence set on correction.
    resolved = _ok(
        runtime,
        CorrectRecordAssociation(
            link_id=resolving["link_id"],
            expected_revision=1,
            idempotency_key="s2-correct-resolving",
            reason="Supporting evidence recorded.",
            evidence_anchors=(
                note_anchor(other_meeting, other_note, NOTE_BODY, role="corroborates"),
            ),
        ),
    )["association"]
    assert (resolved["revision_no"], resolved["relation_type"]) == (2, "created_to_resolve")
    # `escalated_from` and `blocks`: the world the assert checked moves on (the
    # Task leaves the Issue, the Project link ends); a correction re-applies
    # only the evidence rule and never re-runs the cycle search.
    scene = _escalation(runtime, "correct-esc")
    escalation = _ok(runtime, _escalate(scene, "correct-esc"))["association"]
    blocking = _ok(
        runtime,
        _blocks(
            ("task", scene.task),
            ("constraint", scene.constraint),
            "correct-blk",
            scene.corroborates,
        ),
    )["association"]
    _ok(
        runtime,
        EndIssueMembership(
            link_id=scene.task_link,
            expected_revision=1,
            idempotency_key="s2-correct-esc-leave",
            reason="The Task left the Issue.",
        ),
    )
    _ok(
        runtime,
        EndIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=1,
            idempotency_key="s2-correct-esc-unlink",
            reason="The Project left the Issue.",
        ),
    )
    for link, revision, key, anchors, answer in (
        (escalation, 1, "esc-bad", (scene.corroborates,), "evidence_anchors"),
        (escalation, 1, "esc-ok", (scene.origin, scene.corroborates), None),
        (blocking, 1, "blk-bad", (scene.origin,), "evidence_anchors"),
        (blocking, 1, "blk-ok", (scene.corroborates, scene.origin), None),
    ):
        command = CorrectRecordAssociation(
            link_id=link["link_id"],
            expected_revision=revision,
            idempotency_key=f"s2-correct-{key}",
            reason="Evidence corrected.",
            evidence_anchors=anchors,
        )
        if answer is None:
            view = _ok(runtime, command)["association"]
            assert (view["revision_no"], view["relation_type"]) == (2, link["relation_type"])
        else:
            assert _refused(runtime, command) == ("invalid_request", [answer]), key


# ---- escalated_from and blocks (S2 section 3.1, `records.associations.assert`) ----


@dataclass(frozen=True)
class _Escalation:
    """An Issue linked to a Project, a Task member and a later published Constraint."""

    issue: str
    project: str
    task: str
    task_link: str
    #: A Task created before the Constraint that is not a member of the Issue.
    outsider: str
    constraint: str
    meeting: str
    note: str

    @property
    def origin(self) -> dict[str, object]:
        return note_anchor(self.meeting, self.note, NOTE_BODY)

    @property
    def corroborates(self) -> dict[str, object]:
        # The whole version, so it never shares an identity with `origin`.
        return note_anchor(self.meeting, self.note, NOTE_BODY, role="corroborates", passage=None)


def _escalation(runtime: S2Runtime, key: str) -> _Escalation:
    issue = runtime.issue(key)
    project = runtime.project_with_constraints(key)
    runtime.link_project(issue, project, key)
    task_id = runtime.task(key)
    task_link = runtime.member(issue, "task", task_id, f"{key}-t", "work")
    outsider = runtime.task(f"{key}-outsider")
    constraint = runtime.constraint(project, key)
    meeting_id, note_id = meeting(runtime, f"{key}-n")
    return _Escalation(
        issue, project, task_id, task_link, outsider, constraint, meeting_id, note_id
    )


def _escalate(scene: _Escalation, key: str, *anchors: dict[str, object]) -> Any:  # noqa: ANN401
    return assertion(
        "escalated_from",
        ("constraint", scene.constraint),
        ("task", scene.task),
        key,
        anchors or (scene.origin,),
        context=scene.issue,
    )


def _blocks(
    source: tuple[str, str],
    target: tuple[str, str],
    key: str,
    anchor: dict[str, object],
    *,
    context: str | None = None,
) -> Any:  # noqa: ANN401
    return assertion("blocks", source, target, key, (anchor,), context=context)


def test_escalated_from_needs_an_origin_anchor_and_a_context(runtime: S2Runtime) -> None:
    scene = _escalation(runtime, "esc-anchor")
    counts = all_s2_counts(runtime.engine)
    no_context = assertion(
        "escalated_from",
        ("constraint", scene.constraint),
        ("task", scene.task),
        "esc-no-context",
        (scene.origin,),
    )
    assert _refused(runtime, no_context) == ("invalid_request", ["context_issue_id"])
    capture_id, _, _ = capture(runtime, "esc-legacy")
    for key, anchors in (
        ("esc-corroborates", (scene.corroborates,)),
        # A legacy Capture root is never exact evidence of anything.
        ("esc-legacy", (legacy_anchor(capture_id, role="corroborates"),)),
    ):
        assert _refused(runtime, _escalate(scene, key, *anchors)) == (
            "invalid_request",
            ["evidence_anchors"],
        )
    assert all_s2_counts(runtime.engine) == counts
    written = _ok(runtime, _escalate(scene, "esc-ok", scene.origin, scene.corroborates))
    view = written["association"]
    assert (view["relation_type"], view["kind"], view["context_issue_id"]) == (
        "escalated_from",
        "semantic",
        scene.issue,
    )
    assert (view["from"], view["to"]) == (
        {"family": "constraint", "record_id": scene.constraint},
        {"family": "task", "record_id": scene.task},
    )
    assert written["created"] is True
    # The same meaning again answers the active link.
    again = _ok(runtime, _escalate(scene, "esc-again", scene.origin))
    assert (again["created"], again["association"]["link_id"]) == (False, view["link_id"])
    # The database refuses a context-free escalation whatever wrote it.
    link = _link_values(
        PRINCIPAL,
        kind="semantic",
        relation="escalated_from",
        source=("constraint", scene.constraint),
        target=("task", scene.task),
    )
    _refused_sql(
        runtime.engine, lambda c: _write_link(c, link), CHECK, "an_escalation_is_issue_scoped"
    )


def test_escalated_from_refuses_a_draft_or_an_older_constraint(runtime: S2Runtime) -> None:
    scene = _escalation(runtime, "esc-age")
    draft = runtime.ok(
        CreateConstraintDraft(
            project_id=scene.project,
            description="Synthetic draft constraint",
            idempotency_key="s2-cst-esc-draft",
        )
    )["constraint"]["constraint_id"]
    # A Constraint published before the Task it would be escalated from.
    older = runtime.constraint(scene.project, "esc-older")
    later_task = runtime.task("esc-later")
    runtime.member(scene.issue, "task", later_task, "esc-later", "work")
    counts = all_s2_counts(runtime.engine)
    for constraint, task_id, detail in (
        (draft, scene.task, "endpoint"),
        (older, later_task, "from"),
    ):
        command = assertion(
            "escalated_from",
            ("constraint", constraint),
            ("task", task_id),
            f"esc-age-{detail}",
            (scene.origin,),
            context=scene.issue,
        )
        assert _refused(runtime, command) == ("invalid_request", [detail])
    assert all_s2_counts(runtime.engine) == counts
    # The same older Constraint escalates from a Task created before it.
    _ok(
        runtime,
        assertion(
            "escalated_from",
            ("constraint", older),
            ("task", scene.task),
            "esc-age-ok",
            (scene.origin,),
            context=scene.issue,
        ),
    )


def test_blocks_needs_corroborating_evidence(runtime: S2Runtime) -> None:
    scene = _escalation(runtime, "blk-anchor")
    other = runtime.task("blk-anchor-other")
    capture_id, _, _ = capture(runtime, "blk-legacy")
    counts = all_s2_counts(runtime.engine)
    for key, anchor in (
        ("blk-origin", scene.origin),
        ("blk-legacy", legacy_anchor(capture_id, role="corroborates")),
    ):
        command = _blocks(("task", scene.task), ("task", other), key, anchor)
        assert _refused(runtime, command) == ("invalid_request", ["evidence_anchors"])
    assert all_s2_counts(runtime.engine) == counts
    # Every admitted pair, with and without a context.
    for key, source, target, context in (
        ("blk-tt", ("task", scene.task), ("task", other), None),
        ("blk-tc", ("task", other), ("constraint", scene.constraint), scene.issue),
        ("blk-ct", ("constraint", scene.constraint), ("task", runtime.task("blk-ct")), None),
    ):
        view = _ok(runtime, _blocks(source, target, key, scene.corroborates, context=context))[
            "association"
        ]
        assert (view["relation_type"], view["context_issue_id"]) == ("blocks", context)


def test_a_blocks_self_loop_is_refused(runtime: S2Runtime) -> None:
    scene = _escalation(runtime, "blk-self")
    counts = all_s2_counts(runtime.engine)
    for family, record_id in (("task", scene.task), ("constraint", scene.constraint)):
        command = _blocks(
            (family, record_id), (family, record_id), f"blk-self-{family}", scene.corroborates
        )
        assert _refused(runtime, command) == ("invalid_request", ["to"])
    assert all_s2_counts(runtime.engine) == counts


def test_a_blocks_cycle_is_refused(runtime: S2Runtime) -> None:
    scene = _escalation(runtime, "blk-cycle")
    a, b, c = (("task", runtime.task(f"blk-cycle-{name}")) for name in "abc")
    x = ("constraint", scene.constraint)
    anchor = scene.corroborates
    _ok(runtime, _blocks(a, b, "cyc-ab", anchor))
    # Reachability ignores the context: B -> C is scoped to the Issue.
    bc = _ok(runtime, _blocks(b, c, "cyc-bc", anchor, context=scene.issue))["association"]
    _ok(runtime, _blocks(c, x, "cyc-cx", anchor))
    counts = all_s2_counts(runtime.engine)
    for key, source, target in (
        ("cyc-ba", b, a),
        ("cyc-ca", c, a),
        ("cyc-xa", x, a),
        ("cyc-xb", x, b),
    ):
        assert _refused(runtime, _blocks(source, target, key, anchor)) == (
            "invalid_request",
            ["blocks_cycle"],
        ), key
    assert all_s2_counts(runtime.engine) == counts
    # Repeating an existing edge is not a cycle.
    assert _ok(runtime, _blocks(a, b, "cyc-ab-again", anchor))["created"] is False
    # An ended link no longer blocks: with B -> C ended, X -> A closes nothing.
    _ok(
        runtime,
        EndRecordAssociation(
            link_id=bc["link_id"],
            expected_revision=1,
            idempotency_key="s2-cyc-end-bc",
            reason="No longer blocking.",
        ),
    )
    _ok(runtime, _blocks(x, a, "cyc-xa-after", anchor))


def _seed_leaves(engine: Any, hub: str, leaves: int) -> None:  # noqa: ANN401
    """`leaves` direct-insert Tasks, each blocked by `hub` (an active `blocks` root and head)."""
    with engine.begin() as connection:
        for _ in range(leaves):
            leaf = _task(connection, PRINCIPAL)
            _write_link(
                connection,
                _link_values(
                    PRINCIPAL,
                    kind="semantic",
                    relation="blocks",
                    source=("task", hub),
                    target=("task", leaf),
                ),
            )


def test_a_blocks_search_past_its_bound_is_refused(runtime: S2Runtime) -> None:
    assert MAX_BLOCKS_SEARCH == 1000
    scene = _escalation(runtime, "blk-bound")
    hub = scene.task
    _seed_leaves(runtime.engine, hub, MAX_BLOCKS_SEARCH - 1)
    # From the hub the search visits the hub and its leaves: exactly the bound.
    first = runtime.task("blk-bound-first")
    _ok(runtime, _blocks(("task", first), ("task", hub), "bound-at", scene.corroborates))
    # One record more and the search cannot finish inside the bound: refused,
    # although no cycle exists.
    _seed_leaves(runtime.engine, hub, 1)
    second = runtime.task("blk-bound-second")
    counts = all_s2_counts(runtime.engine)
    assert _refused(
        runtime, _blocks(("task", second), ("task", hub), "bound-past", scene.corroborates)
    ) == ("invalid_request", ["blocks_cycle"])
    assert all_s2_counts(runtime.engine) == counts


def test_task_completion_closes_no_constraint_or_issue(runtime: S2Runtime) -> None:
    scene = _escalation(runtime, "esc-done")
    runtime.member(scene.issue, "constraint", scene.constraint, "esc-done-x", "constraint")
    _ok(runtime, _escalate(scene, "esc-done"))
    _ok(
        runtime,
        _blocks(
            ("task", scene.task),
            ("constraint", scene.constraint),
            "esc-done-blk",
            scene.corroborates,
            context=scene.issue,
        ),
    )
    constraint_before = runtime.ok(ReadConstraint(constraint_id=scene.constraint))["constraint"]
    issue_before = runtime.ok(ReadIssue(issue_id=scene.issue, include_members=True))
    counts = all_s2_counts(runtime.engine)
    runtime.transition(scene.task, TaskLifecycleState.COMPLETED, "esc-done")
    assert runtime.ok(ReadConstraint(constraint_id=scene.constraint))["constraint"] == (
        constraint_before
    )
    assert runtime.ok(ReadIssue(issue_id=scene.issue, include_members=True)) == issue_before
    assert issue_before["issue"]["state"] == "open"
    assert all_s2_counts(runtime.engine) == counts


def test_lineage_writes_leave_constraint_bic_unchanged(runtime: S2Runtime) -> None:
    """F11: BIC stays native; no lineage write touches the Constraint row."""
    scene = _escalation(runtime, "esc-bic")
    before = runtime.ok(ReadConstraint(constraint_id=scene.constraint))["constraint"]
    assert before["bic"], "the fixture Constraint carries a ball-in-court party"
    member = runtime.member(scene.issue, "constraint", scene.constraint, "esc-bic", "constraint")
    escalation = _ok(runtime, _escalate(scene, "esc-bic"))["association"]
    blocked = runtime.task("esc-bic-blocked")
    blocking = _ok(
        runtime,
        _blocks(
            ("constraint", scene.constraint), ("task", blocked), "esc-bic-blk", scene.corroborates
        ),
    )["association"]
    _ok(
        runtime,
        assertion(
            "discusses",
            ("meeting_note_version", scene.note),
            ("constraint", scene.constraint),
            "esc-bic-disc",
            (note_anchor(scene.meeting, scene.note, NOTE_BODY, role="discussion"),),
            context=scene.issue,
        ),
    )
    _ok(
        runtime,
        CorrectRecordAssociation(
            link_id=escalation["link_id"],
            expected_revision=1,
            idempotency_key="s2-esc-bic-correct",
            reason="Recorded with its corroboration.",
            evidence_anchors=(scene.origin, scene.corroborates),
        ),
    )
    _ok(runtime, correct(member, 1, "esc-bic", (scene.corroborates,)))
    _ok(
        runtime,
        EndRecordAssociation(
            link_id=blocking["link_id"],
            expected_revision=1,
            idempotency_key="s2-esc-bic-end",
            reason="No longer blocking.",
        ),
    )
    after = runtime.ok(ReadConstraint(constraint_id=scene.constraint))["constraint"]
    assert after == before
