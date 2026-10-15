"""Reconcile legacy `unresolved_missing` Project↔Entity bridge rows (WP-MCP-PROJ-05).

Revision ID: b9025e7fb738
Revises: 5c1e7a9b3d42
Create Date: 2026-10-15

`9f2c8a1d4e70` (WP-MCP-PROJ-01) added `knowledge.project_entity_links` and
backfilled every Continuity Project that already existed with an
`unresolved_missing` row and a null entity id — by that revision's own words,
"nothing here mints an Entity and nothing joins on a name". `author_project`'s
forward path (`_mint_bound_project_entity`) mints a bound project-type Entity
for every Project created *after* that revision, atomically, but nothing was
ever written to resolve the rows the backfill left behind. A caller naming one
of those Projects by `project_id` through `entities.participations.create` or
`.list` meets `ApplicationService._bound_project_entity_id`'s correct refusal
— `ConflictError(SafeDetail.PROJECT_ID)` — forever, because nothing ever moves
the row out of `unresolved_missing`. This revision is that missing step.

**What it does.** Calls
`my_pa.infrastructure.persistence.project_entity_reconciliation.reconcile_project_entity_links`
once, unfiltered (every Principal), on this revision's own connection. For
each `unresolved_missing` row: zero existing project-type Entities whose
canonical name matches the Project's name mints a fresh Entity and binds it;
one or more matches leaves the row unbound and flags it
`unresolved_ambiguous` for a human to resolve. A row already `bound` or
`unresolved_ambiguous` is untouched. No row is ever bound to an Entity found
only by matching its name — that decision is never automatic here, the same
constraint `_mint_bound_project_entity` enforces on the forward path. See that
module's docstring for the full rationale, the ordering guarantee across rows
that share a canonical name within one pass, and why this import is a
deliberate, narrow exception to the pure-SQL precedent every other data-only
revision in this chain follows (`6f6ead27d122` is the closest one): matching a
name and minting an opaque identifier are exactly `normalize_name` and
`issue_identifier(IdKind.ENTITY)`, real Python logic this task's own
constraints forbid reimplementing in SQL.

**What it does not do.** It does not touch any row that is already `bound` or
`unresolved_ambiguous`. It does not validate that an already-`bound` row's
Entity still exists or is still project-typed — `_bound_project_entity_id`
already refuses that case at read time, and revalidating it is out of this
revision's scope. It does not change `continuity_authoring.py`'s forward path,
which was already correct. It adds no DDL, no table, no capability.

**Offline mode (`alembic upgrade --sql`) fails closed, on purpose, following
`8e1c4a7b2d90`'s precedent (see that revision's own `upgrade()`, which fails
closed for a different reason — a digest an offline script cannot
recompute).** Offline mode renders static SQL without a live connection;
`op.get_bind()` still returns an object, but it backs no real database, so
`connection.execute(...)` inside `reconcile_project_entity_links` has nothing
to read or write against. Unlike a migration that only needs a connection to
run deterministic, reviewable SQL a human could read off the generated
script, this reconciliation cannot be re-expressed as static SQL at all: it
mints opaque identifiers through `issue_identifier` (`secrets.token_hex`
under it, by construction never reproducible from a script), and it branches
per row on live candidate-count data with a genuine ordering dependency
across rows in the same pass (see the reconciliation module's docstring).
There is no deterministic SQL text that script could emit instead. So
`upgrade()` checks `context.is_offline_mode()` and emits the same
`DO $$ BEGIN RAISE EXCEPTION ...; END $$` fail-closed block `8e1c4a7b2d90`
uses, naming this revision, instead of calling the real function; normal
online Alembic execution takes the other branch. `downgrade()` needs no such
branch: it already executes nothing in either mode, so there is nothing for
offline mode to fail against.

**`downgrade()` is a documented no-op, following `6f6ead27d122`'s precedent
exactly rather than `9f2c8a1d4e70`'s conditional refusal.** A conditional
refusal (downgrade only when some row changed) was considered and rejected:
in any database where this revision did real work, at least one row is no
longer `unresolved_missing` by construction, so the condition would hold
*every* time reconciliation accomplished anything — a refusal that is
practically unconditional is not a meaningful gate, it is a no-op wearing a
condition. The honest version is a plain no-op. And a *real* reversal is
unsafe regardless: this revision keeps no log of which rows it moved or which
Entities it minted — `ReconciliationReport` is returned to the caller
in-process and nothing durable records it. Without that log, downgrade cannot
tell "an Entity this revision minted" apart from an Entity that already
existed for an unrelated reason, so it cannot safely choose which Entities to
delete, and it cannot safely flip a `bound` row back to `unresolved_missing`
either: if a participation or a later capability has since referenced the
minted Entity, discarding the binding would orphan that reference. Both
`6f6ead27d122` and `9f2c8a1d4e70` refuse to guess under the equivalent gap;
this revision's `downgrade()` makes the same choice, stated plainly as a
no-op rather than a refusal that would never actually trigger.
"""

from __future__ import annotations

from alembic import context, op

from my_pa.infrastructure.persistence.project_entity_reconciliation import (
    reconcile_project_entity_links,
)

revision: str = "b9025e7fb738"
down_revision: str | None = "5c1e7a9b3d42"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    if context.is_offline_mode():
        # Offline mode renders static SQL with no live connection to read or
        # write against, and this reconciliation has no deterministic SQL
        # equivalent to emit instead: it mints opaque identifiers through
        # `issue_identifier` (never reproducible from a script) and branches
        # per row on live candidate-count data with a genuine ordering
        # dependency across rows in the same pass. Fail closed, the same
        # pattern `8e1c4a7b2d90` uses for its own offline-unsafe step. Normal
        # online Alembic execution takes the other branch.
        op.execute(
            "DO $$ BEGIN RAISE EXCEPTION "
            "'b9025e7fb738 requires online Alembic execution for legacy "
            "Project-Entity bridge reconciliation'; "
            "END $$"
        )
    else:
        connection = op.get_bind()
        reconcile_project_entity_links(connection)


def downgrade() -> None:
    # Documented no-op: see the module docstring. Reversing would require a
    # per-row log of which rows this revision touched and which Entities it
    # minted, which it does not retain; flipping linkage_state back or
    # deleting minted Entities here could discard real bindings or orphan a
    # reference something has since made to a minted Entity. Do not guess.
    pass
