"""T-10 / T-11 (WP-RE-03): composite Constraint writes under contention (RE-AC-036, 042, 043).

Marked `database` (auto `database_clone`: every pairing below runs on several
connections), routed to `database-current-head`. Every connection carries a
`lock_timeout`, so a lock this module does not expect fails loudly instead of
hanging the tier.

**T-11** -- `create_published` commits exactly one event and advances the
sequence by exactly one: no intermediate Draft or Publish event (REQUEST §5.F).

**T-10** -- the five pairings the transaction matrix names, each run with a
barrier so the writers overlap:

1. `create_published` against `publish` into the same Category;
2. `close_with_follow_up` against an `update` of its predecessor and a
   `publish` into the successor's Category;
3. `reorder_categories` against `update_category`;
4. `constraint_sync.apply` against an `update` of the Constraint it merges;
5. `project_controls.configure` against `create_draft` in the same Project.

For every pairing: no writer fails with a deadlock (40P01) or a lock timeout
(55P03) -- either would be stop N14 -- the only admissible refusal is the typed
version conflict of a writer that lost its race, and the committed feed is
gap-free with every transaction's events contiguous (RE-AC-042: one allocator
batch per transaction). A composite's events share one transaction and
causally chain where the operation says they must.

Every identity here is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import DBAPIError

from my_pa.application.commands import ApplyConstraintSync
from my_pa.application.constraint_management import (
    ConstraintCategoryVersionConflictError,
    ConstraintManagementService,
    ConstraintVersionConflictError,
)
from my_pa.application.constraint_settings import ProjectControlsConfigurationService
from my_pa.domain.project_controls.history import ConstraintMutationActor
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)
from tests.database.test_constraint_management_service import (
    PRINCIPAL_A,
    PRINCIPAL_PARTY,
    PROJECT_A,
    T0,
    _category,
    _draft,
    _published,
    seed,
)
from tests.database.test_constraint_record_events import ConstraintRuntime
from tests.database.test_constraint_sync_record_events import (
    LEASE,
    PREVIEW_DIGEST,
    _candidate,
    seed_active_run,
    seed_item,
)
from tests.database.test_task_record_events import assert_gap_free, feed

pytestmark = pytest.mark.database

LOCK_TIMEOUT: Final = "20s"
JOIN_TIMEOUT_SECONDS: Final = 60.0
DEADLOCK: Final = "40P01"
LOCK_NOT_AVAILABLE: Final = "55P03"
#: The refusals a writer that lost its race is allowed to report.
LOST_RACE: Final = (ConstraintVersionConflictError, ConstraintCategoryVersionConflictError)


def _impatient(engine: Engine) -> Engine:
    @event.listens_for(engine, "connect")
    def _set_timeout(dbapi_connection: object, _record: object) -> None:
        with dbapi_connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")

    return engine


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    seed(migrated_engine)
    return _impatient(migrated_engine)


def _service(engine: Engine) -> ConstraintManagementService:
    return ConstraintManagementService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(engine), clock=lambda: T0
    )


def _race(*writers: Callable[[], object]) -> list[object]:
    """Run the writers together; return each one's result or raised exception."""
    barrier = threading.Barrier(len(writers), timeout=JOIN_TIMEOUT_SECONDS)

    def run(writer: Callable[[], object]) -> object:
        barrier.wait()
        try:
            return writer()
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=len(writers)) as pool:
        futures = [pool.submit(run, writer) for writer in writers]
        return [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures]


def _assert_no_lock_failure(outcomes: list[object]) -> None:
    """Stop N14: no deadlock and no lock timeout; only a lost race may refuse."""
    for outcome in outcomes:
        if isinstance(outcome, DBAPIError):
            state = getattr(outcome.orig, "sqlstate", None)
            assert state not in {DEADLOCK, LOCK_NOT_AVAILABLE}, f"STOP N14: {state} {outcome}"
            raise AssertionError(f"unexpected database failure: {outcome}")
        if isinstance(outcome, Exception):
            assert isinstance(outcome, LOST_RACE), repr(outcome)


def _assert_batches_are_contiguous(engine: Engine) -> dict[str, list[dict[str, Any]]]:
    """RE-AC-042: every transaction's events are one contiguous allocator batch."""
    assert_gap_free(engine, PRINCIPAL_A)
    with engine.connect() as connection:
        writer = dict(
            connection.execute(
                text("SELECT event_id, xmin::text FROM knowledge.record_events")
            ).all()
        )
    batches: dict[str, list[dict[str, Any]]] = {}
    for item in feed(engine, PRINCIPAL_A):
        batches.setdefault(writer[item["event_id"]], []).append(item)
    for events in batches.values():
        numbers = [item["sequence_number"] for item in events]
        assert numbers == list(range(numbers[0], numbers[0] + len(numbers))), numbers
    return batches


# ---- T-11 -------------------------------------------------------------------


def test_create_published_emits_one_event_and_no_intermediate_sequence(staged: Engine) -> None:
    category = _category(staged)
    before = feed(staged, PRINCIPAL_A)
    result = _service(staged).create_published(
        principal_id=PRINCIPAL_A,
        actor=ConstraintMutationActor.PRINCIPAL,
        project_id=PROJECT_A,
        category_id=category,
        description="Published in one step.",
        date_identified=date(2026, 9, 2),
        due_date=date(2026, 9, 16),
        bic=(PRINCIPAL_PARTY,),
    )
    after = feed(staged, PRINCIPAL_A)
    assert len(after) == len(before) + 1
    (event,) = after[len(before) :]
    assert event["event_kind"] == "created"
    assert event["record_id"] == result.record.constraint_id
    assert event["record_version"] == result.record.version == 2
    assert event["source_capability"] == "constraints.create_published"
    assert event["sequence_number"] == before[-1]["sequence_number"] + 1


# ---- T-10 -------------------------------------------------------------------


def test_create_published_against_publish_in_the_same_category(staged: Engine) -> None:
    category = _category(staged)
    draft = _draft(staged, category)
    outcomes = _race(
        lambda: _service(staged).create_published(
            principal_id=PRINCIPAL_A,
            actor=ConstraintMutationActor.PRINCIPAL,
            project_id=PROJECT_A,
            category_id=category,
            description="Composite.",
            date_identified=date(2026, 9, 2),
            due_date=date(2026, 9, 16),
            bic=(PRINCIPAL_PARTY,),
        ),
        lambda: _service(staged).publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=draft.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            due_date=date(2026, 9, 16),
        ),
    )
    _assert_no_lock_failure(outcomes)
    batches = _assert_batches_are_contiguous(staged)
    assert all(len(events) == 1 for events in batches.values())


def test_close_with_follow_up_against_an_update_and_a_publish(staged: Engine) -> None:
    predecessor = _published(staged, _category(staged, prefix="PRE"))
    successor_category = _category(staged, prefix="SUC")
    other = _draft(staged, successor_category)
    outcomes = _race(
        lambda: _service(staged).close_with_follow_up(
            principal_id=PRINCIPAL_A,
            constraint_id=predecessor.constraint_id,
            expected_version=predecessor.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            successor_description="The follow-up.",
            successor_category_id=successor_category,
            completion_date=date(2026, 9, 3),
        ),
        lambda: _service(staged).update(
            principal_id=PRINCIPAL_A,
            constraint_id=predecessor.constraint_id,
            expected_version=predecessor.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"reference": "RFI-77"},
        ),
        lambda: _service(staged).publish(
            principal_id=PRINCIPAL_A,
            constraint_id=other.constraint_id,
            expected_version=other.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            due_date=date(2026, 9, 16),
        ),
    )
    _assert_no_lock_failure(outcomes)
    batches = _assert_batches_are_contiguous(staged)
    follow_ups = [
        events
        for events in batches.values()
        if len(events) == 2 and events[1]["event_kind"] == "created"
    ]
    if not isinstance(outcomes[0], Exception):
        (pair,) = follow_ups
        closed, created = pair
        assert closed["record_id"] == predecessor.constraint_id
        assert closed["event_kind"] == "state_changed"
        assert created["causation_event_id"] == closed["event_id"]


def test_reorder_against_update_category(staged: Engine) -> None:
    first = _category(staged, prefix="AAA")
    second = _category(staged, prefix="BBB")
    outcomes = _race(
        lambda: _service(staged).reorder_categories(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            ordered_category_ids=(second, first),
            expected_versions={first: 1, second: 1},
            actor=ConstraintMutationActor.PRINCIPAL,
        ),
        lambda: _service(staged).update_category(
            principal_id=PRINCIPAL_A,
            category_id=first,
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"title": "Renamed"},
        ),
    )
    _assert_no_lock_failure(outcomes)
    batches = _assert_batches_are_contiguous(staged)
    if not isinstance(outcomes[0], Exception):
        assert any(
            [item["record_id"] for item in events] == [second, first] for events in batches.values()
        )


def test_sync_apply_against_an_update(disposable_database: str) -> None:
    runtime = ConstraintRuntime(disposable_database)
    try:
        seed(runtime.engine)
        engine = _impatient(runtime.engine)
        record = _published(engine, _category(engine))
        target_id, run_id = seed_active_run(engine)
        seed_item(
            engine,
            target_id,
            run_id,
            record,
            row_key="row-1",
            action="merge",
            field_names=["description"],
            candidate=_candidate(record, "row-1", description="From the workbook."),
        )

        def apply() -> object:
            response = runtime.invoke(
                ApplyConstraintSync(
                    project_id=PROJECT_A,
                    target_id=target_id,
                    run_id=run_id,
                    lease_token=LEASE,
                    preview_digest=PREVIEW_DIGEST,
                    idempotency_key="sync_race_rcev_0001",
                )
            )
            if response.error is not None:
                code = response.error.code.value
                assert code == "conflict", response.error
                return ConstraintVersionConflictError(record, None)  # type: ignore[arg-type]
            return response

        outcomes = _race(
            apply,
            lambda: _service(engine).update(
                principal_id=PRINCIPAL_A,
                constraint_id=record.constraint_id,
                expected_version=record.version,
                actor=ConstraintMutationActor.PRINCIPAL,
                values={"reference": "RFI-88"},
            ),
        )
        _assert_no_lock_failure(outcomes)
        _assert_batches_are_contiguous(engine)
    finally:
        runtime.close()


def test_configure_against_create_draft(staged: Engine) -> None:
    settings = ProjectControlsConfigurationService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(staged), clock=lambda: T0
    )
    outcomes = _race(
        lambda: settings.configure(
            principal_id=PRINCIPAL_A,
            actor=ConstraintMutationActor.PRINCIPAL,
            project_id=PROJECT_A,
            timezone_name="America/New_York",
            idempotency_key="pcs-race-rcev-0001",
            expected_version=1,
        ),
        lambda: _service(staged).create_draft(
            principal_id=PRINCIPAL_A,
            actor=ConstraintMutationActor.PRINCIPAL,
            project_id=PROJECT_A,
            description="Drafted during a configure.",
        ),
    )
    _assert_no_lock_failure(outcomes)
    batches = _assert_batches_are_contiguous(staged)
    families = sorted(events[0]["record_family"] for events in batches.values())
    assert families == ["constraint", "project_controls_settings"]


# ---- RE-AC-043: the inversion the lock order excludes, forced deterministically


def _wait_until_blocked(engine: Engine, done: Callable[[], bool]) -> None:
    import time

    deadline = time.monotonic() + 15.0
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            assert not done(), "the composite did not wait for the category lock"
            waiting = observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
            observer.rollback()
            if waiting:
                return
            time.sleep(0.05)
    pytest.fail("the composite never blocked on the category writer")


def test_a_composite_waiting_on_a_domain_lock_holds_no_allocator_lock(staged: Engine) -> None:
    """The per-substep allocation mutant turns this into a deadlock (40P01).

    A Category writer takes the successor Category's row lock and holds it. A
    `close_with_follow_up` then closes its predecessor and blocks publishing
    the successor into that Category. When the category writer finishes, its
    flush takes the Principal's allocator row. That can only succeed because
    the blocked composite has not touched the allocator: every event it staged
    is still in memory until its own exit.
    """
    predecessor = _published(staged, _category(staged, prefix="PRE"))
    successor_category = _category(staged, prefix="SUC")
    service = _service(staged)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with SqlAlchemyConstraintManagementUnitOfWork(staged) as holder:
            # A Category write: it takes the successor Category's row lock and
            # stages its event, touching the allocator only at its own exit.
            service.update_category(
                principal_id=PRINCIPAL_A,
                category_id=successor_category,
                expected_version=1,
                actor=ConstraintMutationActor.PRINCIPAL,
                values={"title": "Renamed while held"},
                active_uow=holder,
            )
            composite = pool.submit(
                lambda: _service(staged).close_with_follow_up(
                    principal_id=PRINCIPAL_A,
                    constraint_id=predecessor.constraint_id,
                    expected_version=predecessor.version,
                    actor=ConstraintMutationActor.PRINCIPAL,
                    successor_description="The follow-up.",
                    successor_category_id=successor_category,
                    completion_date=date(2026, 9, 3),
                )
            )
            _wait_until_blocked(staged, composite.done)
        # The holder's exit flushed (allocator) and committed.
        result = composite.result(timeout=JOIN_TIMEOUT_SECONDS)
    assert result.successor.lifecycle_state.value == "identified"
    batches = _assert_batches_are_contiguous(staged)
    assert sorted(len(events) for events in batches.values())[-1] == 2
