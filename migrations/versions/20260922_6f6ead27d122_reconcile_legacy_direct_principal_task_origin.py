"""Reconcile legacy direct-Principal Task origins (CCA-005 / WP-TUX-01).

Revision ID: 6f6ead27d122
Revises: e6a4c2f91b73
Create Date: 2026-09-22

CCA-005 / WP-TUX-01 backfill correction. Revision `de5ec1c65857` (WP-TUX-01)
backfilled every existing `knowledge.tasks` row to `origin_kind = 'evidence'`
while leaving `origin_evidence_ref` unchanged. Rows that already carried
`acceptance_kind = 'direct_principal'` therefore became self-contradictory:
the domain `Task` requires a direct-Principal Task to have
`origin_evidence_ref = NULL`, and the CHECK
`a_task_origin_matches_its_provenance` requires
`(origin_kind = 'evidence' AND origin_evidence_ref IS NOT NULL AND
length(trim(origin_evidence_ref)) > 0) OR (origin_kind = 'direct_principal'
AND origin_evidence_ref IS NULL)`. Clearing only `origin_evidence_ref` would
be INVALID: it would leave `origin_kind = 'evidence'` paired with a NULL
reference, which the same CHECK refuses. **Both columns must therefore change
together, in a single UPDATE**, so the row is never observed in an
intermediate state that violates the CHECK.

**This revision is data-only.** It adds no DDL, no table, no capability, and
no purpose; it only repairs the provenance pairing of rows that WP-TUX-01
misclassified. Applying it to the persistent `my_pa` database is
operator-reserved by `AGENTS.md` 8.2; nothing in this file may be read as
authorization to do so. Tests exercise it against disposable catalogs only.

`downgrade()` is a documented no-op. Reversing this UPDATE would require the
discarded `origin_evidence_ref` values, which this revision does not retain,
and would re-introduce the contradiction the domain refuses — it would
re-break domain reconstruction. Do not invent references.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "6f6ead27d122"
down_revision: str | None = "e6a4c2f91b73"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"


def upgrade() -> None:
    # One UPDATE, both columns, so `a_task_origin_matches_its_provenance` is
    # satisfied at every instant the row is visible. Only the rows WP-TUX-01
    # misclassified are touched: `acceptance_kind = 'direct_principal'` rows
    # that were backfilled to `origin_kind = 'evidence'` with a non-null
    # reference. Legitimate evidence-origin Tasks (non-direct_principal
    # acceptance, or review-accepted evidence Tasks) are untouched.
    op.execute(
        f"""
        UPDATE {SCHEMA}.tasks
           SET origin_kind = 'direct_principal',
               origin_evidence_ref = NULL
         WHERE acceptance_kind = 'direct_principal'
           AND origin_kind = 'evidence'
           AND origin_evidence_ref IS NOT NULL;
        """  # noqa: S608
    )


def downgrade() -> None:
    # Documented no-op. Reversing would require the discarded
    # `origin_evidence_ref` values, which this revision does not retain, and
    # would re-break domain reconstruction. Do not invent references.
    pass
