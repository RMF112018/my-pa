"""Partition the capture plane by Principal (WP-03, R2).

Revision ID: e7f3a9c2d514
Revises: c4a7e2d81b53
Create Date: 2026-08-05

The ratified campaign (`RATIFICATION-MYPA-MOSS-V4-20260805`, decision
`PKL-MYPA-D-WP03-001`) supersedes `D-72`'s single-local-principal posture:
capture becomes Principal-partitioned, and the two schema facts that assumed
one operator change here, forward, as literal SQL — the shape `9d5e2f7b4c61`
establishes for altering merged tables without touching their declarations.

**The idempotency key becomes unique per Principal, not globally.** The global
`a_capture_key_admits_one_submission` was correct while every submission
belonged to the one local operator; under many Principals it would let one
Principal's key choice deny another's admission — and worse, `QC-AC-031`'s
replay would hand Principal B the receipt Principal A's key is bound to. The
replacement, `a_capture_key_admits_one_submission_per_principal`, keeps the
whole server-side race-closing argument `capture_submissions` documents (two
concurrent requests both reading "absent" are still decided by the constraint,
not by a check that already ran) while making the collision domain the
Principal's own submissions and nothing wider.

**Two partition indexes, matching the reads WP-03 scopes.** `capture_page`
orders by `(created_at DESC, capture_id)` within one owner, and the scoped
search plane filters `capture_versions` by owner before ordering by
`(recorded_at DESC, version_id DESC)`; each read gets the index that serves
its own statement rather than a scan that happens to be fast at test size.

**No table declaration changes.** `1a4c9e77b2d5` copies the live
`capture_submissions` declaration when it runs (its `_FROZEN` map freezes only
the CHECK constraints), so restating the unique key there would retroactively
change what that merged revision emits and this revision's `DROP CONSTRAINT`
would then name nothing on a fresh upgrade. The declaration keeps the original
constraint; this revision owns the head shape; the comment beside the
declaration says so.

Downgrade reverses exactly: drop the indexes, restore the global key. It fails
— correctly — on data two Principals have written under one key, because that
data cannot satisfy the constraint it would restore.
"""

from __future__ import annotations

from alembic import op

revision: str = "e7f3a9c2d514"
down_revision: str | None = "c4a7e2d81b53"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.capture_submissions
          DROP CONSTRAINT "a_capture_key_admits_one_submission";
        ALTER TABLE knowledge.capture_submissions
          ADD CONSTRAINT "a_capture_key_admits_one_submission_per_principal"
          UNIQUE (principal_id, idempotency_key);
        CREATE INDEX captures_by_principal
          ON knowledge.captures (owner_principal_id, created_at DESC, capture_id);
        CREATE INDEX capture_versions_by_principal
          ON knowledge.capture_versions (owner_principal_id, recorded_at DESC, version_id DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX knowledge.capture_versions_by_principal;
        DROP INDEX knowledge.captures_by_principal;
        ALTER TABLE knowledge.capture_submissions
          DROP CONSTRAINT "a_capture_key_admits_one_submission_per_principal";
        ALTER TABLE knowledge.capture_submissions
          ADD CONSTRAINT "a_capture_key_admits_one_submission"
          UNIQUE (idempotency_key);
        """
    )
