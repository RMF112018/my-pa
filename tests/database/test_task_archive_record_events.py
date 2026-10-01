"""CP-RE-08b (MR-17): Task archive Record Events after PR #298, on a real database.

PR #298 made `archived` a logical flag: an update with `archived=True` and
`archive()` keep an existing `archived_at` instead of re-stamping it, replay
digests bind the caller's intent rather than a generated timestamp, and a
same-state request is a no-op. This module pins what the WP-RE-02 emitters
stage on top of that (RE-AC-019, 021, 022, 024):

* **(a)** `tasks.update` with `archived=True` on an unarchived Task commits one
  `updated` event naming `archived_at` (plus any other changed field) at
  version + 1.
* **(b)** Archiving an already archived Task -- through `tasks.update` or
  `TaskManagementService.archive` -- is NO_OP: no event, no sequence advance.
* **(c)** `unarchive()` and `tasks.update` with `archived=False` name
  `archived_at`.
* **(d)** A logical replay of each of the above commits nothing and advances no
  `record_event_sequences.next_sequence`.
* **(e)** `tasks.bulk_confirm` goes through `_bulk_candidate`, not `_mutate`;
  #298 changed its `archived` branch the same way, so a bulk archive of an
  archived member is a no-op member and stages nothing.

Marked `database` (auto `database_clone`). `archive()` and `unarchive()` have
no public capability of their own, so they run on the standalone Task unit of
work with a ticking clock; everything else goes through
`ApplicationService.invoke`. Every Principal is fresh per test, and every
assertion is relative to it. Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select

from my_pa.application.commands import BulkConfirmTasks, BulkPreviewTasks, CreateTask, UpdateTask
from my_pa.application.tasks import TaskManagementService
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationActor, TaskMutationOutcome
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import tasks
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from tests.database.test_task_record_events import WHEN, Runtime, feed, next_sequence, runtime

__all__ = ["runtime"]

pytestmark = pytest.mark.database


@pytest.fixture
def principal() -> str:
    return issue_identifier(IdKind.PRINCIPAL)


def _archived_at(engine: Engine, principal_id: str, task_id: str) -> datetime | None:
    with engine.connect() as connection:
        value: datetime | None = connection.execute(
            select(tasks.c.archived_at).where(
                tasks.c.principal_id == principal_id, tasks.c.task_id == task_id
            )
        ).scalar_one()
        return value


def _state(engine: Engine, principal_id: str) -> tuple[list[dict[str, Any]], int | None]:
    return feed(engine, principal_id), next_sequence(engine, principal_id)


def _create(runtime: Runtime, principal: str, key: str) -> str:
    created = runtime.ok(
        CreateTask(
            title="Synthetic task",
            idempotency_key=key,
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        ),
        principal_id=principal,
    )
    return str(created["task"]["task_id"])


def _update(runtime: Runtime, principal: str, command: UpdateTask) -> dict[str, Any]:
    return runtime.ok(command, principal_id=principal)


def _archive_via_update(runtime: Runtime, principal: str, task_id: str, key: str) -> None:
    result = _update(
        runtime,
        principal,
        UpdateTask(task_id=task_id, expected_version=1, idempotency_key=key, archived=True),
    )
    assert result["history"]["outcome"] == "applied"
    assert result["task"]["version"] == 2


# ---- (a) tasks.update archived=True on an unarchived Task ---------------------


@pytest.mark.parametrize("with_title", [False, True], ids=["archived-only", "archived-and-title"])
def test_update_archived_true_names_archived_at_at_the_next_version(
    runtime: Runtime, principal: str, with_title: bool
) -> None:
    task_id = _create(runtime, principal, f"cp08b-a-create-{with_title}")
    before_sequence = next_sequence(runtime.work_engine, principal)
    updated = _update(
        runtime,
        principal,
        UpdateTask(
            task_id=task_id,
            expected_version=1,
            idempotency_key=f"cp08b-a-update-{with_title}",
            archived=True,
            title="Renamed" if with_title else None,
        ),
    )
    assert updated["history"]["outcome"] == "applied"
    assert _archived_at(runtime.work_engine, principal, task_id) is not None
    events = feed(runtime.work_engine, principal)
    assert len(events) == 2
    event = events[1]
    assert event["record_id"] == task_id
    assert event["event_kind"] == "updated"
    assert event["changed_fields"] == (["archived_at", "title"] if with_title else ["archived_at"])
    assert event["record_version"] == 2
    assert event["source_capability"] == "tasks.update"
    assert event["source_receipt_id"] == updated["history"]["history_id"]
    assert next_sequence(runtime.work_engine, principal) == (before_sequence or 0) + 1


# ---- (b) archiving an already archived Task ----------------------------------


def test_update_archived_true_on_an_archived_task_is_a_no_op_and_stages_nothing(
    runtime: Runtime, principal: str
) -> None:
    task_id = _create(runtime, principal, "cp08b-b-create")
    _archive_via_update(runtime, principal, task_id, "cp08b-b-archive")
    stamp = _archived_at(runtime.work_engine, principal, task_id)
    before = _state(runtime.work_engine, principal)
    again = _update(
        runtime,
        principal,
        UpdateTask(
            task_id=task_id, expected_version=2, idempotency_key="cp08b-b-again", archived=True
        ),
    )
    assert again["history"]["outcome"] == "no_op"
    assert again["task"]["version"] == 2
    assert _archived_at(runtime.work_engine, principal, task_id) == stamp
    assert _state(runtime.work_engine, principal) == before


# ---- standalone Task unit of work: archive() / unarchive() -------------------


class _TickingClock:
    """One second later on every call, so a re-stamp is always observable."""

    def __init__(self) -> None:
        self._now = WHEN

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


@dataclass
class Standalone:
    engine: Engine
    service: TaskManagementService
    principal: str

    def create(self) -> str:
        receipt = self.service.create_task(
            principal_id=self.principal,
            title="Standalone archive",
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
            actor=TaskMutationActor.PRINCIPAL,
        )
        return receipt.task.task_id

    def state(self) -> tuple[list[dict[str, Any]], int | None]:
        return _state(self.engine, self.principal)


@pytest.fixture
def standalone(disposable_database: str, principal: str) -> Iterator[Standalone]:
    engine = create_database_engine(disposable_database)
    try:
        yield Standalone(
            engine=engine,
            service=TaskManagementService(
                unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(engine),
                clock=_TickingClock(),
            ),
            principal=principal,
        )
    finally:
        engine.dispose()


def test_archive_names_archived_at_at_the_next_version(standalone: Standalone) -> None:
    task_id = standalone.create()
    receipt = standalone.service.archive(
        principal_id=standalone.principal,
        task_id=task_id,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="cp08b-archive-0001",
    )
    assert receipt.history.outcome is TaskMutationOutcome.APPLIED
    events, sequence = standalone.state()
    assert len(events) == 2
    event = events[1]
    assert event["record_id"] == task_id
    assert event["event_kind"] == "updated"
    assert event["changed_fields"] == ["archived_at"]
    assert event["record_version"] == 2
    assert event["source_capability"] == "tasks.update"
    assert event["source_receipt_id"] == receipt.history.history_id
    assert sequence == 3


def test_archive_of_an_archived_task_is_a_no_op_and_stages_nothing(
    standalone: Standalone,
) -> None:
    task_id = standalone.create()
    first = standalone.service.archive(
        principal_id=standalone.principal,
        task_id=task_id,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="cp08b-rearchive-0001",
    )
    assert first.history.outcome is TaskMutationOutcome.APPLIED
    before = standalone.state()
    again = standalone.service.archive(
        principal_id=standalone.principal,
        task_id=task_id,
        expected_version=2,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="cp08b-rearchive-0002",
    )
    assert again.history.outcome is TaskMutationOutcome.NO_OP
    assert again.task.version == 2
    assert again.task.archived_at == first.task.archived_at
    assert standalone.state() == before


# ---- (c) unarchive() and tasks.update archived=False --------------------------


def test_unarchive_names_archived_at_at_the_next_version(standalone: Standalone) -> None:
    task_id = standalone.create()
    standalone.service.archive(
        principal_id=standalone.principal,
        task_id=task_id,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
    )
    receipt = standalone.service.unarchive(
        principal_id=standalone.principal,
        task_id=task_id,
        expected_version=2,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="cp08b-unarchive-0001",
    )
    assert receipt.history.outcome is TaskMutationOutcome.APPLIED
    assert receipt.task.archived_at is None
    events, sequence = standalone.state()
    assert len(events) == 3
    event = events[2]
    assert event["record_id"] == task_id
    assert event["event_kind"] == "updated"
    assert event["changed_fields"] == ["archived_at"]
    assert event["record_version"] == 3
    assert event["source_receipt_id"] == receipt.history.history_id
    assert sequence == 4


def test_update_archived_false_names_archived_at_at_the_next_version(
    runtime: Runtime, principal: str
) -> None:
    task_id = _create(runtime, principal, "cp08b-c-create")
    _archive_via_update(runtime, principal, task_id, "cp08b-c-archive")
    before_sequence = next_sequence(runtime.work_engine, principal)
    restored = _update(
        runtime,
        principal,
        UpdateTask(
            task_id=task_id, expected_version=2, idempotency_key="cp08b-c-restore", archived=False
        ),
    )
    assert restored["history"]["outcome"] == "applied"
    assert _archived_at(runtime.work_engine, principal, task_id) is None
    events = feed(runtime.work_engine, principal)
    assert len(events) == 3
    event = events[2]
    assert event["record_id"] == task_id
    assert event["event_kind"] == "updated"
    assert event["changed_fields"] == ["archived_at"]
    assert event["record_version"] == 3
    assert event["source_capability"] == "tasks.update"
    assert event["source_receipt_id"] == restored["history"]["history_id"]
    assert next_sequence(runtime.work_engine, principal) == (before_sequence or 0) + 1


# ---- (d) logical replays ------------------------------------------------------


@pytest.mark.parametrize("archived", [True, False], ids=["archive", "unarchive"])
def test_a_logical_update_replay_stages_nothing_and_advances_no_sequence(
    runtime: Runtime, principal: str, archived: bool
) -> None:
    task_id = _create(runtime, principal, f"cp08b-d-create-{archived}")
    expected_version = 1
    if not archived:
        _archive_via_update(runtime, principal, task_id, "cp08b-d-archive-first")
        expected_version = 2
    command = UpdateTask(
        task_id=task_id,
        expected_version=expected_version,
        idempotency_key=f"cp08b-d-update-{archived}",
        archived=archived,
    )
    first = _update(runtime, principal, command)
    assert first["history"]["outcome"] == "applied"
    before = _state(runtime.work_engine, principal)
    replay = _update(runtime, principal, command)
    assert replay["replayed"] is True
    assert replay["history"]["history_id"] == first["history"]["history_id"]
    assert _state(runtime.work_engine, principal) == before


def test_a_replay_of_the_archived_no_op_update_stages_nothing(
    runtime: Runtime, principal: str
) -> None:
    task_id = _create(runtime, principal, "cp08b-d-noop-create")
    _archive_via_update(runtime, principal, task_id, "cp08b-d-noop-archive")
    command = UpdateTask(
        task_id=task_id, expected_version=2, idempotency_key="cp08b-d-noop-again", archived=True
    )
    first = _update(runtime, principal, command)
    assert first["history"]["outcome"] == "no_op"
    before = _state(runtime.work_engine, principal)
    replay = _update(runtime, principal, command)
    assert replay["replayed"] is True
    assert replay["history"]["history_id"] == first["history"]["history_id"]
    assert _state(runtime.work_engine, principal) == before


@pytest.mark.parametrize("action", ["archive", "unarchive", "rearchive"])
def test_a_standalone_archive_replay_stages_nothing_and_advances_no_sequence(
    standalone: Standalone, action: str
) -> None:
    task_id = standalone.create()
    version = 1
    if action in {"unarchive", "rearchive"}:
        standalone.service.archive(
            principal_id=standalone.principal,
            task_id=task_id,
            expected_version=1,
            actor=TaskMutationActor.PRINCIPAL,
        )
        version = 2
    method = standalone.service.unarchive if action == "unarchive" else standalone.service.archive
    first = method(
        principal_id=standalone.principal,
        task_id=task_id,
        expected_version=version,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=f"cp08b-d-standalone-{action}",
    )
    assert first.history.outcome is (
        TaskMutationOutcome.NO_OP if action == "rearchive" else TaskMutationOutcome.APPLIED
    )
    before = standalone.state()
    replay = method(
        principal_id=standalone.principal,
        task_id=task_id,
        expected_version=version,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=f"cp08b-d-standalone-{action}",
    )
    assert replay.replayed is True
    assert replay.history.history_id == first.history.history_id
    assert standalone.state() == before


# ---- (e) tasks.bulk_confirm archived members ----------------------------------


def _bulk_archive(task_id: str, expected_version: int, archived: bool) -> dict[str, object]:
    return {
        "kind": "update",
        "task_id": task_id,
        "expected_version": expected_version,
        "values": {"archived": archived},
        "clear_fields": [],
    }


def test_bulk_confirm_archive_names_archived_at_and_skips_an_already_archived_member(
    runtime: Runtime, principal: str
) -> None:
    fresh = _create(runtime, principal, "cp08b-e-fresh")
    archived = _create(runtime, principal, "cp08b-e-archived")
    restore = _create(runtime, principal, "cp08b-e-restore")
    _archive_via_update(runtime, principal, archived, "cp08b-e-archived-first")
    _archive_via_update(runtime, principal, restore, "cp08b-e-restore-first")
    stamp = _archived_at(runtime.work_engine, principal, archived)
    mutations = (
        _bulk_archive(fresh, 1, True),
        _bulk_archive(archived, 2, True),
        _bulk_archive(restore, 2, False),
    )
    bulk = runtime.ok(
        BulkPreviewTasks(mutations=mutations, idempotency_key="cp08b-e-preview"),
        principal_id=principal,
    )["bulk_operation_id"]
    before_events, before_sequence = _state(runtime.work_engine, principal)
    confirm = BulkConfirmTasks(
        bulk_operation_id=bulk, idempotency_key="cp08b-e-confirm", mutations=mutations
    )
    confirmed = runtime.ok(confirm, principal_id=principal)
    assert confirmed["affected"] == 2 and confirmed["no_op"] == 1
    assert _archived_at(runtime.work_engine, principal, archived) == stamp
    events = feed(runtime.work_engine, principal)[len(before_events) :]
    assert [event["record_id"] for event in events] == [fresh, restore]
    assert [event["event_kind"] for event in events] == ["updated", "updated"]
    assert [event["changed_fields"] for event in events] == [["archived_at"], ["archived_at"]]
    assert [event["record_version"] for event in events] == [2, 3]
    assert {event["source_capability"] for event in events} == {"tasks.bulk_confirm"}
    assert next_sequence(runtime.work_engine, principal) == (before_sequence or 0) + 2
    after = _state(runtime.work_engine, principal)
    replay = runtime.ok(confirm, principal_id=principal)
    assert replay["replayed"] is True
    assert _state(runtime.work_engine, principal) == after
