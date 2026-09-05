"""Bind full-run canonical promotion to immutable GoodNotes Review identities.

Revision ID: a4d8e31b2c90
Revises: 6a2f9d1c4b80
Create Date: 2026-09-05
"""

from alembic import op

revision: str = "a4d8e31b2c90"
down_revision: str | None = "6a2f9d1c4b80"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE knowledge.goodnotes_semantic_promotion_receipts (
            principal_id varchar(72) NOT NULL,
            run_id varchar(36) NOT NULL,
            receipt_id varchar(36) NOT NULL,
            binding_sha256 varchar(64) NOT NULL,
            bindings jsonb NOT NULL,
            promoted_at timestamptz NOT NULL,
            PRIMARY KEY (principal_id, run_id),
            CONSTRAINT principal_id_is_an_opaque_identifier
                CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
            CONSTRAINT goodnotes_promotion_receipt_shape
                CHECK (receipt_id ~ '^gnspr_[a-f0-9]{24}$'),
            CONSTRAINT goodnotes_promotion_digest_shape
                CHECK (binding_sha256 ~ '^[a-f0-9]{64}$'),
            CONSTRAINT goodnotes_promotion_bindings_bounded
                CHECK (jsonb_typeof(bindings) = 'array' AND jsonb_array_length(bindings) <= 10000),
            CONSTRAINT one_goodnotes_promotion_receipt UNIQUE (principal_id, receipt_id),
            CONSTRAINT goodnotes_promotion_run_fk FOREIGN KEY (principal_id, run_id)
                REFERENCES knowledge.goodnotes_ingestion_runs (principal_id, run_id)
                ON DELETE RESTRICT
        )
    """)
    op.execute("""
        CREATE TRIGGER goodnotes_semantic_promotion_receipts_are_immutable
        BEFORE UPDATE OR DELETE ON knowledge.goodnotes_semantic_promotion_receipts
        FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written()
    """)


def downgrade() -> None:
    op.execute("DROP TABLE knowledge.goodnotes_semantic_promotion_receipts RESTRICT")
