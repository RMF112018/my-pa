"""WP-RE-01: the allocator and the unit-of-work flush on a real database.

Marked `database` (auto `database_clone`) and routed to `database-current-head`.
Sequential: the concurrent cases are `tests/concurrency/
test_record_event_allocator_concurrency.py`.

* **RE-AC-007** -- a Principal's first batch begins at 1.
* **RE-AC-008** -- a later batch begins at the prior `next_sequence`.
* **RE-AC-009** -- one batch is contiguous and inserted in stage order (a
  causation chain inside one batch satisfies the NOT DEFERRABLE reference).
* **RE-AC-011 / T-05** -- a failed transaction leaves no committed sequence
  advance: (i) the block raised after staging, (ii) an insert failed during the
  flush, (iii) a deferred check failed at COMMIT, after the flush.
* **RE-AC-012 / RE-AC-013 / T-06** -- both directions of RE-I-001: an event
  cannot outlive its canonical rollback, and a canonical change cannot commit
  without its event.
* **RE-AC-015..017** -- the Constraint (U4), Task (U2) and Commitment (U3)
  standalone units of work follow the same rule as U1.

The "canonical change" here is a `meeting_series` row written on the unit of
work's own connection: a real Principal-partitioned table, standing in for any
canonical write the emitters of WP-RE-02..05 will stage beside.

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Connection, Engine, func, insert, select, text
from sqlalchemy.exc import IntegrityError

from my_pa.contracts.ports import AuditSink, RepositoryFailureError
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.record_events import SqlRecordEventWriter
from my_pa.infrastructure.persistence.tables import (
    meeting_series,
    record_event_sequences,
    record_events,
)
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = [pytest.mark.database]

WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)


class _Audit(AuditSink):
    def record(self, event: object) -> None:  # type: ignore[override]
        del event


OWNERS: Final[dict[str, Callable[[Engine], Any]]] = {
    "U1-generic": lambda engine: SqlAlchemyUnitOfWork(engine, audit=_Audit()),
    "U2-task": SqlAlchemyTaskManagementUnitOfWork,
    "U3-commitment": SqlAlchemyCommitmentManagementUnitOfWork,
    "U4-constraint": SqlAlchemyConstraintManagementUnitOfWork,
}


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine


def _principal() -> str:
    return issue_identifier(IdKind.PRINCIPAL)


def _draft(
    principal_id: str, record_id: str | None = None, *, cause: str | None = None
) -> RecordEventDraft:
    return RecordEventDraft.issue(
        principal_id=principal_id,
        record_family=RecordEventFamily.MEETING_SERIES,
        record_id=record_id or issue_identifier(IdKind.MEETING_SERIES),
        event_kind=RecordEventKind.CREATED,
        record_version=1,
        changed_fields=("title",),
        source_capability="meetings.create",
        actor_class=RecordEventActorClass.PRINCIPAL,
        classification=Classification.PRIVATE_LOCAL,
        occurred_at=WHEN,
        causation_event_id=cause,
    )


def _canonical(connection: Connection, principal_id: str) -> str:
    """One canonical write on the unit of work's own connection."""
    series_id = issue_identifier(IdKind.MEETING_SERIES)
    connection.execute(
        insert(meeting_series).values(
            meeting_series_id=series_id,
            principal_id=principal_id,
            title="Synthetic series",
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return series_id


def _next_sequence(engine: Engine, principal_id: str) -> int | None:
    with engine.connect() as connection:
        return connection.execute(
            select(record_event_sequences.c.next_sequence).where(
                record_event_sequences.c.principal_id == principal_id
            )
        ).scalar_one_or_none()


def _events(engine: Engine, principal_id: str) -> list[tuple[str, int]]:
    with engine.connect() as connection:
        return [
            (row.event_id, row.sequence_number)
            for row in connection.execute(
                select(record_events.c.event_id, record_events.c.sequence_number)
                .where(record_events.c.principal_id == principal_id)
                .order_by(record_events.c.sequence_number)
            )
        ]


def _series_exists(engine: Engine, series_id: str) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                select(func.count())
                .select_from(meeting_series)
                .where(meeting_series.c.meeting_series_id == series_id)
            ).scalar_one()
        )


# ---- the allocator itself ---------------------------------------------------


def test_the_first_batch_begins_at_one(engine: Engine) -> None:
    principal = _principal()
    with engine.begin() as connection:
        assert SqlRecordEventWriter(connection).allocate(principal, 3) == 1
    assert _next_sequence(engine, principal) == 4


def test_a_later_batch_begins_at_the_prior_next_sequence(engine: Engine) -> None:
    principal = _principal()
    with engine.begin() as connection:
        SqlRecordEventWriter(connection).allocate(principal, 3)
    with engine.begin() as connection:
        assert SqlRecordEventWriter(connection).allocate(principal, 2) == 4
    with engine.begin() as connection:
        assert SqlRecordEventWriter(connection).allocate(principal, 1) == 6
    assert _next_sequence(engine, principal) == 7


def test_the_allocator_refuses_an_empty_batch(engine: Engine) -> None:
    with pytest.raises(ValueError, match="at least one"), engine.begin() as connection:
        SqlRecordEventWriter(connection).allocate(_principal(), 0)


# ---- one batch through each unit of work ------------------------------------


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_one_batch_is_contiguous_and_in_stage_order(engine: Engine, name: str) -> None:
    principal = _principal()
    with OWNERS[name](engine) as unit:
        first = _draft(principal)
        second = _draft(principal, cause=first.event_id)
        third = _draft(principal, cause=second.event_id)
        for draft in (first, second, third):
            unit.record_events.stage(draft)
    assert _events(engine, principal) == [
        (first.event_id, 1),
        (second.event_id, 2),
        (third.event_id, 3),
    ]
    with OWNERS[name](engine) as unit:
        fourth = _draft(principal)
        unit.record_events.stage(fourth)
    assert _events(engine, principal)[-1] == (fourth.event_id, 4)
    assert _next_sequence(engine, principal) == 5


# ---- T-05: a failed transaction leaves no sequence advance ------------------


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_rollback_after_staging_leaves_no_sequence_advance(engine: Engine, name: str) -> None:
    """T-05 (i): the block raised; the flush never ran."""
    principal = _principal()
    with pytest.raises(LookupError), OWNERS[name](engine) as unit:
        unit.record_events.stage(_draft(principal))
        raise LookupError
    assert _next_sequence(engine, principal) is None
    assert _events(engine, principal) == []


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_rollback_after_allocation_leaves_no_sequence_advance(engine: Engine, name: str) -> None:
    """T-05 (ii): the allocator ran, then an insert failed; the advance rolls back."""
    principal = _principal()
    with OWNERS[name](engine) as unit:
        unit.record_events.stage(_draft(principal))
    assert _next_sequence(engine, principal) == 2
    with pytest.raises(RepositoryFailureError), OWNERS[name](engine) as unit:
        unit.record_events.stage(_draft(principal))
        # A cause that does not exist: the NOT DEFERRABLE reference refuses the
        # second insert, after the allocator has already advanced the row.
        unit.record_events.stage(_draft(principal, cause=issue_identifier(IdKind.RECORD_EVENT)))
    assert _next_sequence(engine, principal) == 2
    assert len(_events(engine, principal)) == 1


def test_a_deferred_check_failing_at_commit_leaves_no_sequence_advance(engine: Engine) -> None:
    """T-05 (iii): the flush succeeded, then COMMIT failed on a deferred check."""
    principal = _principal()
    unit = SqlAlchemyUnitOfWork(engine, audit=_Audit())
    with pytest.raises(IntegrityError), unit:
        connection = unit._connection
        assert connection is not None
        connection.execute(
            text(
                "CREATE TEMP TABLE deferred_probe (k int "
                "UNIQUE DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"
            )
        )
        connection.execute(text("INSERT INTO deferred_probe VALUES (1), (1)"))
        unit.record_events.stage(_draft(principal))
    assert _next_sequence(engine, principal) is None
    assert _events(engine, principal) == []


# ---- T-06: RE-I-001 in both directions --------------------------------------


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_event_cannot_outlive_canonical_rollback(engine: Engine, name: str) -> None:
    principal = _principal()
    with pytest.raises(LookupError), OWNERS[name](engine) as unit:
        series_id = _canonical(unit._connection, principal)
        unit.record_events.stage(_draft(principal, series_id))
        raise LookupError
    assert not _series_exists(engine, series_id)
    assert _events(engine, principal) == []


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_canonical_cannot_commit_without_event(engine: Engine, name: str) -> None:
    principal = _principal()
    with pytest.raises(RepositoryFailureError), OWNERS[name](engine) as unit:
        series_id = _canonical(unit._connection, principal)
        unit.record_events.stage(
            _draft(principal, series_id, cause=issue_identifier(IdKind.RECORD_EVENT))
        )
    assert not _series_exists(engine, series_id)
    assert _events(engine, principal) == []
    assert _next_sequence(engine, principal) is None


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_a_committed_canonical_change_commits_with_its_event(engine: Engine, name: str) -> None:
    principal = _principal()
    with OWNERS[name](engine) as unit:
        series_id = _canonical(unit._connection, principal)
        draft = _draft(principal, series_id)
        unit.record_events.stage(draft)
    assert _series_exists(engine, series_id)
    assert _events(engine, principal) == [(draft.event_id, 1)]


@pytest.mark.parametrize("name", sorted(OWNERS))
def test_a_refused_batch_rolls_back_the_canonical_change(engine: Engine, name: str) -> None:
    """RE-AC-013 where PostgreSQL cannot help: the flush fails before any statement.

    A statement failure aborts the transaction, so PostgreSQL would turn even a
    wrongly issued COMMIT into a rollback. A batch refused in Python -- here, one
    holding two Principals -- aborts nothing, so only the unit of work handing
    the failure to its own rollback keeps the canonical change out.
    """
    principal = _principal()
    with (
        pytest.raises(RepositoryFailureError, match="exactly one Principal"),
        OWNERS[name](engine) as unit,
    ):
        series_id = _canonical(unit._connection, principal)
        unit.record_events.stage(_draft(principal, series_id))
        unit.record_events.stage(_draft(_principal()))
    assert not _series_exists(engine, series_id)
    assert _events(engine, principal) == []
