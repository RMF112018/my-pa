"""partition review, promotion, and assertions by principal

Adds `principal_id` to `capture_review_cases`, `capture_assertions`,
`capture_assertion_spans`, and `capture_promotion_receipts`, with NOT NULL and
principal-first composite indexes. Every review case, assertion, and promotion
receipt becomes partitioned by the Principal who opened the review or accepted
the proposal, completing the per-Principal isolation model for the review and
promotion substrate that `3c8f1e2a5b74` introduced.

**Why this is a separate revision rather than altering `3c8f1e2a5b74` in
place.** That revision merged at WP-08 before the identity foundation existed,
when `P00-OD-010` described a single local principal (`D-72`) and no
multi-Principal scenario could be tested. Adding `principal_id` to the review
tables now would retroactively change what that merged revision emits, which is
the `D-48` hazard. This forward `ALTER` is explicit, testable, and does not
change what any already-merged revision means.

**The upgrade path for existing data.** At head `e7f3a9c2d514` the repository
holds zero review cases, assertions, or promotion receipts — every one is
principal-scoped from the moment it is written — so the `ALTER TABLE ... ADD
COLUMN ... NOT NULL` succeeds on an empty table and no backfill is required. A
deployment holding review/assertion rows from an earlier revision cannot apply
this migration without a backfill step, which is not provided here because the
campaign plan starts from an empty database and the acceptance gates prove
per-Principal isolation before any live data.

**Indexes support principal-scoped list queries.** Review cases are listed by
capture and opened_at under one principal; assertions and promotion receipts are
read by their own ID but may be listed by version or proposal under one
principal. The indexes all lead with `principal_id` so the planner can use them
for principal-scoped queries without scanning unowned rows.

**`capture_assertion_spans` is partitioned too**, even though it holds no
distinct facts. A span row exists only to bind one assertion to one capture
span, and both sides of that link are principal-scoped, so the span link must be
as well — otherwise a query joining through it could synthesize a
cross-principal read from two principal-scoped tables. The pattern is the same
as `capture_proposal_spans`, which carries `version_id` (already
principal-scoped via capture) but must also carry `principal_id` explicitly so
span queries can enforce the partition without joining back to captures.

**No change to `capture_review_decisions`.** That table already carries
`principal_id` (added in `3c8f1e2a5b74`) because a decision records the
deciding Principal. This revision adds the partition to the case, assertion, and
receipt planes, completing the review/promotion substrate.

The downgrade drops the four columns and their indexes. A database with review
or assertion rows cannot be downgraded past this revision without losing the
principal partition.

Revision ID: b9a4ecdfac0b
Revises: e7f3a9c2d514
Created: 2026-08-05 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b9a4ecdfac0b"
down_revision: str | None = "e7f3a9c2d514"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The exact CHECK the live declaration emits for a principal identifier column:
# `_is_identifier("principal_id", IdKind.PRINCIPAL)` in tables.py expands to
# `principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'` named
# `principal_id_is_an_opaque_identifier`. This forward ALTER reproduces that
# name and that regex verbatim so the applied schema is byte-for-byte the shape
# `to_metadata` would build from the live declaration — the invariant the
# schema-parity tests assert. The literal is inlined (not imported from
# `tables.py`) because a merged migration must keep meaning the same thing even
# if the declaration is later edited (`D-48`); the parity tests are what keep the
# two in lock-step.
_PRINCIPAL_CHECK = "principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'"
_PRINCIPAL_CHECK_NAME = "principal_id_is_an_opaque_identifier"


def upgrade() -> None:
    """Add principal_id to review cases, assertions, assertion spans, and promotion receipts."""
    # Review cases: one Principal opens one review case
    op.execute("ALTER TABLE knowledge.capture_review_cases ADD COLUMN principal_id TEXT NOT NULL")
    op.execute(
        f"ALTER TABLE knowledge.capture_review_cases "
        f"ADD CONSTRAINT {_PRINCIPAL_CHECK_NAME} CHECK ({_PRINCIPAL_CHECK})"
    )
    op.create_index(
        "capture_review_cases_by_principal",
        "capture_review_cases",
        ["principal_id", "opened_at"],
        schema="knowledge",
    )

    # Assertions: one Principal accepts one proposal
    op.execute("ALTER TABLE knowledge.capture_assertions ADD COLUMN principal_id TEXT NOT NULL")
    op.execute(
        f"ALTER TABLE knowledge.capture_assertions "
        f"ADD CONSTRAINT {_PRINCIPAL_CHECK_NAME} CHECK ({_PRINCIPAL_CHECK})"
    )
    op.create_index(
        "capture_assertions_by_principal",
        "capture_assertions",
        ["principal_id", "assertion_id"],
        schema="knowledge",
    )
    # A distinct principal-first composite; the historical
    # `capture_assertions_by_version (version_id, state)` created by
    # `3c8f1e2a5b74` is left untouched so this revision only ever *adds*.
    op.create_index(
        "capture_assertions_by_principal_version",
        "capture_assertions",
        ["principal_id", "version_id", "state"],
        schema="knowledge",
    )

    # Assertion spans: inherit principal from assertion
    op.execute("ALTER TABLE knowledge.capture_assertion_spans ADD COLUMN principal_id TEXT NOT NULL")
    op.execute(
        f"ALTER TABLE knowledge.capture_assertion_spans "
        f"ADD CONSTRAINT {_PRINCIPAL_CHECK_NAME} CHECK ({_PRINCIPAL_CHECK})"
    )
    op.create_index(
        "capture_assertion_spans_by_principal",
        "capture_assertion_spans",
        ["principal_id", "assertion_id"],
        schema="knowledge",
    )

    # Promotion receipts: one Principal promotes one proposal
    op.execute("ALTER TABLE knowledge.capture_promotion_receipts ADD COLUMN principal_id TEXT NOT NULL")
    op.execute(
        f"ALTER TABLE knowledge.capture_promotion_receipts "
        f"ADD CONSTRAINT {_PRINCIPAL_CHECK_NAME} CHECK ({_PRINCIPAL_CHECK})"
    )
    op.create_index(
        "capture_promotion_receipts_by_principal",
        "capture_promotion_receipts",
        ["principal_id", "receipt_id"],
        schema="knowledge",
    )


def downgrade() -> None:
    """Remove principal_id from review, assertion, and promotion tables."""
    # Drop indexes and columns in reverse order. Only the indexes this revision
    # created are dropped; `capture_assertions_by_version` is historical and
    # remains.
    op.drop_index("capture_promotion_receipts_by_principal", table_name="capture_promotion_receipts", schema="knowledge")
    op.execute(f"ALTER TABLE knowledge.capture_promotion_receipts DROP CONSTRAINT {_PRINCIPAL_CHECK_NAME}")
    op.execute("ALTER TABLE knowledge.capture_promotion_receipts DROP COLUMN principal_id")

    op.drop_index("capture_assertion_spans_by_principal", table_name="capture_assertion_spans", schema="knowledge")
    op.execute(f"ALTER TABLE knowledge.capture_assertion_spans DROP CONSTRAINT {_PRINCIPAL_CHECK_NAME}")
    op.execute("ALTER TABLE knowledge.capture_assertion_spans DROP COLUMN principal_id")

    op.drop_index("capture_assertions_by_principal_version", table_name="capture_assertions", schema="knowledge")
    op.drop_index("capture_assertions_by_principal", table_name="capture_assertions", schema="knowledge")
    op.execute(f"ALTER TABLE knowledge.capture_assertions DROP CONSTRAINT {_PRINCIPAL_CHECK_NAME}")
    op.execute("ALTER TABLE knowledge.capture_assertions DROP COLUMN principal_id")

    op.drop_index("capture_review_cases_by_principal", table_name="capture_review_cases", schema="knowledge")
    op.execute(f"ALTER TABLE knowledge.capture_review_cases DROP CONSTRAINT {_PRINCIPAL_CHECK_NAME}")
    op.execute("ALTER TABLE knowledge.capture_review_cases DROP COLUMN principal_id")
