"""Widen GoodNotes entity association kinds to Meeting and Agenda.

Revision ID: d9c4e1a7b628
Revises: b7f2c9e4a618
Create Date: 2026-08-17

RWP-04. Additive knowledge-schema DDL. Frozen CHECK
`goodnotes_entity_association_kind_is_known` is widened by explicit ALTER
(`D-48`, `D-69`). Closed-set literals are frozen at this revision. No domain
enum is imported. No Meeting or Agenda store is created.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d9c4e1a7b628"
down_revision: str | tuple[str, ...] | None = "b7f2c9e4a618"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.goodnotes_entity_associations
          DROP CONSTRAINT goodnotes_entity_associations_entity_kind_check;
        ALTER TABLE knowledge.goodnotes_entity_associations
          ADD CONSTRAINT goodnotes_entity_association_kind_is_known
            CHECK (
              entity_kind IS NULL
              OR entity_kind IN ('PROJECT', 'PERSON', 'NOTE', 'MEETING', 'AGENDA')
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.goodnotes_entity_associations
          DROP CONSTRAINT goodnotes_entity_association_kind_is_known;
        ALTER TABLE knowledge.goodnotes_entity_associations
          ADD CONSTRAINT goodnotes_entity_associations_entity_kind_check
            CHECK (
              entity_kind IS NULL
              OR entity_kind IN ('PROJECT', 'PERSON', 'NOTE')
            );
        """
    )
