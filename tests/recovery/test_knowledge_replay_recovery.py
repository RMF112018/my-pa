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

KLP-WP-04 slice B3 adds the checkpoint half: an advance lost after COMMIT
replays from the request ledger with the stored answer -- the same request id,
version and the exact committed envelope -- and writes no second request row,
no second version and no Knowledge row or event. A changed request after the
loss is the lost-response recovery (`stale_expected_version` with the current
envelope).

KLP-WP-04 slice C adds the Knowledge `review.decide` half: an acceptance lost
after COMMIT replays from `relationship_write_requests` (`review_decision`)
with the stored seven keys -- the same decision, assertion and receipt -- and
writes no second decision, mutation or Record Event.

KLP-WP-07 (race 12 closure over every family the vertical slice uses) adds the
DOMAIN_OWNED and Review-queued submit outcomes -- a `project.critical_date`
routed to its task, a `project.decision` completed no-intake and a
`project.financial_fact` queued for Review, each lost after COMMIT, replays the
stored result (same submission, route or proposal/case) and writes no second
submission, proposal, Review case or Knowledge row -- and the non-promoting
Review dispositions the workbench offers (`reject`, `defer`), each lost after
COMMIT, replaying the stored decision with no second decision row. Race 13: a
Record Event flush that fails after the canonical write was staged rolls the
whole submit back -- reservation, assertion, mutation, links and event -- and
the retry is an ordinary first submit.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from types import TracebackType
from typing import Any

import pytest

from my_pa.application.commands import CreateTask
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeSubjectKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.tables import knowledge_assertion_proposals
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_knowledge_assertion_repository import (
    WHEN,
    KnowledgeRuntime,
    counts,
    create_command,
    knowledge_events,
    new_principal,
)
from tests.database.test_knowledge_assertion_review import (
    ReviewRuntime,
    _queued,
    decisions_of,
    proposal_of,
)
from tests.database.test_knowledge_assertion_submissions import (
    CLIENT,
    PAYMENT,
    SUBMIT_GRANTS,
    SubmitRuntime,
    add_direct_payment_head,
    external,
    table_count,
)
from tests.database.test_knowledge_checkpoint_idempotency_replay import (
    CHECKPOINT_GRANTS,
    CheckpointRuntime,
    _checkpoint_row,
    _ledger,
)
from tests.database.test_task_record_events import next_sequence

pytestmark = [pytest.mark.database, pytest.mark.recovery]

CLI_SURFACE = OperatorSurface.CLI


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


@pytest.fixture
def checkpoint_runtime(disposable_database: str) -> Iterator[tuple[CheckpointRuntime, list[bool]]]:
    composed = CheckpointRuntime(disposable_database)
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


def test_a_checkpoint_lost_after_commit_replays_the_exact_envelope(
    checkpoint_runtime: tuple[CheckpointRuntime, list[bool]],
) -> None:
    service, armed = checkpoint_runtime
    principal = new_principal()
    profile = service.profile(principal)
    service.checkpoint(principal, profile, envelope="synthetic-token-v1")
    command = service.command(profile, expected=1, envelope="synthetic-token-v2")
    remote = {
        "transport": CaptureTransport.REMOTE_CLIENT,
        "grants": CHECKPOINT_GRANTS,
        "client_id": CLIENT,
    }
    before = counts(service.engine, principal)
    sequence = next_sequence(service.engine, principal)
    armed.append(True)
    lost = service.invoke(command, principal_id=principal, **remote)
    assert lost.error is not None, "the injected loss must reach the caller as a failure"
    ledger = _ledger(service.engine, principal)
    row = _checkpoint_row(service.engine, principal)
    assert row is not None
    assert row["version"] == 2

    retried: dict[str, Any] = service.ok(command, principal_id=principal, **remote)
    assert (retried["outcome"], retried["checkpoint_version"]) == ("advanced", 2)
    assert retried["private_envelope"] == "synthetic-token-v2"
    assert service.ok(command, principal_id=principal, **remote) == retried
    assert _ledger(service.engine, principal) == ledger
    assert _checkpoint_row(service.engine, principal) == row
    assert counts(service.engine, principal) == before
    assert next_sequence(service.engine, principal) == sequence
    # A changed retry is a new request: the lost-response recovery answer.
    changed = service.checkpoint(principal, profile, expected=1, envelope="synthetic-token-v2b")
    assert (changed["reason"], changed["private_envelope"]) == (
        "stale_expected_version",
        "synthetic-token-v2",
    )


# ---- KLP-WP-04 slice C: Knowledge review.decide lost after COMMIT -------------------


@pytest.fixture
def review_runtime(disposable_database: str) -> Iterator[tuple[ReviewRuntime, list[bool]]]:
    composed = ReviewRuntime(disposable_database)
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


def test_a_review_accept_lost_after_commit_replays_and_stages_no_second_event(
    review_runtime: tuple[ReviewRuntime, list[bool]],
) -> None:
    """KLP-AC-139 (decide): the stored seven-key result, no second mutation or event."""
    service, armed = review_runtime
    principal, _entity, case = _queued(service)
    command = service.decide_command(case, Disposition.ACCEPT)
    request_id = issue_identifier(IdKind.CORRELATION)
    armed.append(True)
    lost = service.invoke_with_request_id(
        command, principal_id=principal, request_id=request_id, operator_surface=CLI_SURFACE
    )
    assert lost.error is not None, "the injected loss must reach the caller as a failure"
    committed = counts(service.engine, principal)
    assert committed["knowledge_assertions"] == 1
    sequence = next_sequence(service.engine, principal)
    (event,) = knowledge_events(service.engine, principal)
    (decision,) = decisions_of(service.engine, case)

    retried = service.invoke_with_request_id(
        command, principal_id=principal, request_id=request_id, operator_surface=CLI_SURFACE
    )
    assert retried.error is None, retried.error
    assert retried.result is not None
    assert retried.result["decision_id"] == decision["decision_id"]
    assert retried.result["assertion_id"] == event["record_id"]
    assert retried.result["receipt_id"] == event["source_receipt_id"]
    assert retried.result["proposal_state"] == "accepted"
    assert counts(service.engine, principal) == committed
    assert next_sequence(service.engine, principal) == sequence
    assert len(decisions_of(service.engine, case)) == 1
    again = service.invoke_with_request_id(
        command, principal_id=principal, request_id=request_id, operator_surface=CLI_SURFACE
    )
    assert again.result == retried.result


# ---- KLP-WP-07: the DOMAIN_OWNED / Review-queued submit outcomes lost after COMMIT ------

_REMOTE: dict[str, Any] = {
    "transport": CaptureTransport.REMOTE_CLIENT,
    "grants": SUBMIT_GRANTS,
    "client_id": CLIENT,
}


def _task(service: SubmitRuntime, principal: str) -> str:
    created = service.ok(
        CreateTask(
            title="Synthetic recovery task",
            idempotency_key="klp07-recovery-task",
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        ),
        principal_id=principal,
    )
    found = next(value for value in _strings(created) if value.startswith("tsk_"))
    return found


def _strings(document: object) -> Iterator[str]:
    if isinstance(document, str):
        yield document
    elif isinstance(document, dict):
        for value in document.values():
            yield from _strings(value)
    elif isinstance(document, list | tuple):
        for value in document:
            yield from _strings(value)


@pytest.mark.parametrize(
    ("predicate", "routed", "outcome"),
    [
        ("project.critical_date", True, "domain_owned_routed"),
        ("project.decision", False, "domain_owned_no_intake"),
        ("project.financial_fact", False, "review_queued"),
    ],
    ids=["routed_critical_date", "decision_no_intake", "review_queued"],
)
def test_a_project_submit_outcome_lost_after_commit_replays_and_writes_nothing_more(
    submit_runtime: tuple[SubmitRuntime, list[bool]],
    predicate: str,
    routed: bool,
    outcome: str,
) -> None:
    service, armed = submit_runtime
    principal = new_principal()
    profile = service.profile(principal)
    project = service.project(principal, "recovery-route")
    extra: dict[str, Any] = {}
    if predicate == "project.critical_date":
        extra["qualifier"] = {"date_kind": "deadline"}
        value = "2026-11-20T00:00:00+00:00"
    else:
        value = "Synthetic recovery fact"
    if routed:
        extra["owner_ref"] = {"kind": "task", "id": _task(service, principal)}
    command = service.submit_command(
        principal,
        profile,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        subject_id=project,
        predicate=predicate,
        value=value,
        candidate="lost",
        evidence=(external("obj-lost"),),
        **extra,
    )
    armed.append(True)
    lost = service.invoke(command, principal_id=principal, **_REMOTE)
    assert lost.error is not None, "the injected loss must reach the caller as a failure"
    committed = counts(service.engine, principal)
    assert committed["knowledge_assertion_submissions"] == 1
    assert committed["knowledge_assertions"] == 0
    proposals = table_count(service.engine, knowledge_assertion_proposals, principal)
    assert proposals == (1 if outcome == "review_queued" else 0)
    sequence = next_sequence(service.engine, principal)

    retried: dict[str, Any] = service.ok(command, principal_id=principal, **_REMOTE)
    assert retried["outcome"] == outcome, retried
    if routed:
        assert retried["routed_record_id"] == extra["owner_ref"]["id"]
        assert retried["canonical_owner"] == "tasks"
    if outcome == "review_queued":
        assert retried["review_case_id"] is not None
        assert proposal_of(service.engine, retried["review_case_id"])["state"] == "needs_review"
    assert counts(service.engine, principal) == committed
    assert table_count(service.engine, knowledge_assertion_proposals, principal) == proposals
    assert next_sequence(service.engine, principal) == sequence
    assert service.ok(command, principal_id=principal, **_REMOTE) == retried


@pytest.mark.parametrize("disposition", [Disposition.REJECT, Disposition.DEFER])
def test_a_non_promoting_review_decision_lost_after_commit_replays(
    review_runtime: tuple[ReviewRuntime, list[bool]], disposition: Disposition
) -> None:
    service, armed = review_runtime
    principal, _entity, case = _queued(service)
    command = service.decide_command(
        case,
        disposition,
        reason="Synthetic reason" if disposition is Disposition.REJECT else None,
    )
    request_id = issue_identifier(IdKind.CORRELATION)
    armed.append(True)
    lost = service.invoke_with_request_id(
        command, principal_id=principal, request_id=request_id, operator_surface=CLI_SURFACE
    )
    assert lost.error is not None, "the injected loss must reach the caller as a failure"
    committed = counts(service.engine, principal)
    sequence = next_sequence(service.engine, principal)
    (decision,) = decisions_of(service.engine, case)
    state = proposal_of(service.engine, case)["state"]
    assert state == ("rejected" if disposition is Disposition.REJECT else "deferred")

    retried = service.invoke_with_request_id(
        command, principal_id=principal, request_id=request_id, operator_surface=CLI_SURFACE
    )
    assert retried.error is None, retried.error
    assert retried.result is not None
    assert retried.result["decision_id"] == decision["decision_id"]
    assert retried.result["proposal_state"] == state
    assert retried.result["assertion_id"] is None
    assert counts(service.engine, principal) == committed
    assert next_sequence(service.engine, principal) == sequence
    assert len(decisions_of(service.engine, case)) == 1
    assert proposal_of(service.engine, case)["state"] == state


def test_a_record_event_flush_failure_rolls_the_whole_submit_back(
    submit_runtime: tuple[SubmitRuntime, list[bool]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Race 13 (KLP-AC-102): the flush is the last work before COMMIT, in one transaction."""
    from my_pa.infrastructure.persistence import unit_of_work as unit_of_work_module

    service, _armed = submit_runtime
    principal = new_principal()
    profile = service.profile(principal)
    org = service.entity(principal, "flush")
    before = counts(service.engine, principal)
    sequence = next_sequence(service.engine, principal)
    original = unit_of_work_module.flush_record_events
    staged: list[int] = []

    def refuse(writer: Any, drafts: Any) -> None:  # noqa: ANN401
        staged.append(len(drafts))
        raise RuntimeError("injected Record Event flush failure")

    monkeypatch.setattr(unit_of_work_module, "flush_record_events", refuse)
    command = service.submit_command(principal, profile, subject_id=org, candidate="flush")
    failed = service.invoke(command, principal_id=principal, **_REMOTE)
    assert failed.error is not None
    assert staged == [1], "the direct create had staged its one event when the flush failed"
    assert counts(service.engine, principal) == before
    assert next_sequence(service.engine, principal) == sequence
    monkeypatch.setattr(unit_of_work_module, "flush_record_events", original)
    created: dict[str, Any] = service.ok(command, principal_id=principal, **_REMOTE)
    assert created["outcome"] == "direct_created", created
    after = counts(service.engine, principal)
    assert after["knowledge_assertion_submissions"] == 1
    assert after["knowledge_assertions"] == 1
    assert after["record_events"] == 1
