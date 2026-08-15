"""Admit user-directed continuity writes and their acceptance pairing.

Revision ID: 7c2e9b4a1d80
Revises: 4f6a9c2d8e17
Create Date: 2026-08-15
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "7c2e9b4a1d80"
down_revision: str | None = "4f6a9c2d8e17"
branch_labels: str | None = None
depends_on: str | None = None

#: The capability vocabulary as of this revision: the twenty-nine public names
#: and the eleven native-source names, sorted.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', "
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
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: What `6b3d9a2f8c14` installed, restated rather than derived.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'continuity.projects', "
    "'continuity.pulse', 'continuity.situations', 'documents.archive', "
    "'documents.create', 'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: The purpose vocabulary as of this revision: twelve prior names plus
#: `continuity_authoring`, sorted.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'continuity_authoring', 'document_authoring', "
    "'document_read', 'knowledge_read', 'knowledge_search', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation')"
)

#: What `6b3d9a2f8c14` installed, restated rather than derived.
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'document_authoring', 'document_read', "
    "'knowledge_read', 'knowledge_search', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation')"
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
    op.execute(
        """
        ALTER TABLE knowledge.tasks
          ADD COLUMN acceptance_kind text NOT NULL DEFAULT 'none';
        UPDATE knowledge.tasks
          SET acceptance_kind = 'review'
          WHERE evidence_state = 'accepted';
        ALTER TABLE knowledge.tasks
          ADD CONSTRAINT a_task_acceptance_kind_is_known
            CHECK (acceptance_kind IN ('none', 'review', 'direct_principal'));
        ALTER TABLE knowledge.tasks
          DROP CONSTRAINT an_accepted_task_records_its_review_decision;
        ALTER TABLE knowledge.tasks
          ADD CONSTRAINT an_accepted_task_records_how_it_was_accepted
            CHECK (
              (
                evidence_state = 'proposed' AND acceptance_kind = 'none'
                AND accepted_by_review_decision_id IS NULL
              ) OR (
                evidence_state = 'accepted' AND acceptance_kind = 'review'
                AND accepted_by_review_decision_id IS NOT NULL
              ) OR (
                evidence_state = 'accepted' AND acceptance_kind = 'direct_principal'
                AND accepted_by_review_decision_id IS NULL
              )
            );

        CREATE TABLE knowledge.continuity_authoring_submissions (
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          idempotency_key text NOT NULL
            CHECK (length(trim(idempotency_key)) > 0),
          capability text NOT NULL,
          payload_digest text NOT NULL
            CHECK (length(trim(payload_digest)) > 0),
          object_id text NOT NULL
            CHECK (length(trim(object_id)) > 0),
          created_at timestamptz NOT NULL,
          CONSTRAINT one_authoring_key_per_principal
            PRIMARY KEY (principal_id, idempotency_key)
        );
        """
    )
    _restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)


def downgrade() -> None:
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
    op.execute(
        """
        DROP TABLE knowledge.continuity_authoring_submissions;
        ALTER TABLE knowledge.tasks
          DROP CONSTRAINT an_accepted_task_records_how_it_was_accepted;
        ALTER TABLE knowledge.tasks
          DROP CONSTRAINT a_task_acceptance_kind_is_known;
        ALTER TABLE knowledge.tasks
          ADD CONSTRAINT an_accepted_task_records_its_review_decision
            CHECK (
              (evidence_state = 'accepted')
              = (accepted_by_review_decision_id IS NOT NULL)
            );
        ALTER TABLE knowledge.tasks DROP COLUMN acceptance_kind;
        """
    )
