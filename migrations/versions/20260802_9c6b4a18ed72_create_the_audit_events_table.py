"""create the audit events table

Adds one table to the existing `knowledge` schema: `audit_events`. It creates no
schema, touches no table an earlier revision created, and reads nothing from the
migrated legacy corpus.

This is the durable store `D-34` assigns to WP-4B. WP-4A defined `AuditSink` and
calls it on every authorization decision, but it had no migration authority, so
until this revision the only implementations were test doubles and a process
that authorized left no durable trace at all.

The table is named explicitly rather than taken from the shared `MetaData`, for
the reason `8b3f5c17d904` states: `my_pa.infrastructure.persistence.tables`
declares every table in this schema in one module, so an unqualified
`create_all` here would also create the eight that earlier revisions own — and
would then start creating whatever a later revision declares, which would make
this file's meaning depend on code written after it.
`tests/schema/test_extraction_schema_migration.py` asserts that each revision
emits exactly the tables it names.

The downgrade drops only `audit_events`. It leaves the `knowledge` schema in
place because this revision did not create it. Note what that downgrade is: it
destroys the audit trail. It exists because a migration must be reversible
against a disposable database, and it is the one operation in this schema that
an operator should never run against a database holding real decisions.

Revision ID: 9c6b4a18ed72
Revises: 8b3f5c17d904
Created: 2026-08-02 14:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Table

from my_pa.infrastructure.persistence.tables import METADATA, audit_events

revision: str = "9c6b4a18ed72"
down_revision: str | None = "8b3f5c17d904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Exactly the one table this revision's docstring documents.
_TABLES: list[Table] = [audit_events]


def upgrade() -> None:
    METADATA.create_all(op.get_bind(), tables=_TABLES)


def downgrade() -> None:
    METADATA.drop_all(op.get_bind(), tables=_TABLES)
