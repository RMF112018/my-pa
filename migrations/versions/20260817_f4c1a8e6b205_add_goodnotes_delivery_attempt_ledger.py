"""Add a dormant GoodNotes delivery-attempt ledger.

Revision ID: f4c1a8e6b205
Revises: d9c4e1a7b628
Create Date: 2026-08-17

RWP-05. Additive knowledge-schema DDL. Frozen CHECKs are explicit (`D-48`,
`D-69`). Closed-set literals are frozen here. Delivery receipts stay unique on
`(principal_id, run_id, destination, summary_hash)`. This ledger does not send
to Teams, email, or Abacus. No backfill of legacy NULL revision identifiers.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f4c1a8e6b205"
down_revision: str | tuple[str, ...] | None = "d9c4e1a7b628"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE knowledge.goodnotes_delivery_attempts (
          principal_id varchar(72) NOT NULL,
          attempt_id varchar(36) NOT NULL
            CHECK (attempt_id ~ '^gndla_[a-f0-9]{24}$'),
          run_id varchar(36) NOT NULL,
          destination varchar(64) NOT NULL
            CHECK (
              char_length(destination) BETWEEN 1 AND 64
              AND destination ~ '^[a-z][a-z0-9-]{0,62}$'
            ),
          idempotency_token varchar(128) NOT NULL
            CHECK (char_length(idempotency_token) BETWEEN 1 AND 128),
          state varchar(16) NOT NULL,
          created_at timestamptz NOT NULL,
          summary_hash varchar(64)
            CHECK (
              summary_hash IS NULL
              OR summary_hash ~ '^[a-f0-9]{64}$'
            ),
          receipt_id varchar(36)
            CHECK (
              receipt_id IS NULL
              OR receipt_id ~ '^gndlv_[a-f0-9]{24}$'
            ),
          CONSTRAINT goodnotes_delivery_attempts_pkey
            PRIMARY KEY (principal_id, attempt_id),
          CONSTRAINT one_goodnotes_delivery_attempt_window
            UNIQUE (principal_id, idempotency_token, state),
          CONSTRAINT goodnotes_delivery_attempt_state_is_known
            CHECK (state IN ('PREPARED', 'SENT', 'ACKNOWLEDGED', 'FAILED')),
          CONSTRAINT goodnotes_delivery_attempt_receipt_matches_state
            CHECK (
              (
                state = 'ACKNOWLEDGED'
                AND receipt_id IS NOT NULL
              )
              OR (
                state <> 'ACKNOWLEDGED'
                AND receipt_id IS NULL
              )
            ),
          CONSTRAINT goodnotes_delivery_attempts_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES knowledge.goodnotes_ingestion_runs (
              principal_id, run_id
            )
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_delivery_attempts_receipt_fk
            FOREIGN KEY (principal_id, receipt_id)
            REFERENCES knowledge.goodnotes_delivery_receipts (
              principal_id, receipt_id
            )
            ON DELETE RESTRICT
        );

        CREATE TRIGGER goodnotes_delivery_attempts_are_immutable
          BEFORE UPDATE OR DELETE ON knowledge.goodnotes_delivery_attempts
          FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS goodnotes_delivery_attempts_are_immutable
          ON knowledge.goodnotes_delivery_attempts;
        DROP TABLE IF EXISTS knowledge.goodnotes_delivery_attempts;
        """
    )
