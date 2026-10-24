"""AT-012 (S3 races, two connections): the knowledge clock and the S3 writes serialize.

S3 contract sections 3.2, 3.3, 3.4, 6.2 and 8.2 against PostgreSQL. Each case
holds what the writers need on a separate connection, starts the writers
through `ApplicationService.invoke`, waits until PostgreSQL reports each one
waiting, and only then releases, so the writers really overlap:

* two lineage writers of one Principal queue on the Principal's commit-mark
  allocator, and their marks stay contiguous; a writer of another Principal
  never waits on it;
* a contest racing a close serializes (on the allocator, and independently on
  the Issue the contest shares), so either the close lands and the contest is
  refused on the closed Issue, or the contest lands and the close is held by
  the gate -- never both;
* a void racing a new handoff of the same chain serializes, so the new event
  follows the chain's last live holder whichever lands first;
* a reader never sees a mark whose transaction has not committed: the horizon
  and every `known_at` answer stay at the committed mark while an allocation
  is in flight.

Every outcome is checked as an invariant over both orders, since PostgreSQL
does not promise which waiter is granted first. Each wait is bounded and each
thread joined with a timeout. Every identity is synthetic.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from itertools import pairwise
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL
from tests.database.lineage_s2_harness import close, handoff, resolution_anchor
from tests.database.lineage_s3_harness import (
    GATEWAY,
    S3Runtime,
    blocks_scene,
    contest,
    contradicts,
    correct_handoff,
    mark_count,
    shortly_after,
)

from my_pa.application.commands import ListIssueHandoffs
from my_pa.contracts.v1.envelope import ResponseEnvelope

pytestmark = pytest.mark.database

BLOCK_DEADLINE_SECONDS: Final = 15.0
JOIN_TIMEOUT_SECONDS: Final = 60.0

_HOLD_ALLOCATOR: Final = "SELECT knowledge.lineage_commit_mark(CAST(:principal AS text))"
_HOLD_ISSUE: Final = (
    "SELECT situation_id FROM knowledge.situations WHERE situation_id = :id FOR UPDATE"
)
_HOLD_COMMITMENT: Final = (
    "SELECT commitment_id FROM knowledge.commitments WHERE commitment_id = :id FOR UPDATE"
)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3Runtime]:
    composed = S3Runtime(disposable_database)
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
    runtime: S3Runtime, hold: str, parameters: dict[str, str], writers: list[Callable[[], Any]]
) -> list[ResponseEnvelope]:
    """Hold one lock, start every writer, wait until all wait, release (roll back)."""
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


def _invoke(runtime: S3Runtime, command: Any, **kwargs: Any) -> Callable[[], ResponseEnvelope]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    return lambda: runtime.invoke(command, **kwargs)


def _detail(envelope: ResponseEnvelope) -> tuple[str, list[str]] | None:
    error = envelope.to_canonical_dict().get("error")
    if error is None:
        return None
    assert isinstance(error, dict)
    return str(error["code"]), list(error["safe_details"])


def _marks(engine: Engine, principal: str = PRINCIPAL) -> list[int]:
    with engine.connect() as connection:
        return [
            int(value)
            for value in connection.execute(
                text(
                    "SELECT commit_seq FROM knowledge.lineage_commit_marks "
                    "WHERE principal_id = :p ORDER BY commit_seq"
                ),
                {"p": principal},
            ).scalars()
        ]


def _horizon(engine: Engine, principal: str = PRINCIPAL) -> Any:  # noqa: ANN401
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT last_seq, last_marked_at FROM knowledge.lineage_commit_sequences "
                "WHERE principal_id = :p"
            ),
            {"p": principal},
        ).one()


def _closure(runtime: S3Runtime, key: str) -> tuple[dict[str, object], ...]:
    _, _, anchor = runtime.evidence_source(f"{key}-closure")
    return (anchor,)


# ---- the allocator -----------------------------------------------------------------------


def test_two_writers_of_one_principal_serialize_on_the_allocator(runtime: S3Runtime) -> None:
    first = blocks_scene(runtime, "allocator-a")
    second = blocks_scene(runtime, "allocator-b")
    before = _marks(runtime.engine)
    # Neither write touches the other's rows: only the allocator makes them queue.
    answers = _race(
        runtime,
        _HOLD_ALLOCATOR,
        {"principal": PRINCIPAL},
        [
            _invoke(runtime, contest(first["link"], 1, "allocator-a", (first["contradicts"],))),
            _invoke(runtime, contest(second["link"], 1, "allocator-b", (second["contradicts"],))),
        ],
    )
    assert [_detail(answer) for answer in answers] == [None, None]
    after = _marks(runtime.engine)
    # The held allocation rolled back: two new marks, contiguous from 1.
    assert after == list(range(1, len(before) + 3))
    with runtime.engine.connect() as connection:
        stamped = sorted(
            int(value)
            for value in connection.execute(
                text(
                    "SELECT commit_seq FROM knowledge.lineage_write_requests "
                    "WHERE capability = 'records.associations.contest'"
                )
            ).scalars()
        )
    assert stamped == after[-2:]


def test_writers_of_two_principals_do_not_wait(runtime: S3Runtime) -> None:
    mine = blocks_scene(runtime, "principals-mine")
    theirs_issue = runtime.issue("principals-theirs", principal_id=OTHER_PRINCIPAL)
    with runtime.engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as pool:
        held = holder.begin()
        holder.execute(text(_HOLD_ALLOCATOR), {"principal": PRINCIPAL})
        # Another Principal's lineage write completes while this one's allocator is held.
        other = pool.submit(
            _invoke(
                runtime,
                close(theirs_issue, 1, "principals-theirs", _theirs_closure(runtime)),
                principal_id=OTHER_PRINCIPAL,
            )
        )
        assert _detail(other.result(timeout=BLOCK_DEADLINE_SECONDS)) is None
        # This Principal's write waits for the held allocator.
        waiting = pool.submit(
            _invoke(runtime, contest(mine["link"], 1, "principals-mine", (mine["contradicts"],)))
        )
        _wait_for(runtime.engine, 1, [waiting])
        held.rollback()
        assert _detail(waiting.result(timeout=JOIN_TIMEOUT_SECONDS)) is None
    # Each Principal's marks stay contiguous from 1.
    for principal in (PRINCIPAL, OTHER_PRINCIPAL):
        marks = _marks(runtime.engine, principal)
        assert marks == list(range(1, len(marks) + 1)), principal
        assert len(marks) == mark_count(runtime.engine, principal)


def _theirs_closure(runtime: S3Runtime) -> tuple[dict[str, object], ...]:
    """A closure set on the other Principal's own note."""
    meeting_id, note_id = runtime.note("principals-theirs-source", principal_id=OTHER_PRINCIPAL)
    return (resolution_anchor(meeting_id, note_id),)


# ---- contest and close ---------------------------------------------------------------------


@pytest.mark.parametrize("contest_first", [True, False])
def test_contest_racing_a_close_serializes(runtime: S3Runtime, contest_first: bool) -> None:
    key = f"race-close-{contest_first}"
    scene = blocks_scene(runtime, key)
    issue = scene["issue"]
    contest_write = _invoke(runtime, contest(scene["link"], 1, key, (scene["contradicts"],)))
    close_write = _invoke(runtime, close(issue, 1, key, _closure(runtime, key)))
    # Hold the Issue as a close does: the contest waits on its share of it even
    # with the allocator free, and the other writer queues behind.
    writers = [contest_write, close_write] if contest_first else [close_write, contest_write]
    answers = _race(runtime, _HOLD_ISSUE, {"id": issue}, writers)
    contested, closed = answers if contest_first else answers[::-1]
    outcomes = (_detail(contested), _detail(closed))
    # Exactly one lands; the other is refused for the reason that order implies.
    assert outcomes in (
        (None, ("conflict", ["closure_gate"])),
        (("conflict", ["state"]), None),
    ), outcomes
    readiness = runtime.readiness(issue)
    if outcomes[0] is None:
        assert readiness["state"] != "closed"
        assert readiness["contested_links"] == [
            {"link_id": scene["link"], "relation_type": "blocks"}
        ]
    else:
        assert readiness["state"] == "closed"


# ---- void and a new handoff ----------------------------------------------------------------


@pytest.mark.parametrize("void_first", [True, False])
def test_a_void_racing_a_new_handoff_serializes(runtime: S3Runtime, void_first: bool) -> None:
    key = f"race-void-{void_first}"
    issue = runtime.issue(key)
    commitment = runtime.commitment(key)
    runtime.member(issue, "commitment", commitment, key, "discussion")
    created = str(runtime.commitment_view(commitment)["created_at"])
    events = []
    for number, side in enumerate(("counterparty", "principal"), start=1):
        events.append(
            runtime.ok(
                handoff(
                    issue,
                    commitment,
                    side,
                    shortly_after(created, 100 * number),
                    f"{key}-{number}",
                    runtime.handoff_anchor(f"{key}-{number}"),
                ),
                surface=GATEWAY,
            )["handoff"]
        )
    meeting_id, note_id = runtime.note(f"{key}-void")
    void = _invoke(
        runtime,
        correct_handoff(events[1]["handoff_id"], "void", key, contradicts(meeting_id, note_id)),
    )
    # Event 2 left the Principal: a new event from the counterparty follows it,
    # one from the Principal follows event 1 once event 2 is voided.
    new_after_void = _invoke(
        runtime,
        handoff(
            issue,
            commitment,
            "principal",
            shortly_after(created, 300),
            f"{key}-new",
            runtime.handoff_anchor(f"{key}-new"),
        ),
    )
    writers = [void, new_after_void] if void_first else [new_after_void, void]
    answers = _race(runtime, _HOLD_COMMITMENT, {"id": commitment}, writers)
    voided, recorded = answers if void_first else answers[::-1]
    outcomes = (_detail(voided), _detail(recorded))
    if void_first:
        # The void lands; the new event follows event 1's holder (the Principal).
        assert outcomes == (None, None), outcomes
    else:
        # The new event lands first from the Principal side, which event 2 is
        # not on, so it is refused; the void of the still-last event 2 lands.
        assert outcomes == (None, ("invalid_request", ["from"])), outcomes
    listed = runtime.ok(ListIssueHandoffs(issue_id=issue, commitment_id=commitment))["handoffs"]
    live = [event for event in listed if not event["voided"]]
    # Holder continuity holds over the live events, whichever order landed.
    for earlier, later in pairwise(live):
        assert earlier["to"] == later["from"]


# ---- readers -------------------------------------------------------------------------------


def test_a_reader_never_sees_a_half_committed_mark(runtime: S3Runtime) -> None:
    scene = blocks_scene(runtime, "reader")
    committed = _horizon(runtime.engine)
    listed = runtime.ok(ListIssueHandoffs(issue_id=scene["issue"]))
    with runtime.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as pool:
        held = holder.begin()
        allocated = holder.execute(text(_HOLD_ALLOCATOR), {"principal": PRINCIPAL}).scalar_one()
        assert int(allocated) == committed.last_seq + 1
        # A reader runs lock-free while the allocation is in flight, and sees none of it.
        read = pool.submit(lambda: runtime.ok(ListIssueHandoffs(issue_id=scene["issue"])))
        during = read.result(timeout=BLOCK_DEADLINE_SECONDS)
        assert during["known_at"] == listed["known_at"]
        assert _horizon(runtime.engine) == committed
        assert len(_marks(runtime.engine)) == committed.last_seq
        held.rollback()
    # The rolled-back allocation never existed; the next write takes the next mark.
    runtime.ok(contest(scene["link"], 1, "reader", (scene["contradicts"],)), surface=GATEWAY)
    assert _marks(runtime.engine) == list(range(1, committed.last_seq + 2))
    after = runtime.ok(ListIssueHandoffs(issue_id=scene["issue"]))
    assert after["known_at"] > listed["known_at"]
