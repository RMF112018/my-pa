"""The continuity objects refuse the shapes their tables refuse.

FAST tier, over the dataclasses. Each assertion here has a schema counterpart,
and the pairing is deliberate rather than duplicative: the CHECK is what a writer
outside this process meets, and the `__post_init__` is what a caller inside it
meets, and a rule that lived in only one of the two would be a rule someone can
route around.

* a closed commitment, decision or task carries the evidence that closed it;
* accepted continuity names the review decision that accepted it, and a proposal
  names none — a biconditional, so a half-finished promotion is unrepresentable;
* a commitment names a counterparty, which is what makes it a social obligation
  rather than a task with a date;
* a `closed` or `associated` lifecycle row carries a non-blank evidence
  reference.

Every value is synthetic: invented principals, an invented Person, and a
counterparty referred to only by an opaque identifier.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.domain.situation.continuity import (
    ClosureEvidenceKind,
    Commitment,
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
    ContinuityLifecycleEvent,
    ContinuityObjectKind,
    Decision,
    DecisionState,
    LifecycleTransition,
    Task,
    TaskState,
)

PRINCIPAL_A = "prn_aaaa0001aaaa0001aaaa0001"
COUNTERPARTY = "per_counterparty0001aaaa"
REVIEW_DECISION = "rdec_review0001review0001"
ORIGIN = "cap_origin0001origin0001"
WHEN = datetime(2026, 8, 10, 12, tzinfo=UTC)


def _commitment(**overrides: object) -> Commitment:
    fields: dict[str, object] = {
        "commitment_id": "cmt_base00001base00001aa",
        "principal_id": PRINCIPAL_A,
        "counterparty_person_id": COUNTERPARTY,
        "direction": CommitmentDirection.OWED_BY_PRINCIPAL,
        "summary": "Send Sample Counterparty the revised figure",
        "state": CommitmentState.OPEN,
        "evidence_state": ContinuityEvidenceState.PROPOSED,
        "origin_evidence_ref": ORIGIN,
        "opened_at": WHEN,
        "created_at": WHEN,
        "updated_at": WHEN,
    }
    fields.update(overrides)
    return Commitment(**fields)  # type: ignore[arg-type]


def test_a_proposed_commitment_constructs_and_names_no_review_decision() -> None:
    """The safe direction: a proposal is what a writer produces by default."""
    commitment = _commitment()
    assert commitment.evidence_state is ContinuityEvidenceState.PROPOSED
    assert commitment.accepted_by_review_decision_id is None


def test_accepted_continuity_names_the_review_decision_that_accepted_it() -> None:
    """Control 2's domain half: acceptance is a review act with a reference."""
    accepted = _commitment(
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        accepted_by_review_decision_id=REVIEW_DECISION,
    )
    assert accepted.evidence_state is ContinuityEvidenceState.ACCEPTED

    with pytest.raises(ValueError, match="names the review decision"):
        _commitment(evidence_state=ContinuityEvidenceState.ACCEPTED)

    # And the other direction: a proposal holding a review decision would be a
    # promotion somebody started and did not finish.
    with pytest.raises(ValueError, match="names the review decision"):
        _commitment(accepted_by_review_decision_id=REVIEW_DECISION)


def test_a_closed_commitment_carries_the_evidence_that_closed_it() -> None:
    """Control 4's domain half. A status field cannot flip on its own."""
    closed = _commitment(
        state=CommitmentState.CLOSED,
        closed_at=WHEN,
        closure_evidence_ref="rdec_closure0001closure01",
    )
    assert closed.closed_at == WHEN

    with pytest.raises(ValueError, match="evidence that closed it"):
        _commitment(state=CommitmentState.CLOSED, closed_at=WHEN)
    with pytest.raises(ValueError, match="evidence that closed it"):
        _commitment(state=CommitmentState.CLOSED, closed_at=WHEN, closure_evidence_ref="   ")
    # And the closed-state/closed-time pairing the five continuity objects share.
    with pytest.raises(ValueError, match="records when it closed"):
        _commitment(state=CommitmentState.CLOSED, closure_evidence_ref="rdec_x0001x0001x0001x")


def test_a_commitment_requires_a_counterparty_and_a_direction() -> None:
    """What separates a Commitment from a Task, asserted rather than described."""
    with pytest.raises(ValueError):
        _commitment(counterparty_person_id="")
    with pytest.raises(ValueError):
        _commitment(counterparty_person_id="not-an-identifier")
    with pytest.raises(ValueError, match="which way the obligation runs"):
        _commitment(direction="owed_by_principal")

    # A Task has no field a counterparty could be written into at all, which is
    # the structural half of the same claim.
    task = Task(
        task_id="tsk_base00001base00001aa",
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        state=TaskState.OPEN,
        evidence_state=ContinuityEvidenceState.PROPOSED,
        origin_evidence_ref=ORIGIN,
        opened_at=WHEN,
        created_at=WHEN,
        updated_at=WHEN,
    )
    assert not hasattr(task, "counterparty_person_id")


def test_every_continuity_object_cites_the_evidence_it_was_read_out_of() -> None:
    """An obligation nobody can trace back is this product asserting one."""
    with pytest.raises(ValueError, match="read out of"):
        _commitment(origin_evidence_ref="  ")
    with pytest.raises(ValueError, match="read out of"):
        Decision(
            decision_id="cdec_base0001base0001aa",
            principal_id=PRINCIPAL_A,
            question="Which synthetic option is taken",
            state=DecisionState.OPEN,
            evidence_state=ContinuityEvidenceState.PROPOSED,
            origin_evidence_ref="",
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )


def test_a_closed_lifecycle_row_carries_evidence_and_so_does_an_association() -> None:
    """Control 4 and control 5 share one record and one rule."""
    opened = ContinuityLifecycleEvent(
        event_id="lce_open00001open00001aa",
        principal_id=PRINCIPAL_A,
        object_kind=ContinuityObjectKind.COMMITMENT,
        object_id="cmt_base00001base00001aa",
        transition=LifecycleTransition.OPENED,
        evidence_kind=ClosureEvidenceKind.CAPTURE,
        occurred_at=WHEN,
        recorded_at=WHEN,
        evidence_ref=ORIGIN,
    )
    assert opened.transition is LifecycleTransition.OPENED

    for transition, message in (
        (LifecycleTransition.CLOSED, "evidence that closed it"),
        (LifecycleTransition.ASSOCIATED, "evidence that justifies it"),
    ):
        with pytest.raises(ValueError, match=message):
            ContinuityLifecycleEvent(
                event_id="lce_bad000001bad000001aa",
                principal_id=PRINCIPAL_A,
                object_kind=ContinuityObjectKind.COMMITMENT,
                object_id="cmt_base00001base00001aa",
                transition=transition,
                evidence_kind=ClosureEvidenceKind.REVIEW_DECISION,
                occurred_at=WHEN,
                recorded_at=WHEN,
                evidence_ref=None,
            )


def test_the_closed_vocabularies_are_the_ones_the_schema_freezes() -> None:
    """Guards every CHECK-mirroring assertion above against a silent widening.

    The migration writes these literals out and cannot import them, so a member
    added here with no forward `ALTER` would leave every test green and be
    refused by the stored constraint in the field. This is where the two sets are
    compared.
    """
    assert {member.value for member in ContinuityEvidenceState} == {"proposed", "accepted"}
    assert {member.value for member in LifecycleTransition} == {"opened", "closed", "associated"}
    assert {member.value for member in ContinuityObjectKind} == {
        "commitment",
        "decision",
        "task",
        "situation",
        "project",
    }
    assert {member.value for member in CommitmentDirection} == {
        "owed_by_principal",
        "owed_to_principal",
    }
    assert {member.value for member in ClosureEvidenceKind} == {
        "review_decision",
        "capture",
        "assertion",
        "relationship_event",
        "frame",
        "situation",
        "project",
        "principal_statement",
    }
