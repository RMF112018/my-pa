"""narrow `extractions.status` to the vocabulary a writer can file

`extraction_status_is_known` was derived from `ExtractionStatus`, so it admitted
`quarantined` — a status `record_outcome` routes to `quarantine_records` before
it ever reaches the insert. The declaration's own comment already said "a
quarantined object is *not* a row here"; the constraint below it said
otherwise. Narrowing to `('extracted', 'unsupported')` makes the declaration
enforce the claim it was already making.

**Why this revision exists at all.** `8b3f5c17d904` creates `extractions` from
the *live* declaration in `my_pa.infrastructure.persistence.tables`, so narrowing
that declaration changed what an already-merged revision emits. A database built
from empty today therefore gets the narrow constraint at `8b3f5c17d904`, while a
database migrated before this landed still carries the wide one. Those two are
the same schema version and must not disagree about what `status` admits. This
revision is what makes them converge.

**Both starting states reach the same place, and that is why it is written as an
unconditional drop-and-add rather than a conditional one.** The constraint's
*name* exists in either case — it is only its text that differs — so
`DROP CONSTRAINT` always finds something and `ADD CONSTRAINT` always lands on an
unconstrained column. On a freshly built database the pair is a no-op that
replaces the narrow text with the identical narrow text; on a migrated one it is
the narrowing. No `IF EXISTS` and no catalogue lookup: a conditional here would
silently do nothing on the day the name changed, which is the shape of check this
repository refuses.

Dropped and recreated rather than altered in place, and in this revision's own
transaction, for the reason `_restate` in `2b7e9f4c1a83` gives: PostgreSQL has no
"alter the expression of a check constraint", and two statements inside one
transaction leave no instant at which the column is unconstrained that another
session could observe.

**A row that the narrow vocabulary cannot represent makes this revision fail, and
that is the intended behaviour.** `ADD CONSTRAINT` validates existing rows, so an
`extractions` row already filed as `quarantined` stops the upgrade with a check
violation naming the constraint. No production path can have written one. If one
exists it was hand-written, it is evidence of something this schema never
sanctioned, and deleting it here to let the migration proceed would destroy that
evidence silently — which `AGENTS.md` forbids and which no operator asked for.
The failure is loud, reversible, and leaves the operator holding the decision.

**The `downgrade` restores the *narrow* vocabulary, and that is this revision's
subject rather than an oversight.** `8b3f5c17d904` builds `extractions` from the
live declaration, so what the revision below this one denotes is not fixed in
time — it moved the day that declaration was narrowed. A database freshly built
to `d2e3f4a5b6c7` today holds `('extracted', 'unsupported')`. Had this
`downgrade` restated the three-value text, a database that went to
`9d4e7a3b1c62` and back would admit three values at the same revision at which a
fresh one admits two: the exact divergence this revision exists to remove,
reintroduced by its own reverse. Measured rather than reasoned — the
three-value form of this `downgrade` was built and run against PostgreSQL 17.10
on this chain, and the two databases at `d2e3f4a5b6c7` then admitted
`{extracted, quarantined, unsupported}` and `{extracted, unsupported}`.
`tests/schema/test_every_revision_denotes_one_schema.py` is what stops that
returning, and it does it against a server rather than against rendered text.

It restores no rows, because none were removed. It does not return an older
database to the byte state it held before this revision ran; that state is not
recoverable from here, and it is not what "downgrade to `d2e3f4a5b6c7`" means.
It returns the database to what `d2e3f4a5b6c7` denotes, which is the only
reading under which two databases at one revision are the same database.

**Why the `_restate` precedent could not simply be copied.** The pattern comes
from `2b7e9f4c1a83`, whose `_CAPABILITIES_BEFORE_THIS_REVISION` is sound because
the revision below *it* carries a frozen literal, so that revision's denotation
cannot move. **That precondition does not hold here**: the revision below is
derived, and it has already moved. A precedent is a pair — a technique and the
condition under which it is sound — and a `..._BEFORE_THIS_REVISION` constant
naming three values was the first copied without the second. `1a4c9e77b2d5`
carries the companion the copy also left behind: a database-tier test pinning
the vocabulary its own downgrade restores. This revision has no such sibling of
its own and does not need one: `tests/schema/test_every_revision_denotes_one
_schema.py` makes the same claim for *every* revision in the chain, against a
server, so a per-revision copy would be a second statement of a property already
held whole.

Written as an explicit restatement and **not** as an empty `downgrade`. Both
reach the same database, and the guards above measure the database rather than
the DDL, so neither is stronger than the other mechanically. Stating the text is
what makes the revision's intent legible to a reader, which is the reason that
survives now that the claim is executed rather than parsed.

**Re-chained, not rewritten.** This revision was authored above `7f2a9d6c4e18`
on `bf/extractions-quarantined-debt`, before the WP-00…WP-06 principal revisions
existed. Its body is carried across unchanged and only its `down_revision`
moves, onto `d2e3f4a5b6c7`. Nothing above `7f2a9d6c4e18` touches
`knowledge.extractions` or `extraction_status_is_known`, so what this revision
finds at the new parent is what it found at the old one; the constraint it drops
is still the one `8b3f5c17d904` created, and every argument in this docstring
about `8b3f5c17d904` being derived holds verbatim at either parent.

It adds no `principal_id` and no partitioning. It creates no table and alters
one constraint on a table that is not partitioned; a partitioned `extractions`
is a different change with different consequences for every read path that
joins it.

Revision ID: 9d4e7a3b1c62
Revises: d2e3f4a5b6c7
Created: 2026-08-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op
from sqlalchemy import Table

revision: str = "9d4e7a3b1c62"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: This revision creates no table. It alters one constraint on a table
#: `8b3f5c17d904` created, and every value it emits is a frozen literal below.
#:
#: Declared, empty, rather than omitted. `test_every_revision_declares_its
#: _emission_readably` in
#: `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
#: requires a readable emission from any revision whose *source text* names a
#: declaration module — and this file's docstring names one, because explaining
#: why this revision exists is impossible without saying which declaration
#: changed. That heuristic is deliberately fail-closed, and the honest way past
#: it is to state the emission rather than to reword the prose until the scan
#: stops matching. An empty list is the true answer, and its reach is stated at
#: what it buys rather than above it: `_emitted` returns any `list`, and `[]` is
#: one, so declaring it satisfies the readability test and **shadows** the
#: `MetaData` fallback below it. A later author who added a table through
#: `op.create_table` or `op.execute` without touching this list would leave the
#: emission "readable" and that guard silent. What the declaration buys is that
#: the emission is stated rather than inferred; it does not buy detection of a
#: table added beside it. Nothing here creates a table today, and
#: `9d4e7a3b1c62`'s raw `ALTER` is outside that guard's reach in any case
#: (`D-109`).
_TABLES: list[Table] = []

SCHEMA: Final = "knowledge"
TABLE: Final = "extractions"
CONSTRAINT: Final = "extraction_status_is_known"

#: The vocabulary this revision establishes, written out. Frozen, per the
#: standing rule in `9c6b4a18ed72`: a revision that read the live declaration
#: would emit different DDL the day that declaration changed, which is the defect
#: this revision is repairing rather than one to repeat. Sorted, which is the
#: order `_one_of` produces, so the two texts can be compared directly.
#:
#: **One constant, used in both directions**, because at this revision and at the
#: one below it the admitted vocabulary is the same text — see the `downgrade`
#: paragraph in the docstring for why that is a property of `8b3f5c17d904` being
#: derived and not a shortcut. A second constant here would be a second statement
#: of one thing, and the first thing a second statement can do is disagree.
_STATUS_VOCABULARY: Final = "status IN ('extracted', 'unsupported')"


def _restate(check: str) -> None:
    """Replace `extractions.extraction_status_is_known` in this transaction."""
    op.execute(f'ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT "{CONSTRAINT}"')
    op.execute(f'ALTER TABLE {SCHEMA}.{TABLE} ADD CONSTRAINT "{CONSTRAINT}" CHECK ({check})')


def upgrade() -> None:
    _restate(_STATUS_VOCABULARY)


def downgrade() -> None:
    _restate(_STATUS_VOCABULARY)
