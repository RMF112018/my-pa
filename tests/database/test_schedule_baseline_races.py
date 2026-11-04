"""Schedule Scenarios S6-2: the section 12.7 race tests P49-P54 (contract 14.11.2, R9-F03).

Two writers of one Project, each in its own transaction on its own
connection, are forced through one interleaving: the first stops at the seam
after its chain read (holding the Project lock J), the second is started and
the first is released only once the second is observed waiting on an advisory
lock in `pg_locks` -- or, if no lock holds it back, has reached the same seam
itself. Nothing is ordered by a sleep. The writes call `write_baseline`
directly (the S6-3 prologue's Principal lock P would serialize them before J
is reached; J is what is under test).

P50 and P54 assert the *class* of the loser's answer: a typed
`BaselineWriteRefusedError`, never the backstop's `ScheduleBaselineRaceError`.
P51-P53 are declared layered (P2-20): they assert the invariant, and a lost
race may answer either class.

`database` tier (`database_clone` by default). Every value is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.contracts.ports import (
    BaselineWriteRefusedError,
    BaselineWritten,
    ScheduleBaselineRaceError,
)
from my_pa.domain.schedule import ScheduleImportApproval
from my_pa.domain.schedule.baselines import (
    ApproveRequest,
    BaselineRefusal,
    BaselineRequest,
    BaselineType,
    ProposeRequest,
    SetGoverningRequest,
    WithdrawRequest,
)
from my_pa.domain.schedule.plane import PlaneProvenance, writer_bucket
from my_pa.infrastructure.persistence.schedule_scenarios import SqlAlchemyScenarioUnitOfWork
from tests.database.schedule_plane_world import (
    OPERATOR,
    Interleaving,
    PlaneWorld,
    advisory_waiter_seen,
    client,
    disposed_lease_engines,  # noqa: F401 - an autouse fixture
    seed_world,
)

pytestmark = pytest.mark.database

P: Final = "prn_s62race0001"
CLIENT: Final = client("client-7")
OTHER_CLIENT: Final = client("client-8")
APPROVAL: Final = ScheduleImportApproval("Approval ref", date(2027, 1, 1), "Approved")
Outcome = tuple[str, object]


@pytest.fixture
def w(db_engine: Engine) -> PlaneWorld:
    return seed_world(db_engine, P, "s62ra", complete=12)


def _bucket(writer: PlaneProvenance) -> str:
    bucket = writer_bucket(writer.decision_channel, writer.asserting_client_id)
    assert bucket is not None
    return bucket


def _writes(
    request: BaselineRequest,
    *,
    writer: PlaneProvenance = OPERATOR,
    project_id: str | None = None,
) -> Callable[[SqlAlchemyScenarioUnitOfWork], object]:
    def action(uow: SqlAlchemyScenarioUnitOfWork) -> object:
        return uow.scenarios.write_baseline(
            P,
            request,
            reason="A synthetic race",
            approval=APPROVAL,
            writer=writer,
            project_id=project_id,
        )

    return action


def _commit(
    engine: Engine, request: BaselineRequest, writer: PlaneProvenance = OPERATOR
) -> BaselineWritten:
    with SqlAlchemyScenarioUnitOfWork(engine) as uow:
        action = _writes(request, writer=writer)
        written = action(uow)
    assert isinstance(written, BaselineWritten)
    return written


def _approve(publication: str) -> ApproveRequest:
    return ApproveRequest(
        type=BaselineType.CONTRACT, effective_from=date(2027, 1, 1), publication_id=publication
    )


def _split(first: Outcome, second: Outcome) -> tuple[list[object], list[object]]:
    winners = [value for kind, value in (first, second) if kind == "ok"]
    losers = [value for kind, value in (first, second) if kind == "error"]
    return winners, losers


def _events(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT seq, action, baseline_id, publication_id, label, proposal_ordinal "
                    "FROM knowledge.schedule_baseline_events ORDER BY seq"
                )
            )
        ]


def test_concurrent_approve_and_withdraw_write_one_decision(
    monkeypatch: pytest.MonkeyPatch, db_engine: Engine, w: PlaneWorld
) -> None:
    """P50: the loser reads the winner's decision under J and is refused by type."""
    proposal = _commit(
        db_engine, ProposeRequest(w.publications[0], BaselineType.CONTRACT, _bucket(CLIENT)), CLIENT
    )
    race = Interleaving.install(monkeypatch, db_engine, "chain_read")
    first, second = race.run(
        _writes(
            ApproveRequest(
                type=BaselineType.CONTRACT,
                effective_from=date(2027, 1, 1),
                baseline_id=proposal.baseline_id,
            )
        ),
        _writes(WithdrawRequest(proposal.baseline_id, _bucket(CLIENT)), writer=CLIENT),
    )
    winners, losers = _split(first, second)
    assert len(winners) == 1 and len(losers) == 1, (first, second)
    loser = losers[0]
    assert isinstance(loser, BaselineWriteRefusedError), loser
    assert loser.refusal is BaselineRefusal.CONFLICT_BASELINE_ID
    decisions = [event for event in _events(db_engine) if event[1] != "propose"]
    assert len(decisions) == 1


def test_concurrent_approvals_of_one_publication(
    monkeypatch: pytest.MonkeyPatch, db_engine: Engine, w: PlaneWorld
) -> None:
    """P51 (layered): one publication is approved at most once."""
    race = Interleaving.install(monkeypatch, db_engine, "chain_read")
    first, second = race.run(
        _writes(_approve(w.publications[0])), _writes(_approve(w.publications[0]))
    )
    winners, losers = _split(first, second)
    assert len(winners) == 1, (first, second)
    assert all(
        isinstance(loser, BaselineWriteRefusedError | ScheduleBaselineRaceError) for loser in losers
    )
    approvals = [event for event in _events(db_engine) if event[1] == "approve"]
    assert len(approvals) == 1


def test_concurrent_approvals_never_reuse_a_label(
    monkeypatch: pytest.MonkeyPatch, db_engine: Engine, w: PlaneWorld
) -> None:
    """P52 (layered): 2 approvals of 2 publications get 2 labels, never one twice."""
    race = Interleaving.install(monkeypatch, db_engine, "chain_read")
    first, second = race.run(
        _writes(_approve(w.publications[0])), _writes(_approve(w.publications[1]))
    )
    winners, losers = _split(first, second)
    assert all(isinstance(loser, ScheduleBaselineRaceError) for loser in losers), losers
    labels = [event[4] for event in _events(db_engine) if event[1] == "approve"]
    assert len(labels) == len(set(labels)) == len(winners)
    assert sorted(getattr(winner, "label") for winner in winners) == sorted(labels)  # noqa: B009
    assert winners and labels[0] == "BL-0"


def test_concurrent_proposals_on_one_publication(
    monkeypatch: pytest.MonkeyPatch, db_engine: Engine, w: PlaneWorld
) -> None:
    """P53 (layered): one publication carries at most one pending proposal."""
    race = Interleaving.install(monkeypatch, db_engine, "chain_read")
    first, second = race.run(
        _writes(
            ProposeRequest(w.publications[0], BaselineType.CONTRACT, _bucket(CLIENT)), writer=CLIENT
        ),
        _writes(
            ProposeRequest(w.publications[0], BaselineType.CONTRACT, _bucket(OTHER_CLIENT)),
            writer=OTHER_CLIENT,
        ),
    )
    winners, losers = _split(first, second)
    assert len(winners) == 1, (first, second)
    assert all(
        isinstance(loser, BaselineWriteRefusedError | ScheduleBaselineRaceError) for loser in losers
    )
    proposals = [event for event in _events(db_engine) if event[1] == "propose"]
    assert len(proposals) == 1


def test_pending_caps_hold_under_concurrency(
    monkeypatch: pytest.MonkeyPatch, db_engine: Engine, w: PlaneWorld
) -> None:
    """P54: with 9 of the bucket's 10 pending, 2 concurrent proposals admit exactly 1."""
    for publication in w.publications[:9]:
        _commit(
            db_engine, ProposeRequest(publication, BaselineType.CONTRACT, _bucket(CLIENT)), CLIENT
        )
    race = Interleaving.install(monkeypatch, db_engine, "chain_read")
    first, second = race.run(
        _writes(
            ProposeRequest(w.publications[9], BaselineType.CONTRACT, _bucket(CLIENT)), writer=CLIENT
        ),
        _writes(
            ProposeRequest(w.publications[10], BaselineType.CONTRACT, _bucket(CLIENT)),
            writer=CLIENT,
        ),
    )
    winners, losers = _split(first, second)
    assert len(winners) == 1 and len(losers) == 1, (first, second)
    loser = losers[0]
    assert isinstance(loser, BaselineWriteRefusedError), loser
    assert loser.refusal is BaselineRefusal.RATE_LIMITED_BASELINE_ID
    assert len([event for event in _events(db_engine) if event[1] == "propose"]) == 10


def test_governing_chain_is_monotonic_under_contention(
    monkeypatch: pytest.MonkeyPatch, db_engine: Engine, w: PlaneWorld
) -> None:
    """P49: a writer whose transaction began first but locked second still records later.

    The second writer's transaction starts (its `now()` is fixed) before the
    first writer's; it then waits on J while the first records its event. Its
    `recorded_at` is `clock_timestamp()` after the lock, so the chain stays
    non-decreasing; a transaction-start `now()` would regress and G15 (b) refuse it.
    """
    bl0 = _commit(db_engine, _approve(w.publications[0]))
    bl1 = _commit(db_engine, _approve(w.publications[1]))
    race = Interleaving.install(monkeypatch, db_engine, "chain_read")
    began = threading.Event()
    go = threading.Event()
    outcome: dict[str, Outcome] = {}

    def second_writer() -> None:
        try:
            with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
                uow.scenarios.baseline_chain(P, w.project)  # the transaction has begun
                began.set()
                assert go.wait(60)
                outcome["second"] = (
                    "ok",
                    _writes(
                        SetGoverningRequest(bl1.baseline_id, bl0.baseline_id), project_id=w.project
                    )(uow),
                )
        except BaseException as error:
            outcome["second"] = ("error", error)

    second = threading.Thread(target=second_writer)
    second.start()
    assert began.wait(60)

    def first_writer() -> None:
        try:
            with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
                outcome["first"] = (
                    "ok",
                    _writes(SetGoverningRequest(bl0.baseline_id, None), project_id=w.project)(uow),
                )
        except BaseException as error:
            outcome["first"] = ("error", error)
        finally:
            race.first_at_seam.set()

    first = threading.Thread(target=first_writer)
    race.first_thread = first
    first.start()
    assert race.first_at_seam.wait(60)
    go.set()
    waiting = threading.Event()
    for _ in range(6000):
        if race.second_at_seam.is_set() or advisory_waiter_seen(db_engine) or not second.is_alive():
            break
        waiting.wait(0.01)
    race.release.set()
    first.join(60)
    second.join(60)
    assert outcome["first"][0] == "ok", outcome
    assert outcome["second"][0] == "ok", outcome
    with db_engine.connect() as connection:
        chain = connection.execute(
            text(
                "SELECT seq, baseline_id, recorded_at FROM knowledge.schedule_governing_events "
                "ORDER BY seq"
            )
        ).all()
    assert [(row.seq, row.baseline_id) for row in chain] == [
        (1, bl0.baseline_id),
        (2, bl1.baseline_id),
    ]
    assert chain[0].recorded_at <= chain[1].recorded_at
