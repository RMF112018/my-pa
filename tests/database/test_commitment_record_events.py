"""WP-RE-02: Commitment Record Events on a real database (RE-AC-025..027, T-16).

Marked `database` (auto `database_clone`), routed to `database-current-head`.
`CommitmentManagementService` is driven twice over: on its own standalone unit
of work (U3), and joined to the generic unit of work (U1) through `active_uow`,
which is how `ApplicationService` reaches it. Either way the committed feed must
hold exactly one event per APPLIED mutation:

* **RE-AC-025** -- a create commits one `created` event;
* **RE-AC-026** -- an update commits one `updated` event only when APPLIED; a
  no-op, a replay and a committed stale REJECTED receipt commit none and advance
  no sequence;
* **RE-AC-027** -- a close commits one `state_changed` event.

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, select

from my_pa.application.commitments import (
    CommitmentManagementService,
    CommitmentVersionConflictError,
)
from my_pa.contracts.ports import AuditSink
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationActor
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.tables import commitment_history
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_task_record_events import assert_gap_free, feed, next_sequence

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
ORIGIN: Final = "cap_rcevwp02cmt00001"


class _Audit(AuditSink):
    def record(self, event: object) -> None:  # type: ignore[override]
        del event


class _Harness:
    """One way of reaching the service: standalone U3, or joined to U1."""

    def __init__(self, engine: Engine, mode: str) -> None:
        self.engine = engine
        self.mode = mode
        self.service = CommitmentManagementService(
            unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(engine),
            clock=lambda: WHEN,
        )

    def call(self, method: Callable[..., Any], **kwargs: object) -> Any:  # noqa: ANN401
        if self.mode == "U3-standalone":
            return method(**kwargs)
        with SqlAlchemyUnitOfWork(self.engine, audit=_Audit()) as active:
            return method(active_uow=active, **kwargs)


@pytest.fixture(params=["U3-standalone", "U1-joined"])
def harness(request: pytest.FixtureRequest, migrated_engine: Engine) -> Iterator[_Harness]:
    yield _Harness(migrated_engine, request.param)


def _create(harness: _Harness, principal: str, key: str | None = None) -> Any:  # noqa: ANN401
    return harness.call(
        harness.service.create_commitment,
        principal_id=principal,
        counterparty_person_id="per_rcevwp02cmt00001",
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary="Send the synthetic report",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=key,
        source_capability="commitments.create",
    )


def test_a_create_commits_one_created_event(harness: _Harness) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    receipt = _create(harness, principal)
    (event,) = feed(harness.engine, principal)
    assert event["record_family"] == "commitment"
    assert event["record_id"] == receipt.commitment.commitment_id
    assert event["event_kind"] == "created"
    assert event["record_version"] == 1
    assert event["source_receipt_id"] == receipt.history.history_id
    assert event["source_capability"] == "commitments.create"
    assert_gap_free(harness.engine, principal)


def test_an_applied_update_commits_one_updated_event(harness: _Harness) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    commitment = _create(harness, principal).commitment
    receipt = harness.call(
        harness.service.update_commitment,
        principal_id=principal,
        commitment_id=commitment.commitment_id,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
        values={"due_at": WHEN + timedelta(days=3)},
    )
    event = feed(harness.engine, principal)[-1]
    assert event["event_kind"] == "updated"
    assert event["changed_fields"] == ["due_at"]
    assert event["record_version"] == 2
    assert event["source_receipt_id"] == receipt.history.history_id
    assert_gap_free(harness.engine, principal)


def test_a_close_commits_one_state_changed_event(harness: _Harness) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    commitment = _create(harness, principal).commitment
    harness.call(
        harness.service.close_commitment,
        principal_id=principal,
        commitment_id=commitment.commitment_id,
        expected_version=1,
        closure_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    event = feed(harness.engine, principal)[-1]
    assert event["event_kind"] == "state_changed"
    assert event["changed_fields"] == ["closed_at", "closure_evidence_ref", "state"]
    assert event["source_capability"] == "commitments.close"


def test_a_no_op_a_replay_and_a_stale_rejection_commit_nothing(harness: _Harness) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    commitment = _create(harness, principal, key="wp02-cmt-rep-0001").commitment
    before = (feed(harness.engine, principal), next_sequence(harness.engine, principal))
    assert _create(harness, principal, key="wp02-cmt-rep-0001").replayed
    no_op = harness.call(
        harness.service.update_commitment,
        principal_id=principal,
        commitment_id=commitment.commitment_id,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
        values={"summary": commitment.summary},
    )
    assert no_op.history.outcome.value == "no_op"
    with pytest.raises(CommitmentVersionConflictError):
        harness.call(
            harness.service.update_commitment,
            principal_id=principal,
            commitment_id=commitment.commitment_id,
            expected_version=4,
            actor=TaskMutationActor.PRINCIPAL,
            values={"summary": "Too late"},
        )
    with harness.engine.connect() as connection:
        outcomes = sorted(
            connection.execute(
                select(commitment_history.c.outcome).where(
                    commitment_history.c.commitment_id == commitment.commitment_id
                )
            ).scalars()
        )
    # U3 commits the REJECTED receipt; joined to U1 the conflict escapes the
    # caller's block and rolls it back. Either way no event is committed.
    assert outcomes in (["applied", "no_op", "rejected"], ["applied", "no_op"])
    assert (feed(harness.engine, principal), next_sequence(harness.engine, principal)) == before
