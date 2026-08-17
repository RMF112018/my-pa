"""Admit `goodnotes.content` and add durable-note stage and raster tables.

Revision ID: a4d9c2e7b815
Revises: c3e9a7f1b204
Create Date: 2026-08-17

RWP-02. Forward `ALTER` admits `goodnotes.content` and `goodnotes_content` to
the audited vocabulary, then creates the Principal-bound stage ledger and
pinned visual-raster table on the existing ingestion-run identity. DDL is
written out rather than imported from `tables.py` (`D-48`, `D-69`). Closed-set
literals are frozen at this revision.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "a4d9c2e7b815"
down_revision: str | None = "c3e9a7f1b204"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: Vocabulary as of this revision: what `d7e1a4c8b926` installed (later GN
#: revisions did not change it), plus `goodnotes.content`, sorted.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.list', 'commitments.read', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'goodnotes.content', 'goodnotes.propose', "
    "'goodnotes.work', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)

_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.list', 'commitments.read', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'goodnotes.propose', 'goodnotes.work', "
    "'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)

_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'goodnotes_content', "
    "'goodnotes_proposal', "
    "'goodnotes_work', 'knowledge_read', "
    "'knowledge_search', 'review_disposition', 'security_validation', "
    "'source_inspection', 'status_observation', 'task_authoring', 'task_read')"
)

_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'goodnotes_proposal', "
    "'goodnotes_work', 'knowledge_read', "
    "'knowledge_search', 'review_disposition', 'security_validation', "
    "'source_inspection', 'status_observation', 'task_authoring', 'task_read')"
)


def _restate(capability: str, purpose: str) -> None:
    """Replace both closed-set constraints on `audit_events` in one transaction."""
    for name, expression in (
        ("capability_is_known", capability),
        ("purpose_is_known", purpose),
    ):
        op.execute(f'ALTER TABLE knowledge.audit_events DROP CONSTRAINT "{name}"')
        op.execute(
            f'ALTER TABLE knowledge.audit_events ADD CONSTRAINT "{name}" CHECK ({expression})'
        )


def upgrade() -> None:
    _restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.goodnotes_ingestion_run_stages (
          principal_id varchar(72) NOT NULL,
          run_id varchar(36) NOT NULL
            CHECK (run_id ~ '^gnrun_[a-f0-9]{{24}}$'),
          stage varchar(32) NOT NULL
            CHECK (stage IN (
              'OBSERVE', 'SETTLE', 'SPLIT_RENDER', 'LINEAGE',
              'CONTENT_READY', 'WAITING_PROPOSAL', 'RECONCILE', 'PREVIEW'
            )),
          status varchar(16) NOT NULL
            CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')),
          attempt integer NOT NULL DEFAULT 1
            CHECK (attempt >= 1),
          started_at timestamptz NOT NULL,
          ended_at timestamptz,
          error_code varchar(64)
            CHECK (
              error_code IS NULL OR char_length(error_code) BETWEEN 1 AND 64
            ),
          error_class varchar(64)
            CHECK (
              error_class IS NULL OR char_length(error_class) BETWEEN 1 AND 64
            ),
          CONSTRAINT goodnotes_ingestion_run_stages_pkey
            PRIMARY KEY (principal_id, run_id, stage),
          CONSTRAINT goodnotes_run_stages_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES {SCHEMA}.goodnotes_ingestion_runs (
              principal_id, run_id
            )
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_run_stage_ended_after_start
            CHECK (ended_at IS NULL OR ended_at >= started_at)
        );

        CREATE TABLE {SCHEMA}.goodnotes_page_rasters (
          principal_id varchar(72) NOT NULL,
          page_version_id varchar(30) NOT NULL
            CHECK (page_version_id ~ '^gnver_[a-f0-9]{{24}}$'),
          run_id varchar(36) NOT NULL
            CHECK (run_id ~ '^gnrun_[a-f0-9]{{24}}$'),
          exact_render_sha256 varchar(64) NOT NULL
            CHECK (exact_render_sha256 ~ '^[a-f0-9]{{64}}$'),
          png_sha256 varchar(64) NOT NULL
            CHECK (png_sha256 ~ '^[a-f0-9]{{64}}$'),
          media_type varchar(32) NOT NULL
            CHECK (media_type = 'image/png'),
          byte_length integer NOT NULL
            CHECK (byte_length BETWEEN 1 AND 2097152),
          png_bytes bytea NOT NULL,
          renderer_name varchar(100) NOT NULL
            CHECK (char_length(renderer_name) BETWEEN 1 AND 100),
          renderer_version varchar(100) NOT NULL
            CHECK (char_length(renderer_version) BETWEEN 1 AND 100),
          render_profile_version varchar(100) NOT NULL
            CHECK (char_length(render_profile_version) BETWEEN 1 AND 100),
          created_at timestamptz NOT NULL,
          CONSTRAINT goodnotes_page_rasters_pkey
            PRIMARY KEY (principal_id, page_version_id),
          CONSTRAINT one_goodnotes_page_raster_digest
            UNIQUE (principal_id, page_version_id, exact_render_sha256),
          CONSTRAINT goodnotes_page_rasters_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES {SCHEMA}.goodnotes_ingestion_runs (
              principal_id, run_id
            )
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_page_rasters_version_fk
            FOREIGN KEY (principal_id, page_version_id)
            REFERENCES {SCHEMA}.goodnotes_page_versions (
              principal_id, page_version_id
            )
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_page_raster_bytes_match_length
            CHECK (octet_length(png_bytes) = byte_length)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DROP TABLE IF EXISTS {SCHEMA}.goodnotes_page_rasters;
        DROP TABLE IF EXISTS {SCHEMA}.goodnotes_ingestion_run_stages;
        """
    )
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
