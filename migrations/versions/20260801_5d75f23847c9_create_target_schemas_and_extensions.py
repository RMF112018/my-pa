"""create target schemas and extensions

Creates the empty domain schemas the migration loads into and the two search
extensions the search design depends on. No table: the control plane and the
domain tables arrive in later revisions, so this revision is the only thing that
has to succeed against a database that has nothing in it at all.

Revision ID: 5d75f23847c9
Revises:
Created: 2026-08-01 09:55:13.551237
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5d75f23847c9"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: One schema per domain area, plus the control schema that records migration
#: runs. A table's schema follows its `primary_domain`; cross-cutting, bridge,
#: and unscoped tables go to `core`.
SCHEMAS: tuple[str, ...] = (
    "core",
    "procore",
    "email",
    "calendar",
    "contacts",
    "financial",
    "schedule",
    "construction",
    "migration_control",
)

#: `pg_trgm` backs fuzzy name and title matching; `unaccent` normalises accented
#: text so it matches its unaccented form. PostgreSQL full-text search plus
#: these two are the search mechanism. A vector index is not installed: it is
#: behind a benchmark gate and is not a prerequisite here.
EXTENSIONS: tuple[str, ...] = ("pg_trgm", "unaccent")


def upgrade() -> None:
    for extension in EXTENSIONS:
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    # RESTRICT, not CASCADE: a downgrade that reaches this revision with objects
    # still in a schema means a later revision did not clean up after itself,
    # and failing loudly is better than silently deleting them.
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" RESTRICT')
    for extension in reversed(EXTENSIONS):
        op.execute(f'DROP EXTENSION IF EXISTS "{extension}" RESTRICT')
