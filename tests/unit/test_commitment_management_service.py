"""`application.commitments.CommitmentManagementService`, against an in-memory fake.

Pure logic, no database: the fake `CommitmentManagementRepository`/
`CommitmentManagementUnitOfWork` pair below is deliberately the same shape
`test_task_management_service.py`'s own fakes establish — a shared mutable
`_World`, one transaction wrapper per `with` block, and repository objects that
are cheap to construct because the state they read and write lives on the world
rather than on themselves. What this suite proves is the service's own
decisions — optimistic concurrency, idempotency replay, NO_OP-vs-APPLIED, and
the OPEN→CLOSED semantics — not anything a real database would additionally
enforce.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType

import pytest

from my_pa.application.commitments import (
    CommitmentIdempotencyConflictError,
    CommitmentManagementService,
    CommitmentNotFoundError,
    CommitmentVersionConflictError,
)
from my_pa.contracts.ports import CommitmentManagementRepository, CommitmentManagementUnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.situation.continuity import (
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.commitment import Commitment
from my_pa.domain.task.commitment_history import CommitmentHistoryEntry, CommitmentMutationAction
from my_pa.domain.task.history import TaskMutationActor, TaskMutationOutcome

PRINCIPAL_A = issue_identifier(IdKind.PRINCIPAL)
PRINCIPAL_B = issue_identifier(IdKind.PRINCIPAL)
COUNTERPARTY = issue_identifier(IdKind.PERSON)
ORIGIN = "cap_origin0001origin0001"
NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


class _World:
    """The state every fake repository/unit-of-work in this module shares.

    `insert_commitment_calls`/`update_commitment_calls`/`insert_history_calls`
    are counted rather than merely possible to infer from the dicts' sizes,
    because the idempotency-replay tests need to assert that a replayed attempt
    calls *none* of them.
    """

    def __init__(self) -> None:
        self.commitments: dict[tuple[str, str], Commitment] = {}
        self.history_by_key: dict[tuple[str, str], CommitmentHistoryEntry] = {}
        self.history_all: list[CommitmentHistoryEntry] = []
        self.insert_commitment_calls = 0
        self.update_commitment_calls = 0
        self.insert_history_calls = 0
        self.commits = 0
        self.rollbacks = 0


class _FakeRepository(CommitmentManagementRepository):
    def __init__(self, world: _World) -> None:
        self._world = world

    def get_for_update(self, principal_id: str, commitment_id: str) -> Commitment | None:
        return self._world.commitments.get((principal_id, commitment_id))

    def get(self, principal_id: str, commitment_id: str) -> Commitment | None:
        return self._world.commitments.get((principal_id, commitment_id))

    def list_commitments(
        self,
        principal_id: str,
        *,
        direction: CommitmentDirection | None = None,
        state: CommitmentState | None = None,
        evidence_state: ContinuityEvidenceState | None = None,
        after: str | None = None,
        limit: int,
    ) -> tuple[Commitment, ...]:
        del after, evidence_state
        raise NotImplementedError("this suite does not exercise the read plane")

    def insert_commitment(self, commitment: Commitment) -> None:
        self._world.insert_commitment_calls += 1
        self._world.commitments[(commitment.principal_id, commitment.commitment_id)] = commitment

    def update_commitment(self, commitment: Commitment) -> None:
        self._world.update_commitment_calls += 1
        self._world.commitments[(commitment.principal_id, commitment.commitment_id)] = commitment

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> CommitmentHistoryEntry | None:
        return self._world.history_by_key.get((principal_id, idempotency_key))

    def insert_history(self, entry: CommitmentHistoryEntry) -> None:
        self._world.insert_history_calls += 1
        self._world.history_all.append(entry)
        if entry.idempotency_key is not None:
            self._world.history_by_key[(entry.principal_id, entry.idempotency_key)] = entry

    def list_history(
        self,
        principal_id: str,
        commitment_id: str,
        limit: int,
        *,
        after: str | None = None,
    ) -> tuple[CommitmentHistoryEntry, ...]:
        raise NotImplementedError("this suite does not exercise the read plane")


class _FakeUnitOfWork(CommitmentManagementUnitOfWork):
    """One `with` block over the shared `_World`, counting how it ended."""

    def __init__(self, world: _World) -> None:
        self._world = world

    def __enter__(self) -> CommitmentManagementUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc is None:
            self._world.commits += 1
        else:
            self._world.rollbacks += 1

    @property
    def commitments(self) -> CommitmentManagementRepository:
        return _FakeRepository(self._world)


def _service(
    world: _World, clock: Callable[[], datetime] = lambda: NOW
) -> CommitmentManagementService:
    return CommitmentManagementService(unit_of_work=lambda: _FakeUnitOfWork(world), clock=clock)


def _idempotency_key(suffix: str) -> str:
    return f"idem-{suffix}-00000000"


# --- create_commitment -----------------------------------------------------------


def test_create_commitment_produces_an_open_owed_to_principal_commitment() -> None:
    world = _World()
    receipt = _service(world).create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=COUNTERPARTY,
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Send permit log by Friday",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert receipt.history.outcome is TaskMutationOutcome.APPLIED
    assert receipt.history.before_version == 0
    assert receipt.history.after_version == 1
    assert receipt.replayed is False
    assert receipt.commitment.state is CommitmentState.OPEN
    assert receipt.commitment.direction is CommitmentDirection.OWED_TO_PRINCIPAL
    assert receipt.commitment.version == 1
    assert world.insert_commitment_calls == 1
    assert world.update_commitment_calls == 0


def test_create_commitment_without_review_decision_produces_proposed_evidence_state() -> None:
    world = _World()
    receipt = _service(world).create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=COUNTERPARTY,
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Send permit log by Friday",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert receipt.commitment.evidence_state is ContinuityEvidenceState.PROPOSED


def test_create_commitment_with_review_decision_produces_accepted_evidence_state() -> None:
    world = _World()
    decision_id = issue_identifier(IdKind.REVIEW_DECISION)
    receipt = _service(world).create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=COUNTERPARTY,
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Send permit log by Friday",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        accepted_by_review_decision_id=decision_id,
    )
    assert receipt.commitment.evidence_state is ContinuityEvidenceState.ACCEPTED
    assert receipt.commitment.accepted_by_review_decision_id == decision_id


# --- close_commitment -------------------------------------------------------------


def test_close_commitment_transitions_state_and_advances_version() -> None:
    world = _World()
    service = _service(world)
    created = service.create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=COUNTERPARTY,
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Send permit log by Friday",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    closed = service.close_commitment(
        principal_id=PRINCIPAL_A,
        commitment_id=created.commitment.commitment_id,
        expected_version=created.commitment.version,
        closure_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert closed.history.outcome is TaskMutationOutcome.APPLIED
    assert closed.commitment.state is CommitmentState.CLOSED
    assert closed.commitment.version == created.commitment.version + 1
    assert closed.commitment.closed_at is not None
    assert closed.commitment.closure_evidence_ref == ORIGIN


def test_close_already_closed_commitment_is_no_op() -> None:
    world = _World()
    service = _service(world)
    created = service.create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=COUNTERPARTY,
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Send permit log by Friday",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    closed = service.close_commitment(
        principal_id=PRINCIPAL_A,
        commitment_id=created.commitment.commitment_id,
        expected_version=created.commitment.version,
        closure_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    again = service.close_commitment(
        principal_id=PRINCIPAL_A,
        commitment_id=created.commitment.commitment_id,
        expected_version=closed.commitment.version,
        closure_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert again.history.outcome is TaskMutationOutcome.NO_OP
    assert again.commitment.version == closed.commitment.version


# --- optimistic concurrency --------------------------------------------------------


def test_version_conflict_raises_and_records_rejected_history() -> None:
    world = _World()
    service = _service(world)
    created = service.create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=COUNTERPARTY,
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Send permit log by Friday",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    with pytest.raises(CommitmentVersionConflictError) as excinfo:
        service.close_commitment(
            principal_id=PRINCIPAL_A,
            commitment_id=created.commitment.commitment_id,
            expected_version=created.commitment.version + 5,
            closure_evidence_ref=ORIGIN,
            actor=TaskMutationActor.PRINCIPAL,
        )
    receipt = excinfo.value.receipt
    assert receipt.history.outcome is TaskMutationOutcome.REJECTED
    assert receipt.history.before_version == receipt.history.after_version
    assert world.update_commitment_calls == 0


# --- not found -------------------------------------------------------------------


def test_close_nonexistent_commitment_raises_not_found() -> None:
    world = _World()
    service = _service(world)
    with pytest.raises(CommitmentNotFoundError):
        service.close_commitment(
            principal_id=PRINCIPAL_A,
            commitment_id=issue_identifier(IdKind.COMMITMENT),
            expected_version=1,
            closure_evidence_ref=ORIGIN,
            actor=TaskMutationActor.PRINCIPAL,
        )
    assert world.insert_history_calls == 0
    assert world.insert_commitment_calls == 0
    assert world.update_commitment_calls == 0


# --- idempotency -------------------------------------------------------------------


def test_idempotency_key_reused_for_different_content_conflicts() -> None:
    world = _World()
    service = _service(world)
    key = _idempotency_key("create")
    service.create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=COUNTERPARTY,
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Send permit log by Friday",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=key,
    )
    inserts_after_first = world.insert_commitment_calls
    history_writes_after_first = world.insert_history_calls

    with pytest.raises(CommitmentIdempotencyConflictError):
        service.create_commitment(
            principal_id=PRINCIPAL_A,
            counterparty_person_id=COUNTERPARTY,
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            summary="A different summary the replay must not apply",
            origin_evidence_ref=ORIGIN,
            actor=TaskMutationActor.PRINCIPAL,
            idempotency_key=key,
        )
    assert world.insert_commitment_calls == inserts_after_first
    assert world.update_commitment_calls == 0
    assert world.insert_history_calls == history_writes_after_first


def test_update_commitment_is_one_atomic_versioned_mutation() -> None:
    world = _World()
    service = _service(world)
    created = service.create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=COUNTERPARTY,
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Old summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        due_at=NOW,
        idempotency_key=_idempotency_key("update-create"),
    )
    writes_before = world.insert_history_calls

    receipt = service.update_commitment(
        principal_id=PRINCIPAL_A,
        commitment_id=created.commitment.commitment_id,
        expected_version=created.commitment.version,
        actor=TaskMutationActor.PRINCIPAL,
        values={"summary": "New summary"},
        clear_due_at=True,
        idempotency_key=_idempotency_key("update-fields"),
    )

    assert receipt.commitment.summary == "New summary"
    assert receipt.commitment.due_at is None
    assert receipt.commitment.version == created.commitment.version + 1
    assert receipt.history.action is CommitmentMutationAction.UPDATE
    assert world.insert_history_calls == writes_before + 1
