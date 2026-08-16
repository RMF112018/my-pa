"""Admit Task description column and rename pulse_items.priority to attention_rank.

Two additive schema changes in one revision:

1. ``knowledge.tasks.description`` — nullable ``text``, the one MCV long-form
   Task text field the remediation plan's ``TaskDetail`` contract requires.
   No existing row changes: every current Task has no description, and ``NULL``
   is the correct representation of that fact.

2. ``knowledge.pulse_items.priority`` → ``attention_rank`` — rename only; type
   (``integer NOT NULL DEFAULT 5``), CHECK bounds, and semantics are unchanged.
   The rename resolves F-013: the domain field is now ``attention_rank`` on
   ``PulseItem`` and ``priority`` on ``Task`` (a ``TaskPriority`` enum), and the
   two can no longer be confused at the wire level.

   The parent CHECK is the server-generated name ``pulse_items_priority_check``
   from ``d2e3f4a5b6c7``'s inline ``CHECK (priority BETWEEN 1 AND 10)``. There
   is no ``a_pulse_priority_is_bounded`` to drop. Renaming that constraint to
   ``a_pulse_attention_rank_is_bounded`` keeps the expression the server already
   holds and matches the live table declaration.

Revision ID: a8a1272aaa0a
Revises: b7c4e9a2d518
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "a8a1272aaa0a"
down_revision: str | None = "b7c4e9a2d518"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA: Final = "knowledge"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN description text")
    op.execute(f"ALTER TABLE {SCHEMA}.pulse_items RENAME COLUMN priority TO attention_rank")
    op.execute(
        f"ALTER TABLE {SCHEMA}.pulse_items "
        "RENAME CONSTRAINT pulse_items_priority_check "
        "TO a_pulse_attention_rank_is_bounded"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE {SCHEMA}.pulse_items "
        "RENAME CONSTRAINT a_pulse_attention_rank_is_bounded "
        "TO pulse_items_priority_check"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.pulse_items RENAME COLUMN attention_rank TO priority")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN description")
