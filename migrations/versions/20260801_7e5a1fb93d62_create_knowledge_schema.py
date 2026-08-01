"""create the knowledge schema

Creates the application's own schema, `knowledge`, and the five tables in it:
configured sources, observed objects, observed versions, enrollments, and jobs.

It is a new schema on purpose. The eight domain schemas hold the migrated legacy
corpus, which this revision does not read, write, or depend on; `public` holds
`alembic_version` and nothing else; and `migration_control` is a ledger scoped to
one migration run, so putting application state there would make an enrollment
retry indistinguishable from a migration retry and would give application code a
write path into migration governance. This revision therefore adds and removes
only objects that did not exist before it, and its downgrade cannot touch the
migrated corpus even if it is run against a loaded database.

The tables are declared once, in `my_pa.infrastructure.persistence.tables`, and
created from that declaration here, so the schema this revision applies and the
schema the writers assume cannot drift.

Revision ID: 7e5a1fb93d62
Revises: 6c4d3ea82f10
Created: 2026-08-01 15:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from my_pa.infrastructure.persistence.tables import METADATA, SCHEMA

revision: str = "7e5a1fb93d62"
down_revision: str | None = "6c4d3ea82f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
    METADATA.create_all(op.get_bind())


def downgrade() -> None:
    METADATA.drop_all(op.get_bind())
    # RESTRICT, not CASCADE: reaching this point with anything still in the
    # schema means a later revision left an object behind, and failing loudly is
    # better than silently deleting whatever it is.
    op.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" RESTRICT')
