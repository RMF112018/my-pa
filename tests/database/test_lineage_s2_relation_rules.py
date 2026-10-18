"""WP-02C: the S2 relation matrix rules against PostgreSQL (S2 contract section 3.1).

Through `ApplicationService.invoke`. The creation relations
(`delegated_from`, `created_to_resolve`) are written only by the composites
and refused by `records.associations.assert`; each composite admits only its
own intent relations and pairs; the assert-time rules (membership, Task
state, Commitment direction, the composite's own Issue) are checked when the
link is created and only then: a correction re-applies only the relation's
evidence rule (R2-F07).

The `escalated_from` and `blocks` rows of this module are the relation
worker's (S2 contract section 9, K3). Every identity is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from my_pa.application.commands import CorrectRecordAssociation
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.task.lifecycle import TaskLifecycleState
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    capture,
    meeting,
    note_anchor,
)
from tests.database.lineage_s2_harness import (
    GATEWAY,
    REVIEW_DECISION,
    S2Runtime,
    all_s2_counts,
    work_commitment,
    work_task,
)
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

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
