"""add target foreign keys

Adds the 270 foreign keys the source declares. SQLite only enforces foreign keys
when `PRAGMA foreign_keys=ON`, so these constraints are
declared-but-historically-unenforced and the data may contain orphans. They are
therefore added last: after the rows and after the indexes, because several of
them reference a unique index rather than a primary key and PostgreSQL needs
that index to exist first.

Every one is added `NOT VALID`. That binds each constraint to all future rows
immediately while skipping the scan of the rows already there, so this revision
cannot fail on a pre-existing orphan and cannot be tempted to fix one.
Validation is a separate, reportable step —
`apps/cli/migration.py validate-foreign-keys` — which validates what it can,
leaves the rest `NOT VALID`, and reports each with its orphan count. A missing
parent is an integrity fact about the source that predates this migration:
surface it, never delete or invent rows to make it pass (OD-017).

Revision ID: 3a8e2cb16d59
Revises: 2f7d1ba05c48
Created: 2026-08-01 10:08:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

from my_pa.infrastructure.migration.sql_files import read_statements

revision: str = "3a8e2cb16d59"
down_revision: str | None = "2f7d1ba05c48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def upgrade() -> None:
    for statement in read_statements(SQL_DIR / "target_foreign_keys.up.sql"):
        op.execute(statement)


def downgrade() -> None:
    for statement in read_statements(SQL_DIR / "target_foreign_keys.down.sql"):
        op.execute(statement)
