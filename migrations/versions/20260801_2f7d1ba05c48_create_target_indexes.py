"""create target indexes

Recreates the source's explicit indexes, including the ten partial indexes and
the one expression index, plus a named unique index for each table-level
`UNIQUE(...)` that SQLite left as an anonymous `sqlite_autoindex_*`. Names are
always emitted explicitly: 67 source index names are over PostgreSQL's 63-byte
limit and PostgreSQL's own auto-naming truncates and can collide.

This runs after the data lands, both because index builds are cheaper on a
populated table and because a unique index that fails tells you about a
duplicate in the source rather than aborting a load midway.

Revision ID: 2f7d1ba05c48
Revises: 4b9f0d27ac31
Created: 2026-08-01 10:08:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

from my_pa.infrastructure.migration.sql_files import read_statements

revision: str = "2f7d1ba05c48"
# The control plane sits between the tables and this revision: the load needs
# `migration_control` to exist and needs the indexes and foreign keys not to.
down_revision: str | None = "4b9f0d27ac31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def upgrade() -> None:
    for statement in read_statements(SQL_DIR / "target_indexes.up.sql"):
        op.execute(statement)


def downgrade() -> None:
    for statement in read_statements(SQL_DIR / "target_indexes.down.sql"):
        op.execute(statement)
