"""T-23, T-24 (WP-RE-08): Task-comment Record Events under concurrency (RE-AC-098, 099).

Marked `database` (auto `database_clone`) and `recovery`, so it is routed to
`database-recovery`. Writes go through the production `ApplicationService`
(U1, the comment joined through `active_uow`). Interleavings are forced with
the `Pause` of `tests/concurrency/test_capture_record_events.py`: the first
transaction is held open right after one statement, the second is observed
blocked in PostgreSQL, then the first is released. Every connection carries a
`lock_timeout`; a deadlock (40P01) or a lock timeout in any unmutated run is
stop N14 (N27).

* **T-23 (RE-AC-099)** -- a comment and a `tasks.update` of the same Task, in
  both orders: the comment's foreign-key share lock on the Task row and the
  update's row lock serialize; both commit; the feed is gap-free with one
  contiguous batch each -- one `task_comment` event and one `task` event.
* **T-24 (RE-AC-098)** -- two comments under one idempotency key: the second's
  pre-read misses the first's uncommitted row, its savepoint insert blocks on
  the unique key, and once the first commits it replays the winner and stages
  nothing -- one comment, one event.

Every identity and body here is synthetic.
"""

from __future__ import annotations

from typing import Final

import pytest
from tests.concurrency.test_capture_record_events import (
    Pause,
    batches,
    ok,
    race,
    runtime,
)
from tests.database.test_task_record_events import Runtime, feed, next_sequence

from my_pa.application.commands import CreateTask, CreateTaskComment, UpdateTask
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TaskOriginKind

__all__ = ["runtime"]

pytestmark = [pytest.mark.database, pytest.mark.recovery]

BODY: Final = "Synthetic wp08 concurrency comment"


def _task(runtime: Runtime, principal: str) -> str:
    created = ok(
        runtime.invoke(
            CreateTask(
                title="Synthetic wp08 T-23 task",
                idempotency_key="wp08-t23-task",
                origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
            ),
            principal_id=principal,
        )
    )
    return str(created["task"]["task_id"])


@pytest.mark.parametrize("first_writer", ["task_update", "comment"])
def test_a_comment_and_a_task_update_on_one_task_do_not_deadlock(
    runtime: Runtime, first_writer: str
) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    task_id = _task(runtime, principal)

    def comment() -> object:
        return runtime.invoke(
            CreateTaskComment(task_id=task_id, body=BODY, idempotency_key="wp08-t23-cmt"),
            principal_id=principal,
        )

    def update() -> object:
        return runtime.invoke(
            UpdateTask(
                task_id=task_id,
                expected_version=1,
                idempotency_key="wp08-t23-upd",
                title="Synthetic wp08 T-23 renamed",
            ),
            principal_id=principal,
        )

    if first_writer == "task_update":
        pause = Pause(runtime.work_engine, "UPDATE knowledge.tasks")
        held, waited = race(runtime, pause, update, comment)  # type: ignore[arg-type]
    else:
        pause = Pause(runtime.work_engine, "INSERT INTO knowledge.task_comments")
        held, waited = race(runtime, pause, comment, update)  # type: ignore[arg-type]
    ok(held)
    ok(waited)
    families = [
        [e["record_family"] for e in batch] for batch in batches(runtime.work_engine, principal)
    ]
    assert families[0] == ["task"], "the Task create's own batch"
    assert sorted(tuple(batch) for batch in families[1:]) == [("task",), ("task_comment",)]


def test_two_comments_under_one_key_commit_one_event(runtime: Runtime) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    task_id = _task(runtime, principal)
    command = CreateTaskComment(task_id=task_id, body=BODY, idempotency_key="wp08-t24-key")
    pause = Pause(runtime.work_engine, "INSERT INTO knowledge.task_comments")
    first, second = race(
        runtime,
        pause,
        lambda: runtime.invoke(command, principal_id=principal),
        lambda: runtime.invoke(command, principal_id=principal),
    )
    made, replayed = ok(first), ok(second)
    assert made["replayed"] is False
    assert replayed["replayed"] is True
    assert replayed["comment"]["comment_id"] == made["comment"]["comment_id"]
    comments = [
        e for e in feed(runtime.work_engine, principal) if e["record_family"] == "task_comment"
    ]
    assert len(comments) == 1, comments
    assert comments[0]["record_id"] == made["comment"]["comment_id"]
    assert next_sequence(runtime.work_engine, principal) == 3
