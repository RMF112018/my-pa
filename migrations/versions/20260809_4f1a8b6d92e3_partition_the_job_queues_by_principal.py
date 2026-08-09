"""partition the job queues by principal

Adds `principal_id` to `knowledge.jobs` and `knowledge.capture_jobs`, backfills
it from the relationship each queue already had, and makes it `NOT NULL` with the
same opaque-identifier CHECK and a principal-first claim-order index.

**What was wrong.** Neither queue carried a principal column. Ownership existed,
but only transitively: `jobs.enrollment_id -> enrollments.principal_id` and
`capture_jobs.version_id -> capture_versions.owner_principal_id`. A transitive
owner is enough to *attribute* a row and not enough to *scope a dequeue*, and
`persistence.jobs.claim_job` did not scope one — it ordered the whole table by
`(created_at, operation_id)` and took the first claimable row with
`FOR UPDATE SKIP LOCKED`. That is a global FIFO across every Principal: one
Principal's backlog delayed another's work, one Principal's failing job consumed
the attempts budget everyone shared, and a count of outstanding work counted
everybody's. WP-04's governing invariant asks that a queue item be scoped to the
Principal that authorized it, and a predicate cannot be written against a column
that does not exist.

**The backfill is the transitive relationship, executed once.** Each queue row
takes the principal of the row it is about — the enrollment that authorized the
work, or the stored owner of the capture version that implied it. That is the
same answer a join would have produced at read time, written down, so the column
is a materialization of a fact the schema already held rather than a new claim
about anything. Both `UPDATE ... FROM` statements are deterministic: the joined
columns are each table's primary key, so every queue row matches exactly one
owner row and the result does not depend on ordering or on when it runs.

**Add nullable, backfill, then constrain — in that order, in one revision.**
`ADD COLUMN ... NOT NULL` on a populated table fails outright, so a revision
written that way would be one that only applies to an empty database. Doing all
three steps here means the revision is correct for a database holding queued
work and for an empty one, and the `SET NOT NULL` at the end is what proves the
backfill was total: if any row failed to match an owner, this revision aborts
and the transaction rolls back rather than leaving a partly partitioned queue.
Nothing is deleted, nothing is rewritten, and no row is dropped for failing to
match — the migration refuses instead.

**The `NOT VALID` / `VALIDATE` split on the CHECK.** The identifier CHECK is
added `NOT VALID` and validated immediately afterwards, which is the same end
state as a plain `ADD CONSTRAINT` and takes a weaker lock on the way there. The
validation is not skipped: an existing row whose backfilled identifier is not a
well-formed `prn_…` fails the `VALIDATE`, which is the point of running it.

**The claim-order index leads with `principal_id`.** `claim_job`'s ordering is
`(created_at, operation_id)` within a state; the index is
`(principal_id, state, created_at)` so a scoped dequeue reads one Principal's
queue rather than filtering the whole table. The historical
`jobs_by_state (state, created_at)` index is left untouched: this revision only
ever adds.

The downgrade drops the indexes, the CHECKs, and the columns. A database whose
queues hold work can be downgraded past this revision without losing the work —
only the partition, which is exactly what the revision added.

Revision ID: 4f1a8b6d92e3
Revises: 9d4e7a3b1c62
Created: 2026-08-09 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "4f1a8b6d92e3"
down_revision: str | None = "9d4e7a3b1c62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The exact CHECK the live declaration emits for a principal identifier column:
# `_is_identifier("principal_id", IdKind.PRINCIPAL)` in `tables.py` expands to
# `principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'` named
# `principal_id_is_an_opaque_identifier`. Reproduced verbatim here so the applied
# schema is the shape `to_metadata` builds from the declaration — the invariant
# the schema-parity tests assert. Inlined rather than imported because a merged
# migration must keep meaning the same thing even if the declaration is later
# edited (`D-48`); the parity tests keep the two in lock-step.
_PRINCIPAL_CHECK = "principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'"
_PRINCIPAL_CHECK_NAME = "principal_id_is_an_opaque_identifier"


def upgrade() -> None:
    """Add, backfill from the transitive owner, then constrain."""
    # --- knowledge.jobs: owner is the enrollment that authorized the work ---
    op.execute("ALTER TABLE knowledge.jobs ADD COLUMN principal_id TEXT")
    op.execute(
        "UPDATE knowledge.jobs AS job "
        "SET principal_id = grant_row.principal_id "
        "FROM knowledge.enrollments AS grant_row "
        "WHERE grant_row.enrollment_id = job.enrollment_id"
    )
    # Refuses rather than deletes: a row that matched no enrollment aborts here.
    op.execute("ALTER TABLE knowledge.jobs ALTER COLUMN principal_id SET NOT NULL")
    op.execute(
        f"ALTER TABLE knowledge.jobs "
        f"ADD CONSTRAINT {_PRINCIPAL_CHECK_NAME} CHECK ({_PRINCIPAL_CHECK}) NOT VALID"
    )
    op.execute(f"ALTER TABLE knowledge.jobs VALIDATE CONSTRAINT {_PRINCIPAL_CHECK_NAME}")
    op.create_index(
        "jobs_by_principal_claim_order",
        "jobs",
        ["principal_id", "state", "created_at"],
        schema="knowledge",
    )

    # --- knowledge.capture_jobs: owner is the stored owner of the version ---
    op.execute("ALTER TABLE knowledge.capture_jobs ADD COLUMN principal_id TEXT")
    op.execute(
        "UPDATE knowledge.capture_jobs AS job "
        "SET principal_id = version.owner_principal_id "
        "FROM knowledge.capture_versions AS version "
        "WHERE version.version_id = job.version_id"
    )
    op.execute("ALTER TABLE knowledge.capture_jobs ALTER COLUMN principal_id SET NOT NULL")
    op.execute(
        f"ALTER TABLE knowledge.capture_jobs "
        f"ADD CONSTRAINT {_PRINCIPAL_CHECK_NAME} CHECK ({_PRINCIPAL_CHECK}) NOT VALID"
    )
    op.execute(f"ALTER TABLE knowledge.capture_jobs VALIDATE CONSTRAINT {_PRINCIPAL_CHECK_NAME}")
    op.create_index(
        "capture_jobs_by_principal_claim_order",
        "capture_jobs",
        ["principal_id", "state", "created_at"],
        schema="knowledge",
    )


def downgrade() -> None:
    """Remove the partition from both queues. The work itself is untouched."""
    op.drop_index(
        "capture_jobs_by_principal_claim_order", table_name="capture_jobs", schema="knowledge"
    )
    op.execute(f"ALTER TABLE knowledge.capture_jobs DROP CONSTRAINT {_PRINCIPAL_CHECK_NAME}")
    op.execute("ALTER TABLE knowledge.capture_jobs DROP COLUMN principal_id")

    op.drop_index("jobs_by_principal_claim_order", table_name="jobs", schema="knowledge")
    op.execute(f"ALTER TABLE knowledge.jobs DROP CONSTRAINT {_PRINCIPAL_CHECK_NAME}")
    op.execute("ALTER TABLE knowledge.jobs DROP COLUMN principal_id")
