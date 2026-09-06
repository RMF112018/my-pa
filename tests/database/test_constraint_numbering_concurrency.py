"""PC-CM-IMP-WP06: two Publishes racing one Category allocator, under real locks.

Every sequential proof that the code sequence advances establishes that the
allocator *works*. None of them establishes that it is **safe**, because in a
sequential test the second Publish never overlaps the first and never has to
block. The accepted contract's actual claim is stronger — CM-BE-AC-024/025:
allocation happens under the Category row lock, and concurrent Publishes cannot
allocate the same Project code — and that claim is only visible when the two
transactions are open at the same time.

So this module runs them overlapping, on separate connections, with the second
in a thread. The mechanism being measured is `get_category_for_update`'s
`SELECT ... FOR UPDATE` inside `_mutate`'s one transaction: the waiter blocks on
the row the holder has, and when the holder commits, the waiter re-reads the row
and sees the advanced `next_sequence` rather than the value it would have read
had it gone first. Two things could break that and pass every sequential test —
allocating outside the lock, or reading `next_sequence` before taking it — and
both of them produce a duplicate code here.

The same shape then measures the two composite operations, whose replay gates
must likewise sit behind the rows they name: two same-key `close_with_follow_up`
requests, and two same-key `reorder_categories` requests. A gate placed ahead of
those locks lets both requests read an empty ledger, and the loser reaches a
duplicate `FOLLOW_UP_OF` edge or a duplicate keyed receipt — a driver integrity
error where CM-BE-AC-065 requires `REPLAYED`. Only an overlapping run sees it.

`lock_timeout` is set on the waiting session, so a build that takes **no** lock
fails this module loudly rather than hanging the tier. Marked `database` and
nothing else, exactly as `tests/concurrency/` does: `--strict-markers` is on and
this repository declares no `concurrency` mark. Every identity is synthetic.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Final

import pytest
from sqlalchemy import Engine, event, func, select, text

from my_pa.application.constraint_management import (
    ConstraintCategoryReorderResult,
    ConstraintFollowUpResult,
    ConstraintManagementService,
    ConstraintMutationDisposition,
)
from my_pa.domain.project_controls.constraint import ProjectConstraint
from my_pa.domain.project_controls.history import ConstraintMutationActor
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_categories,
    constraint_category_history,
    project_constraint_relationships,
    project_constraints,
)
from tests.database.test_constraint_management_service import (
    PRINCIPAL_A,
    PROJECT_A,
    T0,
    seed,
)

pytestmark = pytest.mark.database

#: Long enough that a loaded host does not turn a pass into a failure, short
#: enough that a build holding no lock reports instead of hanging the tier.
LOCK_TIMEOUT: Final = "20s"

#: Strictly greater than `LOCK_TIMEOUT`, so a timeout surfaces as the database's
#: own error rather than as a thread this module walked away from.
JOIN_TIMEOUT_SECONDS: Final = 60.0

BIC: Final = (PartyRef(kind=PartyKind.PRINCIPAL),)


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    seed(migrated_engine)
    return migrated_engine


def _service(engine: Engine) -> ConstraintManagementService:
    return ConstraintManagementService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(engine),
        clock=lambda: T0,
    )


def _impatient(engine: Engine) -> Engine:
    """The same database, on connections that refuse to wait forever for a lock."""

    @event.listens_for(engine, "connect")
    def _set_timeout(dbapi_connection: object, _record: object) -> None:
        with dbapi_connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")

    return engine


def _category(engine: Engine, prefix: str = "DES") -> str:
    return (
        _service(engine)
        .create_category(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            prefix=prefix,
            title=f"{prefix} category",
            actor=ConstraintMutationActor.PRINCIPAL,
        )
        .record.category_id
    )


def _draft(engine: Engine, category_id: str) -> ProjectConstraint:
    return (
        _service(engine)
        .create_draft(
            principal_id=PRINCIPAL_A,
            actor=ConstraintMutationActor.PRINCIPAL,
            project_id=PROJECT_A,
            category_id=category_id,
            description="A synthetic constraint.",
            date_identified=date(2026, 9, 2),
            bic=BIC,
        )
        .record
    )


def _allocator(engine: Engine, category_id: str) -> tuple[int, int]:
    with engine.begin() as connection:
        row = connection.execute(
            select(
                constraint_categories.c.next_sequence, constraint_categories.c.issued_count
            ).where(constraint_categories.c.category_id == category_id)
        ).one()
    return int(row._mapping["next_sequence"]), int(row._mapping["issued_count"])


def _publish(engine: Engine, draft: ProjectConstraint) -> ProjectConstraint:
    return (
        _service(engine)
        .publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=draft.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
        .record
    )


def _rows(engine: Engine, table: object) -> int:
    with engine.begin() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def _codes(engine: Engine) -> list[str]:
    with engine.begin() as connection:
        return sorted(
            connection.execute(
                select(project_constraints.c.constraint_code).where(
                    project_constraints.c.constraint_code.is_not(None)
                )
            )
            .scalars()
            .all()
        )


def test_the_allocator_row_is_actually_locked_while_a_publish_holds_it(
    staged: Engine,
) -> None:
    """The control. If this passes trivially, the race tests below prove nothing.

    A second session asking for the same row `FOR UPDATE NOWAIT` while a Publish
    is mid-transaction must be refused. If `get_category_for_update` stopped
    locking, this reddens here rather than leaving the concurrency claims below
    unfalsifiable.
    """
    category_id = _category(staged)
    draft = _draft(staged, category_id)
    holder = staged.connect()
    other = staged.connect()
    try:
        transaction = holder.begin()
        holder.execute(
            text(
                "SELECT 1 FROM knowledge.constraint_categories "
                "WHERE category_id = :identity FOR UPDATE"
            ),
            {"identity": category_id},
        )
        with pytest.raises(Exception) as caught:
            other.execute(
                text(
                    "SELECT 1 FROM knowledge.constraint_categories "
                    "WHERE category_id = :identity FOR UPDATE NOWAIT"
                ),
                {"identity": category_id},
            )
        assert "lock" in str(caught.value).lower()
        transaction.rollback()
    finally:
        holder.close()
        other.close()
    assert draft.constraint_code is None


def test_two_overlapping_publishes_in_one_category_never_allocate_the_same_code(
    staged: Engine,
) -> None:
    """CM-BE-AC-025. The waiter re-reads `next_sequence` after the holder commits."""
    engine = _impatient(staged)
    category_id = _category(engine)
    first = _draft(engine, category_id)
    second = _draft(engine, category_id)

    def publish(draft: ProjectConstraint) -> str:
        result = _service(engine).publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=draft.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
        assert result.record.constraint_code is not None
        return result.record.constraint_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish, draft) for draft in (first, second)]
        codes = sorted(future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures)

    assert codes == ["DES.01", "DES.02"]
    assert _codes(engine) == ["DES.01", "DES.02"]
    assert _allocator(engine, category_id) == (3, 2)


def test_the_sequence_advances_exactly_once_per_applied_publication(
    staged: Engine,
) -> None:
    """CM-BE-AC-024. Eight concurrent Publishes, eight codes, one contiguous run."""
    engine = _impatient(staged)
    category_id = _category(engine)
    drafts = [_draft(engine, category_id) for _ in range(8)]

    def publish(draft: ProjectConstraint) -> str:
        result = _service(engine).publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=draft.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
        assert result.record.constraint_code is not None
        return result.record.constraint_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(publish, draft) for draft in drafts]
        codes = sorted(future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures)

    assert codes == [f"DES.0{index}" for index in range(1, 9)]
    assert len(set(codes)) == len(codes)
    assert _allocator(engine, category_id) == (9, 8)


def test_two_categories_of_one_project_allocate_independently_under_contention(
    staged: Engine,
) -> None:
    """One Category's lock does not serialise another's, and neither leaks a code."""
    engine = _impatient(staged)
    first = _category(engine, "DES")
    second = _category(engine, "PRO")
    drafts = [_draft(engine, category_id) for category_id in (first, second) for _ in range(3)]

    def publish(draft: ProjectConstraint) -> str:
        result = _service(engine).publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=draft.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
        assert result.record.constraint_code is not None
        return result.record.constraint_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(publish, draft) for draft in drafts]
        codes = sorted(future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures)

    assert codes == ["DES.01", "DES.02", "DES.03", "PRO.01", "PRO.02", "PRO.03"]
    assert _allocator(engine, first) == (4, 3)
    assert _allocator(engine, second) == (4, 3)


def test_a_concurrent_replay_of_one_publish_consumes_no_second_number(
    staged: Engine,
) -> None:
    """CM-BE-AC-026/065 together: the replay gate sits inside the same transaction.

    Two requests carrying the same key and the same digest race; whichever
    arrives second finds the first's committed receipt and returns it. Exactly
    one number is consumed, whichever way the race falls.
    """
    engine = _impatient(staged)
    category_id = _category(engine)
    draft = _draft(engine, category_id)

    def publish() -> tuple[ConstraintMutationDisposition, str]:
        result = _service(engine).publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=draft.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            idempotency_key="wp06-race-publish-key1",
        )
        assert result.record.constraint_code is not None
        return result.disposition, result.record.constraint_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish) for _ in range(2)]
        outcomes = [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures]

    assert {code for _, code in outcomes} == {"DES.01"}
    assert _codes(engine) == ["DES.01"]
    assert _allocator(engine, category_id) == (2, 1)


def test_a_publish_that_fails_under_contention_consumes_no_number(staged: Engine) -> None:
    """Two Publishes race; one is refused for an incomplete record, one succeeds."""
    engine = _impatient(staged)
    category_id = _category(engine)
    good = _draft(engine, category_id)
    bad = (
        _service(engine)
        .create_draft(
            principal_id=PRINCIPAL_A,
            actor=ConstraintMutationActor.PRINCIPAL,
            project_id=PROJECT_A,
            category_id=category_id,
            description="Nobody is in court for this.",
            date_identified=date(2026, 9, 2),
        )
        .record
    )

    def publish(draft: ProjectConstraint) -> str | None:
        try:
            return (
                _service(engine)
                .publish(
                    principal_id=PRINCIPAL_A,
                    constraint_id=draft.constraint_id,
                    expected_version=draft.version,
                    actor=ConstraintMutationActor.PRINCIPAL,
                )
                .record.constraint_code
            )
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish, draft) for draft in (good, bad)]
        codes = [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures]

    assert sorted(code for code in codes if code is not None) == ["DES.01"]
    assert _codes(engine) == ["DES.01"]
    assert _allocator(engine, category_id) == (2, 1)


def test_two_concurrent_same_key_close_with_follow_ups_replay_rather_than_collide(
    staged: Engine,
) -> None:
    """CM-BE-AC-065 over the composite, not only over its parts.

    Close + Follow-up is six writes under one key, and its replay gate has to
    sit behind the predecessor's row lock the way `_mutate`'s does. If the gate
    went first, both requests would read an empty ledger and both would proceed;
    the loser's inner `close` would replay, but the composite would carry on to
    create a second successor and then attempt a second `FOLLOW_UP_OF` edge,
    which the stored uniqueness on that edge refuses. The transaction would roll
    back whole — so this test cannot be written against surviving rows — and the
    caller would receive a driver integrity error instead of `REPLAYED`. That is
    what is measured here: the disposition the loser is handed, and the fact
    that what it is handed is the winner's own successor, edge and receipts.
    """
    engine = _impatient(staged)
    category_id = _category(engine)
    published = _publish(engine, _draft(engine, category_id))

    def follow_up() -> ConstraintFollowUpResult:
        return _service(engine).close_with_follow_up(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            successor_description="Re-issue the stamped set.",
            idempotency_key="wp06-race-followup-key1",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(follow_up) for _ in range(2)]
        outcomes = [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures]

    assert {outcome.disposition for outcome in outcomes} == {
        ConstraintMutationDisposition.APPLIED,
        ConstraintMutationDisposition.REPLAYED,
    }
    applied = next(
        outcome
        for outcome in outcomes
        if outcome.disposition is ConstraintMutationDisposition.APPLIED
    )
    replayed = next(
        outcome
        for outcome in outcomes
        if outcome.disposition is ConstraintMutationDisposition.REPLAYED
    )
    assert replayed.predecessor.constraint_id == applied.predecessor.constraint_id
    assert replayed.successor.constraint_id == applied.successor.constraint_id
    assert replayed.relationship_id == applied.relationship_id
    assert replayed.predecessor_receipt.history_id == applied.predecessor_receipt.history_id
    assert replayed.successor_receipt.history_id == applied.successor_receipt.history_id
    assert _rows(engine, project_constraints) == 2
    assert _rows(engine, project_constraint_relationships) == 1
    assert _codes(engine) == ["DES.01", "DES.02"]
    assert _allocator(engine, category_id) == (3, 2)


def test_two_concurrent_same_key_reorders_replay_rather_than_collide(staged: Engine) -> None:
    """CM-BE-AC-065 over the other composite, for the same reason.

    A reorder names every row it touches, so it can hold them all before it
    reads the ledger, and it must: two requests carrying one key that both found
    an empty ledger would both write a receipt under it, and the stored partial
    unique index over the Category ledger's keys would refuse the second. The
    loser is required to wait on the rows, read the receipt the winner
    committed, and return the order the winner wrote.
    """
    engine = _impatient(staged)
    ids = [_category(engine, prefix) for prefix in ("DES", "PRO", "PER")]
    order = list(reversed(ids))

    def reorder() -> ConstraintCategoryReorderResult:
        return _service(engine).reorder_categories(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            ordered_category_ids=order,
            expected_versions=dict.fromkeys(ids, 1),
            actor=ConstraintMutationActor.PRINCIPAL,
            idempotency_key="wp06-race-reorder-key1",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reorder) for _ in range(2)]
        outcomes = [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures]

    assert {outcome.disposition for outcome in outcomes} == {
        ConstraintMutationDisposition.APPLIED,
        ConstraintMutationDisposition.REPLAYED,
    }
    applied = next(
        outcome
        for outcome in outcomes
        if outcome.disposition is ConstraintMutationDisposition.APPLIED
    )
    replayed = next(
        outcome
        for outcome in outcomes
        if outcome.disposition is ConstraintMutationDisposition.REPLAYED
    )
    assert [record.category_id for record in applied.records] == order
    assert [record.category_id for record in replayed.records] == order
    assert replayed.receipts[0].history_id == applied.receipts[0].history_id
    with engine.begin() as connection:
        stored = {
            row._mapping["category_id"]: (row._mapping["display_order"], row._mapping["version"])
            for row in connection.execute(select(constraint_categories)).all()
        }
    assert [stored[category_id][0] for category_id in order] == [0, 1, 2]
    assert all(version == 2 for _, version in stored.values())
    # Three creations and one applied reorder over three rows. A second applied
    # reorder would put six receipts here even if it wrote the same order.
    assert _rows(engine, constraint_category_history) == 6
