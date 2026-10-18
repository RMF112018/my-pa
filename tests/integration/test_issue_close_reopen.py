"""AT-007 + AT-015 (S2): Issue close and reopen behind the OD-03 gate.

S2 contract sections 3.2, 3.3, 6.1, 6.2 and 7.2, through
`ApplicationService.invoke` against PostgreSQL. Every member is driven to its
native state through its own v1 capability (`tasks.transition`,
`commitments.close`, `constraints.close`/`.reopen`), resolution evidence is
recorded with `issues.memberships.correct` after the native close, and every
lineage write is a stamped local-operator write unless a test says otherwise.

The gate has no exception and no cascade: a member that will never be
satisfied is ended with `issues.memberships.end` (D-16), closing or reopening
changes no member, link or native record, and a later native change never
moves the Issue. Every identity and every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    AddIssueMembership,
    AddIssueProjectLink,
    ArchiveCapture,
    AssertRecordAssociation,
    EndIssueMembership,
    ReadIssue,
    ReopenConstraint,
    UpdateIssue,
    VoidConstraint,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.project_controls.constraint import ConstraintLifecycleState
from my_pa.domain.task.lifecycle import TaskLifecycleState
from my_pa.infrastructure.persistence.tables import (
    commitments,
    project_constraints,
    record_link_heads,
    record_link_revisions,
    record_links,
    tasks,
)
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL, REMOTE_CLIENT
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    capture,
    capture_anchor,
    legacy_anchor,
    meeting,
    membership,
    note_anchor,
)
from tests.database.lineage_s2_harness import (
    GATEWAY,
    S2Runtime,
    all_s2_counts,
    close,
    correct,
    reopen,
    resolution_anchor,
)

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S2Runtime]:
    composed = S2Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _error(runtime: S2Runtime, command: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    return runtime.refused(command, **kwargs)


def _ok(runtime: S2Runtime, command: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    return runtime.ok(command, **kwargs)


def _detail(error: dict[str, Any]) -> tuple[str, list[str]]:
    return str(error["code"]), list(error.get("safe_details") or [])


def _completed_task_member(runtime: S2Runtime, issue: str, key: str) -> tuple[str, str]:
    """A completed, accepted Task member with current resolution evidence: `(task, link)`."""
    task_id = runtime.task(key)
    link = runtime.member(issue, "task", task_id, key, "work")
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, key)
    _, _, anchor = runtime.evidence_source(f"{key}-res")
    _ok(runtime, correct(link, 1, key, (anchor,)))
    return task_id, link


def _closure_set(runtime: S2Runtime, key: str) -> tuple[dict[str, object], ...]:
    _, _, anchor = runtime.evidence_source(f"{key}-closure")
    return (anchor,)


def _reasons(readiness: dict[str, Any], member_id: str) -> list[str]:
    for blocker in readiness["blockers"]:
        if blocker["member"]["record_id"] == member_id:
            return list(blocker["reasons"])
    return []


def _snapshot(runtime: S2Runtime) -> dict[str, Any]:
    """Every link row and every native Work and Constraint row, as stored."""
    with runtime.engine.connect() as connection:
        return {
            table.name: sorted(tuple(row) for row in connection.execute(select(table)))
            for table in (
                record_links,
                record_link_revisions,
                record_link_heads,
                tasks,
                commitments,
                project_constraints,
            )
        }


# ---- the closure evidence set -------------------------------------------------


def test_close_requires_an_available_resolution_anchor(runtime: S2Runtime) -> None:
    issue = runtime.issue("set")
    meeting_id, note_id = meeting(runtime, "set")
    corroborating = resolution_anchor(meeting_id, note_id, role="corroborates")
    before = all_s2_counts(runtime.engine)
    assert _detail(_error(runtime, close(issue, 1, "set-a", (corroborating,)))) == (
        "invalid_request",
        ["closure_evidence_anchors"],
    )
    # An archived Capture version is not available: the set is refused at admission.
    root, version, _ = capture(runtime, "set-archived")
    runtime.ok(
        ArchiveCapture(
            capture_id=root,
            expected_lifecycle_revision=0,
            idempotency_key="s2-set-archive",
            reason="synthetic archive",
        )
    )
    archived = capture_anchor(root, version, NOTE_BODY, role="resolution")
    assert _detail(_error(runtime, close(issue, 1, "set-b", (archived,)))) == (
        "denied",
        ["capture_withdrawn"],
    )
    assert all_s2_counts(runtime.engine) == before
    closed = _ok(
        runtime,
        close(issue, 1, "set-c", (resolution_anchor(meeting_id, note_id),)),
        surface=GATEWAY,
    )
    assert closed["issue"]["state"] == "closed"
    assert closed["issue"]["version"] == 2
    assert closed["issue"]["action"] == "closed"
    assert [anchor["role"] for anchor in closed["closure"]["evidence"]] == ["resolution"]
    assert closed["closure"]["outcome"] == "Resolved."
    assert "evidence_set_digest" not in closed["closure"]


def test_a_legacy_anchor_never_satisfies_closure(runtime: S2Runtime) -> None:
    issue = runtime.issue("legacy")
    root, _, _ = capture(runtime, "legacy")
    # A legacy root only corroborates or contradicts, so it never counts.
    assert _detail(_error(runtime, close(issue, 1, "legacy", (legacy_anchor(root),)))) == (
        "invalid_request",
        ["closure_evidence_anchors"],
    )
    # And it cannot be recorded as a member's resolution evidence either.
    task_id = runtime.task("legacy")
    link = runtime.member(issue, "task", task_id, "legacy", "work")
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, "legacy")
    with pytest.raises(InvalidRequestError):
        correct(link, 1, "legacy", (legacy_anchor(root, role="resolution"),))
    _ok(runtime, correct(link, 1, "legacy-c", (legacy_anchor(root),)))
    assert "resolution_evidence_missing" in _reasons(runtime.readiness(issue), task_id)


def test_a_contradicting_anchor_refuses_closure(runtime: S2Runtime) -> None:
    issue = runtime.issue("contra-set")
    meeting_id, note_id = meeting(runtime, "contra-set")
    anchors = (
        resolution_anchor(meeting_id, note_id),
        resolution_anchor(meeting_id, note_id, role="contradicts", passage="Next: pour"),
    )
    before = all_s2_counts(runtime.engine)
    assert _detail(_error(runtime, close(issue, 1, "contra-set", anchors))) == (
        "invalid_request",
        ["closure_evidence_anchors"],
    )
    assert all_s2_counts(runtime.engine) == before


# ---- the native conditions ------------------------------------------------------


def test_an_open_mandatory_member_refuses_closure(runtime: S2Runtime) -> None:
    issue = runtime.issue("open")
    task_id = runtime.task("open")
    link = runtime.member(issue, "task", task_id, "open", "work")
    _, _, anchor = runtime.evidence_source("open-res")
    _ok(runtime, correct(link, 1, "open", (anchor,)))
    readiness = runtime.readiness(issue)
    assert readiness["ready"] is False
    assert _reasons(readiness, task_id) == ["native_open"]
    before = all_s2_counts(runtime.engine)
    assert _detail(_error(runtime, close(issue, 1, "open", _closure_set(runtime, "open")))) == (
        "conflict",
        ["closure_gate"],
    )
    assert all_s2_counts(runtime.engine) == before
    assert runtime.issue_version(issue) == 1


def test_a_cancelled_task_member_refuses_closure(runtime: S2Runtime) -> None:
    issue = runtime.issue("cancel")
    task_id = runtime.task("cancel")
    link = runtime.member(issue, "task", task_id, "cancel", "work")
    runtime.transition(task_id, TaskLifecycleState.CANCELLED, "cancel")
    _, _, anchor = runtime.evidence_source("cancel-res")
    _ok(runtime, correct(link, 1, "cancel", (anchor,)))
    assert _reasons(runtime.readiness(issue), task_id) == ["native_terminal_unsuccessful"]
    assert _detail(_error(runtime, close(issue, 1, "cancel", _closure_set(runtime, "cancel")))) == (
        "conflict",
        ["closure_gate"],
    )


def test_a_void_constraint_member_refuses_closure(runtime: S2Runtime) -> None:
    issue = runtime.issue("void")
    project = runtime.project_with_constraints("void")
    constraint = runtime.constraint(project, "void")
    link = runtime.member(issue, "constraint", constraint, "void", "constraint")
    runtime.ok(
        VoidConstraint(
            constraint_id=constraint,
            expected_version=runtime.constraint_version(constraint),
            void_reason="Synthetic void.",
            idempotency_key="s2-void-constraint",
        )
    )
    _, _, anchor = runtime.evidence_source("void-res")
    _ok(runtime, correct(link, 1, "void", (anchor,)))
    assert _reasons(runtime.readiness(issue), constraint) == ["native_terminal_unsuccessful"]
    assert _detail(_error(runtime, close(issue, 1, "void", _closure_set(runtime, "void")))) == (
        "conflict",
        ["closure_gate"],
    )


def test_a_proposed_closed_commitment_is_not_counted_accepted(runtime: S2Runtime) -> None:
    """AT-015: `commitments.close` of a `proposed` Commitment does not accept it."""
    issue = runtime.issue("proposed")
    commitment = runtime.commitment("proposed", accepted=False)
    link = runtime.member(issue, "commitment", commitment, "proposed", "work")
    runtime.close_commitment(commitment, "proposed")
    _, _, anchor = runtime.evidence_source("proposed-res")
    _ok(runtime, correct(link, 1, "proposed", (anchor,)))
    readiness = runtime.readiness(issue)
    assert _reasons(readiness, commitment) == ["native_not_accepted"]
    (blocker,) = readiness["blockers"]
    assert (blocker["native_state"], blocker["evidence_state"]) == ("closed", "proposed")
    assert _detail(
        _error(runtime, close(issue, 1, "proposed", _closure_set(runtime, "proposed")))
    ) == ("conflict", ["closure_gate"])


# ---- the resolution evidence ---------------------------------------------------------


def test_a_member_without_resolution_evidence_refuses_closure(runtime: S2Runtime) -> None:
    issue = runtime.issue("missing")
    task_id = runtime.task("missing")
    runtime.member(issue, "task", task_id, "missing", "work")
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, "missing")
    assert "resolution_evidence_missing" in _reasons(runtime.readiness(issue), task_id)
    assert _detail(
        _error(runtime, close(issue, 1, "missing", _closure_set(runtime, "missing")))
    ) == ("conflict", ["closure_gate"])


def test_archived_resolution_evidence_refuses_closure(runtime: S2Runtime) -> None:
    issue = runtime.issue("archived")
    task_id = runtime.task("archived")
    link = runtime.member(issue, "task", task_id, "archived", "work")
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, "archived")
    root, version, _ = capture(runtime, "archived-res")
    _ok(
        runtime,
        correct(
            link, 1, "archived", (capture_anchor(root, version, NOTE_BODY, role="resolution"),)
        ),
    )
    assert _reasons(runtime.readiness(issue), task_id) == []
    runtime.ok(
        ArchiveCapture(
            capture_id=root,
            expected_lifecycle_revision=0,
            idempotency_key="s2-archived-res",
            reason="synthetic archive",
        )
    )
    assert _reasons(runtime.readiness(issue), task_id) == ["resolution_evidence_unavailable"]
    assert _detail(
        _error(runtime, close(issue, 1, "archived", _closure_set(runtime, "archived")))
    ) == ("conflict", ["closure_gate"])


def test_a_contradicted_member_refuses_closure(runtime: S2Runtime) -> None:
    issue = runtime.issue("contra")
    task_id = runtime.task("contra")
    link = runtime.member(issue, "task", task_id, "contra", "work")
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, "contra")
    meeting_id, note_id = meeting(runtime, "contra-res")
    anchors = (
        resolution_anchor(meeting_id, note_id),
        resolution_anchor(meeting_id, note_id, role="contradicts", passage="Next: pour"),
    )
    _ok(runtime, correct(link, 1, "contra", anchors))
    assert _reasons(runtime.readiness(issue), task_id) == ["resolution_evidence_contradicted"]
    assert _detail(_error(runtime, close(issue, 1, "contra", _closure_set(runtime, "contra")))) == (
        "conflict",
        ["closure_gate"],
    )


def test_resolution_evidence_recorded_while_the_task_was_open_refuses_closure(
    runtime: S2Runtime,
) -> None:
    issue = runtime.issue("early")
    task_id = runtime.task("early")
    link = runtime.member(issue, "task", task_id, "early", "work")
    _, _, anchor = runtime.evidence_source("early-res")
    _ok(runtime, correct(link, 1, "early", (anchor,)))
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, "early")
    assert _reasons(runtime.readiness(issue), task_id) == ["resolution_evidence_stale"]
    assert _detail(_error(runtime, close(issue, 1, "early", _closure_set(runtime, "early")))) == (
        "conflict",
        ["closure_gate"],
    )


def _reclosed_constraint(runtime: S2Runtime, key: str) -> tuple[str, str, str, tuple[Any, ...]]:
    """X1 closed and proven, I closed, I reopened, X1 reopened and re-closed."""
    issue = runtime.issue(key)
    project = runtime.project_with_constraints(key)
    constraint = runtime.constraint(project, key)
    link = runtime.member(issue, "constraint", constraint, key, "constraint")
    runtime.close_constraint(constraint, f"{key}-1")
    _, _, anchor = runtime.evidence_source(f"{key}-res")
    _ok(runtime, correct(link, 1, key, (anchor,)))
    _ok(runtime, close(issue, 1, f"{key}-1", _closure_set(runtime, f"{key}-1")))
    _ok(runtime, reopen(issue, 2, key))
    runtime.ok(
        ReopenConstraint(
            constraint_id=constraint,
            to_state=ConstraintLifecycleState.IN_PROGRESS,
            expected_version=runtime.constraint_version(constraint),
            reason="Synthetic reopen.",
            idempotency_key=f"s2-cst-reopen-{key}",
        )
    )
    runtime.close_constraint(constraint, f"{key}-2")
    return issue, constraint, link, (anchor,)


def test_resolution_evidence_recorded_before_a_reclose_refuses_closure(
    runtime: S2Runtime,
) -> None:
    issue, constraint, _, _ = _reclosed_constraint(runtime, "reclose")
    assert _reasons(runtime.readiness(issue), constraint) == ["resolution_evidence_stale"]
    assert _detail(
        _error(runtime, close(issue, 3, "reclose-2", _closure_set(runtime, "reclose-2")))
    ) == ("conflict", ["closure_gate"])


def test_a_same_set_reaffirmation_after_a_reclose_is_admitted(runtime: S2Runtime) -> None:
    issue, constraint, link, anchors = _reclosed_constraint(runtime, "reaffirm")
    reaffirmed = _ok(runtime, correct(link, 2, "reaffirm-2", anchors))
    assert reaffirmed["membership"]["revision_no"] == 3
    assert _reasons(runtime.readiness(issue), constraint) == []
    # Once current again, the same set is the plain no-change correction: refused.
    assert _detail(_error(runtime, correct(link, 3, "reaffirm-3", anchors))) == (
        "invalid_request",
        ["evidence_anchors"],
    )
    closed = _ok(runtime, close(issue, 3, "reaffirm-close", _closure_set(runtime, "reaffirm-c")))
    assert closed["issue"]["version"] == 4


# ---- scope, no exception, no cascade ---------------------------------------------------


def test_non_mandatory_members_do_not_gate_closure(runtime: S2Runtime) -> None:
    issue = runtime.issue("nonmandatory")
    open_task = runtime.task("nonmandatory")
    runtime.member(issue, "task", open_task, "nonmandatory-ref", "reference")
    meeting_id, _ = meeting(runtime, "nonmandatory")
    runtime.member(issue, "meeting", meeting_id, "nonmandatory-mtg", "discussion")
    assert runtime.readiness(issue)["ready"] is True
    _ok(runtime, close(issue, 1, "nonmandatory", _closure_set(runtime, "nonmandatory")))


def test_ending_a_membership_is_the_only_way_past_an_unsatisfiable_member(
    runtime: S2Runtime,
) -> None:
    issue = runtime.issue("scope")
    task_id = runtime.task("scope")
    link = runtime.member(issue, "task", task_id, "scope", "work")
    runtime.transition(task_id, TaskLifecycleState.CANCELLED, "scope")
    assert _detail(_error(runtime, close(issue, 1, "scope", _closure_set(runtime, "scope")))) == (
        "conflict",
        ["closure_gate"],
    )
    _ok(
        runtime,
        EndIssueMembership(
            link_id=link,
            expected_revision=1,
            idempotency_key="s2-scope-end",
            reason="Cancelled work is out of this Issue's scope.",
        ),
    )
    assert runtime.readiness(issue) == {
        "issue_id": issue,
        "version": 1,
        "state": "open",
        "ready": True,
        "blockers": [],
        "blockers_truncated": False,
    }
    _ok(runtime, close(issue, 1, "scope-2", _closure_set(runtime, "scope-2")))


def test_an_exception_field_is_refused() -> None:
    """The gate has no override: an `exception` (any unknown key) is `invalid_request`."""
    arguments = {
        "request_id": "req-s2-exception",
        "purpose": "issue_authoring",
        "principal_id": PRINCIPAL,
        "requested_at": "2026-10-17T12:00:00+00:00",
        "payload": {
            "issue_id": "sit_s2exception0001",
            "expected_version": 1,
            "idempotency_key": "s2-exception",
            "outcome": "Resolved.",
            "closure_evidence_anchors": [],
            "exception": {"reason": "operator override"},
        },
    }
    with pytest.raises(InvalidRequestError):
        normalize("issues.close", arguments)


def test_close_changes_no_member_or_link(runtime: S2Runtime) -> None:
    issue = runtime.issue("still")
    _completed_task_member(runtime, issue, "still")
    commitment = runtime.commitment("still")
    link = runtime.member(issue, "commitment", commitment, "still-cmt", "work")
    runtime.close_commitment(commitment, "still")
    _, _, anchor = runtime.evidence_source("still-cmt")
    _ok(runtime, correct(link, 1, "still-cmt", (anchor,)))
    closure = _closure_set(runtime, "still")
    before = _snapshot(runtime)
    _ok(runtime, close(issue, 1, "still", closure))
    assert _snapshot(runtime) == before


def test_reopen_changes_no_member_or_link(runtime: S2Runtime) -> None:
    issue = runtime.issue("reopen")
    _completed_task_member(runtime, issue, "reopen")
    _ok(runtime, close(issue, 1, "reopen", _closure_set(runtime, "reopen")))
    meeting_id, note_id = meeting(runtime, "reopen-why")
    before = _snapshot(runtime)
    reopened = _ok(
        runtime,
        reopen(
            issue,
            2,
            "reopen",
            anchors=(note_anchor(meeting_id, note_id, NOTE_BODY, role="discussion"),),
        ),
    )
    assert _snapshot(runtime) == before
    assert (reopened["issue"]["state"], reopened["issue"]["action"]) == ("active", "reopened")
    assert reopened["reopening"]["reason"] == "The problem recurred."
    assert [anchor["role"] for anchor in reopened["reopening"]["evidence"]] == ["discussion"]
    view = runtime.ok(ReadIssue(issue_id=issue))["issue"]
    assert (view["state"], view["version"], view["closure"]) == ("active", 3, None)
    # Reopening a non-closed Issue, or closing a closed one, is `conflict` / `state`.
    assert _detail(_error(runtime, reopen(issue, 3, "reopen-again"))) == ("conflict", ["state"])


def test_a_reopened_constraint_does_not_reopen_the_issue(runtime: S2Runtime) -> None:
    issue = runtime.issue("cascade")
    project = runtime.project_with_constraints("cascade")
    constraint = runtime.constraint(project, "cascade")
    link = runtime.member(issue, "constraint", constraint, "cascade", "constraint")
    runtime.close_constraint(constraint, "cascade")
    _, _, anchor = runtime.evidence_source("cascade-res")
    _ok(runtime, correct(link, 1, "cascade", (anchor,)))
    _ok(runtime, close(issue, 1, "cascade", _closure_set(runtime, "cascade")))
    runtime.ok(
        ReopenConstraint(
            constraint_id=constraint,
            to_state=ConstraintLifecycleState.IN_PROGRESS,
            expected_version=runtime.constraint_version(constraint),
            reason="Synthetic reopen.",
            idempotency_key="s2-cascade-reopen",
        )
    )
    view = runtime.ok(ReadIssue(issue_id=issue))["issue"]
    assert (view["state"], view["version"]) == ("closed", 2)
    assert view["closure"]["version"] == 2


# ---- the frozen closed Issue -----------------------------------------------------------


def test_a_closed_issue_refuses_lineage_writes(runtime: S2Runtime) -> None:
    issue = runtime.issue("frozen")
    _, link = _completed_task_member(runtime, issue, "frozen")
    meeting_id, note_id = meeting(runtime, "frozen-m")
    project = runtime.project("frozen")
    _ok(runtime, close(issue, 1, "frozen", _closure_set(runtime, "frozen")))
    before = all_s2_counts(runtime.engine)
    other_task = runtime.task("frozen-other")
    refused = [
        membership(issue, "task", other_task, "frozen-add", role="work"),
        EndIssueMembership(
            link_id=link, expected_revision=2, idempotency_key="s2-frozen-end", reason="Out."
        ),
        correct(link, 2, "frozen-correct", ()),
        AddIssueProjectLink(
            issue_id=issue,
            project_id=project,
            expected_membership_revision=0,
            idempotency_key="s2-frozen-project",
        ),
        AssertRecordAssociation(
            from_record={"family": "meeting_note_version", "record_id": note_id},
            to_record={"family": "situation", "record_id": issue},
            relation_type="discusses",
            idempotency_key="s2-frozen-discusses",
            evidence_anchors=(note_anchor(meeting_id, note_id, NOTE_BODY, role="discussion"),),
        ),
        close(issue, 2, "frozen-again", _closure_set(runtime, "frozen-again")),
    ]
    for command in refused:
        assert _detail(_error(runtime, command)) == ("conflict", ["state"]), command.capability
    assert _detail(
        _error(
            runtime,
            UpdateIssue(
                issue_id=issue,
                expected_version=2,
                idempotency_key="s2-frozen-state",
                state="active",
            ),
        )
    ) == ("invalid_request", ["state"])
    assert all_s2_counts(runtime.engine) == before
    # A foreign closed Issue answers like an absent one.
    foreign = runtime.issue("frozen-foreign", principal_id=OTHER_PRINCIPAL)
    foreign_meeting, foreign_note = meeting(runtime, "frozen-foreign", principal_id=OTHER_PRINCIPAL)
    _ok(
        runtime,
        close(foreign, 1, "frozen-foreign", (resolution_anchor(foreign_meeting, foreign_note),)),
        principal_id=OTHER_PRINCIPAL,
    )
    assert _detail(
        _error(
            runtime,
            AddIssueMembership(
                issue_id=foreign,
                member={"family": "task", "record_id": other_task},
                role="work",
                idempotency_key="s2-frozen-foreign",
            ),
        )
    ) == ("not_found", ["issue_id"])


# ---- readiness ----------------------------------------------------------------------------


def test_closure_readiness_names_each_blocked_member(runtime: S2Runtime) -> None:
    issue = runtime.issue("ready")
    open_task = runtime.task("ready-open")
    open_link = runtime.member(issue, "task", open_task, "ready-open", "work")
    proposed = runtime.commitment("ready-proposed", accepted=False)
    runtime.member(issue, "commitment", proposed, "ready-proposed", "work")
    runtime.close_commitment(proposed, "ready-proposed")
    done, _ = _completed_task_member(runtime, issue, "ready-done")
    readiness = runtime.readiness(issue)
    assert readiness["ready"] is False and readiness["blockers_truncated"] is False
    assert [
        (b["member"]["family"], b["member"]["record_id"]) for b in readiness["blockers"]
    ] == sorted([("commitment", proposed), ("task", open_task)])
    by_member = {b["member"]["record_id"]: b for b in readiness["blockers"]}
    assert by_member[open_task]["reasons"] == ["native_open", "resolution_evidence_missing"]
    assert by_member[open_task]["link_id"] == open_link
    assert (by_member[open_task]["role"], by_member[open_task]["native_state"]) == ("work", "open")
    assert by_member[open_task]["evidence_state"] == "accepted"
    # Closed after it joined, so the membership's observed version is behind too.
    assert by_member[proposed]["reasons"] == [
        "native_not_accepted",
        "resolution_evidence_missing",
        "resolution_evidence_stale",
    ]
    assert done not in by_member
    # A closed Issue answers not ready with no blockers.
    other = runtime.issue("ready-closed")
    _ok(runtime, close(other, 1, "ready-closed", _closure_set(runtime, "ready-closed")))
    assert runtime.readiness(other) == {
        "issue_id": other,
        "version": 2,
        "state": "closed",
        "ready": False,
        "blockers": [],
        "blockers_truncated": False,
    }


# ---- issues.update on a closed Issue ------------------------------------------------------


def test_correcting_a_closed_issue_keeps_it_closed(runtime: S2Runtime) -> None:
    issue = runtime.issue("correct-closed")
    closed = _ok(
        runtime, close(issue, 1, "correct-closed", _closure_set(runtime, "correct-closed"))
    )
    corrected = _ok(
        runtime,
        UpdateIssue(
            issue_id=issue,
            expected_version=2,
            idempotency_key="s2-correct-closed",
            title="Corrected title",
        ),
    )
    assert (corrected["issue"]["action"], corrected["issue"]["state"]) == ("corrected", "closed")
    assert corrected["issue"]["version"] == 3
    view = runtime.ok(ReadIssue(issue_id=issue))["issue"]
    assert (view["title"], view["state"], view["version"]) == ("Corrected title", "closed", 3)
    assert view["closure"] == closed["closure"]


def test_closure_is_never_admitted_through_issues_update(runtime: S2Runtime) -> None:
    issue = runtime.issue("no-update-close")
    with pytest.raises(InvalidRequestError):
        UpdateIssue(issue_id=issue, expected_version=1, idempotency_key="s2-nuc", state="closed")
    assert runtime.ok(ReadIssue(issue_id=issue))["issue"]["state"] == "open"


def test_a_correction_of_a_closed_issue_needs_the_local_operator(runtime: S2Runtime) -> None:
    issue = runtime.issue("attest")
    _ok(runtime, close(issue, 1, "attest", _closure_set(runtime, "attest")))
    command = UpdateIssue(
        issue_id=issue, expected_version=2, idempotency_key="s2-attest", title="Corrected"
    )
    before = all_s2_counts(runtime.engine)
    # A first-time correction by an ordinary remote client, and by an unstamped local caller.
    assert _detail(runtime.refused(command, remote_client=REMOTE_CLIENT))[0] == "denied"
    assert _detail(runtime.refused(command))[0] == "denied"
    assert all_s2_counts(runtime.engine) == before
    assert runtime.issue_version(issue) == 2
    # The operator corrects; a byte-identical replay by a non-attested caller is denied.
    corrected = _ok(runtime, command)
    assert corrected["issue"]["action"] == "corrected"
    assert _detail(runtime.refused(command, remote_client=REMOTE_CLIENT))[0] == "denied"
    assert _detail(runtime.refused(command))[0] == "denied"
    replayed = _ok(runtime, command)
    assert replayed["replayed"] is True
    assert {k: v for k, v in replayed.items() if k != "replayed"} == {
        k: v for k, v in corrected.items() if k != "replayed"
    }
    # An update of a non-closed Issue stays a recorded write, as in S1.
    open_issue = runtime.issue("attest-open")
    runtime.ok(
        UpdateIssue(
            issue_id=open_issue,
            expected_version=1,
            idempotency_key="s2-attest-open",
            title="Recorded",
        )
    )
