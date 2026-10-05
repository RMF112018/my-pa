"""KLP-WP-04: the single-current subject lock row, even with zero assertions (real DB race).

KLP-AC-091. Marked `database` (auto `database_clone`), routed to
`database-current-head`.

Every write to (Principal, canonical subject, predicate_code) serializes on one
`knowledge_assertion_subject_locks` row keyed *without* predicate_version,
created by `INSERT ... ON CONFLICT DO NOTHING` and locked before any assertion
row is written:

* **zero rows** -- a holder session inserts the key's lock row and keeps its
  transaction open (an uncommitted speculative insert). A production submit on
  that key with no assertion anywhere blocks on the upsert (observed in
  `pg_stat_activity`) and writes no assertion while blocked; after the holder
  commits, it creates the fact and the key still has exactly one lock row.
* **across predicate versions** -- a live fact under head v(n), a new head
  v(n+1), and a submit under v(n+1) block on the *same* held row; after release
  it supersedes the older-version fact, leaving one live assertion and one
  lock row (no version in the key).

Bounded: two concurrent submits on one Entity subject are already serialized by
the C3 Entity scope before C6 (`test_knowledge_assertion_concurrency.py`
observes that wait); this module isolates the C6 row itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Final

import pytest
from sqlalchemy import Connection, Engine, func, select, text
from tests.concurrency.test_knowledge_assertion_concurrency import hold_subject_lock
from tests.concurrency.test_knowledge_shared_evidence_raise import (
    DEADLINE_SECONDS,
    _wait_for_waiters,
)
from tests.database.test_knowledge_assertion_repository import WHEN, new_principal
from tests.database.test_knowledge_assertion_submissions import (
    PAYMENT,
    SubmitRuntime,
    add_direct_payment_head,
    external,
    live_assertions,
)

from my_pa.infrastructure.persistence.tables import (
    knowledge_assertion_subject_locks,
    knowledge_assertions,
)

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

ENTITY: Final = "entity"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[SubmitRuntime]:
    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _lock_rows(engine: Engine, principal: str, subject: str) -> int:
    locks = knowledge_assertion_subject_locks
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).where(
                    locks.c.principal_id == principal,
                    locks.c.subject_id == subject,
                    locks.c.predicate_code == PAYMENT,
                )
            ).scalar_one()
        )


def _assertions(engine: Engine, principal: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).where(knowledge_assertions.c.principal_id == principal)
            ).scalar_one()
        )


def _uncommitted_lock_row(holder: Connection, principal: str, subject: str) -> None:
    holder.execute(
        text(
            "INSERT INTO knowledge.knowledge_assertion_subject_locks (principal_id, subject_kind, "
            "subject_id, predicate_code) VALUES (:p, 'entity', :s, :c)"
        ),
        {"p": principal, "s": subject, "c": PAYMENT},
    )


def test_a_submit_with_zero_assertions_blocks_on_the_upserted_lock_row(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    add_direct_payment_head(runtime.engine)
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "zero")
    engine = runtime.engine
    assert _lock_rows(engine, principal, org) == 0
    with engine.connect() as holder:
        _uncommitted_lock_row(holder, principal, org)
        with ThreadPoolExecutor(max_workers=1) as pool:
            submitted = pool.submit(
                runtime.submit,
                principal,
                profile,
                subject_id=org,
                predicate=PAYMENT,
                value="Net 30",
                effective_from=WHEN - timedelta(days=5),
                evidence=(external("inv-zero"),),
            )
            _wait_for_waiters(engine, 1, submitted)
            assert _assertions(engine, principal) == 0  # nothing before the C6 row
            holder.commit()
            result = submitted.result(timeout=DEADLINE_SECONDS)
    assert result["outcome"] == "direct_created", result
    assert _lock_rows(engine, principal, org) == 1


def test_a_newer_predicate_version_serializes_on_the_same_lock_row(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    add_direct_payment_head(runtime.engine)
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "versions")
    first = runtime.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        value="Net 30",
        candidate="v-old",
        effective_from=WHEN - timedelta(days=20),
        evidence=(external("inv-old"),),
    )
    assert first["outcome"] == "direct_created"
    add_direct_payment_head(runtime.engine)
    engine = runtime.engine
    with engine.connect() as holder:
        hold_subject_lock(holder, principal, ENTITY, org, PAYMENT)
        with ThreadPoolExecutor(max_workers=1) as pool:
            submitted = pool.submit(
                runtime.submit,
                principal,
                profile,
                subject_id=org,
                predicate=PAYMENT,
                value="Net 60",
                candidate="v-new",
                effective_from=WHEN - timedelta(days=2),
                evidence=(external("inv-new"),),
            )
            _wait_for_waiters(engine, 1, submitted)
            holder.rollback()
            result = submitted.result(timeout=DEADLINE_SECONDS)
    assert result["outcome"] == "direct_superseded", result
    assert result["superseded_assertion_id"] == first["assertion_id"]
    assert len(live_assertions(engine, principal, PAYMENT)) == 1
    assert _lock_rows(engine, principal, org) == 1
