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

The five are named explicitly rather than taken as "whatever is in the shared
`MetaData`". `METADATA` is shared with every later revision that declares a table
in this schema, so an unqualified `create_all` would create the tables of those
revisions too: this landed revision would silently start doing more than its own
docstring says the moment someone declared a sixth table, and it would stop being
a record of what was applied. The pin makes the code match the docstring, and
`tests/schema/test_extraction_schema_migration.py` asserts the equality per
revision so removing it fails rather than passing quietly.

Revision ID: 7e5a1fb93d62
Revises: 6c4d3ea82f10
Created: 2026-08-01 15:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Table

from my_pa.infrastructure.persistence.tables import (
    METADATA,
    SCHEMA,
    enrollments,
    jobs,
    source_object_versions,
    source_objects,
    sources,
)

revision: str = "7e5a1fb93d62"
down_revision: str | None = "6c4d3ea82f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Exactly the five tables this revision's docstring documents. Order is not
#: significant — SQLAlchemy sorts by foreign-key dependency on create and
#: reverses that on drop — but membership is.
_TABLES: list[Table] = [sources, source_objects, source_object_versions, enrollments, jobs]


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
    METADATA.create_all(op.get_bind(), tables=_TABLES)


def downgrade() -> None:
    METADATA.drop_all(op.get_bind(), tables=_TABLES)
    # RESTRICT, not CASCADE: reaching this point with anything still in the
    # schema means a later revision left an object behind, and failing loudly is
    # better than silently deleting whatever it is.
    op.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" RESTRICT')
