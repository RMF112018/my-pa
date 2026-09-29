"""T-14 (WP-RE-02): `tasks.bulk_confirm` Record Events, alone and under contention.

RE-AC-024: a bulk confirm commits exactly one event per APPLIED member, in
`mutations` order, and none for a no-op member. Marked `database` (auto
`database_clone`: the race uses several connections), routed to
`database-current-head`.

The race runs `tasks.bulk_confirm` against a concurrent `tasks.update` of one of
its members, several times. Whichever wins, the committed feed must equal the
committed APPLIED history receipts one for one, stay gap-free, and neither side
may fail with a deadlock (40P01) or a lock timeout -- that would be stop N14.
Every identity here is synthetic.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Final

import pytest
from sqlalchemy import select

from my_pa.application.commands import (
    BulkConfirmTasks,
    BulkPreviewTasks,
    CreateTask,
    UpdateTask,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.persistence.tables import task_history
from tests.database.test_task_record_events import Runtime, assert_gap_free, feed, runtime

__all__ = ["runtime"]

pytestmark = pytest.mark.database

JOIN_TIMEOUT_SECONDS: Final = 60.0
ROUNDS: Final = 4


def _task(runtime: Runtime, key: str) -> str:
    created = runtime.ok(
        CreateTask(
            title=f"Task {key}", idempotency_key=key, origin_kind=TaskOriginKind.DIRECT_PRINCIPAL
        )
    )
    return str(created["task"]["task_id"])


def _update(task_id: str, title: str) -> dict[str, object]:
    return {
        "kind": "update",
        "task_id": task_id,
        "expected_version": 1,
        "values": {"title": title},
        "clear_fields": [],
    }


def _preview(runtime: Runtime, mutations: tuple[dict[str, object], ...], key: str) -> str:
    return str(
        runtime.ok(BulkPreviewTasks(mutations=mutations, idempotency_key=key))["bulk_operation_id"]
    )


def _applied_receipts(runtime: Runtime) -> set[str]:
    with runtime.work_engine.connect() as connection:
        return set(
            connection.execute(
                select(task_history.c.history_id).where(task_history.c.outcome == "applied")
            ).scalars()
        )


def test_bulk_confirm_commits_one_event_per_applied_member_in_mutation_order(
    runtime: Runtime,
) -> None:
    first, second, unchanged = (_task(runtime, f"wp02-bulk-{n}") for n in ("a", "b", "c"))
    mutations = (
        _update(second, "Second, bulk"),
        _update(unchanged, "Task wp02-bulk-c"),
        _update(first, "First, bulk"),
    )
    bulk = _preview(runtime, mutations, "wp02-bulk-preview-0001")
    before = len(feed(runtime.work_engine))
    confirmed = runtime.ok(
        BulkConfirmTasks(
            bulk_operation_id=bulk, idempotency_key="wp02-bulk-confirm-0001", mutations=mutations
        )
    )
    assert confirmed["affected"] == 2 and confirmed["no_op"] == 1
    events = feed(runtime.work_engine)[before:]
    assert [event["record_id"] for event in events] == [second, first]
    assert {event["source_capability"] for event in events} == {"tasks.bulk_confirm"}
    assert [event["changed_fields"] for event in events] == [["title"], ["title"]]
    assert [event["record_version"] for event in events] == [2, 2]
    history_ids = set(confirmed["history_ids"])
    assert {event["source_receipt_id"] for event in events} < history_ids
    assert_gap_free(runtime.work_engine)
    replay = runtime.ok(
        BulkConfirmTasks(
            bulk_operation_id=bulk, idempotency_key="wp02-bulk-confirm-0001", mutations=mutations
        )
    )
    assert replay["replayed"] is True
    assert len(feed(runtime.work_engine)) == before + 2


def _race(runtime: Runtime, round_: int) -> list[ResponseEnvelope]:
    """One round: `tasks.bulk_confirm` of two Tasks against `tasks.update` of one."""
    first = _task(runtime, f"wp02-race-{round_}-a")
    second = _task(runtime, f"wp02-race-{round_}-b")
    mutations = (_update(first, f"Bulk {round_} a"), _update(second, f"Bulk {round_} b"))
    bulk = _preview(runtime, mutations, f"wp02-race-{round_}-preview")
    barrier = threading.Barrier(2, timeout=JOIN_TIMEOUT_SECONDS)

    def confirm() -> ResponseEnvelope:
        barrier.wait()
        return runtime.invoke(
            BulkConfirmTasks(
                bulk_operation_id=bulk,
                idempotency_key=f"wp02-race-{round_}-confirm",
                mutations=mutations,
            )
        )

    def update() -> ResponseEnvelope:
        barrier.wait()
        return runtime.invoke(
            UpdateTask(
                task_id=second,
                expected_version=1,
                idempotency_key=f"wp02-race-{round_}-update",
                title=f"Direct {round_}",
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        return [
            future.result(timeout=JOIN_TIMEOUT_SECONDS)
            for future in (pool.submit(confirm), pool.submit(update))
        ]


def test_bulk_confirm_against_a_concurrent_update_never_deadlocks(runtime: Runtime) -> None:
    for round_ in range(ROUNDS):
        errors = [outcome.error for outcome in _race(runtime, round_) if outcome.error]
        # Exactly one side wins task `second`; the loser is a typed conflict,
        # never a deadlock or a lock timeout (which would surface as a
        # non-conflict error here).
        assert len(errors) == 1, errors
        assert errors[0].code is ErrorCode.CONFLICT, errors
    events = feed(runtime.work_engine)
    assert {event["source_receipt_id"] for event in events} == _applied_receipts(runtime)
    assert len(events) == len(_applied_receipts(runtime))
    assert_gap_free(runtime.work_engine)
