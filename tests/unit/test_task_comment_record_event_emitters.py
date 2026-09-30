"""WP-RE-08: a Task comment stages exactly the Record Event it should (FAST half).

Driven through `TaskManagementService` over the conftest fake unit of work,
whose `FakeRecordEventStager` publishes to `World.record_events` only when the
block ends normally. The database half is
`tests/database/test_task_comment_record_events.py`; T-23/T-24 are
`tests/concurrency/test_task_comment_record_events.py`.

* **RE-AC-096** -- a comment this call inserted stages one `task_comment`
  `created` event at version 1, named by the comment, `changed_fields`
  `{author_id, author_kind, task_id}`, actor from the author kind,
  classification `private_local`, no receipt (OD-W8-6), no causation, and no
  `task` event.
* **RE-AC-097** -- a replay by key, an idempotency conflict and a missing Task
  stage nothing.
* **RE-AC-098 (FAST half)** -- a comment that loses a concurrent same-key insert
  (the pre-read missed; the insert returned the winner's row) stages nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest

from my_pa.application.tasks import (
    TaskIdempotencyConflictError,
    TaskManagementService,
    TaskNotFoundError,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.comment import TaskComment
from my_pa.domain.task.history import TaskMutationActor
from my_pa.domain.task.lifecycle import TaskOriginKind
from tests.conftest import FakeTaskManagementUnitOfWork, World, _TasksWrite

PRINCIPAL: Final = "prn_tcmtemit00000001"
WHEN: Final = datetime(2026, 9, 30, 12, tzinfo=UTC)
CORRELATION: Final = "corr_tcmtemit0000001"
BODY: Final = "Synthetic comment body"


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def service(world: World) -> TaskManagementService:
    return TaskManagementService(
        unit_of_work=lambda: FakeTaskManagementUnitOfWork(world), clock=lambda: WHEN
    )


def _task(world: World, service: TaskManagementService) -> str:
    task_id = service.create_task(
        principal_id=PRINCIPAL,
        title="Synthetic task",
        origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        actor=TaskMutationActor.PRINCIPAL,
    ).task.task_id
    world.record_events.clear()
    return task_id


def _comment(
    service: TaskManagementService,
    task_id: str,
    key: str = "comment-0001",
    body: str = BODY,
    actor: TaskMutationActor = TaskMutationActor.PRINCIPAL,
) -> TaskComment:
    return service.create_task_comment(
        principal_id=PRINCIPAL,
        task_id=task_id,
        body=body,
        actor=actor,
        idempotency_key=key,
        source_capability="tasks.comments.create",
        correlation_id=CORRELATION,
    ).comment


def _only(world: World) -> RecordEventDraft:
    assert len(world.record_events) == 1, world.record_events
    return world.record_events[0]


# ---- RE-AC-096 --------------------------------------------------------------


def test_a_comment_stages_one_created_event(world: World, service: TaskManagementService) -> None:
    comment = _comment(service, _task(world, service))
    event = _only(world)
    assert event.record_family is RecordEventFamily.TASK_COMMENT
    assert event.record_id == comment.comment_id
    assert event.event_kind is RecordEventKind.CREATED
    assert event.record_version == 1
    assert event.changed_fields == ("author_id", "author_kind", "task_id")
    assert event.source_capability == "tasks.comments.create"
    assert event.source_receipt_id is None
    assert event.actor_class is RecordEventActorClass.PRINCIPAL
    assert event.classification is Classification.PRIVATE_LOCAL
    assert event.occurred_at == comment.created_at
    assert event.correlation_id == CORRELATION
    assert event.causation_event_id is None
    assert event.authority is None
    assert event.principal_id == PRINCIPAL


def test_a_comment_stages_no_task_event(world: World, service: TaskManagementService) -> None:
    _comment(service, _task(world, service))
    assert [event.record_family for event in world.record_events] == [
        RecordEventFamily.TASK_COMMENT
    ]


def test_the_actor_follows_the_author_kind(world: World, service: TaskManagementService) -> None:
    _comment(service, _task(world, service), actor=TaskMutationActor.ASSISTANT)
    assert _only(world).actor_class is RecordEventActorClass.ASSISTANT


def test_a_standalone_caller_names_the_comment_capability(
    world: World, service: TaskManagementService
) -> None:
    task_id = _task(world, service)
    service.create_task_comment(
        principal_id=PRINCIPAL,
        task_id=task_id,
        body=BODY,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="comment-default-0001",
    )
    assert _only(world).source_capability == "tasks.comments.create"


# ---- RE-AC-097 --------------------------------------------------------------


def test_a_replayed_comment_stages_nothing(world: World, service: TaskManagementService) -> None:
    task_id = _task(world, service)
    first = _comment(service, task_id)
    world.record_events.clear()
    again = service.create_task_comment(
        principal_id=PRINCIPAL,
        task_id=task_id,
        body=BODY,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="comment-0001",
    )
    assert again.replayed is True
    assert again.comment.comment_id == first.comment_id
    assert world.record_events == []


def test_a_conflict_and_a_missing_task_stage_nothing(
    world: World, service: TaskManagementService
) -> None:
    task_id = _task(world, service)
    _comment(service, task_id)
    world.record_events.clear()
    with pytest.raises(TaskIdempotencyConflictError):
        _comment(service, task_id, body="Different synthetic body")
    with pytest.raises(TaskNotFoundError):
        _comment(service, issue_identifier(IdKind.TASK), key="comment-missing-0001")
    assert world.record_events == []


# ---- RE-AC-098 (FAST half) --------------------------------------------------


def test_a_comment_that_loses_a_concurrent_insert_stages_nothing(
    world: World, service: TaskManagementService, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id = _task(world, service)
    winner = _comment(service, task_id)
    world.record_events.clear()
    # The race: this attempt's pre-read ran before the winner committed, so it
    # saw no key; its insert then met the winner's row and returned it.
    monkeypatch.setattr(
        _TasksWrite, "find_comment_by_idempotency_key", lambda self, principal_id, key: None
    )
    loser = service.create_task_comment(
        principal_id=PRINCIPAL,
        task_id=task_id,
        body=BODY,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="comment-0001",
    )
    assert loser.replayed is True
    assert loser.comment.comment_id == winner.comment_id
    assert world.record_events == []
