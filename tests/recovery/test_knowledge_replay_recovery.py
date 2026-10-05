"""KLP-WP-03: an explicit create whose response is lost after COMMIT replays (KLP-AC-139).

Marked `database` and `recovery`, routed to `database-recovery`.

The failure is injected *after* the transaction committed: the unit of work
commits and then raises, so the caller receives an error while the create, its
mutation and its one Record Event are durable. The retry with the same key and
request is answered from the submission ledger -- the stored public result,
byte-identical to what the lost response would have carried -- and stages no
second canonical mutation, no second event, and advances no sequence. A retry
with a changed request under the same key is still a conflict.

KLP-WP-04 slice B2 adds the autonomous-submit half: a supersession (two
mutations, two events) lost after COMMIT replays from the autonomous arbiter
with the stored result -- assertion, mutation, superseded id -- and stages no
second mutation or event.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from types import TracebackType
from typing import Any

import pytest

from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_knowledge_assertion_repository import (
    WHEN,
    KnowledgeRuntime,
    counts,
    create_command,
    knowledge_events,
    new_principal,
)
from tests.database.test_knowledge_assertion_submissions import (
    CLIENT,
    PAYMENT,
    SUBMIT_GRANTS,
    SubmitRuntime,
    add_direct_payment_head,
    external,
)
from tests.database.test_task_record_events import next_sequence

pytestmark = [pytest.mark.database, pytest.mark.recovery]


class _LostResponseError(Exception):
    """The connection dropped after COMMIT, before the answer left the process."""


class _CommitThenLose(SqlAlchemyUnitOfWork):
    armed: list[bool]

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        super().__exit__(exc_type, exc, traceback)
        if exc_type is None and self.armed and self.armed.pop():
            raise _LostResponseError


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[tuple[KnowledgeRuntime, list[bool]]]:
    composed = KnowledgeRuntime(disposable_database)
    armed: list[bool] = []
    audit = SqlAlchemyAuditSink(composed.audit_engine)

    def unit_of_work() -> UnitOfWork:
        work = _CommitThenLose(
            composed.engine,
            audit=audit,
            relationship_memory_enabled=True,
            relationship_intelligence_enabled=True,
        )
        work.armed = armed
        return work

    composed.service._unit_of_work = unit_of_work  # type: ignore[attr-defined]
    try:
        yield composed, armed
    finally:
        composed.close()


def test_a_create_lost_after_commit_replays_and_stages_no_second_event(
    runtime: tuple[KnowledgeRuntime, list[bool]],
) -> None:
    service, armed = runtime
    principal = new_principal()
    command = create_command("klp03-recovery", subject_id=principal)
    armed.append(True)
    lost = service.invoke(command, principal_id=principal)
    assert lost.error is not None, "the injected loss must reach the caller as a failure"
    committed = counts(service.engine, principal)
    assert committed["knowledge_assertions"] == 1
    assert committed["record_events"] == 1
    sequence = next_sequence(service.engine, principal)
    (event,) = knowledge_events(service.engine, principal)

    retried: dict[str, Any] = service.ok(command, principal_id=principal)
    assert retried["outcome"] == "direct_created"
    assert retried["mutation_id"] == event["source_receipt_id"]
    assert retried["assertion_id"] == event["record_id"]
    assert retried["current_lifecycle"] == "active"
    assert counts(service.engine, principal) == committed
    assert next_sequence(service.engine, principal) == sequence
    assert service.ok(command, principal_id=principal) == retried

    changed = service.error(
        create_command("klp03-recovery", subject_id=principal, value="Another value"),
        principal_id=principal,
    )
    assert changed["code"] == "conflict"
    assert counts(service.engine, principal) == committed


@pytest.fixture
def submit_runtime(disposable_database: str) -> Iterator[tuple[SubmitRuntime, list[bool]]]:
    composed = SubmitRuntime(disposable_database)
    armed: list[bool] = []
    audit = SqlAlchemyAuditSink(composed.audit_engine)

    def unit_of_work() -> UnitOfWork:
        work = _CommitThenLose(
            composed.engine,
            audit=audit,
            relationship_memory_enabled=True,
            relationship_intelligence_enabled=True,
        )
        work.armed = armed
        return work

    composed.service._unit_of_work = unit_of_work  # type: ignore[attr-defined]
    try:
        yield composed, armed
    finally:
        composed.close()


def test_a_submit_lost_after_commit_replays_and_stages_no_second_event(
    submit_runtime: tuple[SubmitRuntime, list[bool]],
) -> None:
    service, armed = submit_runtime
    principal = new_principal()
    add_direct_payment_head(service.engine)
    profile = service.profile(principal)
    org = service.entity(principal, "recovery")
    first = service.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        value="Net 30",
        candidate="r1",
        effective_from=WHEN - timedelta(days=9),
        evidence=(external("inv-r1"),),
    )
    command = service.submit_command(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        value="Net 45",
        candidate="r2",
        effective_from=WHEN - timedelta(days=1),
        evidence=(external("inv-r2"),),
    )
    remote = {
        "transport": CaptureTransport.REMOTE_CLIENT,
        "grants": SUBMIT_GRANTS,
        "client_id": CLIENT,
    }
    armed.append(True)
    lost = service.invoke(command, principal_id=principal, **remote)
    assert lost.error is not None, "the injected loss must reach the caller as a failure"
    committed = counts(service.engine, principal)
    sequence = next_sequence(service.engine, principal)
    events = knowledge_events(service.engine, principal)
    assert len(events) == 3  # create, then supersede_predecessor + supersede_successor
    retried: dict[str, Any] = service.ok(command, principal_id=principal, **remote)
    assert retried["outcome"] == "direct_superseded"
    assert retried["superseded_assertion_id"] == first["assertion_id"]
    assert retried["mutation_id"] == events[-1]["source_receipt_id"]
    assert counts(service.engine, principal) == committed
    assert next_sequence(service.engine, principal) == sequence
    assert service.ok(command, principal_id=principal, **remote) == retried
