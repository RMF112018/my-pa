"""Add GoodNotes entity associations and NEW-only delivery receipts.

Revision ID: e8c1b5a7d204
Revises: d7e1a4c8b926
Create Date: 2026-08-16

GN-06 / WP-08 + WP-10. Additive knowledge-schema DDL. Ranked GN-04 candidates
associate against existing Principal-partitioned records or stay unresolved
literals; this revision does not create Projects, people, or Tasks and does not
widen `goodnotes_note_links`. Delivery receipts are immutable and unique over
(principal_id, run_id, destination, summary_hash). DDL is written out rather
than imported from `tables.py` (`D-48`, `D-69`). Closed-set literals are frozen
here. No capability or purpose vocabulary change.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e8c1b5a7d204"
down_revision: str | tuple[str, ...] | None = "d7e1a4c8b926"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE knowledge.goodnotes_entity_associations (
          principal_id varchar(72) NOT NULL,
          association_id varchar(36) NOT NULL
            CHECK (association_id ~ '^gnent_[a-f0-9]{24}$'),
          run_id varchar(36) NOT NULL,
          note_id varchar(36) NOT NULL,
          candidate varchar(200) NOT NULL
            CHECK (char_length(candidate) BETWEEN 1 AND 200),
          rank integer NOT NULL
            CHECK (rank >= 1),
          resolution varchar(16) NOT NULL
            CHECK (resolution IN ('ASSOCIATED', 'UNRESOLVED')),
          entity_kind varchar(16)
            CHECK (
              entity_kind IS NULL
              OR entity_kind IN ('PROJECT', 'PERSON', 'NOTE')
            ),
          resolved_id varchar(72)
            CHECK (
              resolved_id IS NULL
              OR char_length(resolved_id) BETWEEN 1 AND 72
            ),
          created_at timestamptz NOT NULL,
          CONSTRAINT goodnotes_entity_associations_pkey
            PRIMARY KEY (principal_id, association_id),
          CONSTRAINT one_goodnotes_entity_association_candidate
            UNIQUE (principal_id, run_id, note_id, rank, candidate),
          CONSTRAINT goodnotes_entity_association_resolution_matches
            CHECK (
              (
                resolution = 'ASSOCIATED'
                AND entity_kind IS NOT NULL
                AND resolved_id IS NOT NULL
              )
              OR (
                resolution = 'UNRESOLVED'
                AND entity_kind IS NULL
                AND resolved_id IS NULL
              )
            ),
          CONSTRAINT goodnotes_entity_associations_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES knowledge.goodnotes_ingestion_runs (
              principal_id, run_id
            )
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_entity_associations_note_fk
            FOREIGN KEY (principal_id, note_id)
            REFERENCES knowledge.goodnotes_notes (principal_id, note_id)
            ON DELETE RESTRICT
        );

        CREATE TABLE knowledge.goodnotes_delivery_receipts (
          principal_id varchar(72) NOT NULL,
          receipt_id varchar(36) NOT NULL
            CHECK (receipt_id ~ '^gndlv_[a-f0-9]{24}$'),
          run_id varchar(36) NOT NULL,
          destination varchar(64) NOT NULL
            CHECK (
              char_length(destination) BETWEEN 1 AND 64
              AND destination ~ '^[a-z][a-z0-9-]{0,62}$'
            ),
          summary_hash varchar(64) NOT NULL
            CHECK (summary_hash ~ '^[a-f0-9]{64}$'),
          suppressed boolean NOT NULL,
          body text
            CHECK (
              (suppressed AND body IS NULL)
              OR (
                NOT suppressed
                AND body IS NOT NULL
                AND char_length(body) BETWEEN 1 AND 200000
              )
            ),
          created_at timestamptz NOT NULL,
          CONSTRAINT goodnotes_delivery_receipts_pkey
            PRIMARY KEY (principal_id, receipt_id),
          CONSTRAINT one_goodnotes_delivery_summary
            UNIQUE (principal_id, run_id, destination, summary_hash),
          CONSTRAINT goodnotes_delivery_receipts_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES knowledge.goodnotes_ingestion_runs (
              principal_id, run_id
            )
            ON DELETE RESTRICT
        );

        CREATE TRIGGER goodnotes_entity_associations_are_immutable
          BEFORE UPDATE OR DELETE ON knowledge.goodnotes_entity_associations
          FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written();

        CREATE TRIGGER goodnotes_delivery_receipts_are_immutable
          BEFORE UPDATE OR DELETE ON knowledge.goodnotes_delivery_receipts
          FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS goodnotes_delivery_receipts_are_immutable
          ON knowledge.goodnotes_delivery_receipts;
        DROP TRIGGER IF EXISTS goodnotes_entity_associations_are_immutable
          ON knowledge.goodnotes_entity_associations;
        DROP TABLE IF EXISTS knowledge.goodnotes_delivery_receipts;
        DROP TABLE IF EXISTS knowledge.goodnotes_entity_associations;
        """
    )
