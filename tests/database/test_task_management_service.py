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

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.tasks import TaskManagementService, TaskVersionConflictError
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationActor, TaskMutationOutcome
from my_pa.infrastructure.database.engine import create_database_engine
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
        title="A materially different title the replay must not apply",
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
