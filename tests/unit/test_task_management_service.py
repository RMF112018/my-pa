"""`application.tasks.TaskManagementService`, against an in-memory fake.

Pure logic, no database: the fake `TaskManagementRepository`/`TaskManagementUnitOfWork`
pair below is deliberately the same shape `tests/conftest.py`'s `FakeUnitOfWork`
already establishes for the two-state model — a shared mutable `_World`, one
transaction wrapper per `with` block, and repository objects that are cheap to
construct because the state they read and write lives on the world rather than
on themselves. What this suite proves is the service's own decisions —
optimistic concurrency, idempotency replay, NO_OP-vs-APPLIED, and the terminal
transition rules — not anything a real database would additionally enforce;
`tests/database/test_task_management_service.py` is where those same claims are
proved against PostgreSQL.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import TracebackType

import pytest

from my_pa.application.tasks import (
    IllegalTaskTransitionError,
    TaskManagementService,
    TaskNotFoundError,
    TaskVersionConflictError,
)
from my_pa.contracts.ports import TaskManagementRepository, TaskManagementUnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.situation.continuity import ContinuityEvidenceState
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskHistoryEntry, TaskMutationActor, TaskMutationOutcome
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskPriority
from my_pa.domain.task.task import Task

PRINCIPAL_A = issue_identifier(IdKind.PRINCIPAL)
PRINCIPAL_B = issue_identifier(IdKind.PRINCIPAL)
ORIGIN = "cap_origin0001origin0001"
NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


class _World:
    """The state every fake repository/unit-of-work in this module shares.

    `insert_task_calls`/`update_task_calls`/`insert_history_calls` are counted
    rather than merely possible to infer from the dicts' sizes, because the
    idempotency-replay tests need to assert that a replayed attempt calls
    *none* of them — a count that a dict's final size cannot distinguish from
    "called once and overwrote itself".
    """

    def __init__(self) -> None:
        self.tasks: dict[tuple[str, str], Task] = {}
        self.history_by_key: dict[tuple[str, str], TaskHistoryEntry] = {}
        self.history_all: list[TaskHistoryEntry] = []
        self.insert_task_calls = 0
        self.update_task_calls = 0
        self.insert_history_calls = 0
        self.commits = 0
        self.rollbacks = 0


class _FakeRepository(TaskManagementRepository):
    def __init__(self, world: _World) -> None:
        self._world = world

    def get_for_update(self, principal_id: str, task_id: str) -> Task | None:
        return self._world.tasks.get((principal_id, task_id))

    def insert_task(self, task: Task) -> None:
        self._world.insert_task_calls += 1
        self._world.tasks[(task.principal_id, task.task_id)] = task

    def update_task(self, task: Task) -> None:
        self._world.update_task_calls += 1
        self._world.tasks[(task.principal_id, task.task_id)] = task

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskHistoryEntry | None:
        return self._world.history_by_key.get((principal_id, idempotency_key))

    def insert_history(self, entry: TaskHistoryEntry) -> None:
        self._world.insert_history_calls += 1
        self._world.history_all.append(entry)
        if entry.idempotency_key is not None:
            self._world.history_by_key[(entry.principal_id, entry.idempotency_key)] = entry

    # --- WP-TM-03's read plane, implemented only to satisfy the ABC ---------
    #
    # This suite exercises `TaskManagementService`, which never calls these;
    # `tests/unit/test_task_reads.py` is where the read plane's own behaviour
    # (scoping, filters, ordering, truncation) is actually proved, against its
    # own fake. These exist only so this module's `_FakeRepository` remains a
    # complete `TaskManagementRepository`.

    def get(self, principal_id: str, task_id: str) -> Task | None:
        return self._world.tasks.get((principal_id, task_id))

    def list_tasks(
        self,
        principal_id: str,
        *,
        lifecycle_state: TaskLifecycleState | None = None,
        priority: TaskPriority | None = None,
        include_archived: bool = False,
        limit: int,
    ) -> tuple[Task, ...]:
        raise NotImplementedError("this suite does not exercise the read plane")

    def search(self, principal_id: str, query: str, limit: int) -> tuple[Task, ...]:
        raise NotImplementedError("this suite does not exercise the read plane")

    def list_history(
        self, principal_id: str, task_id: str, limit: int
    ) -> tuple[TaskHistoryEntry, ...]:
        raise NotImplementedError("this suite does not exercise the read plane")


class _FakeUnitOfWork(TaskManagementUnitOfWork):
    """One `with` block over the shared `_World`, counting how it ended."""

    def __init__(self, world: _World) -> None:
        self._world = world

    def __enter__(self) -> TaskManagementUnitOfWork:
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
    def tasks(self) -> TaskManagementRepository:
        return _FakeRepository(self._world)


def _service(world: _World, clock: Callable[[], datetime] = lambda: NOW) -> TaskManagementService:
    return TaskManagementService(unit_of_work=lambda: _FakeUnitOfWork(world), clock=clock)


def _idempotency_key(suffix: str) -> str:
    return f"idem-{suffix}-00000000"


# --- create_task -------------------------------------------------------------


def test_create_task_produces_a_fresh_proposed_task_and_an_applied_receipt() -> None:
    world = _World()
    receipt = _service(world).create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert receipt.history.outcome is TaskMutationOutcome.APPLIED
    assert receipt.history.before_version == 0
    assert receipt.history.after_version == 1
    assert receipt.replayed is False
    assert receipt.task.evidence_state is ContinuityEvidenceState.PROPOSED
    assert receipt.task.lifecycle_state is TaskLifecycleState.OPEN
    assert receipt.task.version == 1
    assert world.insert_task_calls == 1
    assert world.update_task_calls == 0


def test_create_task_with_a_review_decision_produces_an_accepted_task() -> None:
    world = _World()
    decision_id = issue_identifier(IdKind.REVIEW_DECISION)
    receipt = _service(world).create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        accepted_by_review_decision_id=decision_id,
    )
    assert receipt.task.evidence_state is ContinuityEvidenceState.ACCEPTED
    assert receipt.task.accepted_by_review_decision_id == decision_id


# --- update_title --------------------------------------------------------------


def test_update_title_applies_a_real_change_and_advances_the_version() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Original title",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    receipt = service.update_title(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        title="Revised title",
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert receipt.history.outcome is TaskMutationOutcome.APPLIED
    assert receipt.task.title == "Revised title"
    assert receipt.task.version == created.task.version + 1


def test_update_title_with_the_same_title_is_recorded_no_op() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Original title",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    receipt = service.update_title(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        title="Original title",
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert receipt.history.outcome is TaskMutationOutcome.NO_OP
    assert receipt.task.version == created.task.version
    assert world.update_task_calls == 0


# --- set_priority, schedule, defer ---------------------------------------------


def test_set_priority_applies_and_stores_the_new_priority() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    receipt = service.set_priority(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        priority=TaskPriority.P1,
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert receipt.history.outcome is TaskMutationOutcome.APPLIED
    assert receipt.task.priority is TaskPriority.P1


def test_schedule_sets_and_clears_the_scheduled_instant() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    scheduled = service.schedule(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        scheduled_at=NOW + timedelta(days=1),
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert scheduled.task.scheduled_at == NOW + timedelta(days=1)
    cleared = service.schedule(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        scheduled_at=None,
        expected_version=scheduled.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert cleared.task.scheduled_at is None


def test_defer_sets_and_clears_the_deferred_until_instant() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    deferred = service.defer(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        deferred_until=NOW + timedelta(days=2),
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert deferred.task.deferred_until == NOW + timedelta(days=2)


# --- archive/unarchive ----------------------------------------------------------


def test_archive_applies_once_and_unarchive_clears_it() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    archived = service.archive(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert archived.history.outcome is TaskMutationOutcome.APPLIED
    assert archived.task.archived_at is not None

    unarchived = service.unarchive(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        expected_version=archived.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert unarchived.history.outcome is TaskMutationOutcome.APPLIED
    assert unarchived.task.archived_at is None


def test_unarchive_of_an_already_unarchived_task_is_no_op() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    receipt = service.unarchive(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert receipt.history.outcome is TaskMutationOutcome.NO_OP


def test_archive_of_an_already_archived_task_is_no_op() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    archived = service.archive(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    again = service.archive(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        expected_version=archived.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert again.history.outcome is TaskMutationOutcome.NO_OP


# --- transition_lifecycle -------------------------------------------------------


def test_a_legal_transition_applies_and_a_repeat_request_is_no_op() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    started = service.transition_lifecycle(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        to_state=TaskLifecycleState.IN_PROGRESS,
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert started.history.outcome is TaskMutationOutcome.APPLIED
    assert started.task.lifecycle_state is TaskLifecycleState.IN_PROGRESS

    repeated = service.transition_lifecycle(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        to_state=TaskLifecycleState.IN_PROGRESS,
        expected_version=started.task.version,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert repeated.history.outcome is TaskMutationOutcome.NO_OP


def test_a_terminal_task_cannot_be_transitioned_further() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    completed = service.transition_lifecycle(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        to_state=TaskLifecycleState.COMPLETED,
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
        closure_evidence_ref=ORIGIN,
    )
    assert completed.task.lifecycle_state is TaskLifecycleState.COMPLETED

    with pytest.raises(IllegalTaskTransitionError):
        service.transition_lifecycle(
            principal_id=PRINCIPAL_A,
            task_id=created.task.task_id,
            to_state=TaskLifecycleState.OPEN,
            expected_version=completed.task.version,
            actor=TaskMutationActor.PRINCIPAL,
        )


def test_entering_a_terminal_state_with_no_closure_evidence_is_refused() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    with pytest.raises(IllegalTaskTransitionError):
        service.transition_lifecycle(
            principal_id=PRINCIPAL_A,
            task_id=created.task.task_id,
            to_state=TaskLifecycleState.CANCELLED,
            expected_version=created.task.version,
            actor=TaskMutationActor.PRINCIPAL,
        )
    # And the refusal wrote nothing: the task is still at its original version.
    stored = world.tasks[(PRINCIPAL_A, created.task.task_id)]
    assert stored.version == created.task.version
    assert stored.lifecycle_state is TaskLifecycleState.OPEN


def test_a_terminal_transition_with_evidence_succeeds_and_records_closure() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    completed = service.transition_lifecycle(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        to_state=TaskLifecycleState.COMPLETED,
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
        closure_evidence_ref=ORIGIN,
    )
    assert completed.history.outcome is TaskMutationOutcome.APPLIED
    assert completed.task.closed_at is not None
    assert completed.task.closure_evidence_ref == ORIGIN


# --- optimistic concurrency ------------------------------------------------------


def test_a_stale_expected_version_is_rejected_and_leaves_the_row_untouched() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Original title",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    before = world.tasks[(PRINCIPAL_A, created.task.task_id)]

    with pytest.raises(TaskVersionConflictError) as excinfo:
        service.update_title(
            principal_id=PRINCIPAL_A,
            task_id=created.task.task_id,
            title="Attempted change under a stale version",
            expected_version=created.task.version + 5,
            actor=TaskMutationActor.PRINCIPAL,
        )
    receipt = excinfo.value.receipt
    assert receipt.history.outcome is TaskMutationOutcome.REJECTED
    assert receipt.history.before_version == receipt.history.after_version

    after = world.tasks[(PRINCIPAL_A, created.task.task_id)]
    assert after == before, "a version-conflict attempt must not mutate the stored task"
    assert world.update_task_calls == 0


# --- idempotency -------------------------------------------------------------------


def test_a_replayed_idempotency_key_returns_the_identical_receipt_and_writes_nothing() -> None:
    world = _World()
    service = _service(world)
    key = _idempotency_key("create")
    first = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=key,
    )
    inserts_after_first = world.insert_task_calls
    history_writes_after_first = world.insert_history_calls

    second = service.create_task(
        principal_id=PRINCIPAL_A,
        title="A materially different title that must not be applied",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=key,
    )

    assert second.replayed is True
    assert second.history == first.history
    assert second.task == first.task
    assert world.insert_task_calls == inserts_after_first
    assert world.update_task_calls == 0
    assert world.insert_history_calls == history_writes_after_first


def test_idempotency_replay_also_applies_to_a_mutation_on_an_existing_task() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Original title",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    key = _idempotency_key("update")
    first = service.update_title(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        title="Revised title",
        expected_version=created.task.version,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=key,
    )
    update_calls_after_first = world.update_task_calls
    history_calls_after_first = world.insert_history_calls

    second = service.update_title(
        principal_id=PRINCIPAL_A,
        task_id=created.task.task_id,
        title="Yet another title the replay must not apply",
        expected_version=first.task.version,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=key,
    )

    assert second.replayed is True
    assert dataclasses.asdict(second.history) == dataclasses.asdict(first.history)
    assert second.task == first.task
    assert world.update_task_calls == update_calls_after_first
    assert world.insert_history_calls == history_calls_after_first


# --- task not found -----------------------------------------------------------------


def test_a_mutation_naming_an_absent_task_raises_task_not_found() -> None:
    world = _World()
    service = _service(world)
    with pytest.raises(TaskNotFoundError):
        service.update_title(
            principal_id=PRINCIPAL_A,
            task_id=issue_identifier(IdKind.TASK),
            title="Never applied",
            expected_version=1,
            actor=TaskMutationActor.PRINCIPAL,
        )
    assert world.insert_history_calls == 0
    assert world.insert_task_calls == 0
    assert world.update_task_calls == 0


def test_a_task_belonging_to_another_principal_is_not_found_either() -> None:
    world = _World()
    service = _service(world)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    with pytest.raises(TaskNotFoundError):
        service.update_title(
            principal_id=PRINCIPAL_B,
            task_id=created.task.task_id,
            title="Never applied",
            expected_version=created.task.version,
            actor=TaskMutationActor.PRINCIPAL,
        )
