"""`application.tasks.TaskManagementService`, against a live PostgreSQL server.

The `database` tier, on its own disposable database — a distinct name from
every other database-tier fixture's so this suite can run concurrently with
`tests/database/test_continuity_isolation.py` and the rest without either
dropping the other's database out from under it.

`tests/unit/test_task_management_service.py` already proves the service's
decisions against an in-memory fake; what only a real server can prove, and
what this suite exists to prove, is that those decisions actually survive a
transaction boundary:

* **Idempotency retry is exactly one row, not a race that happens not to have
  lost yet.** Two calls sharing an `idempotency_key`, queried back from the
  server rather than trusted from the service's return value, leave exactly one
  `tasks` row and exactly one `task_history` row, and the second call's receipt
  names the identical history row the first call produced.
* **A stale `expected_version` leaves the stored row exactly as it was.** The
  `REJECTED` history row commits — the receipt from a refusal is not nothing,
  it is the record of the refusal — and the `tasks` row is unreadable as having
  changed a single column.
* **A refused mutation leaves no partial trace beyond the one `REJECTED` history
  row it is entitled to write.** Same claim as the version-conflict test, from
  the row-count side rather than the content side, so a mutation that appended
  two history rows for one rejected attempt would fail here even if the content
  check above missed it.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.commitments import CommitmentManagementService
from my_pa.application.tasks import TaskManagementService, TaskVersionConflictError
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import BulkIdempotencyConflictError, WorkCursorError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.situation.continuity import (
    CommitmentDirection,
    CommitmentState,
    ContinuityAcceptanceKind,
    ContinuityEvidenceState,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.bulk import TaskBulkOperation
from my_pa.domain.task.history import (
    TaskHistoryEntry,
    TaskMutationAction,
    TaskMutationActor,
    TaskMutationOutcome,
)
from my_pa.domain.task.lifecycle import (
    TaskArchiveMode,
    TaskPriority,
    TaskWorkView,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
    SqlCommitmentManagementRepository,
)
from my_pa.infrastructure.persistence.continuity_authoring import SqlContinuityAuthoringRepository
from my_pa.infrastructure.persistence.task_management import (
    SqlAlchemyTaskManagementUnitOfWork,
    SqlTaskManagementRepository,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: A name distinct from every other database-tier fixture's disposable
#: database, so this suite can run alongside `test_continuity_isolation.py` and
#: `tests/schema/test_task_schema_migration.py` without one dropping the
#: database the other is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_task_management_service_test"

PRINCIPAL_A: Final = "prn_taskmgmta001taskmgmta001"
PRINCIPAL_B: Final = "prn_taskmgmtb001taskmgmtb001"
ORIGIN: Final = "cap_origin0001origin0001"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    """The disposable database, upgraded to head and disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _service(engine: Engine) -> TaskManagementService:
    return TaskManagementService(
        unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(engine),
        clock=lambda: datetime(2026, 8, 10, 12, tzinfo=UTC),
    )


def _idempotency_key(suffix: str) -> str:
    return f"idem-{suffix}-00000000"


def _task_row(engine: Engine, task_id: str) -> dict[str, object]:
    with engine.connect() as connection:
        row = connection.execute(
            text(f"SELECT * FROM {SCHEMA}.tasks WHERE task_id = :task_id"),  # noqa: S608
            {"task_id": task_id},
        ).one()
        return dict(row._mapping)


def _history_rows(engine: Engine, task_id: str) -> list[dict[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT * FROM {SCHEMA}.task_history WHERE task_id = :task_id "  # noqa: S608
                "ORDER BY recorded_at"
            ),
            {"task_id": task_id},
        ).all()
        return [dict(row._mapping) for row in rows]


def _row_count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.{table}")  # noqa: S608 - module constant
        ).scalar_one()


def _bulk_operation(*, key: str, now: datetime) -> TaskBulkOperation:
    return TaskBulkOperation(
        bulk_operation_id=issue_identifier(IdKind.BULK_OPERATION),
        principal_id=PRINCIPAL_A,
        preview_idempotency_key=key,
        request_digest="a" * 64,
        previewed_at=now,
        expires_at=now.replace(hour=13),
        preview_affected=1,
        preview_no_op=0,
    )


# --- idempotency: exactly one row survives a retry --------------------------


def test_a_replayed_create_writes_exactly_one_task_and_one_history_row(
    migrated_engine: Engine,
) -> None:
    service = _service(migrated_engine)
    key = _idempotency_key("create")

    first = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=key,
    )
    second = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=key,
    )

    assert second.replayed is True
    assert second.history.history_id == first.history.history_id

    task_id = first.task.task_id
    tasks_matching = _row_count(migrated_engine, "tasks")
    history_matching = _history_rows(migrated_engine, task_id)
    assert tasks_matching == 1, "the replay must not have inserted a second task row"
    assert len(history_matching) == 1, "the replay must not have inserted a second history row"
    assert history_matching[0]["history_id"] == first.history.history_id

    stored = _task_row(migrated_engine, task_id)
    assert stored["title"] == "Draft the synthetic summary"


# --- optimistic concurrency: the row is untouched by a rejected attempt -----


def test_a_stale_expected_version_leaves_the_stored_row_unchanged(
    migrated_engine: Engine,
) -> None:
    service = _service(migrated_engine)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Original title",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    task_id = created.task.task_id
    before = _task_row(migrated_engine, task_id)

    with pytest.raises(TaskVersionConflictError) as excinfo:
        service.update_title(
            principal_id=PRINCIPAL_A,
            task_id=task_id,
            title="Attempted change under a stale version",
            expected_version=created.task.version + 5,
            actor=TaskMutationActor.PRINCIPAL,
        )
    assert excinfo.value.receipt.history.outcome is TaskMutationOutcome.REJECTED

    after = _task_row(migrated_engine, task_id)
    assert after == before, f"a rejected mutation changed the stored row: {before} -> {after}"

    history = _history_rows(migrated_engine, task_id)
    rejected = [row for row in history if row["outcome"] == "rejected"]
    assert len(rejected) == 1
    assert rejected[0]["before_version"] == rejected[0]["after_version"]


# --- transactional atomicity: a rejected attempt leaves no partial trace ----


def test_a_rejected_attempt_leaves_no_row_beyond_its_own_rejected_history_entry(
    migrated_engine: Engine,
) -> None:
    service = _service(migrated_engine)
    created = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Original title",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    task_id = created.task.task_id

    tasks_before = _row_count(migrated_engine, "tasks")
    history_before = _row_count(migrated_engine, "task_history")

    with pytest.raises(TaskVersionConflictError):
        service.set_priority(
            principal_id=PRINCIPAL_A,
            task_id=task_id,
            priority=None,
            expected_version=created.task.version + 1,
            actor=TaskMutationActor.PRINCIPAL,
        )

    tasks_after = _row_count(migrated_engine, "tasks")
    history_after = _row_count(migrated_engine, "task_history")

    # No new task row, no dangling update: the count is identical.
    assert tasks_after == tasks_before
    # Exactly the one REJECTED receipt this attempt is entitled to write.
    assert history_after == history_before + 1

    history = _history_rows(migrated_engine, task_id)
    assert [row["outcome"] for row in history] == ["applied", "rejected"]


def test_concurrent_bulk_preview_key_race_is_typed_and_writes_no_tasks(
    migrated_engine: Engine,
) -> None:
    """The losing unique claim is typed only after PostgreSQL chooses the winner."""
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    first = _bulk_operation(key="bulk-preview-race-0001", now=now)
    second = _bulk_operation(key="bulk-preview-race-0001", now=now)
    first_inserted = threading.Event()
    second_attempting = threading.Event()
    release_first = threading.Event()
    failures: list[BaseException] = []

    def winner() -> None:
        with migrated_engine.begin() as connection:
            SqlTaskManagementRepository(connection).insert_bulk(first)
            first_inserted.set()
            assert release_first.wait(timeout=5)

    def contender() -> None:
        assert first_inserted.wait(timeout=5)
        try:
            with migrated_engine.begin() as connection:
                second_attempting.set()
                SqlTaskManagementRepository(connection).insert_bulk(second)
        except BaseException as error:
            failures.append(error)

    first_thread = threading.Thread(target=winner)
    second_thread = threading.Thread(target=contender)
    first_thread.start()
    second_thread.start()
    assert second_attempting.wait(timeout=5)
    release_first.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive() and not second_thread.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], BulkIdempotencyConflictError)
    assert _row_count(migrated_engine, "task_bulk_operations") == 1
    assert _row_count(migrated_engine, "tasks") == 0
    assert _row_count(migrated_engine, "task_history") == 0


def test_concurrent_bulk_confirm_key_race_rolls_back_losing_task_and_history(
    migrated_engine: Engine,
) -> None:
    """A confirm-key loser rolls back the Task and history written before its claim."""
    service = _service(migrated_engine)
    created = [
        service.create_task(
            principal_id=PRINCIPAL_A,
            title=f"Race task {index}",
            origin_evidence_ref=ORIGIN,
            actor=TaskMutationActor.PRINCIPAL,
            idempotency_key=_idempotency_key(f"bulk-race-create-{index}"),
        )
        for index in range(2)
    ]
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    operations = [_bulk_operation(key=f"bulk-race-preview-{index}", now=now) for index in range(2)]
    with migrated_engine.begin() as connection:
        repository = SqlTaskManagementRepository(connection)
        for operation in operations:
            repository.insert_bulk(operation)

    first_claimed = threading.Event()
    second_attempting = threading.Event()
    release_first = threading.Event()
    failures: list[BaseException] = []
    confirm_key = "bulk-confirm-race-0001"

    def confirm(index: int, *, wait_after_claim: bool) -> None:
        try:
            with migrated_engine.begin() as connection:
                repository = SqlTaskManagementRepository(connection)
                current = repository.get_for_update(PRINCIPAL_A, created[index].task.task_id)
                assert current is not None
                updated = dataclasses.replace(
                    current,
                    title=f"Race task {index}, confirmed",
                    version=current.version + 1,
                    updated_at=now,
                )
                repository.update_task(updated)
                history = TaskHistoryEntry(
                    history_id=issue_identifier(IdKind.TASK_HISTORY),
                    principal_id=PRINCIPAL_A,
                    task_id=current.task_id,
                    action=TaskMutationAction.UPDATE,
                    actor=TaskMutationActor.PRINCIPAL,
                    outcome=TaskMutationOutcome.APPLIED,
                    before_version=current.version,
                    after_version=updated.version,
                    occurred_at=now,
                    recorded_at=now,
                    request_digest="a" * 64,
                    bulk_operation_id=operations[index].bulk_operation_id,
                )
                repository.insert_history(history)
                confirmed = dataclasses.replace(
                    operations[index],
                    confirmed_at=now,
                    confirm_idempotency_key=confirm_key,
                    affected=1,
                    no_op=0,
                    rejected=0,
                    history_ids=(history.history_id,),
                )
                if not wait_after_claim:
                    assert first_claimed.wait(timeout=5)
                    second_attempting.set()
                repository.confirm_bulk(confirmed)
                if wait_after_claim:
                    first_claimed.set()
                    assert release_first.wait(timeout=5)
        except BaseException as error:
            failures.append(error)

    first_thread = threading.Thread(target=confirm, args=(0,), kwargs={"wait_after_claim": True})
    second_thread = threading.Thread(target=confirm, args=(1,), kwargs={"wait_after_claim": False})
    first_thread.start()
    second_thread.start()
    assert second_attempting.wait(timeout=5)
    release_first.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive() and not second_thread.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], BulkIdempotencyConflictError)
    assert _task_row(migrated_engine, created[0].task.task_id)["title"].endswith("confirmed")
    assert _task_row(migrated_engine, created[1].task.task_id)["title"] == "Race task 1"
    assert len(_history_rows(migrated_engine, created[0].task.task_id)) == 2
    assert len(_history_rows(migrated_engine, created[1].task.task_id)) == 1


def test_sql_task_cursors_refuse_absent_and_foreign_anchors(
    migrated_engine: Engine,
) -> None:
    service = _service(migrated_engine)
    mine = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Mine",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=_idempotency_key("cursor-mine"),
    )
    foreign = service.create_task(
        principal_id=PRINCIPAL_B,
        title="Foreign",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=_idempotency_key("cursor-foreign"),
    )
    wrong_query = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Different result set",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=_idempotency_key("cursor-wrong-query"),
    )
    wrong_priority = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Needle priority mismatch",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        priority=TaskPriority.P2,
        idempotency_key=_idempotency_key("cursor-wrong-priority"),
    )
    archived = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Needle archived",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        priority=TaskPriority.P1,
        idempotency_key=_idempotency_key("cursor-archived"),
    )
    archived = service.update_task(
        principal_id=PRINCIPAL_A,
        task_id=archived.task.task_id,
        expected_version=archived.task.version,
        actor=TaskMutationActor.PRINCIPAL,
        values={"archived_at": datetime(2026, 8, 10, 13, tzinfo=UTC)},
        idempotency_key=_idempotency_key("cursor-archive-update"),
    )
    waiting = service.create_task(
        principal_id=PRINCIPAL_A,
        title="Needle waiting",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        priority=TaskPriority.P1,
        idempotency_key=_idempotency_key("cursor-waiting"),
    )
    needle = tuple(
        service.create_task(
            principal_id=PRINCIPAL_A,
            title=f"Needle continuation {index}",
            origin_evidence_ref=ORIGIN,
            actor=TaskMutationActor.PRINCIPAL,
            priority=TaskPriority.P1,
            idempotency_key=_idempotency_key(f"cursor-needle-{index}"),
        )
        for index in range(2)
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.tasks SET lifecycle_state = 'waiting' "  # noqa: S608
                "WHERE task_id = :task_id"
            ),
            {"task_id": waiting.task.task_id},
        )
    with migrated_engine.begin() as connection:
        repository = SqlTaskManagementRepository(connection)
        for cursor in (issue_identifier(IdKind.TASK), foreign.task.task_id):
            with pytest.raises(WorkCursorError):
                repository.list_tasks(PRINCIPAL_A, after=cursor, limit=10)
            with pytest.raises(WorkCursorError):
                repository.search(PRINCIPAL_A, "mine", 10, after=cursor)
        with pytest.raises(WorkCursorError):
            repository.list_tasks(
                PRINCIPAL_A,
                priority=TaskPriority.P1,
                after=wrong_priority.task.task_id,
                limit=10,
            )
        with pytest.raises(WorkCursorError):
            repository.list_tasks(
                PRINCIPAL_A,
                archive_mode=TaskArchiveMode.EXCLUDE,
                after=archived.task.task_id,
                limit=10,
            )
        with pytest.raises(WorkCursorError):
            repository.list_tasks(
                PRINCIPAL_A,
                work_view=TaskWorkView.BLOCKED,
                after=waiting.task.task_id,
                limit=10,
            )
        with pytest.raises(WorkCursorError):
            repository.search(PRINCIPAL_A, "mine", 10, after=wrong_query.task.task_id)
        with pytest.raises(WorkCursorError):
            repository.search(PRINCIPAL_A, "needle", 10, after=archived.task.task_id)
        with pytest.raises(WorkCursorError):
            repository.search(
                PRINCIPAL_A,
                "needle",
                10,
                work_view=TaskWorkView.BLOCKED,
                after=waiting.task.task_id,
            )
        first = repository.search(PRINCIPAL_A, "continuation", 1)
        assert len(first) == 1
        second = repository.search(PRINCIPAL_A, "continuation", 10, after=first[0].task_id)
        assert {task.task_id for task in (*first, *second)} == {
            receipt.task.task_id for receipt in needle
        }
        for cursor in (issue_identifier(IdKind.TASK_HISTORY), foreign.history.history_id):
            with pytest.raises(WorkCursorError):
                repository.list_history(PRINCIPAL_A, mine.task.task_id, 10, after=cursor)


def test_sql_commitment_cursors_refuse_absent_and_foreign_anchors(
    migrated_engine: Engine,
) -> None:
    service = CommitmentManagementService(
        unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(migrated_engine),
        clock=lambda: datetime(2026, 8, 10, 12, tzinfo=UTC),
    )
    mine = service.create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=issue_identifier(IdKind.PERSON),
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Mine",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=_idempotency_key("commitment-cursor-mine"),
    )
    foreign = service.create_commitment(
        principal_id=PRINCIPAL_B,
        counterparty_person_id=issue_identifier(IdKind.PERSON),
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Foreign",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=_idempotency_key("commitment-cursor-foreign"),
    )
    accepted = service.create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=issue_identifier(IdKind.PERSON),
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Accepted",
        origin_evidence_ref=ORIGIN,
        accepted_by_review_decision_id=issue_identifier(IdKind.REVIEW_DECISION),
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=_idempotency_key("commitment-cursor-accepted"),
    )
    wrong_direction = service.create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=issue_identifier(IdKind.PERSON),
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary="Needle wrong direction",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=_idempotency_key("commitment-cursor-direction"),
    )
    wrong_state = service.create_commitment(
        principal_id=PRINCIPAL_A,
        counterparty_person_id=issue_identifier(IdKind.PERSON),
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Needle wrong state",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=_idempotency_key("commitment-cursor-state"),
    )
    wrong_state = service.close_commitment(
        principal_id=PRINCIPAL_A,
        commitment_id=wrong_state.commitment.commitment_id,
        expected_version=wrong_state.commitment.version,
        closure_evidence_ref="cap_closure0001closure0001",
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=_idempotency_key("commitment-cursor-close"),
    )
    needle = tuple(
        service.create_commitment(
            principal_id=PRINCIPAL_A,
            counterparty_person_id=issue_identifier(IdKind.PERSON),
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            summary=f"Needle continuation {index}",
            origin_evidence_ref=ORIGIN,
            actor=TaskMutationActor.PRINCIPAL,
            idempotency_key=_idempotency_key(f"commitment-cursor-needle-{index}"),
        )
        for index in range(2)
    )
    with migrated_engine.begin() as connection:
        repository = SqlCommitmentManagementRepository(connection)
        visible = repository.list_commitments(
            PRINCIPAL_A,
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            evidence_state=ContinuityEvidenceState.ACCEPTED,
            limit=10,
        )
        assert [commitment.commitment_id for commitment in visible] == [
            accepted.commitment.commitment_id
        ]
        with pytest.raises(WorkCursorError):
            repository.list_commitments(
                PRINCIPAL_A,
                direction=CommitmentDirection.OWED_TO_PRINCIPAL,
                evidence_state=ContinuityEvidenceState.ACCEPTED,
                after=mine.commitment.commitment_id,
                limit=10,
            )
        with pytest.raises(WorkCursorError):
            repository.search(PRINCIPAL_A, "mine", 10, after=accepted.commitment.commitment_id)
        with pytest.raises(WorkCursorError):
            repository.search(
                PRINCIPAL_A,
                "needle",
                10,
                direction=CommitmentDirection.OWED_TO_PRINCIPAL,
                after=wrong_direction.commitment.commitment_id,
            )
        with pytest.raises(WorkCursorError):
            repository.search(
                PRINCIPAL_A,
                "needle",
                10,
                state=CommitmentState.OPEN,
                after=wrong_state.commitment.commitment_id,
            )
        first = repository.search(
            PRINCIPAL_A,
            "continuation",
            1,
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            state=CommitmentState.OPEN,
        )
        assert len(first) == 1
        second = repository.search(
            PRINCIPAL_A,
            "continuation",
            10,
            after=first[0].commitment_id,
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            state=CommitmentState.OPEN,
        )
        assert {commitment.commitment_id for commitment in (*first, *second)} == {
            receipt.commitment.commitment_id for receipt in needle
        }
        for cursor in (issue_identifier(IdKind.COMMITMENT), foreign.commitment.commitment_id):
            with pytest.raises(WorkCursorError):
                repository.list_commitments(PRINCIPAL_A, after=cursor, limit=10)
            with pytest.raises(WorkCursorError):
                repository.search(PRINCIPAL_A, "mine", 10, after=cursor)
        for cursor in (
            issue_identifier(IdKind.COMMITMENT_HISTORY),
            foreign.history.history_id,
        ):
            with pytest.raises(WorkCursorError):
                repository.list_history(
                    PRINCIPAL_A, mine.commitment.commitment_id, 10, after=cursor
                )


def test_list_and_get_hydrate_a_direct_principal_accepted_task(migrated_engine: Engine) -> None:
    """Continuity-authored tasks are accepted without a review decision.

    `tasks.list`/`tasks.read` hydrate through `domain.task.task.Task`, which
    previously required every accepted row to name a review decision. Direct
    Principal authoring stores `acceptance_kind = direct_principal` and a NULL
    review-decision id, which is what ChatLLM then hit as `internal_error`.
    """

    task_id = issue_identifier(IdKind.TASK)
    with migrated_engine.begin() as connection:
        SqlContinuityAuthoringRepository(connection).author_task(
            principal_id=PRINCIPAL_A,
            task_id=task_id,
            title="Verify ChatLLM write behavior on pulse",
            origin_evidence_ref=ORIGIN,
        )
    with migrated_engine.connect() as connection:
        repository = SqlTaskManagementRepository(connection)
        listed = repository.list_tasks(PRINCIPAL_A, limit=10)
        read = repository.get(PRINCIPAL_A, task_id)
    assert [task.task_id for task in listed] == [task_id]
    assert listed[0].acceptance_kind is ContinuityAcceptanceKind.DIRECT_PRINCIPAL
    assert listed[0].accepted_by_review_decision_id is None
    assert read is not None
    assert read.task_id == task_id
    assert read.title == "Verify ChatLLM write behavior on pulse"
