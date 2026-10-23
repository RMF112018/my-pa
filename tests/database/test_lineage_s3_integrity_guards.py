"""AT-012 (S3 guards): the record lineage S3 integrity guards, on a live server.

The S3 revision (S3 contract section 4) puts the S3 invariants in the database
so they hold for every writer: append-only refusal on the commit marks and the
handoff corrections, TRUNCATE refusal on all five new tables, the allocator
that only advances by one later in time, the mark that is its allocation, the
S3 link transition table and the one live head per identity, the canonical
`related_context` root, the correction admission and the chain that skips
voided events, the backfill ledger that only moves forward, and the S3 write
request completion. Each test drives one guard with direct SQL and asserts the
SQLSTATE and the guard's own message or constraint name, so a test can only
pass for the reason it names.

`database` tier on a disposable head-migrated clone per test. Every value is
synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, text, update
from sqlalchemy.engine import Connection

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    issue_responsibility_corrections,
    issue_responsibility_events,
    lineage_backfill_items,
    lineage_backfill_runs,
    lineage_write_requests,
    record_link_revisions,
    record_links,
)
from tests.database.test_lineage_integrity_guards import (
    ALL_TABLES as S1_TABLES,
)
from tests.database.test_lineage_integrity_guards import (
    CHECK,
    RESTRICT,
    WHEN,
    World,
    _advance_head,
    _link_revision,
    _link_values,
    _refused,
    _world,
    _write_link,
)
from tests.database.test_lineage_s2_integrity_guards import (
    S2_TABLES,
    _commitment,
    _handoff,
)

pytestmark = pytest.mark.database

UNIQUE: Final = "23505"
S3_TABLES: Final = (
    "lineage_commit_sequences",
    "lineage_commit_marks",
    "issue_responsibility_corrections",
    "lineage_backfill_runs",
    "lineage_backfill_items",
)
#: The two immutable S3 tables and a column each can be "updated" through.
IMMUTABLE: Final[dict[str, str]] = {
    "lineage_commit_marks": "marked_at",
    "issue_responsibility_corrections": "reason",
}
RUN: Final = "lbfr_lineages3guard001"
DIGEST: Final = "d" * 64


# ------------------------------------------------------------------ seeding


def _correction(
    world: World,
    handoff_id: str,
    number: int,
    action: str,
    *,
    effective: datetime | None = None,
    **overrides: object,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "principal_id": world.principal,
        "correction_id": issue_identifier(IdKind.ISSUE_HANDOFF_CORRECTION),
        "handoff_id": handoff_id,
        "correction_no": number,
        "predecessor_correction_no": None if number == 1 else number - 1,
        "action": action,
        "corrected_effective_at": effective if action == "retime" else None,
        "evidence_anchor_id": world.anchor,
        "evidence_role": "handoff" if action == "retime" else "contradicts",
        "reason": "Synthetic correction.",
        "acceptance_basis": "user_confirmed",
        "authority_class": "local_operator",
        "decision_channel": "local_cli",
        "source_capability": "issues.handoffs.correct",
        "recorded_at": WHEN + timedelta(hours=3),
    }
    values.update(overrides)
    return values


def _event(world: World, commitment_id: str, sequence: int, **values: Any) -> dict[str, Any]:  # noqa: ANN401
    return _handoff(world, commitment_id, sequence, **values)


def _chain(engine: Engine, world: World) -> tuple[str, str, list[str]]:
    """`(commitment, entity, [e1, e2, e3])`: entity -> P -> entity -> P, 10 minutes apart."""
    commitment_id, entity = _commitment(engine, world.principal)
    holders = ((entity, None), (None, entity), (entity, None))
    events: list[str] = []
    with engine.begin() as c:
        for sequence, (leaving, arriving) in enumerate(holders, start=1):
            row = _event(
                world,
                commitment_id,
                sequence,
                from_entity=leaving,
                to_entity=arriving,
                effective=WHEN + timedelta(minutes=10 * sequence),
                recorded=WHEN + timedelta(hours=2),
            )
            c.execute(insert(issue_responsibility_events).values(**row))
            events.append(str(row["handoff_id"]))
    return commitment_id, entity, events


def _run_row(world: World, **overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "principal_id": world.principal,
        "run_id": RUN,
        "state": "enumerated",
        "validator_version": 1,
        "commit_seq_cutoff": 0,
        "source_cutoff_at": WHEN,
        "population_count": 2,
        "classified_count": 0,
        "plan_digest": None,
        "census": {"task_follow_up": {"examined": 2, "enumerated": 2}},
        "created_at": WHEN,
        "classified_at": None,
        "authority_class": "local_operator",
        "decision_channel": "local_cli",
    }
    values.update(overrides)
    return values


def _item_row(world: World, number: int, **overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "principal_id": world.principal,
        "run_id": RUN,
        "item_no": number,
        "source_kind": "task_follow_up",
        "source_family": "task",
        "source_id": world.task,
        "source_ref": f"cmt_lineages3guard00{number}",
        "source_version": 1,
        "source_digest": DIGEST,
    }
    values.update(overrides)
    return values


def _settled() -> dict[str, Any]:
    return {
        "classification": "native_virtual_proven",
        "reason": "native_follow_up",
        "existing_link_state": "none",
        "quarantined": False,
        "classified_at": WHEN + timedelta(hours=1),
    }


def _ledger(engine: Engine, world: World) -> None:
    with engine.begin() as c:
        c.execute(insert(lineage_backfill_runs).values(**_run_row(world)))
        for number in (1, 2):
            c.execute(insert(lineage_backfill_items).values(**_item_row(world, number)))


@pytest.fixture
def world(db_engine: Engine) -> Iterator[World]:
    yield _world(db_engine)


def _update(table: str, **values: object) -> Callable[[Connection], object]:
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    statement = text(f"UPDATE knowledge.{table} SET {assignments}")  # noqa: S608 - fixed names

    def run(c: Connection) -> object:
        return c.execute(statement, values)

    return run


# ------------------------------------------------------------------ tests


@pytest.mark.parametrize("table", sorted(IMMUTABLE))
def test_s3_immutable_tables_refuse_update_and_delete(
    db_engine: Engine, world: World, table: str
) -> None:
    commitment_id, _entity, events = _chain(db_engine, world)
    del commitment_id
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_corrections).values(
                **_correction(world, events[2], 1, "void")
            )
        )
    column = IMMUTABLE[table]
    _refused(
        db_engine,
        lambda c: c.execute(text(f"UPDATE knowledge.{table} SET {column} = {column}")),  # noqa: S608
        RESTRICT,
        f"{table} is append-only",
    )
    _refused(
        db_engine,
        lambda c: c.execute(text(f"DELETE FROM knowledge.{table}")),  # noqa: S608
        RESTRICT,
        f"{table} is append-only",
    )


@pytest.mark.parametrize("table", S3_TABLES)
def test_s3_tables_refuse_truncate(db_engine: Engine, world: World, table: str) -> None:
    """Each S3 table, holding a row, refuses on its own trigger: every other is disabled."""
    _commitment_id, _entity, events = _chain(db_engine, world)
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_corrections).values(
                **_correction(world, events[2], 1, "void")
            )
        )
    _ledger(db_engine, world)
    with db_engine.connect() as c:
        for name in S3_TABLES:
            held = c.execute(text(f"SELECT count(*) FROM knowledge.{name}")).scalar_one()  # noqa: S608
            assert held >= 1, name
    everything = (*S1_TABLES, *S2_TABLES, *S3_TABLES)

    def truncate(c: Connection) -> None:
        for other in everything:
            if other != table:
                c.execute(
                    text(f"ALTER TABLE knowledge.{other} DISABLE TRIGGER {other}_refuse_truncate")
                )
        c.execute(text("TRUNCATE " + ", ".join(f"knowledge.{t}" for t in everything)))

    _refused(db_engine, truncate, RESTRICT, f"{table} refuses TRUNCATE")


def test_the_allocator_only_advances_by_one(db_engine: Engine, world: World) -> None:
    del world
    with db_engine.connect() as c:
        seq, marked = c.execute(
            text(
                "SELECT last_seq, last_marked_at FROM knowledge.lineage_commit_sequences "
                "WHERE principal_id = 'prn_lineageguard0001'"
            )
        ).one()
    later = marked + timedelta(seconds=1)
    for change in (
        {"last_seq": seq + 2, "last_marked_at": later},
        {"last_seq": seq, "last_marked_at": later},
        {"last_seq": seq + 1, "last_marked_at": marked},
        {"last_seq": seq + 1, "last_marked_at": marked - timedelta(seconds=1)},
        {"last_seq": seq + 1, "last_marked_at": later, "principal_id": "prn_lineageguard0009"},
    ):
        _refused(
            db_engine,
            _update("lineage_commit_sequences", **change),
            RESTRICT,
            "advances by one, later in time",
        )
    _refused(
        db_engine,
        lambda c: c.execute(text("DELETE FROM knowledge.lineage_commit_sequences")),
        RESTRICT,
        "a lineage commit sequence is never deleted",
    )
    # The one admitted move: by one, later in time.
    with db_engine.begin() as c:
        _update("lineage_commit_sequences", last_seq=seq + 1, last_marked_at=later)(c)


def test_a_commit_mark_is_its_allocation(db_engine: Engine, world: World) -> None:
    del world
    principal = "prn_lineageguard0001"
    with db_engine.connect() as c:
        seq, marked = c.execute(
            text(
                "SELECT last_seq, last_marked_at FROM knowledge.lineage_commit_sequences "
                "WHERE principal_id = :p"
            ),
            {"p": principal},
        ).one()

    def forged(**values: object) -> Callable[[Connection], object]:
        row = {
            "p": principal,
            "seq": seq + 1,
            "at": marked,
            "xact": None,
        }
        row.update(values)

        def statement(c: Connection) -> object:
            return c.execute(
                text(
                    "INSERT INTO knowledge.lineage_commit_marks "
                    "(principal_id, commit_seq, marked_at, recorded_xact) VALUES "
                    "(:p, :seq, :at, coalesce(CAST(:xact AS xid8), pg_current_xact_id()))"
                ),
                row,
            )

        return statement

    # Not the allocator's next sequence, not its time, another transaction, or
    # a Principal with no allocator row: each refused.
    for case in (
        forged(),
        forged(seq=seq, at=marked - timedelta(seconds=1)),
        forged(seq=seq, xact="1"),
        forged(p="prn_lineageguard0009", seq=1),
    ):
        _refused(db_engine, case, CHECK, "a commit mark is its transaction's allocation")
    # The allocation itself passes: the function allocates and inserts.
    with db_engine.begin() as c:
        taken = c.execute(text("SELECT knowledge.lineage_commit_mark(:p)"), {"p": principal})
        assert taken.scalar_one() == seq + 1


def _revise(
    world: World, link_id: str, number: int, action: str, state: str, **values: object
) -> Callable[[Connection], object]:
    capability = {
        "contest": "records.associations.contest",
        "reinstate": "records.associations.reinstate",
        "end": "records.associations.end",
        "correct_evidence": "records.associations.correct",
    }[action]

    row = _link_revision(
        world.principal, link_id, number, "end" if action == "end" else "correct_evidence"
    )
    row.update(action=action, lifecycle_state=state, source_capability=capability, **values)

    def statement(c: Connection) -> None:
        c.execute(insert(record_link_revisions).values(**row))
        _advance_head(c, world.principal, link_id, number, state)

    return statement


def test_a_link_revision_follows_the_s3_transitions(db_engine: Engine, world: World) -> None:
    link = world.origin
    # From `active`: reinstate is refused.
    _refused(
        db_engine,
        _revise(world, link, 2, "reinstate", "active"),
        RESTRICT,
        "a link revision follows an active predecessor",
    )
    # A contest names its reason and is `contested` exactly when it contests.
    _refused(
        db_engine,
        _revise(world, link, 2, "contest", "active"),
        CHECK,
        "a_link_revision_contests_exactly_when_contested",
    )
    _refused(
        db_engine,
        _revise(world, link, 2, "contest", "contested", reason=None),
        CHECK,
        "a_link_revision_states_its_reason",
    )
    with db_engine.begin() as c:
        _revise(world, link, 2, "contest", "contested")(c)
    # From `contested`: no evidence correction and no second contest.
    for action, state in (("correct_evidence", "contested"), ("contest", "contested")):
        _refused(
            db_engine,
            _revise(world, link, 3, action, state),
            RESTRICT,
            "a link revision follows an active predecessor",
        )
    # A reinstatement is `active`: `a_reinstatement_is_active` states it, and over
    # the closed state set the contest and end CHECKs already refuse the other
    # two states (so either constraint may be the one PostgreSQL names first).
    _refused(
        db_engine,
        _revise(world, link, 3, "reinstate", "contested"),
        CHECK,
        "violates check constraint",
    )
    with db_engine.begin() as c:
        _revise(world, link, 3, "reinstate", "active")(c)
    with db_engine.begin() as c:
        _revise(world, link, 4, "contest", "contested")(c)
    # `end` from `contested`, and `ended` stays terminal.
    with db_engine.begin() as c:
        _revise(world, link, 5, "end", "ended")(c)
    for action, state in (("reinstate", "active"), ("contest", "contested")):
        _refused(
            db_engine,
            _revise(world, link, 6, action, state),
            RESTRICT,
            "a link revision follows an active predecessor",
        )


def test_one_live_head_per_identity_includes_contested(db_engine: Engine, world: World) -> None:
    link = world.origin
    with db_engine.begin() as c:
        _revise(world, link, 2, "contest", "contested")(c)
    with db_engine.connect() as c:
        root = dict(
            c.execute(
                text("SELECT * FROM knowledge.record_links WHERE link_id = :link"), {"link": link}
            )
            .mappings()
            .one()
        )
    # The same meaning again while the first is contested: no second live head.
    again = {
        **{key: value for key, value in root.items() if key != "link_id"},
        "link_id": issue_identifier(IdKind.RECORD_LINK),
    }
    _refused(
        db_engine,
        lambda c: _write_link(c, again),
        UNIQUE,
        "record_link_one_active_identity",
    )
    # Once it ends, the meaning can be asserted again.
    with db_engine.begin() as c:
        _revise(world, link, 3, "end", "ended")(c)
    with db_engine.begin() as c:
        _write_link(c, again)


def _related(world: World, source: str, target: str, **values: object) -> dict[str, Any]:
    return _link_values(
        world.principal,
        kind="semantic",
        relation="related_context",
        source=("task", source),
        target=("task", target),
        context=world.issue,
        **values,
    )


def test_a_related_context_root_is_canonical_and_scoped(db_engine: Engine, world: World) -> None:
    # Mixed case: by code point `A` (65) sorts before `a` (97), whatever the
    # database collation says.
    upper, lower = "tsk_Aguardrelated01", "tsk_aguardrelated01"
    with db_engine.begin() as c:
        for task_id in (upper, lower):
            _task_with(c, world.principal, task_id)
    for source, target, values in (
        (lower, upper, {}),
        (upper, lower, {"context": None}),
        (upper, upper, {}),
    ):
        row = (
            _link_values(
                world.principal,
                kind="semantic",
                relation="related_context",
                source=("task", source),
                target=("task", target),
                context=None,
            )
            if values
            else _related(world, source, target)
        )
        _refused(
            db_engine,
            lambda c, row=row: c.execute(insert(record_links).values(**row)),
            CHECK,
            "a_related_context_is_canonical_and_scoped",
        )
    with db_engine.begin() as c:
        _write_link(c, _related(world, upper, lower))


def _task_with(c: Connection, principal: str, task_id: str) -> None:
    from my_pa.infrastructure.persistence.tables import tasks

    c.execute(
        insert(tasks).values(
            task_id=task_id,
            principal_id=principal,
            title="Synthetic task",
            origin_kind="direct_principal",
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )


def test_a_retime_must_stay_in_order_in_the_database(db_engine: Engine, world: World) -> None:
    _commitment_id, _entity, events = _chain(db_engine, world)
    message = "a retimed handoff is not effective"
    for effective, needle in (
        (WHEN - timedelta(minutes=1), "before its commitment"),
        (WHEN + timedelta(minutes=5), "before the previous live one"),
        (WHEN + timedelta(minutes=35), "after the next live one"),
    ):
        _refused(
            db_engine,
            lambda c, effective=effective: c.execute(
                insert(issue_responsibility_corrections).values(
                    **_correction(world, events[1], 1, "retime", effective=effective)
                )
            ),
            CHECK,
            f"{message} {needle}",
        )
    # In order: between the live neighbours (10 and 30 minutes).
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_corrections).values(
                **_correction(world, events[1], 1, "retime", effective=WHEN + timedelta(minutes=25))
            )
        )
    # The current effective time is the latest retime: event 3 now cannot move
    # before 25 minutes, which its own 30-minute time allowed before.
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_responsibility_corrections).values(
                **_correction(world, events[2], 1, "retime", effective=WHEN + timedelta(minutes=24))
            )
        ),
        CHECK,
        f"{message} before the previous live one",
    )


def test_only_the_last_live_handoff_can_be_voided_in_the_database(
    db_engine: Engine, world: World
) -> None:
    _commitment_id, _entity, events = _chain(db_engine, world)
    for handoff_id in events[:2]:
        _refused(
            db_engine,
            lambda c, handoff_id=handoff_id: c.execute(
                insert(issue_responsibility_corrections).values(
                    **_correction(world, handoff_id, 1, "void")
                )
            ),
            CHECK,
            "only the last live handoff of a chain is voided",
        )
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_corrections).values(
                **_correction(world, events[2], 1, "void")
            )
        )
    # Event 2 is now the last live one; a voided event takes no correction.
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_corrections).values(
                **_correction(world, events[1], 1, "void")
            )
        )
    for action in ("void", "retime"):
        _refused(
            db_engine,
            lambda c, action=action: c.execute(
                insert(issue_responsibility_corrections).values(
                    **_correction(
                        world, events[2], 2, action, effective=WHEN + timedelta(minutes=40)
                    )
                )
            ),
            CHECK,
            "a voided handoff takes no further correction",
        )


def test_new_handoffs_follow_the_last_live_holder(db_engine: Engine, world: World) -> None:
    commitment_id, entity, events = _chain(db_engine, world)
    # Void event 3 (entity -> P): the last live event is 2, which reached the entity.
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_corrections).values(
                **_correction(world, events[2], 1, "void")
            )
        )

    def fourth(
        leaving: str | None, arriving: str | None, minutes: int
    ) -> Callable[[Connection], object]:
        return lambda c: c.execute(
            insert(issue_responsibility_events).values(
                **_event(
                    world,
                    commitment_id,
                    4,
                    from_entity=leaving,
                    to_entity=arriving,
                    effective=WHEN + timedelta(minutes=minutes),
                    recorded=WHEN + timedelta(hours=4),
                )
            )
        )

    # Event 4 leaves the holder event 2 reached (the entity), not event 3's.
    _refused(
        db_engine,
        fourth(None, entity, 40),
        RESTRICT,
        "a handoff leaves the holder its predecessor reached",
    )
    # Ordered against event 2's time (20 minutes), not the voided event 3's (30).
    _refused(
        db_engine,
        fourth(entity, None, 15),
        CHECK,
        "a handoff is not effective before its predecessor",
    )
    with db_engine.begin() as c:
        fourth(entity, None, 25)(c)


def test_a_backfill_run_moves_forward_only(db_engine: Engine, world: World) -> None:
    _ledger(db_engine, world)
    with db_engine.begin() as c:
        _update("lineage_backfill_runs", classified_count=1)(c)
    for change in (
        {"classified_count": 0},
        {"population_count": 3},
        {"commit_seq_cutoff": 1},
        {"source_cutoff_at": WHEN + timedelta(hours=1)},
        {"validator_version": 1, "run_id": "lbfr_lineages3guard009"},
    ):
        _refused(
            db_engine,
            _update("lineage_backfill_runs", **change),
            RESTRICT,
            "a backfill run only moves forward",
        )
    _refused(
        db_engine,
        lambda c: c.execute(text("UPDATE knowledge.lineage_backfill_runs SET census = '{}'")),
        RESTRICT,
        "a backfill run only moves forward",
    )
    classified = {
        "classified_count": 2,
        "state": "classified",
        "plan_digest": "a" * 64,
        "classified_at": WHEN + timedelta(hours=2),
    }
    with db_engine.begin() as c:
        _update("lineage_backfill_runs", **classified)(c)
    for change in (
        {"state": "enumerated", "plan_digest": None, "classified_at": None},
        {"plan_digest": "b" * 64},
        {"classified_at": WHEN + timedelta(hours=3)},
    ):
        _refused(
            db_engine,
            _update("lineage_backfill_runs", **change),
            RESTRICT,
            "a backfill run only moves forward",
        )
    _refused(
        db_engine,
        lambda c: c.execute(text("DELETE FROM knowledge.lineage_backfill_runs")),
        RESTRICT,
        "a backfill run is never deleted",
    )


def test_a_backfill_item_is_settled_once(db_engine: Engine, world: World) -> None:
    _ledger(db_engine, world)

    def settle(item_no: int, **values: object) -> Callable[[Connection], object]:
        return lambda c: c.execute(
            update(lineage_backfill_items)
            .where(lineage_backfill_items.c.item_no == item_no)
            .values(**values)
        )

    # An unclassified item changes only by being settled, all of it together.
    _refused(
        db_engine,
        settle(1, source_digest="e" * 64),
        RESTRICT,
        "a backfill item is settled once",
    )
    _refused(
        db_engine,
        settle(1, classification="native_virtual_proven"),
        CHECK,
        "a_backfill_item_is_settled_whole",
    )
    _refused(
        db_engine,
        settle(1, **{**_settled(), "classification": "unresolved", "reason": "source_changed"}),
        CHECK,
        "a_backfill_item_is_quarantined_exactly_when_unsettled",
    )
    with db_engine.begin() as c:
        settle(1, **_settled())(c)
    for change in (
        {**_settled(), "reason": "native_meeting_series"},
        {"source_ref": "cmt_lineages3guard009"},
        {"quarantined": True},
    ):
        _refused(db_engine, settle(1, **change), RESTRICT, "a backfill item is settled once")
    _refused(
        db_engine,
        lambda c: c.execute(text("DELETE FROM knowledge.lineage_backfill_items")),
        RESTRICT,
        "a backfill item is never deleted",
    )


def _reserve(c: Connection, world: World, capability: str, key: str) -> None:
    c.execute(
        insert(lineage_write_requests).values(
            principal_id=world.principal,
            capability=capability,
            idempotency_key=key,
            request_digest="a" * 64,
            created_at=WHEN,
        )
    )


def _complete(c: Connection, key: str, **result: object) -> None:
    c.execute(
        update(lineage_write_requests)
        .where(lineage_write_requests.c.idempotency_key == key)
        .values(completed_at=WHEN, **result)
    )


def test_an_s3_write_request_completes_once(db_engine: Engine, world: World) -> None:
    _commitment_id, _entity, events = _chain(db_engine, world)
    correction = _correction(world, events[2], 1, "void")
    _ledger(db_engine, world)
    with db_engine.begin() as c:
        c.execute(insert(issue_responsibility_corrections).values(**correction))
    with db_engine.connect() as c:
        mark = c.execute(
            text(
                "SELECT commit_seq FROM knowledge.issue_responsibility_corrections "
                "WHERE correction_id = :id"
            ),
            {"id": correction["correction_id"]},
        ).scalar_one()
    corrected = {"result_handoff_correction_id": correction["correction_id"]}
    with db_engine.begin() as c:
        _reserve(c, world, "issues.handoffs.correct", "s3-correct")
        _complete(c, "s3-correct", **corrected)
    _refused(
        db_engine,
        lambda c: _complete(c, "s3-correct", **corrected),
        RESTRICT,
        "a lineage write request completes once",
    )
    # Each S3 completion names exactly its own result group.
    for capability, key, result, name in (
        (
            "issues.handoffs.correct",
            "s3-correct-wrong",
            {"result_backfill_run_id": RUN, "result_backfill_checkpoint": 0},
            "a_completed_handoff_correction_names_its_correction",
        ),
        (
            "records.backfill.plan",
            "s3-plan-wrong",
            {**corrected},
            "a_completed_backfill_write_names_its_run",
        ),
        (
            "records.backfill.plan",
            "s3-plan-marked",
            {"result_backfill_run_id": RUN, "result_backfill_checkpoint": 0, "commit_seq": mark},
            "a_completed_backfill_write_names_its_run",
        ),
        (
            "records.associations.contest",
            "s3-contest-wrong",
            {**corrected},
            "a_completed_link_write_names_its_revision",
        ),
        (
            "issues.create",
            "s1-with-s3-result",
            {"result_issue_id": world.issue, "result_issue_version": 1, **corrected},
            "a_completed_issue_write_names_its_revision",
        ),
    ):
        _refused(
            db_engine,
            lambda c, capability=capability, key=key, result=result: (
                _reserve(c, world, capability, key),
                _complete(c, key, **result),
            ),
            CHECK,
            name,
        )
    # A reserved request carries no result and no mark.
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(lineage_write_requests).values(
                principal_id=world.principal,
                capability="records.backfill.plan",
                idempotency_key="s3-reserved-marked",
                request_digest="a" * 64,
                created_at=WHEN,
                commit_seq=mark,
            )
        ),
        CHECK,
        "an_incomplete_lineage_write_request_names_no_result",
    )
    with db_engine.begin() as c:
        _reserve(c, world, "records.backfill.plan", "s3-plan")
        _complete(c, "s3-plan", result_backfill_run_id=RUN, result_backfill_checkpoint=0)
    _refused(
        db_engine,
        lambda c: _complete(c, "s3-plan", result_backfill_checkpoint=1),
        RESTRICT,
        "a lineage write request completes once",
    )
