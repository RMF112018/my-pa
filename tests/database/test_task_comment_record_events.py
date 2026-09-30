"""WP-RE-08: Task-comment Record Events on a real database (RE-AC-096, 097; T-16).

Marked `database` (auto `database_clone`) and routed to `database-current-head`.
Writes go through `ApplicationService.invoke` on the production SQL unit of work
(U1, the comment joined through `active_uow`), and once through the standalone
Task unit of work (U2):

* **RE-AC-096** -- a comment commits one `task_comment` `created` event at
  version 1, naming
  `{author_id, author_kind, task_id}`, with no receipt, no causation and no
  `task` event; the Task's version does not move.
* **RE-AC-097 / T-16** -- a replay (same key and body), an idempotency conflict,
  a missing Task and a foreign Task commit no event and advance no sequence.

Assertions are relative to each test's own Principal. Every identity and body
here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import select

from my_pa.application.commands import CreateTask, CreateTaskComment
from my_pa.application.tasks import TaskManagementService
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationActor
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.persistence.tables import tasks
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from tests.database.test_task_record_events import Runtime, feed, next_sequence

pytestmark = pytest.mark.database

BODY: Final = "Synthetic wp08 comment body"
WHEN: Final = datetime(2026, 9, 30, 12, tzinfo=UTC)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _principal() -> str:
    return issue_identifier(IdKind.PRINCIPAL)


def _task(runtime: Runtime, principal: str, key: str) -> str:
    created = runtime.ok(
        CreateTask(
            title="Synthetic wp08 task",
            idempotency_key=key,
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        ),
        principal_id=principal,
    )
    return str(created["task"]["task_id"])


def _comments(runtime: Runtime, principal: str) -> list[dict[str, Any]]:
    return [e for e in feed(runtime.work_engine, principal) if e["record_family"] == "task_comment"]


def _task_version(runtime: Runtime, task_id: str) -> int:
    with runtime.work_engine.connect() as connection:
        return int(
            connection.execute(
                select(tasks.c.version).where(tasks.c.task_id == task_id)
            ).scalar_one()
        )


def test_a_comment_commits_one_created_event_and_no_task_event(runtime: Runtime) -> None:
    principal = _principal()
    task_id = _task(runtime, principal, "wp08-tcm-task-0001")
    version_before = _task_version(runtime, task_id)
    before = feed(runtime.work_engine, principal)
    result = runtime.ok(
        CreateTaskComment(task_id=task_id, body=BODY, idempotency_key="wp08-tcm-0001"),
        principal_id=principal,
    )
    comment = result["comment"]
    after = feed(runtime.work_engine, principal)
    assert len(after) == len(before) + 1, "a comment commits exactly one event"
    event = after[-1]
    assert event["record_family"] == "task_comment"
    assert event["record_id"] == comment["comment_id"]
    assert event["event_kind"] == "created"
    assert event["record_version"] == 1
    assert event["changed_fields"] == ["author_id", "author_kind", "task_id"]
    assert event["source_capability"] == "tasks.comments.create"
    assert event["source_receipt_id"] is None
    assert event["actor_class"] == "principal"
    assert event["classification"] == "private_local"
    assert event["authority"] is None
    assert event["causation_event_id"] is None
    assert event["correlation_id"] is not None
    assert event["sequence_number"] == before[-1]["sequence_number"] + 1
    # No fake Task-version event: the Task did not change.
    assert [e["record_family"] for e in after].count("task") == 1
    assert _task_version(runtime, task_id) == version_before


def test_replay_conflict_and_missing_task_commit_nothing(runtime: Runtime) -> None:
    principal, stranger = _principal(), _principal()
    task_id = _task(runtime, principal, "wp08-tcm-task-0002")
    foreign_task = _task(runtime, stranger, "wp08-tcm-task-foreign")
    runtime.ok(
        CreateTaskComment(task_id=task_id, body=BODY, idempotency_key="wp08-tcm-rep"),
        principal_id=principal,
    )
    before = (feed(runtime.work_engine, principal), next_sequence(runtime.work_engine, principal))
    replay = runtime.ok(
        CreateTaskComment(task_id=task_id, body=BODY, idempotency_key="wp08-tcm-rep"),
        principal_id=principal,
    )
    assert replay["replayed"] is True
    conflict = runtime.invoke(
        CreateTaskComment(task_id=task_id, body="Other body", idempotency_key="wp08-tcm-rep"),
        principal_id=principal,
    )
    assert conflict.error is not None and conflict.error.code is ErrorCode.CONFLICT
    for missing in (issue_identifier(IdKind.TASK), foreign_task):
        refused = runtime.invoke(
            CreateTaskComment(task_id=missing, body=BODY, idempotency_key=f"wp08-tcm-{missing}"),
            principal_id=principal,
        )
        assert refused.error is not None and refused.error.code is ErrorCode.NOT_FOUND
    after = (feed(runtime.work_engine, principal), next_sequence(runtime.work_engine, principal))
    assert after == before
    assert [e["record_family"] for e in feed(runtime.work_engine, stranger)] == ["task"]


def test_the_standalone_unit_of_work_commits_the_same_event(runtime: Runtime) -> None:
    principal = _principal()
    task_id = _task(runtime, principal, "wp08-tcm-task-0003")
    service = TaskManagementService(
        unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(runtime.work_engine),
        clock=lambda: WHEN,
    )
    receipt = service.create_task_comment(
        principal_id=principal,
        task_id=task_id,
        body=BODY,
        actor=TaskMutationActor.ASSISTANT,
        idempotency_key="wp08-tcm-u2-0001",
    )
    events = _comments(runtime, principal)
    assert len(events) == 1, events
    assert events[0]["record_id"] == receipt.comment.comment_id
    assert events[0]["actor_class"] == "assistant"
    assert events[0]["source_capability"] == "tasks.comments.create"
    assert next_sequence(runtime.work_engine, principal) == 3
