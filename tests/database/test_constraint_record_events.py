"""WP-RE-03: Constraint and Category Record Events on a real database (RE-AC-031..038).

Marked `database` (auto `database_clone`), routed to `database-current-head`.
`ConstraintManagementService` runs on the production Constraint unit of work
(U4), and one test goes through `ApplicationService` to prove the public path
threads the exact capability and the request's correlation id.

* **RE-AC-031 / 033 / 035** -- create is `created`; publish, transition, close,
  void and reopen are `state_changed`; each commits in the same transaction as
  its canonical row (equal `xmin`), so it was staged on U4.
* **RE-AC-034** -- an APPLIED update is `updated`; an empty patch (NO_OP)
  commits none.
* **RE-AC-037 / 038** -- Category create / update / deactivate; a reorder
  commits one `updated` per Category in request order, in one batch.
* **T-16** -- a replay, a NO_OP and a committed stale REJECTED receipt commit
  zero events and advance no sequence, for Constraints and Categories.

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, select, text

from my_pa.application.commands import Command, CreateConstraintDraft
from my_pa.application.constraint_management import (
    ConstraintCategoryVersionConflictError,
    ConstraintMutationDisposition,
    ConstraintVersionConflictError,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.project_controls.constraint import ConstraintLifecycleState
from my_pa.domain.project_controls.history import ConstraintMutationActor
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_category_history,
    project_constraint_history,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_constraint_management_service import (
    PRINCIPAL_A,
    PROJECT_A,
    _category,
    _draft,
    _published,
    _service,
    seed,
)
from tests.database.test_task_record_events import LIMITS, assert_gap_free, feed, next_sequence

pytestmark = pytest.mark.database

SCHEMA: Final = "knowledge"
REQUESTED_AT: Final = datetime(2026, 9, 2, 12, tzinfo=UTC)


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    seed(migrated_engine)
    return migrated_engine


def xmin(engine: Engine, table: str, key: str, value: str) -> str:
    """The id of the transaction that last wrote one row."""
    with engine.connect() as connection:
        return str(
            connection.execute(
                text(f"SELECT xmin::text FROM {SCHEMA}.{table} WHERE {key} = :value"),  # noqa: S608
                {"value": value},
            ).scalar_one()
        )


def event_xmin(engine: Engine, event_id: str) -> str:
    return xmin(engine, "record_events", "event_id", event_id)


class ConstraintRuntime:
    """`ApplicationService` with the production Constraint unit of work composed."""

    def __init__(self, url: str) -> None:
        self.engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.engine, audit=audit)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            constraint_management_unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(
                self.engine
            ),
        )

    def close(self) -> None:
        self.engine.dispose()
        self.audit_engine.dispose()

    def invoke(self, command_value: Command) -> ResponseEnvelope:
        capability = command_value.capability
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=sorted(permitted_purposes(capability))[0],
                principal_id=PRINCIPAL_A,
                requested_at=REQUESTED_AT,
            ),
            command_value,
            principal=Principal(
                principal_id=PRINCIPAL_A, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
        )


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[ConstraintRuntime]:
    composed = ConstraintRuntime(disposable_database)
    seed(composed.engine)
    try:
        yield composed
    finally:
        composed.close()


def _events_after(engine: Engine, count: int) -> list[dict[str, Any]]:
    return feed(engine, PRINCIPAL_A)[count:]


# ---- RE-AC-031 / 033 / 035 --------------------------------------------------


def test_create_and_publish_commit_one_event_each_on_the_constraint_transaction(
    staged: Engine,
) -> None:
    category = _category(staged)
    before = len(feed(staged, PRINCIPAL_A))
    draft = _draft(staged, category)
    created = _events_after(staged, before)
    assert [event["event_kind"] for event in created] == ["created"]
    assert created[0]["record_id"] == draft.constraint_id
    assert created[0]["record_family"] == "constraint"
    assert created[0]["source_capability"] == "constraints.create"
    assert created[0]["actor_class"] == "principal"
    with staged.connect() as connection:
        receipt = connection.execute(
            select(project_constraint_history.c.history_id).where(
                project_constraint_history.c.constraint_id == draft.constraint_id
            )
        ).scalar_one()
    assert created[0]["source_receipt_id"] == receipt
    # Same transaction as the canonical receipt: staged on U4 and nowhere else.
    assert event_xmin(staged, created[0]["event_id"]) == xmin(
        staged, "project_constraint_history", "history_id", receipt
    )
    published = _service(staged).publish(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    event = feed(staged, PRINCIPAL_A)[-1]
    assert event["event_kind"] == "state_changed"
    assert event["record_version"] == published.record.version == 2
    assert event["source_capability"] == "constraints.publish"
    assert "constraint_code" in event["changed_fields"]
    assert_gap_free(staged, PRINCIPAL_A)


def test_transition_close_reopen_and_void_are_state_changed(staged: Engine) -> None:
    record = _published(staged, _category(staged))
    service = _service(staged)
    before = len(feed(staged, PRINCIPAL_A))
    moved = service.transition_active(
        principal_id=PRINCIPAL_A,
        constraint_id=record.constraint_id,
        target_state=ConstraintLifecycleState.IN_PROGRESS,
        expected_version=record.version,
        actor=ConstraintMutationActor.PRINCIPAL,
    ).record
    closed = service.close(
        principal_id=PRINCIPAL_A,
        constraint_id=record.constraint_id,
        expected_version=moved.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        completion_date=date(2026, 9, 3),
    ).record
    reopened = service.reopen(
        principal_id=PRINCIPAL_A,
        constraint_id=record.constraint_id,
        target_state=ConstraintLifecycleState.IDENTIFIED,
        expected_version=closed.version,
        actor=ConstraintMutationActor.PRINCIPAL,
    ).record
    service.void(
        principal_id=PRINCIPAL_A,
        constraint_id=record.constraint_id,
        expected_version=reopened.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        void_reason="Superseded.",
        voided_date=date(2026, 9, 4),
    )
    events = _events_after(staged, before)
    assert [event["event_kind"] for event in events] == ["state_changed"] * 4
    assert [event["source_capability"] for event in events] == [
        "constraints.transition",
        "constraints.close",
        "constraints.reopen",
        "constraints.void",
    ]
    assert [event["record_version"] for event in events] == [3, 4, 5, 6]
    assert_gap_free(staged, PRINCIPAL_A)


# ---- RE-AC-034 --------------------------------------------------------------


def test_an_applied_update_is_updated_and_an_empty_patch_commits_nothing(staged: Engine) -> None:
    draft = _draft(staged, _category(staged))
    service = _service(staged)
    service.update(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"reference": "RFI-12"},
    )
    event = feed(staged, PRINCIPAL_A)[-1]
    assert event["event_kind"] == "updated"
    assert event["changed_fields"] == ["reference"]
    assert event["record_version"] == 2
    before = (feed(staged, PRINCIPAL_A), next_sequence(staged, PRINCIPAL_A))
    no_op = service.update(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=2,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={},
    )
    assert no_op.disposition is ConstraintMutationDisposition.NO_OP
    assert (feed(staged, PRINCIPAL_A), next_sequence(staged, PRINCIPAL_A)) == before


# ---- T-16 -------------------------------------------------------------------


def test_a_replay_and_a_committed_rejection_commit_nothing(staged: Engine) -> None:
    draft = _draft(staged, _category(staged))
    service = _service(staged)
    kwargs: dict[str, Any] = {
        "principal_id": PRINCIPAL_A,
        "constraint_id": draft.constraint_id,
        "expected_version": 1,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "values": {"reference": "RFI-9"},
        "idempotency_key": "cst-db-replay-0001",
    }
    service.update(**kwargs)
    before = (feed(staged, PRINCIPAL_A), next_sequence(staged, PRINCIPAL_A))
    assert service.update(**kwargs).disposition is ConstraintMutationDisposition.REPLAYED
    with pytest.raises(ConstraintVersionConflictError):
        service.update(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"reference": "stale"},
        )
    with staged.connect() as connection:
        outcomes = sorted(
            connection.execute(
                select(project_constraint_history.c.outcome).where(
                    project_constraint_history.c.constraint_id == draft.constraint_id
                )
            ).scalars()
        )
    assert "rejected" in outcomes  # the REJECTED receipt committed
    assert (feed(staged, PRINCIPAL_A), next_sequence(staged, PRINCIPAL_A)) == before


# ---- RE-AC-037 / 038 --------------------------------------------------------


def test_category_create_update_and_deactivate(staged: Engine) -> None:
    before = len(feed(staged, PRINCIPAL_A))
    service = _service(staged)
    created = service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="STR",
        title="Structure",
        actor=ConstraintMutationActor.PRINCIPAL,
    ).record
    service.update_category(
        principal_id=PRINCIPAL_A,
        category_id=created.category_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"title": "Structures"},
    )
    service.deactivate_category(
        principal_id=PRINCIPAL_A,
        category_id=created.category_id,
        expected_version=2,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    events = _events_after(staged, before)
    assert [event["record_family"] for event in events] == ["constraint_category"] * 3
    assert [event["event_kind"] for event in events] == ["created", "updated", "state_changed"]
    assert [event["record_version"] for event in events] == [1, 2, 3]
    with staged.connect() as connection:
        receipts = list(
            connection.execute(
                select(constraint_category_history.c.history_id)
                .where(constraint_category_history.c.category_id == created.category_id)
                .order_by(constraint_category_history.c.after_version)
            ).scalars()
        )
    assert [event["source_receipt_id"] for event in events] == receipts


def test_a_reorder_commits_one_updated_per_category_in_request_order(staged: Engine) -> None:
    first = _category(staged, prefix="AAA")
    second = _category(staged, prefix="BBB")
    before = len(feed(staged, PRINCIPAL_A))
    _service(staged).reorder_categories(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        ordered_category_ids=(second, first),
        expected_versions={first: 1, second: 1},
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    events = _events_after(staged, before)
    assert [event["record_id"] for event in events] == [second, first]
    assert {event["event_kind"] for event in events} == {"updated"}
    assert [event["record_version"] for event in events] == [2, 2]
    assert all("version" in event["changed_fields"] for event in events)
    # One allocator batch: consecutive numbers, one transaction.
    assert events[1]["sequence_number"] == events[0]["sequence_number"] + 1
    assert event_xmin(staged, events[0]["event_id"]) == event_xmin(staged, events[1]["event_id"])


def test_a_stale_reorder_commits_nothing(staged: Engine) -> None:
    first = _category(staged, prefix="AAA")
    second = _category(staged, prefix="BBB")
    before = (feed(staged, PRINCIPAL_A), next_sequence(staged, PRINCIPAL_A))
    with pytest.raises(ConstraintCategoryVersionConflictError):
        _service(staged).reorder_categories(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            ordered_category_ids=(second, first),
            expected_versions={first: 7, second: 1},
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    assert (feed(staged, PRINCIPAL_A), next_sequence(staged, PRINCIPAL_A)) == before


# ---- the public path: exact capability and the request's correlation --------


def test_the_public_path_carries_the_exact_capability_and_correlation(
    runtime: ConstraintRuntime,
) -> None:
    response = runtime.invoke(
        CreateConstraintDraft(project_id=PROJECT_A, description="From the public path.")
    )
    assert response.error is None, response.error
    (event,) = feed(runtime.engine, PRINCIPAL_A)
    assert event["source_capability"] == "constraints.create"
    assert event["correlation_id"] == response.correlation_id
