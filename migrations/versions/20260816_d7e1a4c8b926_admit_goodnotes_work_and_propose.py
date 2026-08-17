"""Admit `goodnotes.work` / `goodnotes.propose` and create semantic proposal table.

Revision ID: d7e1a4c8b926
Revises: c9e2b6a4d813
Create Date: 2026-08-16

GN-04 / WP-06. The forward `ALTER` admits `goodnotes.work`, `goodnotes.propose`,
`goodnotes_work`, and `goodnotes_proposal` to the audited vocabulary, then
creates the Principal-bound receipt table. DDL is written out rather than
imported from `tables.py` (`D-48`, `D-69`). Closed-set literals are frozen at
this revision. Proposals are immutable receipts; they are not canonical notes,
occurrences, revisions, or run-note-changes. Revoke is not a vocabulary delete
of stored rows, but this chain still restores the prior CHECK on downgrade.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "d7e1a4c8b926"
down_revision: str | None = "c9e2b6a4d813"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The capability vocabulary as of this revision: what `b7c4e9a2d518` installed
#: (later GN-01/GN-03 revisions did not change it), plus `goodnotes.propose` and
#: `goodnotes.work`, sorted.
_CAPABILITIES_AT_THIS_REVISION: Final = (
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

#: What `b7c4e9a2d518` installed, restated rather than derived. GN-01/GN-03 did
#: not change the vocabulary.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.list', 'commitments.read', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'knowledge.coverage', 'knowledge.read', "
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

#: The purpose vocabulary as of this revision: what `b7c4e9a2d518` installed,
#: plus `goodnotes_proposal` and `goodnotes_work`, sorted.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'goodnotes_proposal', "
    "'goodnotes_work', 'knowledge_read', "
    "'knowledge_search', 'review_disposition', 'security_validation', "
    "'source_inspection', 'status_observation', 'task_authoring', 'task_read')"
)

_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'knowledge_read', "
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
        CREATE TABLE {SCHEMA}.goodnotes_semantic_proposals (
          principal_id varchar(72) NOT NULL,
          proposal_id varchar(36) NOT NULL
            CHECK (proposal_id ~ '^gnprp_[a-f0-9]{{24}}$'),
          run_id varchar(36) NOT NULL
            CHECK (run_id ~ '^gnrun_[a-f0-9]{{24}}$'),
          page_version_id varchar(30) NOT NULL
            CHECK (page_version_id ~ '^gnver_[a-f0-9]{{24}}$'),
          content_sha256 varchar(64) NOT NULL
            CHECK (content_sha256 ~ '^[a-f0-9]{{64}}$'),
          schema_version varchar(40) NOT NULL
            CHECK (char_length(schema_version) BETWEEN 1 AND 40),
          analyzer_name varchar(100) NOT NULL
            CHECK (char_length(analyzer_name) BETWEEN 1 AND 100),
          analyzer_version varchar(100) NOT NULL
            CHECK (char_length(analyzer_version) BETWEEN 1 AND 100),
          idempotency_key text NOT NULL
            CHECK (length(idempotency_key) BETWEEN 1 AND 128),
          request_fingerprint varchar(64) NOT NULL
            CHECK (request_fingerprint ~ '^[a-f0-9]{{64}}$'),
          payload_sha256 varchar(64) NOT NULL
            CHECK (payload_sha256 ~ '^[a-f0-9]{{64}}$'),
          payload jsonb NOT NULL,
          created_at timestamptz NOT NULL,
          correlation_id text NOT NULL
            CHECK (correlation_id ~ '^corr_[A-Za-z0-9]{{8,64}}$'),
          audit_id text
            CHECK (
              audit_id IS NULL OR audit_id ~ '^audit_[A-Za-z0-9]{{8,64}}$'
            ),
          request_id text NOT NULL
            CHECK (length(request_id) BETWEEN 1 AND 128),
          CONSTRAINT goodnotes_semantic_proposals_pkey
            PRIMARY KEY (principal_id, proposal_id),
          CONSTRAINT one_goodnotes_semantic_proposal_key
            UNIQUE (principal_id, idempotency_key),
          CONSTRAINT goodnotes_semantic_proposals_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES {SCHEMA}.goodnotes_ingestion_runs (
              principal_id, run_id
            )
            ON DELETE RESTRICT
        );

        CREATE TRIGGER goodnotes_semantic_proposals_are_immutable
          BEFORE UPDATE OR DELETE ON {SCHEMA}.goodnotes_semantic_proposals
          FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written();
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DROP TRIGGER IF EXISTS goodnotes_semantic_proposals_are_immutable
          ON {SCHEMA}.goodnotes_semantic_proposals;
        DROP TABLE IF EXISTS {SCHEMA}.goodnotes_semantic_proposals;
        """
    )
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
