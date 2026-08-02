"""create the extraction, quarantine, and coverage tables

Adds three tables to the existing `knowledge` schema: `extractions`,
`quarantine_records`, and `coverage_limitations`. It creates no schema, touches
no table an earlier revision created, and reads nothing from the migrated legacy
corpus.

The three are named explicitly rather than taken from the shared `MetaData`.
`my_pa.infrastructure.persistence.tables` declares every table in this schema in
one module, so an unqualified `create_all` here would also create the five the
knowledge revision owns — and would then start creating whatever a later
revision declares, which would make this file's meaning depend on code written
after it. `tests/schema/test_extraction_schema_migration.py` asserts that each
revision emits exactly the tables it names, so removing this pin fails rather
than passing quietly.

The downgrade drops only these three. It leaves the `knowledge` schema in place
because this revision did not create it, and dropping a schema a previous
revision owns is how a downgrade takes evidence with it.

Revision ID: 8b3f5c17d904
Revises: 7e5a1fb93d62
Created: 2026-08-01 18:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Table

from my_pa.infrastructure.persistence.tables import (
    METADATA,
    coverage_limitations,
    extractions,
    quarantine_records,
)

revision: str = "8b3f5c17d904"
down_revision: str | None = "7e5a1fb93d62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Exactly the three tables this revision's docstring documents.
_TABLES: list[Table] = [extractions, quarantine_records, coverage_limitations]


def upgrade() -> None:
    METADATA.create_all(op.get_bind(), tables=_TABLES)


def downgrade() -> None:
    METADATA.drop_all(op.get_bind(), tables=_TABLES)
