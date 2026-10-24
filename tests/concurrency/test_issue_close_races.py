"""AT-007 (races, two connections): an Issue close serializes with what it depends on.

S2 contract sections 3.3 and 6.2 against PostgreSQL. Each case holds the row
both writers need on a separate connection, starts the writers through
`ApplicationService.invoke` (or a native capability), waits until PostgreSQL
reports every writer waiting, and only then releases the row, so the two
really overlap:

* two closes, or two reopens, under one `expected_version` admit exactly one;
* a close racing a membership add or end serializes on the Issue (the close
  holds it `FOR UPDATE`; every membership writer shares it, new in S2), so the
  gate's answer is about the membership set that actually committed;
* a close racing a Constraint reopen serializes on the member's native row
  (the close shares it), so a close never commits over a member that was
  reopened under it -- the reopen lands after, on a closed Issue that does not
  follow it (no cascade);
* a close racing an archive of a member's resolution source serializes on
  the Capture root (the close shares every resolution source, R2-F06).

Every outcome is checked as an invariant over both orders, since PostgreSQL
does not promise which waiter is granted first. Each wait is bounded and each
thread joined with a timeout, so a build that takes no lock reports rather
than hangs. Two handoffs of one Commitment's chain serialize on the chain's
advisory key, so the second re-reads the chain the first extended, and two
`blocks` asserts that would together close a cycle serialize on the
Principal's `:blocks` key, so the second's cycle search sees the first's
edge. Every identity is synthetic.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    capture,
    capture_anchor,
    meeting,
    membership,
    note_anchor,
)
from tests.database.lineage_s2_harness import (
    GATEWAY,
    S2Runtime,
    all_s2_counts,
    assertion,
    close,
    correct,
    handoff,
    reopen,
)

from my_pa.application.commands import (
    ArchiveCapture,
    EndIssueMembership,
    ReadIssue,
    ReopenConstraint,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.project_controls.constraint import ConstraintLifecycleState
from my_pa.domain.task.lifecycle import TaskLifecycleState

pytestmark = pytest.mark.database

BLOCK_DEADLINE_SECONDS: Final = 15.0
JOIN_TIMEOUT_SECONDS: Final = 60.0


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S2Runtime]:
    composed = S2Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _waiting(engine: Engine) -> int:
    with engine.connect() as observer:
        return int(
            observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
        )


def _wait_for(engine: Engine, waiters: int, futures: list[Future[Any]]) -> None:
    deadline = time.monotonic() + BLOCK_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        assert not any(future.done() for future in futures), "a side did not wait"
        if _waiting(engine) >= waiters:
            return
        time.sleep(0.02)
    pytest.fail("the expected sides never blocked")


def _race(
    runtime: S2Runtime, hold: str, parameters: dict[str, str], writers: list[Callable[[], Any]]
) -> list[ResponseEnvelope]:
    """Hold one row `FOR UPDATE`, start every writer, wait until all wait, release."""
    with runtime.engine.connect() as holder, ThreadPoolExecutor(max_workers=len(writers)) as pool:
        held = holder.begin()
        holder.execute(text(hold), parameters)
        futures: list[Future[Any]] = []
        for writer in writers:
            futures.append(pool.submit(writer))
            # Started one at a time, so the queue order is the list order.
            _wait_for(runtime.engine, len(futures), futures)
        held.rollback()
        return [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures]


_HOLD_ISSUE: Final = (
    "SELECT situation_id FROM knowledge.situations WHERE situation_id = :id FOR UPDATE"
)


def _error(envelope: ResponseEnvelope) -> dict[str, Any] | None:
    error = envelope.to_canonical_dict().get("error")
    assert error is None or isinstance(error, dict)
    return error


def _detail(envelope: ResponseEnvelope) -> tuple[str, list[str]] | None:
    error = _error(envelope)
    return None if error is None else (str(error["code"]), list(error["safe_details"]))


def _invoke(runtime: S2Runtime, command: Any) -> Callable[[], ResponseEnvelope]:  # noqa: ANN401
    return lambda: runtime.invoke(command, surface=GATEWAY)


def _closure(runtime: S2Runtime, key: str) -> tuple[dict[str, object], ...]:
    _, _, anchor = runtime.evidence_source(f"{key}-closure")
    return (anchor,)


def _state(runtime: S2Runtime, issue: str) -> tuple[str, int]:
    view = runtime.ok(ReadIssue(issue_id=issue))["issue"]
    return str(view["state"]), int(view["version"])


def test_concurrent_closes_with_one_expected_version_admit_one(runtime: S2Runtime) -> None:
    issue = runtime.issue("race-close")
    first, second = _race(
        runtime,
        _HOLD_ISSUE,
        {"id": issue},
        [
            _invoke(runtime, close(issue, 1, "race-close-a", _closure(runtime, "a"))),
            _invoke(runtime, close(issue, 1, "race-close-b", _closure(runtime, "b"))),
        ],
    )
    outcomes = sorted([_detail(first), _detail(second)], key=lambda item: item is not None)
    assert outcomes == [None, ("conflict", ["stale_version"])]
    assert _state(runtime, issue) == ("closed", 2)


def test_concurrent_reopens_with_one_expected_version_admit_one(runtime: S2Runtime) -> None:
    issue = runtime.issue("race-reopen")
    runtime.ok(close(issue, 1, "race-reopen", _closure(runtime, "race-reopen")), surface=GATEWAY)
    first, second = _race(
        runtime,
        _HOLD_ISSUE,
        {"id": issue},
        [
            _invoke(runtime, reopen(issue, 2, "race-reopen-a")),
            _invoke(runtime, reopen(issue, 2, "race-reopen-b")),
        ],
    )
    outcomes = sorted([_detail(first), _detail(second)], key=lambda item: item is not None)
    assert outcomes == [None, ("conflict", ["stale_version"])]
    assert _state(runtime, issue) == ("active", 3)


def test_close_racing_a_membership_add_serializes(runtime: S2Runtime) -> None:
    """The membership shares the Issue the close holds: never a close over a new open member."""
    issue = runtime.issue("race-add")
    open_task = runtime.task("race-add")
    closure = _closure(runtime, "race-add")
    before = all_s2_counts(runtime.engine)
    closed, added = _race(
        runtime,
        _HOLD_ISSUE,
        {"id": issue},
        [
            _invoke(runtime, close(issue, 1, "race-add", closure)),
            _invoke(runtime, membership(issue, "task", open_task, "race-add", role="work")),
        ],
    )
    if _detail(closed) is None:
        # The close committed first; the add then found the Issue closed.
        assert _detail(added) == ("conflict", ["state"])
        assert all_s2_counts(runtime.engine)["record_links"] == before["record_links"]
        assert _state(runtime, issue) == ("closed", 2)
    else:
        # The add committed first; the gate then saw the open member.
        assert _detail(closed) == ("conflict", ["closure_gate"])
        assert _detail(added) is None
        assert _state(runtime, issue) == ("open", 1)


def test_close_racing_a_membership_end_serializes(runtime: S2Runtime) -> None:
    """The end shares the Issue too (S2 section 6.2): the gate sees the committed set."""
    issue = runtime.issue("race-end")
    task_id = runtime.task("race-end")
    link = runtime.member(issue, "task", task_id, "race-end", "work")
    runtime.transition(task_id, TaskLifecycleState.CANCELLED, "race-end")
    closure = _closure(runtime, "race-end")
    closed, ended = _race(
        runtime,
        _HOLD_ISSUE,
        {"id": issue},
        [
            _invoke(runtime, close(issue, 1, "race-end", closure)),
            _invoke(
                runtime,
                EndIssueMembership(
                    link_id=link,
                    expected_revision=1,
                    idempotency_key="s2-race-end",
                    reason="Cancelled work leaves the Issue.",
                ),
            ),
        ],
    )
    if _detail(closed) is None:
        # Closed only because the end had committed: the cancelled Task was out.
        assert _detail(ended) is None
        assert _state(runtime, issue) == ("closed", 2)
    else:
        # The close went first and saw the cancelled member; the end followed.
        assert _detail(closed) == ("conflict", ["closure_gate"])
        assert _detail(ended) is None
        assert _state(runtime, issue) == ("open", 1)


def test_close_racing_a_constraint_reopen_serializes(runtime: S2Runtime) -> None:
    issue = runtime.issue("race-cst")
    project = runtime.project_with_constraints("race-cst")
    constraint = runtime.constraint(project, "race-cst")
    link = runtime.member(issue, "constraint", constraint, "race-cst", "constraint")
    runtime.close_constraint(constraint, "race-cst")
    _, _, anchor = runtime.evidence_source("race-cst-res")
    runtime.ok(correct(link, 1, "race-cst", (anchor,)), surface=GATEWAY)
    closure = _closure(runtime, "race-cst")
    version = runtime.constraint_version(constraint)
    closed, reopened = _race(
        runtime,
        "SELECT constraint_id FROM knowledge.project_constraints WHERE constraint_id = :id "
        "FOR UPDATE",
        {"id": constraint},
        [
            _invoke(runtime, close(issue, 1, "race-cst", closure)),
            lambda: runtime.invoke(
                ReopenConstraint(
                    constraint_id=constraint,
                    to_state=ConstraintLifecycleState.IN_PROGRESS,
                    expected_version=version,
                    reason="Synthetic reopen.",
                    idempotency_key="s2-race-cst-reopen",
                )
            ),
        ],
    )
    assert _detail(reopened) is None, "the native reopen is a native write and always lands"
    if _detail(closed) is None:
        # The close shared the member and committed; the reopen followed it, and
        # the closed Issue does not follow the native change (no cascade).
        assert _state(runtime, issue) == ("closed", 2)
    else:
        assert _detail(closed) == ("conflict", ["closure_gate"])
        assert _state(runtime, issue) == ("open", 1)


def test_close_racing_a_resolution_source_archive_serializes(runtime: S2Runtime) -> None:
    """The close shares the member's resolution source: an archive cannot slip between."""
    issue = runtime.issue("race-archive")
    task_id = runtime.task("race-archive")
    link = runtime.member(issue, "task", task_id, "race-archive", "work")
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, "race-archive")
    root, version, _ = capture(runtime, "race-archive")
    runtime.ok(
        correct(
            link,
            1,
            "race-archive",
            (capture_anchor(root, version, NOTE_BODY, role="resolution"),),
        ),
        surface=GATEWAY,
    )
    # The closure set does not name the Capture: only the member's evidence does.
    closure = _closure(runtime, "race-archive")
    closed, archived = _race(
        runtime,
        "SELECT capture_id FROM knowledge.captures WHERE capture_id = :id FOR UPDATE",
        {"id": root},
        [
            _invoke(runtime, close(issue, 1, "race-archive", closure)),
            lambda: runtime.invoke(
                ArchiveCapture(
                    capture_id=root,
                    expected_lifecycle_revision=0,
                    idempotency_key="s2-race-archive",
                    reason="synthetic archive",
                )
            ),
        ],
    )
    assert _detail(archived) is None
    if _detail(closed) is None:
        assert _state(runtime, issue) == ("closed", 2)
    else:
        # The archive committed first: the gate saw the evidence unavailable.
        assert _detail(closed) == ("conflict", ["closure_gate"])
        assert _state(runtime, issue) == ("open", 1)


def test_concurrent_handoffs_on_one_commitment_admit_one(runtime: S2Runtime) -> None:
    """Both read the chain under its advisory key: the second sees the first's event."""
    issue = runtime.issue("race-handoff")
    commitment = runtime.commitment("race-handoff")
    runtime.member(issue, "commitment", commitment, "race-handoff", "work")
    created = datetime.fromisoformat(str(runtime.commitment_view(commitment)["created_at"]))
    effective = (created + timedelta(milliseconds=1)).isoformat()
    anchor = runtime.handoff_anchor("race-handoff")
    before = all_s2_counts(runtime.engine)["issue_responsibility_events"]
    first, second = _race(
        runtime,
        "SELECT commitment_id FROM knowledge.commitments WHERE commitment_id = :id FOR UPDATE",
        {"id": commitment},
        [
            _invoke(
                runtime, handoff(issue, commitment, "counterparty", effective, "race-a", anchor)
            ),
            _invoke(
                runtime, handoff(issue, commitment, "counterparty", effective, "race-b", anchor)
            ),
        ],
    )
    outcomes = sorted([_detail(first), _detail(second)], key=lambda item: item is not None)
    # The loser re-read the chain: the Principal holds now, so `from` is the wrong side.
    assert outcomes == [None, ("invalid_request", ["from"])]
    assert all_s2_counts(runtime.engine)["issue_responsibility_events"] == before + 1


def test_concurrent_blocks_asserts_cannot_form_a_cycle(runtime: S2Runtime) -> None:
    """A -> B and B -> A at once: the `:blocks` key serializes the two cycle searches.

    Both writers wait on the held Task, are released together, and then take
    the Principal's `:blocks` key in turn; the second searches only after the
    first committed, so it finds the edge and refuses (S2 section 3.1).
    """
    first_task, second_task = runtime.task("race-blocks-a"), runtime.task("race-blocks-b")
    meeting_id, note_id = meeting(runtime, "race-blocks")
    anchor = note_anchor(meeting_id, note_id, NOTE_BODY, role="corroborates", passage=None)
    a, b = ("task", first_task), ("task", second_task)
    first, second = _race(
        runtime,
        "SELECT task_id FROM knowledge.tasks WHERE task_id = :id FOR UPDATE",
        {"id": first_task},
        [
            _invoke(runtime, assertion("blocks", a, b, "race-blocks-ab", (anchor,))),
            _invoke(runtime, assertion("blocks", b, a, "race-blocks-ba", (anchor,))),
        ],
    )
    outcomes = sorted([_detail(first), _detail(second)], key=lambda item: item is not None)
    assert outcomes == [None, ("invalid_request", ["blocks_cycle"])]
    with runtime.engine.connect() as connection:
        written = connection.execute(
            text("SELECT count(*) FROM knowledge.record_links WHERE relation_type = 'blocks'")
        ).scalar_one()
    assert written == 1
