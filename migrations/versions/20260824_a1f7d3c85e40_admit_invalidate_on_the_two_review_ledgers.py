"""Admit `invalidate` on the capture and Relationship Memory review ledgers.

Revision ID: a1f7d3c85e40
Revises: e5b0c94d7182
Create Date: 2026-08-24

`WP-RI-B-05` added `invalidate` to `Disposition`, and Manager ruling R-8 decided
which planes write it: the Relationship Memory plane does, and capture and
GoodNotes keep an explicit fail-closed refusal. Two CHECK constraints stand in
the way of the first and would stand in the way of the second if it ever changed:
`3c8f1e2a5b74` froze `capture_review_decisions.review_disposition_is_known` at
seven members and `f1c6b904a2d7` froze
`relationship_memory_review_decisions.a_memory_review_disposition_is_known` at
the same seven. Both are widened here to the eight the enum now publishes.

**The memory one is load-bearing and was measured, not predicted.** B4M's first
database run failed seven tests on
`psycopg.errors.CheckViolation ... "a_memory_review_disposition_is_known"` with
`disposition = 'invalidate'` -- the frozen text refusing the exact row the
disposition exists to produce.

**The capture one is dormant and is widened anyway**, which is the part worth
arguing. Nothing in Phase B writes `invalidate` to `capture_review_decisions`:
the capture and GoodNotes branches refuse the disposition explicitly, and R-8
keeps that refusal. But the live declaration derives its CHECK from `Disposition`
and now spells eight, while a migrated database would admit seven -- and a live
declaration disagreeing with a migrated database is exactly the drift
`tests/schema/test_extraction_schema_migration.py` exists to catch. A dormant
constraint that disagrees is still a constraint that disagrees.

**One column this revision deliberately does not add**, and the omission is a
disclosure rather than an oversight. `relationship_memory_review_decisions.reason`
and its three CHECKs are declared in `tables.py` and are **already created by
`f1c6b904a2d7` in every database these migrations can reach**, because that
revision builds its eight tables by copying the *live* `Table` objects with
`to_metadata` and freezes only their CHECK *texts*. So an `ADD COLUMN` here would
fail on empty -> head with "column already exists", and its `downgrade` would drop
a column an earlier revision created.

That asymmetry is a real structural drift and it is not this revision's to close:
`f1c6b904a2d7` tracks the live declaration for *shape* while freezing only
*vocabulary*, which is `D-69`'s defect one level up, and it applies to every
column any later package adds to any of those eight tables rather than to this
one. Closing it means teaching `_historical_relationship_memory_tables()` to drop
what did not exist when it merged, the way `_FROZEN` already restates what did.
Recorded in the Phase B pull request as a carried gap with that fix named.

The literals below are written out and frozen at this revision (`D-69`). With
`invalidate` added they *are* `Disposition`'s membership exactly, which is what
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
reports on -- and that guard reads `Table` objects handed to `create_all`, of
which this revision has none.

`downgrade` restores the seven exactly on both tables and removes no row to make
them fit. Both ledgers carry `BEFORE UPDATE OR DELETE` triggers that raise, so
deleting a decision is not something a migration could do -- and should not be:
the row records a decision a person took. A database holding one refuses to come
back down, loudly, which is the answer `c7a1f04b9e63`'s downgrade gives to the
same question about `entity_proposals`.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "a1f7d3c85e40"
down_revision: str | None = "e5b0c94d7182"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_DISPOSITIONS_AT_THIS_REVISION: Final = (
    "'accept', 'correct_and_accept', 'defer', 'escalate', 'invalidate', "
    "'mark_unresolved', 'reject', 'reprocess'"
)

_DISPOSITIONS_BEFORE_THIS_REVISION: Final = (
    "'accept', 'correct_and_accept', 'defer', 'escalate', 'mark_unresolved', 'reject', 'reprocess'"
)

#: The two ledgers and the name each gives the same closed set. Two names for one
#: vocabulary because two packages declared them separately; restated here rather
#: than derived from the tables, so this revision keeps emitting what it emitted.
_LEDGERS: Final = (
    ("capture_review_decisions", "review_disposition_is_known"),
    ("relationship_memory_review_decisions", "a_memory_review_disposition_is_known"),
)


def _restate(values: str) -> None:
    """Replace the disposition CHECK on both ledgers, in one transaction."""
    for table, constraint in _LEDGERS:
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} "
            f"DROP CONSTRAINT {constraint}, "
            f"ADD CONSTRAINT {constraint} CHECK (disposition IN ({values}))"
        )


def upgrade() -> None:
    _restate(_DISPOSITIONS_AT_THIS_REVISION)


def downgrade() -> None:
    _restate(_DISPOSITIONS_BEFORE_THIS_REVISION)
