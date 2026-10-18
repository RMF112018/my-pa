"""AT-005: directional responsibilities, explicit handoffs and independent delegations.

S2 contract sections 3.1, 3.4, 6.4 and 7.2, through `ApplicationService.invoke`
against PostgreSQL. A handoff is one explicit, evidenced, attested
`issues.handoffs.record` event: closing a Commitment, completing a Task, a
composite create and a membership change write none, and a handoff changes no
native field. The request names only the side the responsibility leaves; the
server resolves both holders from the chain's last holder and the
Commitment's current counterparty, so a re-pointed counterparty never wedges
the chain. Delegated Commitments (`issues.work.create_commitment` with a
`delegated_from` intent) are independent native records.

Every lineage write is a stamped local-operator write unless a test says
otherwise. Every identity and every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from sqlalchemy import func, select

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    AssertRecordAssociation,
    CreateIssueWorkCommitment,
    EndIssueMembership,
    ListIssueHandoffs,
    UpdateCommitment,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.task.lifecycle import TaskLifecycleState
from my_pa.infrastructure.persistence.tables import issue_responsibility_events
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL
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
    handoff,
    resolution_anchor,
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


def _events(runtime: S2Runtime) -> int:
    with runtime.engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).select_from(issue_responsibility_events)
            ).scalar_one()
        )


def _at(view: dict[str, Any], microseconds: int = 0) -> str:
    """An instant just after the Commitment's creation, ISO-8601 with offset.

    A view shows instants to the millisecond, so the shown `created_at` may be
    up to a millisecond before the stored one: the base is one millisecond
    later, then `microseconds` on.
    """
    created = datetime.fromisoformat(str(view["created_at"]))
    return (created + timedelta(milliseconds=1, microseconds=microseconds)).isoformat()


def _shown(instant: str) -> datetime:
    """An instant as a view shows it: to the millisecond."""
    value = datetime.fromisoformat(instant)
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def _member_commitment(
    runtime: S2Runtime, issue: str, key: str, *, accepted: bool = True
) -> tuple[str, dict[str, Any]]:
    """A Commitment (owed to the Principal) that is a `work` member of `issue`."""
    commitment = runtime.commitment(key, accepted=accepted)
    runtime.member(issue, "commitment", commitment, key, "work")
    return commitment, runtime.commitment_view(commitment)


def _native(view: dict[str, Any]) -> tuple[Any, ...]:
    return (
        view["version"],
        view["state"],
        view["evidence_state"],
        view["counterparty_entity_id"],
        view["direction"],
    )


def _delegation(
    task_id: str, anchor: dict[str, object], *, relation: str = "delegated_from"
) -> dict[str, object]:
    return {
        "relation_type": relation,
        "to_record": {"family": "task", "record_id": task_id},
        "evidence_anchors": [anchor],
    }


def _delegate(
    runtime: S2Runtime, issue: str, key: str, task_id: str, *, direction: str = "owed_to_principal"
) -> CreateIssueWorkCommitment:
    """`issues.work.create_commitment` delegated from `task_id`, to a new counterparty."""
    meeting_id, note_id = meeting(runtime, f"{key}-origin")
    origin, _, _ = capture(runtime, f"{key}-native-origin")
    return work_commitment(
        issue,
        key,
        {
            "counterparty_entity_id": seed_counterparty_entity(runtime.engine, PRINCIPAL),
            "direction": direction,
            "summary": f"Synthetic delegated commitment {key}",
            "origin_evidence_ref": origin,
            "accepted_by_review_decision_id": REVIEW_DECISION,
        },
        intents=(_delegation(task_id, note_anchor(meeting_id, note_id, NOTE_BODY)),),
    )


def _member_task(runtime: S2Runtime, issue: str, key: str) -> tuple[str, str]:
    written = _ok(runtime, work_task(issue, key))
    return str(written["record"]["record_id"]), str(written["membership"]["link_id"])


# ---- no inferred handoff ------------------------------------------------------------------


def test_closing_a_commitment_writes_no_handoff(runtime: S2Runtime) -> None:
    issue = runtime.issue("no-infer-close")
    commitment, before = _member_commitment(runtime, issue, "no-infer-close")
    runtime.close_commitment(commitment, "no-infer-close")
    assert _events(runtime) == 0
    page = _ok(runtime, ListIssueHandoffs(issue_id=issue, commitment_id=commitment))
    assert page == {"handoffs": [], "next_cursor": None}
    after = runtime.commitment_view(commitment)
    assert after["state"] == "closed"
    assert after["counterparty_entity_id"] == before["counterparty_entity_id"]


def test_an_explicit_handoff_records_counterparty_then_principal(runtime: S2Runtime) -> None:
    issue = runtime.issue("explicit")
    commitment, view = _member_commitment(runtime, issue, "explicit")
    runtime.close_commitment(commitment, "explicit")
    closed = runtime.commitment_view(commitment)
    written = _ok(
        runtime,
        handoff(
            issue,
            commitment,
            "counterparty",
            _at(view, 5),
            "explicit",
            runtime.handoff_anchor("explicit"),
        ),
    )
    event = written["handoff"]
    assert written["replayed"] is False
    assert event["sequence_no"] == 1
    assert event["from"] == {"kind": "entity", "entity_id": view["counterparty_entity_id"]}
    assert event["to"] == {"kind": "principal", "entity_id": None}
    assert event["evidence"]["role"] == "handoff"
    assert event["acceptance_basis"] == "user_confirmed"
    assert event["authority_class"] == "local_operator"
    assert datetime.fromisoformat(event["effective_at"]) == _shown(_at(view, 5))
    # The native Commitment is untouched: still closed, same counterparty and direction.
    assert _native(runtime.commitment_view(commitment)) == _native(closed)
    assert _events(runtime) == 1


def test_a_handoff_needs_an_exact_handoff_anchor(runtime: S2Runtime) -> None:
    issue = runtime.issue("anchor")
    commitment, view = _member_commitment(runtime, issue, "anchor")
    meeting_id, note_id = meeting(runtime, "anchor-note")
    capture_id, _, _ = capture(runtime, "anchor-legacy")
    exact = resolution_anchor(meeting_id, note_id, role="handoff")
    for refused in (
        resolution_anchor(meeting_id, note_id, role="resolution"),
        resolution_anchor(meeting_id, note_id, role="origin"),
        legacy_anchor(capture_id, role="corroborates"),
        {**exact, "unknown": 1},
    ):
        with pytest.raises(InvalidRequestError) as caught:
            handoff(issue, commitment, "counterparty", _at(view), "anchor", refused)
        assert [detail.value for detail in caught.value.safe_details] == ["evidence_anchor"]
    # A well-shaped anchor that does not match its source is refused by the server.
    before = all_s2_counts(runtime.engine)
    mismatched = {**exact, "source_sha256": "0" * 64}
    assert _refused(
        runtime, handoff(issue, commitment, "counterparty", _at(view), "anchor-x", mismatched)
    ) == ("invalid_request", ["evidence_anchor"])
    absent = {**exact, "version_id": "mnote_lineages2absent0001"}
    assert _refused(
        runtime, handoff(issue, commitment, "counterparty", _at(view), "anchor-y", absent)
    ) == ("not_found", ["evidence_anchor"])
    assert all_s2_counts(runtime.engine) == before
    _ok(runtime, handoff(issue, commitment, "counterparty", _at(view), "anchor-ok", exact))
    assert _events(runtime) == 1


def test_a_handoff_names_only_the_principal_and_the_counterparty(runtime: S2Runtime) -> None:
    issue = runtime.issue("holders")
    commitment, view = _member_commitment(runtime, issue, "holders")
    counterparty = view["counterparty_entity_id"]
    stranger = seed_counterparty_entity(runtime.engine, PRINCIPAL)
    base = {
        "issue_id": issue,
        "commitment_id": commitment,
        "from_side": "principal",
        "effective_at": _at(view),
        "reason": "Moved.",
        "evidence_anchor": runtime.handoff_anchor("holders"),
        "idempotency_key": "s2-holders-shape",
    }
    arguments = {
        "request_id": "req-lineage-s2-holders",
        "purpose": "issue_authoring",
        "principal_id": "prn_lineageissue0001",
        "requested_at": "2026-10-18T12:00:00Z",
    }
    # A client never names a holder: every holder field is an unknown key.
    for field in ("from_entity_id", "to_entity_id", "to_side", "holder", "from"):
        with pytest.raises(InvalidRequestError):
            normalize(
                "issues.handoffs.record",
                {**arguments, "payload": {**base, field: stranger}},
            )
    for side in ("entity", "unassigned", stranger):
        with pytest.raises(InvalidRequestError) as caught:
            normalize(
                "issues.handoffs.record", {**arguments, "payload": {**base, "from_side": side}}
            )
        assert [detail.value for detail in caught.value.safe_details] == ["from"]
    first = _ok(
        runtime,
        handoff(issue, commitment, "principal", _at(view, 1), "holders-1", base["evidence_anchor"]),
    )["handoff"]
    second = _ok(
        runtime,
        handoff(
            issue, commitment, "counterparty", _at(view, 2), "holders-2", base["evidence_anchor"]
        ),
    )["handoff"]
    assert (first["from"], first["to"]) == (
        {"kind": "principal", "entity_id": None},
        {"kind": "entity", "entity_id": counterparty},
    )
    assert (second["from"], second["to"]) == (
        {"kind": "entity", "entity_id": counterparty},
        {"kind": "principal", "entity_id": None},
    )
    holders = {
        (event[side]["kind"], event[side]["entity_id"])
        for event in (first, second)
        for side in ("from", "to")
    }
    assert holders == {("principal", None), ("entity", counterparty)}


def test_a_handoff_chain_continues_from_the_last_holder(runtime: S2Runtime) -> None:
    issue = runtime.issue("chain")
    commitment, view = _member_commitment(runtime, issue, "chain")
    anchor = runtime.handoff_anchor("chain")
    sides = ("counterparty", "principal", "counterparty")
    events = [
        _ok(runtime, handoff(issue, commitment, side, _at(view, n), f"chain-{n}", anchor))[
            "handoff"
        ]
        for n, side in enumerate(sides, 1)
    ]
    assert [event["sequence_no"] for event in events] == [1, 2, 3]
    for previous, event in pairwise(events):
        assert event["from"] == previous["to"]
    assert events[1]["to"] == {"kind": "entity", "entity_id": view["counterparty_entity_id"]}


def test_a_handoff_effective_after_now_is_refused(runtime: S2Runtime) -> None:
    issue = runtime.issue("future")
    commitment, _ = _member_commitment(runtime, issue, "future")
    anchor = runtime.handoff_anchor("future")
    future = (datetime.now().astimezone() + timedelta(days=1)).isoformat()
    before = all_s2_counts(runtime.engine)
    assert _refused(
        runtime, handoff(issue, commitment, "counterparty", future, "future", anchor)
    ) == ("invalid_request", ["effective_at"])
    assert all_s2_counts(runtime.engine) == before
    # An instant without an offset is refused by shape.
    with pytest.raises(InvalidRequestError) as caught:
        handoff(issue, commitment, "counterparty", "2026-10-18T12:00:00", "naive", anchor)
    assert [detail.value for detail in caught.value.safe_details] == ["effective_at"]
    assert _events(runtime) == 0


def test_a_handoff_subject_must_be_an_active_member(runtime: S2Runtime) -> None:
    issue = runtime.issue("member")
    outsider = runtime.commitment("member-outsider")
    view = runtime.commitment_view(outsider)
    anchor = runtime.handoff_anchor("member")
    assert _refused(
        runtime, handoff(issue, outsider, "counterparty", _at(view), "member-out", anchor)
    ) == ("invalid_request", ["commitment_id"])
    # A Commitment that was a member and was ended is not a member any more.
    ended = runtime.commitment("member-ended")
    link = runtime.member(issue, "commitment", ended, "member-ended", "work")
    _ok(
        runtime,
        EndIssueMembership(
            link_id=link, expected_revision=1, idempotency_key="s2-member-end", reason="Out."
        ),
    )
    ended_view = runtime.commitment_view(ended)
    assert _refused(
        runtime, handoff(issue, ended, "counterparty", _at(ended_view), "member-ended", anchor)
    ) == ("invalid_request", ["commitment_id"])
    # A Task is never a handoff subject: the identifier prefix refuses it.
    task_id = runtime.task("member-task")
    with pytest.raises(InvalidRequestError):
        handoff(issue, task_id, "counterparty", _at(view), "member-task", anchor)
    assert _events(runtime) == 0


# ---- delegated and resolving work ------------------------------------------------------------


def test_a_follow_up_task_of_a_closed_commitment_is_admitted(runtime: S2Runtime) -> None:
    issue = runtime.issue("follow-up")
    commitment, _ = _member_commitment(runtime, issue, "follow-up")
    runtime.close_commitment(commitment, "follow-up")
    closed = runtime.commitment_view(commitment)
    written = _ok(
        runtime,
        work_task(
            issue,
            "follow-up",
            {
                "title": "Synthetic follow-up",
                "origin_kind": "direct_principal",
                "role": "follow_up",
                "commitment_id": commitment,
            },
        ),
    )
    task_id = written["record"]["record_id"]
    assert written["record"]["family"] == "task"
    assert written["membership"]["member_role"] == "work"
    assert written["membership"]["to"] == {"family": "task", "record_id": task_id}
    # C1 is not reopened or changed, and no handoff is written.
    assert _native(runtime.commitment_view(commitment)) == _native(closed)
    assert _events(runtime) == 0


def test_two_delegations_create_two_independent_commitments(runtime: S2Runtime) -> None:
    issue = runtime.issue("two")
    task_id, _ = _member_task(runtime, issue, "two-t1")
    first = _ok(runtime, _delegate(runtime, issue, "two-c2", task_id))
    second = _ok(runtime, _delegate(runtime, issue, "two-c3", task_id))
    c2, c3 = first["record"]["record_id"], second["record"]["record_id"]
    assert c2 != c3
    for written in (first, second):
        (delegation,) = written["associations"]
        assert delegation["relation_type"] == "delegated_from"
        assert delegation["to"] == {"family": "task", "record_id": task_id}
        assert delegation["context_issue_id"] == issue
    c2_view, c3_view = runtime.commitment_view(c2), runtime.commitment_view(c3)
    assert c2_view["counterparty_entity_id"] != c3_view["counterparty_entity_id"]
    runtime.close_commitment(c2, "two-c2")
    assert runtime.commitment_view(c2)["state"] == "closed"
    assert runtime.commitment_view(c3)["state"] == c3_view["state"] == "open"
    assert _native(runtime.commitment_view(c3)) == _native(c3_view)


def test_delegated_from_requires_an_owed_to_principal_commitment(runtime: S2Runtime) -> None:
    issue = runtime.issue("direction")
    task_id, _ = _member_task(runtime, issue, "direction-t1")
    command = _delegate(runtime, issue, "direction", task_id, direction="owed_by_principal")
    before = all_s2_counts(runtime.engine)
    assert _refused(runtime, command) == ("invalid_request", ["direction"])
    assert all_s2_counts(runtime.engine) == before
    _ok(runtime, _delegate(runtime, issue, "direction-ok", task_id))


def test_creation_relations_are_refused_by_assert(runtime: S2Runtime) -> None:
    issue = runtime.issue("assert")
    task_id, _ = _member_task(runtime, issue, "assert-t1")
    commitment, _ = _member_commitment(runtime, issue, "assert-c")
    meeting_id, note_id = meeting(runtime, "assert-note")
    anchor = note_anchor(meeting_id, note_id, NOTE_BODY)
    before = all_s2_counts(runtime.engine)
    for relation, to_record in (
        ("delegated_from", {"family": "task", "record_id": task_id}),
        ("created_to_resolve", {"family": "situation", "record_id": issue}),
    ):
        assert _refused(
            runtime,
            AssertRecordAssociation(
                from_record={"family": "commitment", "record_id": commitment},
                to_record=to_record,
                relation_type=relation,
                idempotency_key=f"s2-assert-{relation}",
                evidence_anchors=(anchor,),
                context_issue_id=issue,
            ),
        ) == ("invalid_request", ["relation_type"])
    assert all_s2_counts(runtime.engine) == before


def test_completing_t1_closes_no_delegated_commitment(runtime: S2Runtime) -> None:
    issue = runtime.issue("complete")
    task_id, _ = _member_task(runtime, issue, "complete-t1")
    delegates = [
        _ok(runtime, _delegate(runtime, issue, f"complete-{key}", task_id))["record"]["record_id"]
        for key in ("c2", "c3")
    ]
    before = [_native(runtime.commitment_view(commitment)) for commitment in delegates]
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, "complete-t1")
    assert [_native(runtime.commitment_view(commitment)) for commitment in delegates] == before
    assert {runtime.commitment_view(commitment)["state"] for commitment in delegates} == {"open"}


def test_no_handoff_is_inferred_for_a_delegate(runtime: S2Runtime) -> None:
    issue = runtime.issue("delegate")
    task_id, _ = _member_task(runtime, issue, "delegate-t1")
    delegate = _ok(runtime, _delegate(runtime, issue, "delegate-c2", task_id))
    commitment = delegate["record"]["record_id"]
    assert _events(runtime) == 0
    runtime.close_commitment(commitment, "delegate-c2")
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, "delegate-t1")
    assert _events(runtime) == 0
    assert _ok(runtime, ListIssueHandoffs(issue_id=issue)) == {"handoffs": [], "next_cursor": None}


# ---- the ledger read and the chain rules ------------------------------------------------------


def test_handoffs_list_returns_the_sequence_in_order(runtime: S2Runtime) -> None:
    issue = runtime.issue("list")
    first, first_view = _member_commitment(runtime, issue, "list-a")
    second, second_view = _member_commitment(runtime, issue, "list-b")
    quiet, _ = _member_commitment(runtime, issue, "list-quiet")
    anchor = runtime.handoff_anchor("list")
    recorded = [
        _ok(runtime, handoff(issue, first, "counterparty", _at(first_view, 1), "list-1", anchor)),
        _ok(runtime, handoff(issue, second, "principal", _at(second_view, 1), "list-2", anchor)),
        _ok(runtime, handoff(issue, first, "principal", _at(first_view, 2), "list-3", anchor)),
    ]
    ids = [written["handoff"]["handoff_id"] for written in recorded]
    page = _ok(runtime, ListIssueHandoffs(issue_id=issue, page_size=2))
    assert [event["handoff_id"] for event in page["handoffs"]] == ids[:2]
    assert page["next_cursor"] == ids[1]
    rest = _ok(runtime, ListIssueHandoffs(issue_id=issue, page_size=2, after=ids[1]))
    assert [event["handoff_id"] for event in rest["handoffs"]] == ids[2:]
    assert rest["next_cursor"] is None
    # Every listed event is exactly what its write answered.
    assert page["handoffs"] + rest["handoffs"] == [written["handoff"] for written in recorded]
    chain = _ok(runtime, ListIssueHandoffs(issue_id=issue, commitment_id=first))
    assert [event["sequence_no"] for event in chain["handoffs"]] == [1, 2]
    assert _ok(runtime, ListIssueHandoffs(issue_id=issue, commitment_id=quiet)) == {
        "handoffs": [],
        "next_cursor": None,
    }
    assert _refused(
        runtime, ListIssueHandoffs(issue_id=issue, commitment_id=second, after=ids[0])
    ) == ("invalid_request", ["cursor"])
    with pytest.raises(InvalidRequestError) as caught:
        ListIssueHandoffs(issue_id=issue, page_size=101)
    assert [detail.value for detail in caught.value.safe_details] == ["page_size"]


def test_a_counterparty_repoint_leaves_the_chain_continuable(runtime: S2Runtime) -> None:
    issue = runtime.issue("repoint")
    commitment, view = _member_commitment(runtime, issue, "repoint")
    original = view["counterparty_entity_id"]
    anchor = runtime.handoff_anchor("repoint")
    # The Principal hands the next action to P1.
    first = _ok(
        runtime, handoff(issue, commitment, "principal", _at(view, 1), "repoint-1", anchor)
    )["handoff"]
    assert first["to"] == {"kind": "entity", "entity_id": original}
    repointed = seed_counterparty_entity(runtime.engine, PRINCIPAL)
    _ok(
        runtime,
        UpdateCommitment(
            commitment_id=commitment,
            expected_version=int(view["version"]),
            idempotency_key="s2-repoint-update",
            counterparty_entity_id=repointed,
        ),
    )
    # P1 still holds: the next event leaves P1 (the chain's last holder), not P1'.
    second = _ok(
        runtime, handoff(issue, commitment, "counterparty", _at(view, 2), "repoint-2", anchor)
    )["handoff"]
    assert second["from"] == {"kind": "entity", "entity_id": original}
    assert second["to"] == {"kind": "principal", "entity_id": None}
    # With the Principal holding, the next event reaches the current counterparty P1'.
    third = _ok(
        runtime, handoff(issue, commitment, "principal", _at(view, 3), "repoint-3", anchor)
    )["handoff"]
    assert third["to"] == {"kind": "entity", "entity_id": repointed}
    fourth = _ok(
        runtime, handoff(issue, commitment, "counterparty", _at(view, 4), "repoint-4", anchor)
    )["handoff"]
    assert fourth["from"] == {"kind": "entity", "entity_id": repointed}
    assert [event["sequence_no"] for event in (first, second, third, fourth)] == [1, 2, 3, 4]


def test_a_handoff_from_the_wrong_side_is_refused(runtime: S2Runtime) -> None:
    issue = runtime.issue("side")
    commitment, view = _member_commitment(runtime, issue, "side")
    anchor = runtime.handoff_anchor("side")
    _ok(runtime, handoff(issue, commitment, "counterparty", _at(view, 1), "side-1", anchor))
    before = all_s2_counts(runtime.engine)
    # The Principal holds now: the counterparty side cannot hand it on.
    assert _refused(
        runtime, handoff(issue, commitment, "counterparty", _at(view, 2), "side-2", anchor)
    ) == ("invalid_request", ["from"])
    assert all_s2_counts(runtime.engine) == before
    # Restated with the right side, it is admitted.
    restated = _ok(runtime, handoff(issue, commitment, "principal", _at(view, 2), "side-3", anchor))
    assert restated["handoff"]["sequence_no"] == 2


def test_a_handoff_effective_before_its_predecessor_is_refused(runtime: S2Runtime) -> None:
    issue = runtime.issue("order")
    commitment, view = _member_commitment(runtime, issue, "order")
    anchor = runtime.handoff_anchor("order")
    created = datetime.fromisoformat(str(view["created_at"]))
    before_creation = (created - timedelta(milliseconds=1)).isoformat()
    assert _refused(
        runtime, handoff(issue, commitment, "counterparty", before_creation, "order-0", anchor)
    ) == ("invalid_request", ["effective_at"])
    _ok(runtime, handoff(issue, commitment, "counterparty", _at(view, 10), "order-1", anchor))
    counts = all_s2_counts(runtime.engine)
    assert _refused(
        runtime, handoff(issue, commitment, "principal", _at(view, 5), "order-2", anchor)
    ) == ("invalid_request", ["effective_at"])
    assert all_s2_counts(runtime.engine) == counts
    # At the predecessor's own instant is in order.
    _ok(runtime, handoff(issue, commitment, "principal", _at(view, 10), "order-3", anchor))
    assert _events(runtime) == 2


def test_a_foreign_commitment_answers_like_an_absent_one_for_handoffs(runtime: S2Runtime) -> None:
    issue = runtime.issue("foreign")
    commitment, view = _member_commitment(runtime, issue, "foreign")
    anchor = runtime.handoff_anchor("foreign")
    foreign_issue = runtime.issue("foreign-other", principal_id=OTHER_PRINCIPAL)
    foreign = runtime.commitment("foreign-other", principal_id=OTHER_PRINCIPAL)
    absent = "cmt_lineages2absent0001"
    answers = [
        _refused(runtime, handoff(issue, subject, "counterparty", _at(view), f"f-{n}", anchor))
        for n, subject in enumerate((foreign, absent))
    ]
    assert answers == [("not_found", ["commitment_id"])] * 2
    for subject in (foreign_issue, "sit_lineages2absent0001"):
        assert _refused(
            runtime,
            handoff(subject, commitment, "counterparty", _at(view), f"fi-{subject}", anchor),
        ) == ("not_found", ["issue_id"])
    assert _events(runtime) == 0


def test_handoffs_list_of_a_foreign_commitment_is_not_found(runtime: S2Runtime) -> None:
    issue = runtime.issue("list-foreign")
    foreign_issue = runtime.issue("list-foreign-other", principal_id=OTHER_PRINCIPAL)
    foreign = runtime.commitment("list-foreign-other", principal_id=OTHER_PRINCIPAL)
    for subject in (foreign, "cmt_lineages2absent0002"):
        assert _refused(runtime, ListIssueHandoffs(issue_id=issue, commitment_id=subject)) == (
            "not_found",
            ["commitment_id"],
        )
    for subject in (foreign_issue, "sit_lineages2absent0002"):
        assert _refused(runtime, ListIssueHandoffs(issue_id=subject)) == (
            "not_found",
            ["issue_id"],
        )
