"""partition the relationship-identity substrate by principal

Adds `principal_id` (NOT NULL, opaque-identifier CHECK, principal-first index) to
every relationship-identity table created by `7f2a9d6c4e18` that does not already
carry one, completing the per-Principal partition for the relationship graph so
WP-06 (R5 relationship / project continuity) can read and write relationship
records, timelines, and briefings strictly within one Principal's partition.

**Scope: all 17 relationship-identity tables, not a subset.** The WP-06 plan
named 11 tables, but `7f2a9d6c4e18` created 17 in one revision and they form a
single identity graph joined through `observation_id`, `person_id`, and
`resolution_id`. Partitioning only the "primary" tables would leave the link and
support tables (`relationship_aliases`, `relationship_affiliations`,
`relationship_evidence`, `relationship_evidence_observations`,
`relationship_conversation_participants`,
`relationship_conversation_observations`, `relationship_resolution_observations`,
`relationship_duplicate_members`, `relationship_observation_links`) unpartitioned,
and a query joining a principal-scoped table to an unpartitioned link table could
synthesize a cross-Principal read from two otherwise-scoped tables. That is the
exact hazard the WP-05 review/promotion partition (`b9a4ecdfac0b`) called out when
it partitioned `capture_assertion_spans` and `capture_proposal_spans` even though
they hold no distinct facts. The same reasoning applies here, so every table in
the graph carries the partition explicitly.

**`relationship_identity_review_decisions` already carries `principal_id`.** It
was created with `principal_id TEXT NOT NULL CHECK (principal_id ~
'^prn_[A-Za-z0-9]{8,64}$')` in `7f2a9d6c4e18` because a decision records the
deciding Principal. This revision does not re-add the column; it only adds the
principal-first index that the other 16 tables receive, so the whole graph is
indexed identically for principal-scoped list queries.

**Why a forward ALTER rather than editing `7f2a9d6c4e18` in place.** That
revision is already merged. Editing it would retroactively change what a merged
revision emits — the `D-48` hazard. This forward `ALTER` is explicit, testable,
and leaves every already-merged revision meaning exactly what it meant.

**The upgrade path for existing data.** At head `b9a4ecdfac0b` the repository
holds zero relationship-identity rows — the relationship substrate is
fixture-only and every row is principal-scoped from the moment it is written — so
`ALTER TABLE ... ADD COLUMN ... NOT NULL` succeeds on empty tables with no
backfill. A deployment holding relationship rows from an earlier revision cannot
apply this migration without a backfill step, which is not provided here because
the campaign plan starts from an empty database and the acceptance gates prove
per-Principal isolation before any live data.

**The CHECK literal is inlined, not imported.** `_PRINCIPAL_CHECK` reproduces the
exact regex and constraint name that `tables.py`'s `_is_identifier("principal_id",
IdKind.PRINCIPAL)` emits, so the applied schema is byte-for-byte the shape
`to_metadata` builds from the live declaration — the invariant the schema-parity
tests assert. A merged migration must keep meaning the same thing even if the
declaration is later edited (`D-48`); the parity tests keep the two in lock-step.

The downgrade drops the added indexes and columns (and the lone index on
`relationship_identity_review_decisions`). A database with relationship rows
cannot be downgraded past this revision without losing the principal partition.

Revision ID: c1f2d3e4a5b6
Revises: b9a4ecdfac0b
Created: 2026-08-05 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c1f2d3e4a5b6"
down_revision: str | None = "b9a4ecdfac0b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PRINCIPAL_CHECK = "principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'"
_PRINCIPAL_CHECK_NAME = "principal_id_is_an_opaque_identifier"

# Every relationship-identity table `7f2a9d6c4e18` created except
# `relationship_identity_review_decisions`, which already carries `principal_id`.
_TABLES_TO_PARTITION: tuple[str, ...] = (
    "relationship_people",
    "relationship_organizations",
    "relationship_identity_observations",
    "relationship_unresolved_mentions",
    "relationship_duplicate_sets",
    "relationship_duplicate_members",
    "relationship_identity_review_cases",
    "relationship_identity_resolutions",
    "relationship_resolution_observations",
    "relationship_observation_links",
    "relationship_aliases",
    "relationship_affiliations",
    "relationship_evidence",
    "relationship_evidence_observations",
    "relationship_conversation_participants",
    "relationship_conversation_observations",
)

# Already carries `principal_id`; only the principal-first index is added.
_TABLE_ALREADY_PARTITIONED = "relationship_identity_review_decisions"


def _index_name(table: str) -> str:
    return f"{table}_by_principal"


def upgrade() -> None:
    """Add principal_id + CHECK + principal-first index to the relationship graph."""
    for table in _TABLES_TO_PARTITION:
        op.execute(f"ALTER TABLE knowledge.{table} ADD COLUMN principal_id TEXT NOT NULL")
        op.execute(
            f"ALTER TABLE knowledge.{table} "
            f"ADD CONSTRAINT {_PRINCIPAL_CHECK_NAME} CHECK ({_PRINCIPAL_CHECK})"
        )
        op.create_index(
            _index_name(table),
            table,
            ["principal_id"],
            schema="knowledge",
        )

    # The one table that already carries the column gets the matching index so
    # the whole graph is indexed identically.
    op.create_index(
        _index_name(_TABLE_ALREADY_PARTITIONED),
        _TABLE_ALREADY_PARTITIONED,
        ["principal_id"],
        schema="knowledge",
    )


def downgrade() -> None:
    """Remove the principal partition from the relationship graph."""
    op.drop_index(
        _index_name(_TABLE_ALREADY_PARTITIONED),
        table_name=_TABLE_ALREADY_PARTITIONED,
        schema="knowledge",
    )
    for table in reversed(_TABLES_TO_PARTITION):
        op.drop_index(_index_name(table), table_name=table, schema="knowledge")
        op.execute(f"ALTER TABLE knowledge.{table} DROP CONSTRAINT {_PRINCIPAL_CHECK_NAME}")
        op.execute(f"ALTER TABLE knowledge.{table} DROP COLUMN principal_id")
