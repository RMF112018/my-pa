"""Representative scenario: Commitment / Follow-Up / Waiting On (WP-TM-05).

Full-stack through `ApplicationService.invoke`, exercising the read and write
planes together. Writes go through `CommitmentManagementService` and
`TaskManagementService` (via their own `UnitOfWork` fakes), reads go through
`FakeUnitOfWork`'s read-only fakes — all sharing one `World`, so a write is
immediately visible to a subsequent read.

Scenario: "Sarah / permit log / Friday"
    1. Create an OWED_TO_PRINCIPAL commitment → counterparty Sarah
    2. Create a follow-up task linked to it (role = FOLLOW_UP)
    3. Query "waiting on" → the commitment appears with the follow-up task
    4. Complete the follow-up task (transition to COMPLETED)
    5. Query "waiting on" again → commitment still appears (completing a
       follow-up does NOT close its commitment)
    6. Verify commitment state is still OPEN
    7. Idempotency replay → re-create with same key, verify replayed=True
    8. Two-principal isolation → a second principal sees no commitments
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from types import TracebackType

from my_pa.application.commands import (
    CreateCommitment,
    CreateTask,
    ListCommitments,
    ReadCommitment,
    TransitionTask,
    WaitingOn,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import (
    CommitmentManagementRepository,
    CommitmentManagementUnitOfWork,
    TaskManagementRepository,
    TaskManagementUnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.situation.continuity import (
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.commitment import Commitment
from my_pa.domain.task.commitment_history import CommitmentHistoryEntry
from my_pa.domain.task.history import TaskHistoryEntry
from my_pa.domain.task.lifecycle import (
    TaskArchiveMode,
    TaskLifecycleState,
    TaskPriority,
    TaskWorkView,
)
from my_pa.domain.task.role import TaskRole
from my_pa.domain.task.task import Task
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeUnitOfWork,
    World,
    metadata_for,
    operator,
)

COUNTERPARTY = issue_identifier(IdKind.PERSON)
ORIGIN = "cap_origin0001origin0001"
ACCEPTANCE = issue_identifier(IdKind.REVIEW_DECISION)


# ---------------------------------------------------------------------------
# In-memory fakes that write to `World`, making writes visible to the
# read-plane fakes `FakeUnitOfWork` already holds.
# ---------------------------------------------------------------------------


class _CommitmentRepo(CommitmentManagementRepository):
    """Commitment repository backed by `World.commitments_v2` / `commitment_history_v2`."""

    def __init__(self, world: World) -> None:
        self._world = world

    def get_for_update(self, principal_id: str, commitment_id: str) -> Commitment | None:
        return next(
            (
                c
                for c in self._world.commitments_v2
                if c.principal_id == principal_id and c.commitment_id == commitment_id
            ),
            None,
        )

    def get(self, principal_id: str, commitment_id: str) -> Commitment | None:
        return self.get_for_update(principal_id, commitment_id)

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
        owned = [c for c in self._world.commitments_v2 if c.principal_id == principal_id]
        if direction is not None:
            owned = [c for c in owned if c.direction is direction]
        if state is not None:
            owned = [c for c in owned if c.state is state]
        if evidence_state is not None:
            owned = [c for c in owned if c.evidence_state is evidence_state]
        ordered = sorted(
            owned,
            key=lambda c: (
                c.due_at is None,
                c.due_at or datetime.max.replace(tzinfo=UTC),
                -c.created_at.timestamp(),
                c.commitment_id,
            ),
        )
        if after is not None:
            ordered = ordered[
                next(
                    (
                        index + 1
                        for index, commitment in enumerate(ordered)
                        if commitment.commitment_id == after
                    ),
                    len(ordered),
                ) :
            ]
        return tuple(ordered[:limit])

    def insert_commitment(self, commitment: Commitment) -> None:
        self._world.commitments_v2.append(commitment)

    def update_commitment(self, commitment: Commitment) -> None:
        self._world.commitments_v2[:] = [
            commitment if c.commitment_id == commitment.commitment_id else c
            for c in self._world.commitments_v2
        ]

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> CommitmentHistoryEntry | None:
        return next(
            (
                h
                for h in self._world.commitment_history_v2
                if h.principal_id == principal_id and h.idempotency_key == idempotency_key
            ),
            None,
        )

    def insert_history(self, entry: CommitmentHistoryEntry) -> None:
        self._world.commitment_history_v2.append(entry)

    def list_history(
        self,
        principal_id: str,
        commitment_id: str,
        limit: int,
        *,
        after: str | None = None,
    ) -> tuple[CommitmentHistoryEntry, ...]:
        owned = [
            h
            for h in self._world.commitment_history_v2
            if h.principal_id == principal_id and h.commitment_id == commitment_id
        ]
        return tuple(sorted(owned, key=lambda h: h.recorded_at)[:limit])


class _CommitmentUoW(CommitmentManagementUnitOfWork):
    def __init__(self, world: World) -> None:
        self._world = world

    def __enter__(self) -> CommitmentManagementUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    @property
    def commitments(self) -> CommitmentManagementRepository:
        return _CommitmentRepo(self._world)


class _TaskRepo(TaskManagementRepository):
    """Task repository backed by `World.tasks_v2` / `task_history_v2`."""

    def __init__(self, world: World) -> None:
        self._world = world

    def get_for_update(self, principal_id: str, task_id: str) -> Task | None:
        return next(
            (
                t
                for t in self._world.tasks_v2
                if t.principal_id == principal_id and t.task_id == task_id
            ),
            None,
        )

    def get(self, principal_id: str, task_id: str) -> Task | None:
        return self.get_for_update(principal_id, task_id)

    def insert_task(self, task: Task) -> None:
        self._world.tasks_v2.append(task)

    def update_task(self, task: Task) -> None:
        self._world.tasks_v2[:] = [
            task if t.task_id == task.task_id else t for t in self._world.tasks_v2
        ]

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskHistoryEntry | None:
        return next(
            (
                h
                for h in self._world.task_history_v2
                if h.principal_id == principal_id and h.idempotency_key == idempotency_key
            ),
            None,
        )

    def insert_history(self, entry: TaskHistoryEntry) -> None:
        self._world.task_history_v2.append(entry)

    def list_tasks(
        self,
        principal_id: str,
        *,
        lifecycle_state: TaskLifecycleState | None = None,
        priority: TaskPriority | None = None,
        archive_mode: TaskArchiveMode = TaskArchiveMode.EXCLUDE,
        after: str | None = None,
        work_view: TaskWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
        limit: int,
    ) -> tuple[Task, ...]:
        raise NotImplementedError("write-plane fake does not serve list reads")

    def search(
        self,
        principal_id: str,
        query: str,
        limit: int,
        *,
        after: str | None = None,
        archive_mode: TaskArchiveMode = TaskArchiveMode.EXCLUDE,
        work_view: TaskWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
    ) -> tuple[Task, ...]:
        raise NotImplementedError("write-plane fake does not serve search")

    def list_history(
        self, principal_id: str, task_id: str, limit: int, *, after: str | None = None
    ) -> tuple[TaskHistoryEntry, ...]:
        raise NotImplementedError("write-plane fake does not serve history reads")

    def latest_applied_terminal_history(
        self, principal_id: str, task_id: str
    ) -> TaskHistoryEntry | None:
        raise NotImplementedError("write-plane fake does not serve history reads")


class _TaskUoW(TaskManagementUnitOfWork):
    def __init__(self, world: World) -> None:
        self._world = world

    def __enter__(self) -> TaskManagementUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    @property
    def tasks(self) -> TaskManagementRepository:
        return _TaskRepo(self._world)


def _build_wired_service(world: World) -> ApplicationService:
    """An `ApplicationService` with both management planes wired to `world`."""
    return ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        managed_store=world.managed_store,
        task_management_unit_of_work=lambda: _TaskUoW(world),
        commitment_management_unit_of_work=lambda: _CommitmentUoW(world),
    )


def _idempotency_key(suffix: str) -> str:
    return f"idem-{suffix}-00000000"


# ---------------------------------------------------------------------------
# Scenario: "Sarah / permit log / Friday"
# ---------------------------------------------------------------------------


def test_waiting_on_excludes_proposed_commitments() -> None:
    world = World()
    service = _build_wired_service(world)
    principal = operator()
    world.work_evidence_refs.add((principal.principal_id, ORIGIN))

    create = service.invoke(
        metadata_for(Capability.COMMITMENTS_CREATE, Purpose.COMMITMENT_AUTHORING, principal),
        CreateCommitment(
            counterparty_person_id=COUNTERPARTY,
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            summary="Unreviewed permit promise",
            origin_evidence_ref=ORIGIN,
            idempotency_key=_idempotency_key("proposed-commitment"),
        ),
        principal=principal,
    )
    assert create.error is None, create.error
    assert create.result is not None
    assert create.result["commitment"]["evidence_state"] == ContinuityEvidenceState.PROPOSED.value

    waiting = service.invoke(
        metadata_for(Capability.COMMITMENTS_WAITING_ON, Purpose.COMMITMENT_READ, principal),
        WaitingOn(),
        principal=principal,
    )
    assert waiting.error is None, waiting.error
    assert waiting.result is not None
    assert waiting.result["waiting_on"] == []


def test_sarah_permit_log_scenario() -> None:
    world = World()
    service = _build_wired_service(world)
    principal_a = operator()
    world.work_evidence_refs.add((principal_a.principal_id, ORIGIN))

    # --- Step 1: Create an OWED_TO_PRINCIPAL commitment ----------------------
    create_key = _idempotency_key("create-commitment")
    create_meta = metadata_for(
        Capability.COMMITMENTS_CREATE, Purpose.COMMITMENT_AUTHORING, principal_a
    )
    create_cmd = CreateCommitment(
        counterparty_person_id=COUNTERPARTY,
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Send permit log by Friday",
        origin_evidence_ref=ORIGIN,
        accepted_by_review_decision_id=ACCEPTANCE,
        idempotency_key=create_key,
    )
    create_resp = service.invoke(create_meta, create_cmd, principal=principal_a)
    assert create_resp.error is None, create_resp.error
    assert create_resp.result is not None
    commitment_data = create_resp.result["commitment"]
    commitment_id = commitment_data["commitment_id"]
    assert commitment_data["direction"] == CommitmentDirection.OWED_TO_PRINCIPAL.value
    assert commitment_data["state"] == CommitmentState.OPEN.value

    # --- Step 2: Create a follow-up task linked to the commitment ------------
    #
    # `_tasks_create` does not yet wire `CreateTask.commitment_id`/`role`
    # through to the underlying service (the handler issues a plain
    # `create_task` and the follow-up `link_commitment`/`set_role` calls
    # are documented but not yet composed). So we create the task via
    # `invoke`, then apply the link and role directly on `World.tasks_v2`
    # — the same effect the handler will eventually produce.
    task_key = _idempotency_key("create-follow-up")
    task_meta = metadata_for(Capability.TASKS_CREATE, Purpose.TASK_AUTHORING, principal_a)
    task_cmd = CreateTask(
        title="Follow up with Sarah about the permit log",
        origin_evidence_ref=ORIGIN,
        idempotency_key=task_key,
    )
    task_resp = service.invoke(task_meta, task_cmd, principal=principal_a)
    assert task_resp.error is None, task_resp.error
    assert task_resp.result is not None
    follow_up_task_id = task_resp.result["task"]["task_id"]

    # Link the task to the commitment and set FOLLOW_UP role in-memory.
    world.tasks_v2[:] = [
        dataclasses.replace(t, commitment_id=commitment_id, role=TaskRole.FOLLOW_UP)
        if t.task_id == follow_up_task_id
        else t
        for t in world.tasks_v2
    ]

    # --- Step 3: Query "waiting on" — commitment appears with follow-up ------
    waiting_meta = metadata_for(
        Capability.COMMITMENTS_WAITING_ON, Purpose.COMMITMENT_READ, principal_a
    )
    waiting_cmd = WaitingOn()
    waiting_resp = service.invoke(waiting_meta, waiting_cmd, principal=principal_a)
    assert waiting_resp.error is None, waiting_resp.error
    assert waiting_resp.result is not None
    waiting_entries = waiting_resp.result["waiting_on"]
    assert len(waiting_entries) == 1
    entry = waiting_entries[0]
    assert entry["commitment_id"] == commitment_id
    assert entry["title"] == "Send permit log by Friday"
    assert entry["follow_up_task_id"] == follow_up_task_id
    assert entry["follow_up_task_state"] == TaskLifecycleState.OPEN.value

    # --- Step 4: Complete the follow-up task ---------------------------------
    transition_meta = metadata_for(Capability.TASKS_TRANSITION, Purpose.TASK_AUTHORING, principal_a)
    transition_cmd = TransitionTask(
        task_id=follow_up_task_id,
        to_state=TaskLifecycleState.COMPLETED,
        expected_version=1,
        closure_evidence_ref=ORIGIN,
        idempotency_key=_idempotency_key("complete-task"),
    )
    transition_resp = service.invoke(transition_meta, transition_cmd, principal=principal_a)
    assert transition_resp.error is None, transition_resp.error

    # --- Step 5: Query "waiting on" again — commitment still appears ---------
    waiting_resp2 = service.invoke(waiting_meta, waiting_cmd, principal=principal_a)
    assert waiting_resp2.error is None, waiting_resp2.error
    assert waiting_resp2.result is not None
    entries2 = waiting_resp2.result["waiting_on"]
    assert len(entries2) == 1, "completing a follow-up must NOT close the linked commitment"
    assert entries2[0]["follow_up_task_state"] == TaskLifecycleState.COMPLETED.value

    # --- Step 6: Verify commitment is still OPEN -----------------------------
    read_meta = metadata_for(Capability.COMMITMENTS_READ, Purpose.COMMITMENT_READ, principal_a)
    read_cmd = ReadCommitment(commitment_id=commitment_id)
    read_resp = service.invoke(read_meta, read_cmd, principal=principal_a)
    assert read_resp.error is None, read_resp.error
    assert read_resp.result is not None
    assert read_resp.result["commitment"]["state"] == CommitmentState.OPEN.value

    # --- Step 7: Idempotency replay — re-create with same key ----------------
    replay_resp = service.invoke(create_meta, create_cmd, principal=principal_a)
    assert replay_resp.error is None, replay_resp.error
    assert replay_resp.result is not None
    assert replay_resp.result["replayed"] is True
    assert replay_resp.result["commitment"]["commitment_id"] == commitment_id

    # --- Step 8: Two-principal isolation — second principal sees nothing ------
    principal_b = operator()
    list_meta_b = metadata_for(Capability.COMMITMENTS_LIST, Purpose.COMMITMENT_READ, principal_b)
    list_cmd = ListCommitments()
    list_resp_b = service.invoke(list_meta_b, list_cmd, principal=principal_b)
    assert list_resp_b.error is None, list_resp_b.error
    assert list_resp_b.result is not None
    assert list_resp_b.result["commitments"] == []

    waiting_meta_b = metadata_for(
        Capability.COMMITMENTS_WAITING_ON, Purpose.COMMITMENT_READ, principal_b
    )
    waiting_resp_b = service.invoke(waiting_meta_b, waiting_cmd, principal=principal_b)
    assert waiting_resp_b.error is None, waiting_resp_b.error
    assert waiting_resp_b.result is not None
    assert waiting_resp_b.result["waiting_on"] == []


def test_counterparty_picker_queries_are_principal_scoped() -> None:
    """The picker cannot label a Person outside the authenticated partition."""
    from dataclasses import dataclass

    from sqlalchemy.sql.elements import ClauseElement

    from my_pa.infrastructure.persistence.commitment_management import (
        SqlCommitmentManagementRepository,
    )

    @dataclass(frozen=True)
    class Row:
        person_id: str
        display_name: str

    class Result:
        def all(self) -> list[Row]:
            return [Row("per_aaaaaaaa11111111", "Sam Rivera")]

        def one_or_none(self) -> None:
            return None

    class Connection:
        def __init__(self) -> None:
            self.statements: list[ClauseElement] = []

        def execute(self, statement: ClauseElement) -> Result:
            self.statements.append(statement)
            return Result()

    connection = Connection()
    repository = SqlCommitmentManagementRepository(connection)  # type: ignore[arg-type]
    options = repository.list_counterparties("prn_aaaaaaaa11111111", limit=101)
    assert [(item.person_id, item.display_name) for item in options] == [
        ("per_aaaaaaaa11111111", "Sam Rivera")
    ]
    list_sql = str(connection.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "relationship_people.principal_id = 'prn_aaaaaaaa11111111'" in list_sql
    assert "relationship_people.superseded_by_person_id IS NULL" in list_sql
    assert "ORDER BY lower(knowledge.relationship_people.display_name) ASC" in list_sql
    assert "LIMIT 101" in list_sql

    assert repository.counterparty("prn_aaaaaaaa11111111", "per_bbbbbbbb22222222") is None
    lookup_sql = str(connection.statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert "relationship_people.principal_id = 'prn_aaaaaaaa11111111'" in lookup_sql
    assert "relationship_people.person_id = 'per_bbbbbbbb22222222'" in lookup_sql
