"""create target views

Hand-ports the two read models the source defines as SQLite views. They are not
ETL input -- they carry no rows of their own -- so the loader skips them and they
have to be recreated as PostgreSQL views over the migrated base tables (OD-018).

Both port with their predicates unchanged. `procore_inspection_items.is_unanswered`
carries no `CHECK (x IN (0,1))` in the source, so it mapped to `bigint` rather
than `boolean` (OD-015) and `= 1` remains correct; had it been promoted, this
predicate would have needed `IS TRUE` instead. That is the whole reason the
boolean promotion was tied to a declared constraint rather than to a column name.

Revision ID: 6c4d3ea82f10
Revises: 3a8e2cb16d59
Created: 2026-08-01 16:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "6c4d3ea82f10"
down_revision: str | None = "3a8e2cb16d59"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# LEFT JOIN, not INNER: the source view keeps an item whose inspection record or
# section is missing, and reproducing the read model means reproducing that too.
_UNANSWERED_ITEMS = """
CREATE VIEW procore.v_procore_inspection_unanswered_items AS
SELECT
    i.project_key,
    r.name_redacted AS inspection_name_redacted,
    s.name_redacted AS section_name_redacted,
    i.item_number,
    i.item_name_redacted,
    i.responded_with,
    i.status,
    i.updated_at_utc
FROM procore.procore_inspection_items i
LEFT JOIN procore.procore_inspection_records r
    ON r.project_key = i.project_key
   AND r.inspection_id = i.inspection_id
LEFT JOIN procore.procore_inspection_sections s
    ON s.project_key = i.project_key
   AND s.section_id = i.section_id
WHERE i.is_unanswered = 1
"""

# The source view is SELECT *. It is spelled out here because a view defined with
# * freezes the column list at creation time anyway, so the expansion is what
# PostgreSQL would store -- writing it explicitly just makes that visible.
_OPEN_ACTION_SIGNALS = """
CREATE VIEW procore.v_procore_open_action_signals AS
SELECT *
FROM procore.procore_action_signals
WHERE signal_status = 'open'
"""


def upgrade() -> None:
    op.execute(_UNANSWERED_ITEMS)
    op.execute(_OPEN_ACTION_SIGNALS)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS procore.v_procore_open_action_signals")
    op.execute("DROP VIEW IF EXISTS procore.v_procore_inspection_unanswered_items")
