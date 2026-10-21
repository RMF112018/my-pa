"""AT-012 (races, two connections): lineage writes and native writers serialize (S1).

S1 contract sections 3.2, 4.3 and 6.2 against PostgreSQL. Every case runs the
lineage write through `ApplicationService.invoke` and the native side on a
second connection (raw SQL, or a native capability), waits until PostgreSQL
reports the expected waiters, and only then lets the first side finish:

* a native delete waiting on a membership's `FOR SHARE` is refused by
  `a_linked_record_is_not_deleted` once the membership commits;
* a membership waiting on a committed native delete answers `not_found`, and
  proceeds when the delete rolls back;
* a Task archive and a Capture archive racing a membership serialize: either
  the link and then the archive, or the archive and then a refusal with no row;
* a deadlock the lineage side loses answers `conflict` and writes nothing;
* the native side of a lineage deadlock is recorded as observed (the section
  6.2 residual: native writers are not routed through `is_transaction_conflict`).

Each lock wait is bounded by the statement timeout and each thread is joined
with a timeout, so a build that takes no lock reports rather than hangs. The
deadlock cases set `deadlock_timeout` per session (the test role is the
cluster superuser, as in CI) so which side PostgreSQL aborts is deterministic.
Every identity here is synthetic.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from tests.database.lineage_issue_harness import PRINCIPAL, LineageRuntime
from tests.database.lineage_record_harness import (
    GATEWAY,
    NOTE_BODY,
    all_lineage_counts,
    capture,
    capture_anchor,
    membership,
    task,
)

from my_pa.application.commands import ArchiveCapture, UpdateTask
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.lineage.canonical import normalized_identity
from my_pa.domain.lineage.model import RecordRef
from my_pa.domain.lineage.vocabulary import MemberRole, RecordFamily, RecordLinkKind, RelationType
from my_pa.infrastructure.persistence.record_lineage import LINEAGE_ADVISORY_NAMESPACE

pytestmark = pytest.mark.database

BLOCK_DEADLINE_SECONDS: Final = 15.0
JOIN_TIMEOUT_SECONDS: Final = 60.0


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[LineageRuntime]:
    composed = LineageRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _waiting(engine: Engine) -> int:
    with engine.connect() as observer:
        return int(
            observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
        )


def _wait_for(engine: Engine, waiters: int, futures: list[Future[Any]]) -> None:
    deadline = time.monotonic() + BLOCK_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        assert not any(future.done() for future in futures), "a side did not wait"
        if _waiting(engine) >= waiters:
            return
        time.sleep(0.02)
    pytest.fail("the expected sides never blocked")


def _member_identity(issue_id: str, task_id: str, role: MemberRole) -> str:
    return normalized_identity(
        kind=RecordLinkKind.ISSUE_MEMBERSHIP,
        relation_type=RelationType.ISSUE_MEMBER,
        from_ref=RecordRef(family=RecordFamily.SITUATION, record_id=issue_id),
        to_ref=RecordRef(family=RecordFamily.TASK, record_id=task_id),
        member_role=role,
        context_issue_id=issue_id,
    )


def _hold_identity(connection: Connection, identity: str) -> None:
    connection.execute(
        text(
            "SELECT pg_advisory_xact_lock(CAST(:namespace AS integer), "
            "hashtext(CAST(:principal AS text) || ':' || CAST(:identity AS text)))"
        ),
        {"namespace": LINEAGE_ADVISORY_NAMESPACE, "principal": PRINCIPAL, "identity": identity},
    )


def _delete_task(connection: Connection, task_id: str) -> None:
    """The native delete: the Task's history, then the Task (no capability deletes one)."""
    connection.execute(
        text("DELETE FROM knowledge.task_history WHERE task_id = :id"), {"id": task_id}
    )
    connection.execute(text("DELETE FROM knowledge.tasks WHERE task_id = :id"), {"id": task_id})


def _member(issue: str, task_id: str, key: str) -> Callable[[LineageRuntime], ResponseEnvelope]:
    return lambda runtime: runtime.invoke(
        membership(issue, "task", task_id, key, role="work"), surface=GATEWAY
    )


def _error(envelope: ResponseEnvelope) -> dict[str, Any] | None:
    error = envelope.to_canonical_dict().get("error")
    assert error is None or isinstance(error, dict)
    return error


def _set_deadlock_timeout(engine: Engine, value: str) -> None:
    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection: Any, _record: Any) -> None:  # noqa: ANN401
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET deadlock_timeout = '{value}'")
        cursor.close()


def test_a_native_delete_waiting_on_an_assert_is_refused_after_the_assert_commits(
    runtime: LineageRuntime,
) -> None:
    issue = runtime.issue("race-delete-wait")
    task_id = task(runtime, "race-delete-wait")
    identity = _member_identity(issue, task_id, MemberRole.WORK)

    def native() -> str:
        with runtime.engine.connect() as connection:
            try:
                with connection.begin():
                    _delete_task(connection, task_id)
            except DBAPIError as error:
                return str(error.orig)
        return "deleted"

    with runtime.engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as pool:
        held = holder.begin()
        _hold_identity(holder, identity)
        lineage = pool.submit(_member(issue, task_id, "race-delete-wait"), runtime)
        # The membership holds the Task `FOR SHARE` and waits on the identity lock.
        _wait_for(runtime.engine, 1, [lineage])
        deleting = pool.submit(native)
        _wait_for(runtime.engine, 2, [lineage, deleting])
        held.rollback()
        answer = lineage.result(timeout=JOIN_TIMEOUT_SECONDS)
        outcome = deleting.result(timeout=JOIN_TIMEOUT_SECONDS)
    assert _error(answer) is None
    assert "a task a record link names is never deleted" in outcome


def test_an_assert_waiting_on_a_native_delete_answers_not_found_after_the_delete_commits(
    runtime: LineageRuntime,
) -> None:
    issue = runtime.issue("race-delete-first")
    task_id = task(runtime, "race-delete-first")
    before = all_lineage_counts(runtime.engine)
    with runtime.engine.connect() as native, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = native.begin()
        _delete_task(native, task_id)
        lineage = pool.submit(_member(issue, task_id, "race-delete-first"), runtime)
        _wait_for(runtime.engine, 1, [lineage])
        transaction.commit()
        answer = lineage.result(timeout=JOIN_TIMEOUT_SECONDS)
    error = _error(answer)
    assert error is not None and error["code"] == "not_found"
    assert error["safe_details"] == ["member"]
    assert all_lineage_counts(runtime.engine) == before


def test_an_assert_proceeds_after_a_native_delete_rolls_back(runtime: LineageRuntime) -> None:
    issue = runtime.issue("race-delete-undone")
    task_id = task(runtime, "race-delete-undone")
    with runtime.engine.connect() as native, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = native.begin()
        _delete_task(native, task_id)
        lineage = pool.submit(_member(issue, task_id, "race-delete-undone"), runtime)
        _wait_for(runtime.engine, 1, [lineage])
        transaction.rollback()
        answer = lineage.result(timeout=JOIN_TIMEOUT_SECONDS)
    assert _error(answer) is None
    assert answer.to_canonical_dict()["result"]["created"] is True


def _race_with_holder(
    runtime: LineageRuntime, hold: str, parameters: dict[str, str], writers: list[Callable[[], Any]]
) -> list[ResponseEnvelope]:
    with runtime.engine.connect() as holder, ThreadPoolExecutor(max_workers=len(writers)) as pool:
        held = holder.begin()
        holder.execute(text(hold), parameters)
        futures = [pool.submit(writer) for writer in writers]
        _wait_for(runtime.engine, len(writers), futures)
        held.rollback()
        return [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures]


def test_task_archive_racing_a_membership_add_serializes(runtime: LineageRuntime) -> None:
    issue = runtime.issue("race-archive")
    task_id = task(runtime, "race-archive")
    before = all_lineage_counts(runtime.engine)
    archive, member = _race_with_holder(
        runtime,
        "SELECT task_id FROM knowledge.tasks WHERE task_id = :id FOR UPDATE",
        {"id": task_id},
        [
            lambda: runtime.invoke(
                UpdateTask(
                    task_id=task_id,
                    expected_version=1,
                    idempotency_key="lineage-race-archive-task",
                    archived=True,
                )
            ),
            lambda: _member(issue, task_id, "race-archive")(runtime),
        ],
    )
    assert _error(archive) is None, "the archive is a native write and always lands"
    member_error = _error(member)
    counts = all_lineage_counts(runtime.engine)
    if member_error is None:
        # The membership won the row first; the archive followed it.
        assert counts["record_links"] == 1
    else:
        assert member_error["code"] == "invalid_request"
        assert member_error["safe_details"] == ["endpoint"]
        assert counts == before


def test_capture_archive_racing_a_capture_anchor_serializes(runtime: LineageRuntime) -> None:
    issue = runtime.issue("race-capture")
    root, version, _ = capture(runtime, "race-capture")
    task_id = task(runtime, "race-capture")
    before = all_lineage_counts(runtime.engine)
    archive, member = _race_with_holder(
        runtime,
        "SELECT capture_id FROM knowledge.captures WHERE capture_id = :id FOR UPDATE",
        {"id": root},
        [
            lambda: runtime.invoke(
                ArchiveCapture(
                    capture_id=root,
                    expected_lifecycle_revision=0,
                    idempotency_key="lineage-race-capture-archive",
                    reason="synthetic archive",
                )
            ),
            lambda: runtime.invoke(
                membership(
                    issue,
                    "task",
                    task_id,
                    "race-capture",
                    anchors=(capture_anchor(root, version, NOTE_BODY, role="corroborates"),),
                ),
                surface=GATEWAY,
            ),
        ],
    )
    assert _error(archive) is None
    member_error = _error(member)
    counts = all_lineage_counts(runtime.engine)
    if member_error is None:
        assert counts["lineage_evidence_anchors"] == 1
    else:
        assert member_error["code"] == "denied"
        assert member_error["safe_details"] == ["capture_withdrawn"]
        assert counts == before


def _deadlock(
    runtime: LineageRuntime, *, native_timeout: str, key: str
) -> tuple[ResponseEnvelope, str]:
    """Native: Task `FOR UPDATE`, then the Issue row. Lineage: Issue `FOR SHARE`, then Task.

    The membership shares the Issue (`situation` sorts before `task`) and waits
    on the Task the native side holds; the native side then updates the Issue
    and waits on the membership's share. PostgreSQL breaks the cycle on the
    side whose `deadlock_timeout` expires first.
    """
    issue = runtime.issue(key)
    task_id = task(runtime, key)

    def native_second_step(connection: Connection) -> str:
        try:
            connection.execute(
                text(
                    "UPDATE knowledge.situations SET version = version + 1 WHERE situation_id = :id"
                ),
                {"id": issue},
            )
        except DBAPIError as error:
            return str(getattr(error.orig, "sqlstate", "") or "")
        return "updated"

    with runtime.engine.connect() as native, ThreadPoolExecutor(max_workers=2) as pool:
        transaction = native.begin()
        native.execute(text(f"SET LOCAL deadlock_timeout = '{native_timeout}'"))
        native.execute(
            text("SELECT task_id FROM knowledge.tasks WHERE task_id = :id FOR UPDATE"),
            {"id": task_id},
        )
        lineage = pool.submit(_member(issue, task_id, key), runtime)
        _wait_for(runtime.engine, 1, [lineage])
        second = pool.submit(native_second_step, native)
        answer = lineage.result(timeout=JOIN_TIMEOUT_SECONDS)
        native_outcome = second.result(timeout=JOIN_TIMEOUT_SECONDS)
        transaction.rollback()
    return answer, native_outcome


def test_a_lineage_deadlock_answers_conflict_and_writes_nothing(runtime: LineageRuntime) -> None:
    _set_deadlock_timeout(runtime.engine, "1s")
    before = all_lineage_counts(runtime.engine)
    answer, native = _deadlock(runtime, native_timeout="30s", key="race-deadlock-lineage")
    error = _error(answer)
    assert error is not None and error["code"] == "conflict"
    assert native == "updated", "the native side wins once the lineage side is aborted"
    after = all_lineage_counts(runtime.engine)
    # Only the seeded Issue's revision was written; the membership left nothing.
    assert after["record_links"] == before["record_links"]
    assert after["lineage_write_requests"] == before["lineage_write_requests"] + 1


def test_the_native_side_of_a_lineage_deadlock_is_recorded(runtime: LineageRuntime) -> None:
    """Residual pin (section 6.2): the native side surfaces the raw deadlock.

    No S1 change routes native writers through `is_transaction_conflict`, so a
    native writer that loses a lineage deadlock sees the driver's `40P01`
    (`deadlock_detected`) rather than a classified conflict. The lineage write
    that survives commits. Fixing the native side is a separate work package.
    """
    _set_deadlock_timeout(runtime.engine, "30s")
    answer, native = _deadlock(runtime, native_timeout="1s", key="race-deadlock-native")
    assert native == "40P01"
    assert _error(answer) is None
    assert answer.to_canonical_dict()["result"]["created"] is True
