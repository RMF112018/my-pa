"""Add durable GoodNotes pull and semantic-review ledgers.

Revision ID: 6a2f9d1c4b80
Revises: 16f05c46b8c3
Create Date: 2026-09-04

The five tables are additive, Principal-partitioned, content-free orchestration
metadata. Pull attempts, completions, and review decisions are append-only. The
closed audit vocabularies are frozen here so migrated databases admit the three
public pull capabilities added by phase A.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "6a2f9d1c4b80"
down_revision: str | None = "16f05c46b8c3"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', 'capture.read', "
    "'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', "
    "'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', "
    "'commitments.update', 'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', "
    "'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', "
    "'entities.affiliations.create', 'entities.affiliations.end', "
    "'entities.affiliations.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', "
    "'entities.assignments.create', 'entities.assignments.end', 'entities.assignments.list', "
    "'entities.assignments.revise', 'entities.communication.add', "
    "'entities.communication.list', 'entities.communication.retire', "
    "'entities.communication.revise', 'entities.context', 'entities.create', "
    "'entities.get', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.identity_history', 'entities.merge', 'entities.merge.preview', "
    "'entities.names.add', 'entities.names.list', 'entities.names.retire', "
    "'entities.names.supersede', 'entities.observations.list', 'entities.observe', "
    "'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', "
    "'entities.profile', 'entities.proposals.create', 'entities.relationships', "
    "'entities.relationships.create', 'entities.relationships.end', "
    "'entities.relationships.revise', 'entities.resolve', 'entities.restore', "
    "'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'goodnotes.content', 'goodnotes.propose', 'goodnotes.work', "
    "'gsqs.start', 'gsqs.status', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'relationship_memory.archive', 'relationship_memory.create', "
    "'relationship_memory.get', 'relationship_memory.history', 'relationship_memory.list', "
    "'relationship_memory.propose', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', 'reports.begin_cycle', "
    "'reports.commit', 'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status', 'tasks.bulk_confirm', "
    "'tasks.bulk_preview', 'tasks.create', 'tasks.history', 'tasks.list', "
    "'tasks.read', 'tasks.search', 'tasks.transition', 'tasks.update')"
)
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', 'capture.read', "
    "'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', "
    "'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', "
    "'commitments.update', 'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', "
    "'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', "
    "'entities.affiliations.create', 'entities.affiliations.end', "
    "'entities.affiliations.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', "
    "'entities.assignments.create', 'entities.assignments.end', 'entities.assignments.list', "
    "'entities.assignments.revise', 'entities.communication.add', "
    "'entities.communication.list', 'entities.communication.retire', "
    "'entities.communication.revise', 'entities.context', 'entities.create', "
    "'entities.get', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.identity_history', 'entities.merge', 'entities.merge.preview', "
    "'entities.names.add', 'entities.names.list', 'entities.names.retire', "
    "'entities.names.supersede', 'entities.observations.list', 'entities.observe', "
    "'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', "
    "'entities.profile', 'entities.proposals.create', 'entities.relationships', "
    "'entities.relationships.create', 'entities.relationships.end', "
    "'entities.relationships.revise', 'entities.resolve', 'entities.restore', "
    "'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'goodnotes.complete', 'goodnotes.content', 'goodnotes.propose', "
    "'goodnotes.pull', 'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', "
    "'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', 'knowledge.search', "
    "'native_sources.backfill', 'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', 'relationship_memory.archive', "
    "'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', "
    "'relationship_memory.propose', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', 'reports.begin_cycle', "
    "'reports.commit', 'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status', 'tasks.bulk_confirm', "
    "'tasks.bulk_preview', 'tasks.create', 'tasks.history', 'tasks.list', "
    "'tasks.read', 'tasks.search', 'tasks.transition', 'tasks.update')"
)

_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', "
    "'entity_read', 'goodnotes_content', 'goodnotes_proposal', 'goodnotes_work', "
    "'gsqs_b0_execution', 'gsqs_b0_observation', 'knowledge_read', 'knowledge_search', "
    "'relationship_memory_authoring', 'relationship_memory_proposal', "
    "'relationship_memory_read', 'report_authoring', 'report_read', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation', 'task_authoring', 'task_read')"
)
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', "
    "'entity_read', 'goodnotes_content', 'goodnotes_proposal', 'goodnotes_pull', "
    "'goodnotes_pull_observation', 'goodnotes_work', 'gsqs_b0_execution', "
    "'gsqs_b0_observation', 'knowledge_read', 'knowledge_search', "
    "'relationship_memory_authoring', 'relationship_memory_proposal', "
    "'relationship_memory_read', 'report_authoring', 'report_read', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation', 'task_authoring', 'task_read')"
)


def _restate(capability: str, purpose: str) -> None:
    for name, expression in (
        ("capability_is_known", capability),
        ("purpose_is_known", purpose),
    ):
        op.execute(f'ALTER TABLE {SCHEMA}.audit_events DROP CONSTRAINT "{name}"')
        op.execute(
            f'ALTER TABLE {SCHEMA}.audit_events ADD CONSTRAINT "{name}" CHECK ({expression})'
        )


def _immutable(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER {table}_are_immutable BEFORE UPDATE OR DELETE ON {SCHEMA}.{table} "
        "FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written()"
    )


def upgrade() -> None:
    _restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.goodnotes_pull_sessions (
          principal_id varchar(72) NOT NULL,
          context_id varchar(128) NOT NULL,
          client_id varchar(128) NOT NULL,
          max_attempts integer NOT NULL,
          created_at timestamptz NOT NULL,
          PRIMARY KEY (principal_id, context_id),
          CONSTRAINT goodnotes_pull_session_principal_id_shape
            CHECK (principal_id ~ '^prn_[a-f0-9]{{24}}$'),
          CONSTRAINT goodnotes_pull_session_context_is_bounded
            CHECK (char_length(context_id) BETWEEN 1 AND 128 AND context_id !~ '\\s'),
          CONSTRAINT goodnotes_pull_session_client_is_bounded
            CHECK (char_length(client_id) BETWEEN 1 AND 128 AND client_id !~ '\\s'),
          CONSTRAINT goodnotes_pull_session_attempts_are_bounded
            CHECK (max_attempts BETWEEN 1 AND 10),
          CONSTRAINT one_goodnotes_pull_session_per_client UNIQUE (principal_id, client_id),
          CONSTRAINT goodnotes_pull_session_context_client_identity
            UNIQUE (principal_id, context_id, client_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.goodnotes_pull_claims (
          principal_id varchar(72) NOT NULL,
          claim_id varchar(64) NOT NULL,
          context_id varchar(128) NOT NULL,
          client_id varchar(128) NOT NULL,
          request_fingerprint varchar(64) NOT NULL,
          assignment_count integer NOT NULL,
          created_at timestamptz NOT NULL,
          PRIMARY KEY (principal_id, claim_id),
          CONSTRAINT goodnotes_pull_claim_principal_id_shape
            CHECK (principal_id ~ '^prn_[a-f0-9]{{24}}$'),
          CONSTRAINT goodnotes_pull_claim_id_shape CHECK (claim_id ~ '^[a-f0-9]{{64}}$'),
          CONSTRAINT goodnotes_pull_claim_fingerprint_shape
            CHECK (request_fingerprint ~ '^[a-f0-9]{{64}}$'),
          CONSTRAINT goodnotes_pull_claim_assignment_count_is_bounded
            CHECK (assignment_count BETWEEN 0 AND 100),
          CONSTRAINT goodnotes_pull_claims_session_fk
            FOREIGN KEY (principal_id, context_id, client_id)
            REFERENCES {SCHEMA}.goodnotes_pull_sessions
              (principal_id, context_id, client_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.goodnotes_pull_assignments (
          principal_id varchar(72) NOT NULL,
          assignment_id varchar(64) NOT NULL,
          claim_id varchar(64) NOT NULL,
          context_id varchar(128) NOT NULL,
          client_id varchar(128) NOT NULL,
          run_id varchar(36) NOT NULL,
          page_version_id varchar(30) NOT NULL,
          content_sha256 varchar(64) NOT NULL,
          attempt integer NOT NULL,
          ordinal integer NOT NULL,
          created_at timestamptz NOT NULL,
          PRIMARY KEY (principal_id, assignment_id),
          CONSTRAINT goodnotes_pull_assignment_principal_id_shape
            CHECK (principal_id ~ '^prn_[a-f0-9]{{24}}$'),
          CONSTRAINT goodnotes_pull_assignment_id_shape
            CHECK (assignment_id ~ '^[a-f0-9]{{64}}$'),
          CONSTRAINT goodnotes_pull_attempt_is_bounded CHECK (attempt BETWEEN 1 AND 10),
          CONSTRAINT goodnotes_pull_ordinal_is_bounded CHECK (ordinal BETWEEN 1 AND 100),
          CONSTRAINT one_goodnotes_pull_claim_ordinal UNIQUE (principal_id, claim_id, ordinal),
          CONSTRAINT one_goodnotes_pull_work_attempt UNIQUE
            (principal_id, run_id, page_version_id, content_sha256, attempt),
          CONSTRAINT goodnotes_pull_assignments_claim_fk
            FOREIGN KEY (principal_id, claim_id)
            REFERENCES {SCHEMA}.goodnotes_pull_claims (principal_id, claim_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_pull_assignments_session_fk
            FOREIGN KEY (principal_id, context_id, client_id)
            REFERENCES {SCHEMA}.goodnotes_pull_sessions
              (principal_id, context_id, client_id) ON DELETE RESTRICT,
          CONSTRAINT goodnotes_pull_assignments_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES {SCHEMA}.goodnotes_ingestion_runs (principal_id, run_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_pull_assignments_page_version_fk
            FOREIGN KEY (principal_id, page_version_id)
            REFERENCES {SCHEMA}.goodnotes_page_versions (principal_id, page_version_id)
            ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.goodnotes_pull_completions (
          principal_id varchar(72) NOT NULL,
          completion_id varchar(64) NOT NULL,
          assignment_id varchar(64) NOT NULL,
          context_id varchar(128) NOT NULL,
          client_id varchar(128) NOT NULL,
          idempotency_key varchar(128) NOT NULL,
          request_fingerprint varchar(64) NOT NULL,
          result_sha256 varchar(64) NOT NULL,
          created_at timestamptz NOT NULL,
          PRIMARY KEY (principal_id, completion_id),
          CONSTRAINT goodnotes_pull_completion_principal_id_shape
            CHECK (principal_id ~ '^prn_[a-f0-9]{{24}}$'),
          CONSTRAINT goodnotes_pull_completion_id_shape
            CHECK (completion_id ~ '^[a-f0-9]{{64}}$'),
          CONSTRAINT goodnotes_pull_completion_key_is_bounded
            CHECK (char_length(idempotency_key) BETWEEN 1 AND 128 AND idempotency_key !~ '\\s'),
          CONSTRAINT goodnotes_pull_completion_fingerprint_shape
            CHECK (request_fingerprint ~ '^[a-f0-9]{{64}}$'),
          CONSTRAINT goodnotes_pull_result_digest_shape
            CHECK (result_sha256 ~ '^[a-f0-9]{{64}}$'),
          CONSTRAINT one_goodnotes_pull_completion_per_assignment
            UNIQUE (principal_id, assignment_id),
          CONSTRAINT one_goodnotes_pull_completion_key
            UNIQUE (principal_id, idempotency_key),
          CONSTRAINT goodnotes_pull_completions_assignment_fk
            FOREIGN KEY (principal_id, assignment_id)
            REFERENCES {SCHEMA}.goodnotes_pull_assignments (principal_id, assignment_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_pull_completions_session_fk
            FOREIGN KEY (principal_id, context_id, client_id)
            REFERENCES {SCHEMA}.goodnotes_pull_sessions
              (principal_id, context_id, client_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.goodnotes_semantic_review_decisions (
          principal_id varchar(72) NOT NULL,
          decision_id varchar(36) NOT NULL,
          run_id varchar(36) NOT NULL,
          proposal_id varchar(36) NOT NULL,
          proposal_sha256 varchar(64) NOT NULL,
          sequence integer NOT NULL,
          action varchar(32) NOT NULL,
          request_fingerprint varchar(64) NOT NULL,
          corrected_payload jsonb,
          corrected_result_sha256 varchar(64),
          decided_at timestamptz NOT NULL,
          PRIMARY KEY (principal_id, decision_id),
          CONSTRAINT goodnotes_semantic_review_principal_id_shape
            CHECK (principal_id ~ '^prn_[a-f0-9]{{24}}$'),
          CONSTRAINT goodnotes_semantic_review_decision_id_shape
            CHECK (decision_id ~ '^gnsrd_[a-f0-9]{{24}}$'),
          CONSTRAINT goodnotes_semantic_review_proposal_digest_shape
            CHECK (proposal_sha256 ~ '^[a-f0-9]{{64}}$'),
          CONSTRAINT goodnotes_semantic_review_sequence_is_positive CHECK (sequence >= 1),
          CONSTRAINT goodnotes_semantic_review_action_is_known
            CHECK (action IN ('accept', 'correct_and_accept', 'defer', 'escalate',
                              'invalidate', 'mark_unresolved', 'reject', 'reprocess')),
          CONSTRAINT goodnotes_semantic_review_correction_matches_action
            CHECK ((action = 'correct_and_accept') =
                   (corrected_payload IS NOT NULL AND corrected_result_sha256 IS NOT NULL)),
          CONSTRAINT goodnotes_semantic_review_corrected_digest_shape
            CHECK (corrected_result_sha256 IS NULL OR corrected_result_sha256 ~ '^[a-f0-9]{{64}}$'),
          CONSTRAINT goodnotes_semantic_review_fingerprint_shape
            CHECK (request_fingerprint ~ '^[a-f0-9]{{64}}$'),
          CONSTRAINT one_goodnotes_semantic_review_per_sequence
            UNIQUE (principal_id, run_id, proposal_sha256, sequence),
          CONSTRAINT one_goodnotes_semantic_review_request
            UNIQUE (principal_id, request_fingerprint),
          CONSTRAINT goodnotes_semantic_review_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES {SCHEMA}.goodnotes_ingestion_runs (principal_id, run_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_semantic_review_proposal_fk
            FOREIGN KEY (principal_id, proposal_id)
            REFERENCES {SCHEMA}.goodnotes_semantic_proposals (principal_id, proposal_id)
            ON DELETE RESTRICT
        )
        """
    )
    for table in (
        "goodnotes_pull_sessions",
        "goodnotes_pull_claims",
        "goodnotes_pull_assignments",
        "goodnotes_pull_completions",
        "goodnotes_semantic_review_decisions",
    ):
        _immutable(table)


def downgrade() -> None:
    for table in (
        "goodnotes_semantic_review_decisions",
        "goodnotes_pull_completions",
        "goodnotes_pull_assignments",
        "goodnotes_pull_claims",
        "goodnotes_pull_sessions",
    ):
        op.execute(f"DROP TRIGGER {table}_are_immutable ON {SCHEMA}.{table}")
        op.execute(f"DROP TABLE {SCHEMA}.{table}")
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
