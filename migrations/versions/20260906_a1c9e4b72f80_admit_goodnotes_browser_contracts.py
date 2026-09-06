"""Admit GoodNotes browser query, read, and correct contracts.

Revision ID: a1c9e4b72f80
Revises: 2774329487be
Create Date: 2026-09-06

Vocabulary-only: six public capabilities and three purposes. No new tables.
Lists and search are reads. `goodnotes.correct` is an additive product-owned
revision write and does not overwrite a source raster.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "a1c9e4b72f80"
down_revision: str | None = "2774329487be"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: Frozen copy of `d4e8b1c7a902._CAPABILITIES_AT_THIS_REVISION`. Later
#: revisions through `2774329487be` did not widen this CHECK.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.create', 'capture.list', 'capture.read', "
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
    "'entities.get', 'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', "
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
    "'entities.update', 'goodnotes.complete', 'goodnotes.content', "
    "'goodnotes.propose', "
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
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.create', 'capture.list', 'capture.read', "
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
    "'entities.get', 'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', "
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
    "'entities.update', 'goodnotes.complete', 'goodnotes.content', "
    "'goodnotes.correct', 'goodnotes.notebooks.list', 'goodnotes.pages.list', "
    "'goodnotes.propose', "
    "'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', "
    "'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', "
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

#: Frozen copy of `d4e8b1c7a902._PURPOSES_AT_THIS_REVISION`.
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', "
    "'canvas_workspace_read', 'capture_authoring', 'capture_review', "
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
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', "
    "'canvas_workspace_read', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', "
    "'entity_read', 'goodnotes_browse', 'goodnotes_content', 'goodnotes_correction', "
    "'goodnotes_proposal', 'goodnotes_pull', "
    "'goodnotes_pull_observation', 'goodnotes_read', 'goodnotes_work', 'gsqs_b0_execution', "
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


def upgrade() -> None:
    _restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)


def downgrade() -> None:
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
