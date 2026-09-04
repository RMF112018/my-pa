"""Section 27, under actual concurrency: two merges racing one preview serialise.

Every existing proof that a consumed preview cannot produce a second operation
is **sequential** -- one apply finishes and commits, a second is then refused.
That establishes the check exists. It does not establish that the check holds
when the two requests overlap, which is the case section 27 actually names:
"conflicting merge attempts serialize/fail safely" and "no state-dependent
write may silently last-write-wins".

The guard is `consume_identity_preview`: a single `UPDATE ... SET consumed_at
WHERE consumed_at IS NULL` that reports whether it changed a row. Under
PostgreSQL's read-committed default the second transaction's `UPDATE` blocks on
the row lock the first holds, and when the first commits the second
**re-evaluates its own `WHERE`** against the new row version -- finds
`consumed_at` set, matches nothing, and reports zero. That re-evaluation is the
whole safety property, and a sequential test cannot see it, because in a
sequential test the second statement never blocks.

So this module runs the two overlapping, on two connections, with the second in
a thread. `lock_timeout` is set on the waiter so that a build where the first
transaction does *not* hold a lock -- an unguarded read-then-write, say -- fails
this module loudly instead of hanging the tier.

Marked `database` and nothing else, which is what the two modules already in
`tests/concurrency/` do: `--strict-markers` is on and the repository declares no
`concurrency` mark, so the directory carries the intent and the mark carries the
tier. A mark of its own would need a `pyproject.toml` edit that changed which
selections run this, which is not this worker's to make. Every identity is
synthetic.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.domain.relationship.identity_correction import IDENTITY_PREVIEW_LIFETIME
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_merge_race_test"

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED: Final = "ent_bbbb0002bbbb0002"
PREVIEW: Final = "eipv_aaaa0001aaaa01"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
DIGEST: Final = "0" * 64
OTHER_DIGEST: Final = "1" * 64

#: How long the waiting transaction will wait for the lock before failing. Long
#: enough that a loaded host does not turn a pass into a failure, short enough
#: that a build with no lock at all reports rather than hangs.
LOCK_TIMEOUT: Final = "20s"

#: How long the test itself will wait for the waiting thread once the holder has
#: committed. Strictly greater than `LOCK_TIMEOUT`, so a timeout surfaces as the
#: database's own error rather than as a thread this module abandoned.
JOIN_TIMEOUT_SECONDS: Final = 60.0

pytestmark = pytest.mark.database


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


def _stage(engine: Engine) -> None:
    with engine.begin() as connection:
        for entity_id in (SURVIVOR, MERGED):
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                    "(entity_id, principal_id, entity_type, canonical_name, display_name, "
                    " status, created_at, updated_at, version) "
                    "VALUES (:entity_id, :principal_id, 'person', :name, :name, "
                    " 'active', :when, :when, 1)"
                ),
                {
                    "entity_id": entity_id,
                    "principal_id": PRINCIPAL,
                    "name": f"synthetic {entity_id}",
                    "when": WHEN,
                },
            )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_identity_previews "  # noqa: S608
                "(preview_id, principal_id, operation_type, survivor_entity_id, "
                " expected_survivor_version, merged_away, preview_digest, conflict_digest, "
                " plan_digest, "
                " created_by, actor_class, created_at, expires_at) "
                "VALUES (:preview_id, :principal_id, 'merge', :survivor, 1, "
                " CAST(:merged_away AS jsonb), :preview_digest, :conflict_digest, :plan_digest, "
                " 'operator', 'user', :created_at, :expires_at)"
            ),
            {
                "preview_id": PREVIEW,
                "principal_id": PRINCIPAL,
                "survivor": SURVIVOR,
                "merged_away": '[{"entity_id": "' + MERGED + '", "expected_version": 1}]',
                "preview_digest": DIGEST,
                "conflict_digest": OTHER_DIGEST,
                "plan_digest": OTHER_DIGEST,
                "created_at": WHEN,
                "expires_at": WHEN + IDENTITY_PREVIEW_LIFETIME,
            },
        )


def _consumed_at(engine: Engine) -> object:
    with engine.connect() as connection:
        return connection.execute(
            text(
                f"SELECT consumed_at FROM {SCHEMA}.entity_identity_previews "  # noqa: S608
                "WHERE preview_id = :preview_id"
            ),
            {"preview_id": PREVIEW},
        ).scalar_one()


def test_a_second_consumer_waits_and_is_then_told_it_changed_nothing(
    migrated_engine: Engine,
) -> None:
    """The overlap, run rather than reasoned about.

    Two transactions, both alive at once. The first consumes and holds its row
    lock open; the second issues the same guarded `UPDATE` and blocks on that
    lock rather than reading a stale `consumed_at IS NULL` and proceeding. When
    the first commits, the second re-evaluates its own predicate against the
    committed row, matches nothing, and reports `False`.

    `False` rather than an exception is the correct answer at this layer: the
    repository reports what it changed and the application turns "changed
    nothing" into `identity_correction_conflict`. What must not happen is
    `True` twice -- which is what an unguarded read-then-write would produce,
    and which would let one preview mint two operations.
    """
    holder = migrated_engine.connect()
    waiter = migrated_engine.connect()
    try:
        holder.begin()
        first = SqlEntityRepository(holder).consume_identity_preview(PRINCIPAL, PREVIEW, at=WHEN)
        assert first, "the first consumer did not consume an unconsumed preview"

        waiter.begin()
        waiter.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            racing = pool.submit(
                SqlEntityRepository(waiter).consume_identity_preview,
                PRINCIPAL,
                PREVIEW,
                at=WHEN,
            )
            # The holder has not committed, so the waiter cannot have finished.
            # Asserted rather than assumed: if it had, the `UPDATE` took no lock
            # and the two statements are not serialised at all -- which is the
            # defect this module exists to find, and it would otherwise be
            # invisible because the second answer would still be `False` once
            # the first committed.
            assert not racing.done(), (
                "the second consumer returned while the first transaction was still "
                "open, so the guarded UPDATE is taking no row lock"
            )
            holder.commit()
            second = racing.result(timeout=JOIN_TIMEOUT_SECONDS)
        assert second is False, "one preview was consumed twice"
        waiter.commit()
    finally:
        holder.close()
        waiter.close()

    assert _consumed_at(migrated_engine) is not None
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entity_identity_previews "  # noqa: S608
                "WHERE preview_id = :preview_id AND consumed_at IS NOT NULL"
            ),
            {"preview_id": PREVIEW},
        ).scalar_one()
    assert rows == 1


def test_the_first_consumer_alone_still_succeeds(migrated_engine: Engine) -> None:
    """The control. Without it a build that refused every consumer would pass above."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        assert repository.consume_identity_preview(PRINCIPAL, PREVIEW, at=WHEN)
    assert _consumed_at(migrated_engine) is not None


def test_a_rolled_back_consumer_leaves_the_preview_available(migrated_engine: Engine) -> None:
    """Serialising must not spend the operator's approval on an attempt that failed.

    The mirror of the race above: the first transaction consumes and then rolls
    back, so the second is not competing with a fact but with an attempt that
    left none. The preview must still be consumable -- otherwise a failed merge
    would leave an operator holding a token they cannot use and no merge to show
    for it, which is the state `tests/recovery` refuses at the whole-merge level.
    """
    with migrated_engine.connect() as connection:
        connection.begin()
        repository = SqlEntityRepository(connection)
        assert repository.consume_identity_preview(PRINCIPAL, PREVIEW, at=WHEN)
        connection.rollback()

    assert _consumed_at(migrated_engine) is None
    with migrated_engine.begin() as connection:
        retry = SqlEntityRepository(connection)
        assert retry.consume_identity_preview(PRINCIPAL, PREVIEW, at=WHEN)


def test_a_foreign_principal_cannot_consume_this_preview(migrated_engine: Engine) -> None:
    """The partition holds under the same guard, so the race is not a way around it."""
    other = "prn_bbbb0002bbbb0002bbbb0002"
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        assert not repository.consume_identity_preview(other, PREVIEW, at=WHEN)
    assert _consumed_at(migrated_engine) is None
