"""Add the bounded Principal-partitioned GoodNotes page plane.

Revision ID: 91d7b3e5a204
Revises: f1a6c3e8b902
Created: 2026-08-12 06:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "91d7b3e5a204"
down_revision: str | None = "f1a6c3e8b902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goodnotes_pages",
        sa.Column("principal_id", sa.String(72), nullable=False),
        sa.Column("page_id", sa.String(30), nullable=False),
        sa.Column("source_id", sa.String(72), nullable=False),
        sa.Column("source_object_id", sa.String(72), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.CheckConstraint("page_number >= 1", name="goodnotes_page_number_is_positive"),
        sa.PrimaryKeyConstraint("principal_id", "page_id"),
        sa.UniqueConstraint(
            "principal_id", "source_object_id", "page_number", name="one_goodnotes_page_identity"
        ),
        schema="knowledge",
    )
    op.create_table(
        "goodnotes_page_versions",
        sa.Column("principal_id", sa.String(72), nullable=False),
        sa.Column("page_version_id", sa.String(30), nullable=False),
        sa.Column("page_id", sa.String(30), nullable=False),
        sa.Column("source_version_id", sa.String(72), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id", "page_id"],
            ["knowledge.goodnotes_pages.principal_id", "knowledge.goodnotes_pages.page_id"],
        ),
        sa.PrimaryKeyConstraint("principal_id", "page_version_id"),
        sa.UniqueConstraint(
            "principal_id", "page_id", "source_version_id", name="one_goodnotes_observed_version"
        ),
        schema="knowledge",
    )
    op.create_table(
        "goodnotes_region_proposals",
        sa.Column("principal_id", sa.String(72), nullable=False),
        sa.Column("region_id", sa.String(30), nullable=False),
        sa.Column("page_version_id", sa.String(30), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("box", sa.JSON(), nullable=False),
        sa.Column("transcription", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extractor", sa.String(100), nullable=False),
        sa.Column("extractor_version", sa.String(100), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="goodnotes_region_ordinal_is_nonnegative"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="goodnotes_region_confidence_is_bounded"
        ),
        sa.ForeignKeyConstraint(
            ["principal_id", "page_version_id"],
            [
                "knowledge.goodnotes_page_versions.principal_id",
                "knowledge.goodnotes_page_versions.page_version_id",
            ],
        ),
        sa.PrimaryKeyConstraint("principal_id", "region_id"),
        sa.UniqueConstraint(
            "principal_id", "page_version_id", "ordinal", name="one_goodnotes_region_ordinal"
        ),
        schema="knowledge",
    )
    op.create_table(
        "goodnotes_review_decisions",
        sa.Column("principal_id", sa.String(72), nullable=False),
        sa.Column("decision_id", sa.String(30), nullable=False),
        sa.Column("region_id", sa.String(30), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("corrected_text", sa.Text()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "disposition IN ('accepted', 'corrected_accepted')",
            name="goodnotes_disposition_is_known",
        ),
        sa.CheckConstraint(
            "(disposition = 'accepted' AND corrected_text IS NULL) OR "
            "(disposition = 'corrected_accepted' AND length(corrected_text) > 0)",
            name="goodnotes_correction_matches_disposition",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id", "region_id"],
            [
                "knowledge.goodnotes_region_proposals.principal_id",
                "knowledge.goodnotes_region_proposals.region_id",
            ],
        ),
        sa.PrimaryKeyConstraint("principal_id", "decision_id"),
        sa.UniqueConstraint("principal_id", "region_id", name="one_goodnotes_region_disposition"),
        schema="knowledge",
    )
    op.create_table(
        "goodnotes_reconciliation_receipts",
        sa.Column("principal_id", sa.String(72), nullable=False),
        sa.Column("receipt_id", sa.String(30), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("page_version_ids", sa.JSON(), nullable=False),
        sa.Column("created_regions", sa.Integer(), nullable=False),
        sa.CheckConstraint("created_regions >= 0", name="goodnotes_created_regions_is_nonnegative"),
        sa.PrimaryKeyConstraint("principal_id", "idempotency_key"),
        schema="knowledge",
    )
    op.create_index(
        "goodnotes_transcription_fts",
        "goodnotes_region_proposals",
        [sa.text("to_tsvector('simple', transcription)")],
        unique=False,
        schema="knowledge",
        postgresql_using="gin",
    )
    op.create_index(
        "goodnotes_corrected_text_fts",
        "goodnotes_review_decisions",
        [sa.text("to_tsvector('simple', corrected_text)")],
        unique=False,
        schema="knowledge",
        postgresql_using="gin",
    )
    op.execute(
        "CREATE TRIGGER goodnotes_page_versions_are_immutable "
        "BEFORE UPDATE OR DELETE ON knowledge.goodnotes_page_versions "
        "FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written()"
    )
    op.execute(
        "CREATE TRIGGER goodnotes_region_proposals_are_immutable "
        "BEFORE UPDATE OR DELETE ON knowledge.goodnotes_region_proposals "
        "FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written()"
    )


def downgrade() -> None:
    op.drop_table("goodnotes_reconciliation_receipts", schema="knowledge")
    op.drop_index(
        "goodnotes_corrected_text_fts", table_name="goodnotes_review_decisions", schema="knowledge"
    )
    op.drop_table("goodnotes_review_decisions", schema="knowledge")
    op.drop_index(
        "goodnotes_transcription_fts", table_name="goodnotes_region_proposals", schema="knowledge"
    )
    op.drop_table("goodnotes_region_proposals", schema="knowledge")
    op.drop_table("goodnotes_page_versions", schema="knowledge")
    op.drop_table("goodnotes_pages", schema="knowledge")
