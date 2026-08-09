"""narrow `extractions.status` to the vocabulary a writer can file

`extraction_status_is_known` was derived from `ExtractionStatus`, so it admitted
`quarantined` — a status `record_outcome` routes to `quarantine_records` before
it ever reaches the insert. The declaration's own comment already said "a
quarantined object is *not* a row here"; the constraint five dozen lines below it
said otherwise. Narrowing to `('extracted', 'unsupported')` makes the declaration
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

The `downgrade` restores the three-value vocabulary, which is what `8b3f5c17d904`
denoted before this revision existed. It restores no rows, because none were
removed.

Revision ID: 9d4e7a3b1c62
Revises: 7f2a9d6c4e18
Created: 2026-08-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op
from sqlalchemy import Table

revision: str = "9d4e7a3b1c62"
down_revision: str | None = "7f2a9d6c4e18"
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
#: stops matching. An empty list is the true answer and it keeps the guard's
#: reach intact: a table added here later has to be named, or the emission stops
#: being readable and the guard says so.
_TABLES: list[Table] = []

SCHEMA: Final = "knowledge"
TABLE: Final = "extractions"
CONSTRAINT: Final = "extraction_status_is_known"

#: The vocabulary this revision establishes, written out. Frozen, per the
#: standing rule in `9c6b4a18ed72`: a revision that read the live declaration
#: would emit different DDL the day that declaration changed, which is the defect
#: this revision is repairing rather than one to repeat. Sorted, which is the
#: order `_one_of` produces, so the two texts can be compared directly.
_STATUS_AT_THIS_REVISION: Final = "status IN ('extracted', 'unsupported')"

#: What `8b3f5c17d904` denoted before this revision, restated for the same reason
#: `_CAPABILITIES_BEFORE_THIS_REVISION` is restated in `2b7e9f4c1a83`: a downgrade
#: has to put the constraint back to what the revision below it means, not to
#: whatever the domain says on the day the downgrade runs.
_STATUS_BEFORE_THIS_REVISION: Final = "status IN ('extracted', 'quarantined', 'unsupported')"


def _restate(check: str) -> None:
    """Replace `extractions.extraction_status_is_known` in this transaction."""
    op.execute(f'ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT "{CONSTRAINT}"')
    op.execute(f'ALTER TABLE {SCHEMA}.{TABLE} ADD CONSTRAINT "{CONSTRAINT}" CHECK ({check})')


def upgrade() -> None:
    _restate(_STATUS_AT_THIS_REVISION)


def downgrade() -> None:
    _restate(_STATUS_BEFORE_THIS_REVISION)
