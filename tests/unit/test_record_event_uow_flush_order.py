"""T-01 (WP-RE-01): every SQL unit of work flushes Record Events in the right place.

RE-AC-012..017, the no-database half. Each of the four transaction owners --
U1 `SqlAlchemyUnitOfWork`, U2 `SqlAlchemyTaskManagementUnitOfWork`, U3
`SqlAlchemyCommitmentManagementUnitOfWork`, U4
`SqlAlchemyConstraintManagementUnitOfWork` -- is driven over a recording fake
engine, and the recorded call order is the claim:

* a successful block with staged drafts runs `allocate`, then one insert per
  draft in stage order, then `context.__exit__` (the COMMIT) -- the flush is the
  last database work, and it happens while the connection is still held;
* a block that raised runs neither the allocator nor an insert, and rolls back;
* an empty buffer never touches the allocator;
* a flush failure is handed to `context.__exit__` as the exception (so the
  transaction rolls back with the canonical change) and re-raised translated;
* the buffer is empty after every exit, and reset by the next `__enter__`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Final, cast

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.sql.dml import Insert

from my_pa.contracts.ports import (
    AuditSink,
    EvidenceUnavailableError,
    RepositoryFailureError,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

PRINCIPAL: Final = "prn_flushorder0001"
OTHER_PRINCIPAL: Final = "prn_flushorder0002"
WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)


class _Result:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _Connection:
    """Records each statement by the table it writes; answers the allocator."""

    def __init__(self, log: list[tuple[str, Any]], fail_on: str | None, error: Exception) -> None:
        self._log = log
        self._fail_on = fail_on
        self._error = error

    def execute(self, statement: Insert, *args: object) -> _Result:
        table = statement.table.name
        kind = {"record_event_sequences": "allocate", "record_events": "insert"}[table]
        if kind == "insert":
            params = statement.compile().params
            self._log.append(("insert", (params["event_id"], params["sequence_number"])))
        else:
            self._log.append(("allocate", None))
        if kind == self._fail_on:
            raise self._error
        return _Result(41)


class _Context:
    def __init__(self, connection: _Connection, log: list[tuple[str, Any]]) -> None:
        self._connection = connection
        self._log = log

    def __enter__(self) -> _Connection:
        self._log.append(("begin", None))
        return self._connection

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self._log.append(("context.__exit__", exc_type))
        return False


class _Engine:
    def __init__(
        self,
        *,
        fail_on: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.log: list[tuple[str, Any]] = []
        self._fail_on = fail_on
        self._error = error or ProgrammingError("statement", {}, Exception("refused"))

    def begin(self) -> _Context:
        return _Context(_Connection(self.log, self._fail_on, self._error), self.log)


class _Audit(AuditSink):
    def record(self, event: object) -> None:  # type: ignore[override]
        del event


_Owner = (
    SqlAlchemyUnitOfWork
    | SqlAlchemyTaskManagementUnitOfWork
    | SqlAlchemyCommitmentManagementUnitOfWork
    | SqlAlchemyConstraintManagementUnitOfWork
)


def _u1(engine: Engine) -> _Owner:
    return SqlAlchemyUnitOfWork(engine, audit=_Audit())


OWNERS: Final[dict[str, Callable[[Engine], _Owner]]] = {
    "U1-generic": _u1,
    "U2-task": SqlAlchemyTaskManagementUnitOfWork,
    "U3-commitment": SqlAlchemyCommitmentManagementUnitOfWork,
    "U4-constraint": SqlAlchemyConstraintManagementUnitOfWork,
}


def _draft(principal_id: str = PRINCIPAL, *, cause: str | None = None) -> RecordEventDraft:
    return RecordEventDraft.issue(
        principal_id=principal_id,
        record_family=RecordEventFamily.TASK,
        record_id="tsk_flushorder0001",
        event_kind=RecordEventKind.UPDATED,
        record_version=2,
        changed_fields=("title",),
        source_capability="tasks.update",
        actor_class=RecordEventActorClass.PRINCIPAL,
        classification=Classification.PRIVATE_LOCAL,
        occurred_at=WHEN,
        causation_event_id=cause,
    )


def _owner(name: str, engine: _Engine) -> _Owner:
    return OWNERS[name](cast(Engine, engine))


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_a_successful_block_allocates_then_inserts_in_order_then_commits(name: str) -> None:
    engine = _Engine()
    unit = _owner(name, engine)
    first = _draft()
    second = _draft(cause=first.event_id)
    with unit:
        unit.record_events.stage(first)
        unit.record_events.stage(second)
        assert unit.record_events.pending_count == 2
    assert engine.log == [
        ("begin", None),
        ("allocate", None),
        ("insert", (first.event_id, 41)),
        ("insert", (second.event_id, 42)),
        ("context.__exit__", None),
    ]


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_a_block_that_raised_never_flushes_and_rolls_back(name: str) -> None:
    engine = _Engine()
    unit = _owner(name, engine)
    with pytest.raises(LookupError), unit:
        unit.record_events.stage(_draft())
        raise LookupError("the canonical write failed")
    assert engine.log == [("begin", None), ("context.__exit__", LookupError)]


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_an_empty_buffer_never_reaches_the_allocator(name: str) -> None:
    engine = _Engine()
    with _owner(name, engine):
        pass
    assert engine.log == [("begin", None), ("context.__exit__", None)]


@pytest.mark.parametrize("name", sorted(OWNERS))
@pytest.mark.parametrize("fail_on", ["allocate", "insert"])
def test_a_flush_failure_rolls_back_and_is_re_raised_translated(name: str, fail_on: str) -> None:
    engine = _Engine(fail_on=fail_on)
    unit = _owner(name, engine)
    with pytest.raises(RepositoryFailureError) as raised, unit:
        unit.record_events.stage(_draft())
    assert engine.log[-1] == ("context.__exit__", RepositoryFailureError)
    assert "statement" not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_an_unreachable_store_during_the_flush_is_evidence_unavailable(name: str) -> None:
    engine = _Engine(fail_on="allocate", error=OperationalError("statement", {}, Exception("gone")))
    unit = _owner(name, engine)
    with pytest.raises(EvidenceUnavailableError), unit:
        unit.record_events.stage(_draft())
    assert engine.log[-1] == ("context.__exit__", EvidenceUnavailableError)


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_a_buffer_holding_two_principals_is_refused_before_any_statement(name: str) -> None:
    engine = _Engine()
    unit = _owner(name, engine)
    with pytest.raises(RepositoryFailureError, match="exactly one Principal"), unit:
        unit.record_events.stage(_draft())
        unit.record_events.stage(_draft(OTHER_PRINCIPAL))
    assert engine.log == [("begin", None), ("context.__exit__", RepositoryFailureError)]


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_the_buffer_is_empty_after_every_exit_and_reset_on_enter(name: str) -> None:
    engine = _Engine()
    unit = _owner(name, engine)
    with pytest.raises(LookupError), unit:
        unit.record_events.stage(_draft())
        raise LookupError
    with unit:
        assert unit.record_events.pending_count == 0
    assert ("allocate", None) not in engine.log


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_the_buffer_is_unreachable_outside_a_transaction(name: str) -> None:
    unit = _owner(name, _Engine())
    with pytest.raises(RuntimeError, match="not inside a transaction"):
        _ = unit.record_events


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_the_flush_runs_while_the_connection_is_still_held(name: str) -> None:
    """G1-TX-001: the flush precedes the `_context`/`_connection` clear."""
    engine = _Engine()
    unit = _owner(name, engine)
    seen: list[object] = []
    original = _Connection.execute

    def spy(connection: _Connection, statement: Insert, *args: object) -> _Result:
        seen.append(unit._connection)
        return original(connection, statement, *args)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(_Connection, "execute", spy)
        with unit:
            unit.record_events.stage(_draft())
    assert seen
    assert all(connection is not None for connection in seen)
