"""Refuse TRUNCATE of the Record Event relations.

Revision ID: c8e4a1b70d35
Revises: 1d9b248e7f83
Create Date: 2026-10-02

RE-DBH-01. Statement-level ``BEFORE TRUNCATE`` triggers on
``knowledge.record_events`` and ``knowledge.record_event_sequences``. The
existing row-level ``BEFORE UPDATE OR DELETE`` trigger on ``record_events``
is unchanged. This revision creates no role, grant, or row.

A table owner can still drop the trigger. The trigger is defense in depth.
The runtime privilege boundary is the separate role provisioner, not this
revision. ``downgrade`` refuses while either relation holds a row and deletes
nothing; an empty downgrade drops only these two triggers and their function.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "c8e4a1b70d35"
down_revision: str | None = "1d9b248e7f83"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"
FUNCTION: Final = "record_event_relations_refuse_truncate"
TRIGGERS: Final = (
    ("record_events_refuse_truncate", "record_events"),
    ("record_event_sequences_refuse_truncate", "record_event_sequences"),
)

_REFUSE_DOWNGRADE: Final = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM knowledge.record_events)
     OR EXISTS (SELECT 1 FROM knowledge.record_event_sequences) THEN
    RAISE EXCEPTION 'record events exist; refusing to downgrade c8e4a1b70d35'
      USING ERRCODE = 'restrict_violation';
  END IF;
END $$
"""


def upgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.{FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION '% refuses %', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'restrict_violation';
          RETURN NULL;
        END; $$
        """
    )
    for trigger, table in TRIGGERS:
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
              BEFORE TRUNCATE ON {SCHEMA}.{table}
              FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.{FUNCTION}()
            """
        )


def downgrade() -> None:
    op.execute(_REFUSE_DOWNGRADE)
    for trigger, table in reversed(TRIGGERS):
        op.execute(f"DROP TRIGGER {trigger} ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{FUNCTION}()")
