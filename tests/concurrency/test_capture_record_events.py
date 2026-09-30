"""T-21, T-22, T-25 (WP-RE-08): Capture Record Events under concurrency (RE-AC-095).

Marked `database` (auto `database_clone`: every test runs several connections)
and `recovery`, so it is routed to `database-recovery`. Writes go through the
production `ApplicationService` over the general unit of work (U1).

The interleavings are forced, not hoped for: a `Pause` holds the first
transaction open immediately after a chosen statement, the second transaction is
started and observed blocked in PostgreSQL (`pg_stat_activity`), and only then
is the first released. Every connection carries a `lock_timeout`, so a lock this
module does not expect fails loudly; a deadlock (40P01) or a lock timeout in any
unmutated run here is stop N14 (N27).

* **T-21** -- two revises of one head: the first inserts its version and waits;
  the second reads the same head and blocks on the unique version index; once
  the first commits, the second is refused with `internal_error` (the unique
  violation -> `RepositoryFailureError` -> `InternalError`), commits no version
  and no event, and advances no sequence. Exactly one version and one `updated`
  event commit.
* **T-22** -- two creates under one idempotency key: the second blocks on the
  first's uncommitted submission key and then replays; one capture, one
  `created` event.
* **T-25** -- a Project-bound capture create and that Project's update, in both
  orders: the capture's foreign-key share lock and `lock_project`'s row lock
  serialize, both commit, and the feed is gap-free with one batch each.

Every identity and text here is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, select, text
from tests.concurrency.test_meeting_writes import _wait_until_blocked
from tests.database.test_task_record_events import Runtime, assert_gap_free, feed, next_sequence

from my_pa.application.commands import (
    Command,
    CreateCapture,
    CreateProject,
    ReviseCapture,
    UpdateProject,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import capture_versions

pytestmark = [pytest.mark.database, pytest.mark.recovery]

LOCK_TIMEOUT: Final = "20s"
JOIN_TIMEOUT_SECONDS: Final = 60.0
NOTE: Final = "Synthetic wp08 concurrency note"


class Pause:
    """Hold the armed thread's transaction open right after one statement.

    Armed from inside the worker thread, so the other thread's identical
    statements pass straight through. `reached` says the statement ran;
    `release` lets the transaction continue to its commit.
    """

    def __init__(self, engine: Engine, statement_prefix: str) -> None:
        self._prefix = statement_prefix
        self._owner: int | None = None
        self.reached = threading.Event()
        self.release = threading.Event()
        event.listen(engine, "after_cursor_execute", self._after)

    def arm(self) -> None:
        self._owner = threading.get_ident()

    def _after(self, *args: Any) -> None:  # noqa: ANN401
        statement = str(args[2])
        if self._owner == threading.get_ident() and statement.lstrip().startswith(self._prefix):
            self._owner = None
            self.reached.set()
            if not self.release.wait(JOIN_TIMEOUT_SECONDS):
                raise AssertionError("the paused transaction was never released")


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)

    @event.listens_for(composed.work_engine, "connect")
    def _impatient(dbapi_connection: object, _record: object) -> None:
        with dbapi_connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")

    try:
        yield composed
    finally:
        composed.close()


def race(
    runtime: Runtime,
    pause: Pause,
    first: Callable[[], ResponseEnvelope],
    second: Callable[[], ResponseEnvelope],
) -> tuple[ResponseEnvelope, ResponseEnvelope]:
    """Run `first` to its paused statement, block `second` behind it, then release."""

    def armed() -> ResponseEnvelope:
        pause.arm()
        return first()

    with ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(armed)
        assert pause.reached.wait(JOIN_TIMEOUT_SECONDS), "the first transaction never paused"
        waiting = pool.submit(second)
        try:
            _wait_until_blocked(runtime.work_engine, waiting)
        finally:
            pause.release.set()
        return held.result(timeout=JOIN_TIMEOUT_SECONDS), waiting.result(
            timeout=JOIN_TIMEOUT_SECONDS
        )


def ok(response: ResponseEnvelope) -> dict[str, Any]:
    """Stop N14 surfaces here: a deadlock or a lock timeout is an error envelope."""
    assert response.error is None, f"STOP N14 candidate or refusal: {response.error}"
    assert response.result is not None
    return response.result


def batches(engine: Engine, principal: str) -> list[list[dict[str, Any]]]:
    """Every committing transaction's events, each one contiguous run of the feed."""
    assert_gap_free(engine, principal)
    with engine.connect() as connection:
        writer = dict(
            connection.execute(
                text(
                    "SELECT event_id, xmin::text FROM knowledge.record_events "
                    "WHERE principal_id = :p"
                ),
                {"p": principal},
            ).all()
        )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in feed(engine, principal):
        grouped.setdefault(writer[item["event_id"]], []).append(item)
    for events in grouped.values():
        numbers = [item["sequence_number"] for item in events]
        assert numbers == list(range(numbers[0], numbers[0] + len(numbers))), numbers
    return sorted(grouped.values(), key=lambda events: events[0]["sequence_number"])


def _invoke(runtime: Runtime, principal: str, command: Command) -> Callable[[], ResponseEnvelope]:
    return lambda: runtime.invoke(command, principal_id=principal)


def _captures(engine: Engine, principal: str) -> list[dict[str, Any]]:
    return [e for e in feed(engine, principal) if e["record_family"] == "capture"]


# ---- T-21 -------------------------------------------------------------------


def test_two_revises_of_one_head_commit_one_version_and_one_event(runtime: Runtime) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    capture_id = str(
        ok(
            runtime.invoke(
                CreateCapture(text=NOTE, idempotency_key="wp08-t21-seed"), principal_id=principal
            )
        )["capture_id"]
    )
    before_sequence = next_sequence(runtime.work_engine, principal)
    pause = Pause(runtime.work_engine, "INSERT INTO knowledge.capture_versions")
    winner, loser = race(
        runtime,
        pause,
        _invoke(
            runtime,
            principal,
            ReviseCapture(capture_id=capture_id, text="First revise", idempotency_key="wp08-t21-a"),
        ),
        _invoke(
            runtime,
            principal,
            ReviseCapture(
                capture_id=capture_id, text="Second revise", idempotency_key="wp08-t21-b"
            ),
        ),
    )
    won = ok(winner)
    assert won["version_number"] == 2
    # Unverified item 1, proved by behaviour: the loser's version insert meets
    # the winner's committed row on the unique index and is refused as
    # `internal_error` -- not `unavailable`, which is what a lock timeout is.
    assert loser.error is not None
    assert loser.error.code is ErrorCode.INTERNAL_ERROR, loser.error
    with runtime.work_engine.connect() as connection:
        numbers = list(
            connection.execute(
                select(capture_versions.c.version_number)
                .where(capture_versions.c.capture_id == capture_id)
                .order_by(capture_versions.c.version_number)
            ).scalars()
        )
    assert numbers == [1, 2]
    created, updated = _captures(runtime.work_engine, principal)
    assert (created["event_kind"], updated["event_kind"]) == ("created", "updated")
    assert updated["record_version"] == 2
    assert updated["source_receipt_id"] == won["receipt_id"]
    assert next_sequence(runtime.work_engine, principal) == (before_sequence or 1) + 1
    batches(runtime.work_engine, principal)


# ---- T-22 -------------------------------------------------------------------


def test_two_creates_under_one_key_commit_one_capture_and_one_event(runtime: Runtime) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    command = CreateCapture(text=NOTE, idempotency_key="wp08-t22-key")
    pause = Pause(runtime.work_engine, "INSERT INTO knowledge.capture_submissions")
    first, second = race(
        runtime, pause, _invoke(runtime, principal, command), _invoke(runtime, principal, command)
    )
    made, replayed = ok(first), ok(second)
    assert made["created"] is True
    assert replayed["created"] is False
    assert replayed["receipt_id"] == made["receipt_id"]
    events = _captures(runtime.work_engine, principal)
    assert len(events) == 1, events
    assert events[0]["record_id"] == made["capture_id"]
    assert next_sequence(runtime.work_engine, principal) == 2


# ---- T-25 -------------------------------------------------------------------


@pytest.mark.parametrize("first_writer", ["project_update", "capture_create"])
def test_a_project_bound_capture_and_a_project_update_do_not_deadlock(
    runtime: Runtime, first_writer: str
) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    project = ok(
        runtime.invoke(
            CreateProject(name="Synthetic wp08 T-25 project", idempotency_key="wp08-t25-prj"),
            principal_id=principal,
        )
    )
    capture = _invoke(
        runtime,
        principal,
        CreateCapture(text=NOTE, idempotency_key="wp08-t25-cap", project_id=project["project_id"]),
    )
    update = _invoke(
        runtime,
        principal,
        UpdateProject(
            project_id=project["project_id"],
            expected_version=1,
            idempotency_key="wp08-t25-upd",
            name="Synthetic wp08 T-25 renamed",
        ),
    )
    if first_writer == "project_update":
        pause = Pause(runtime.work_engine, "UPDATE knowledge.projects")
        held, waited = race(runtime, pause, update, capture)
    else:
        pause = Pause(runtime.work_engine, "INSERT INTO knowledge.captures")
        held, waited = race(runtime, pause, capture, update)
    ok(held)
    ok(waited)
    families = [
        [e["record_family"] for e in batch] for batch in batches(runtime.work_engine, principal)
    ]
    # The Project create's batch, then one batch per racing writer.
    assert families[0] == ["project", "entity"]
    assert sorted(tuple(batch) for batch in families[1:]) == [("capture",), ("project",)]
