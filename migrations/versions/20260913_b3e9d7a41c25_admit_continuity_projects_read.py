"""Admit `continuity.projects.read` and the Project list keyset index.

Revision ID: b3e9d7a41c25
Revises: 9f2c8a1d4e70
Create Date: 2026-09-13

WP-MCP-PROJ-02 widens `knowledge.audit_events.capability_is_known` by one
name and adds the `(principal_id, created_at DESC, project_id DESC)` index
that `continuity.projects` keyset pagination uses. Purposes are unchanged.
Literals are frozen here rather than derived from domain enums (`D-48` /
architecture freeze). `9f2c8a1d4e70` did not restate the audited closed sets,
so the BEFORE texts are byte copies of `de5ec1c65857`'s AT lists.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "b3e9d7a41c25"
down_revision: str | None = "9f2c8a1d4e70"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"
INDEX: Final = "projects_by_principal_created_at_id_desc"

#: Frozen copy of de5ec1c65857's AT vocabulary (still current after
#: 9f2c8a1d4e70, which admitted no capability names).
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.create', 'capture.list', 'capture.read', 'capture.revise', 'capture.search', "
    "'commitments.close', 'commitments.create', 'commitments.history', 'commitments.list', "
    "'commitments.read', 'commitments.search', 'commitments.update', 'commitments.waiting_on', "
    "'constraint_categories.create', 'constraint_categories.deactivate', "
    "'constraint_categories.list', 'constraint_categories.reorder', "
    "'constraint_categories.update', 'constraint_sync.acknowledge', 'constraint_sync.apply', "
    "'constraint_sync.conflicts', 'constraint_sync.delta', 'constraint_sync.preview', "
    "'constraint_sync.resolve', 'constraint_sync.state', 'constraints.close', "
    "'constraints.close_follow_up', 'constraints.create', 'constraints.history', "
    "'constraints.list', 'constraints.overview', 'constraints.publish', 'constraints.read', "
    "'constraints.reopen', 'constraints.search', 'constraints.transition', 'constraints.update', "
    "'constraints.void', 'context.feedback', 'context.prepare', 'continuity.projects', "
    "'continuity.projects.create', 'continuity.pulse', 'continuity.situations', "
    "'continuity.situations.create', 'continuity.tasks.create', 'documents.archive', "
    "'documents.create', 'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'entities.addresses.add', 'entities.addresses.list', "
    "'entities.addresses.retire', 'entities.addresses.revise', 'entities.affiliations.create', "
    "'entities.affiliations.end', 'entities.affiliations.revise', 'entities.aliases.add', "
    "'entities.aliases.list', 'entities.aliases.retire', 'entities.aliases.supersede', "
    "'entities.archive', 'entities.assignments.create', 'entities.assignments.end', "
    "'entities.assignments.list', 'entities.assignments.revise', 'entities.communication.add', "
    "'entities.communication.list', 'entities.communication.retire', "
    "'entities.communication.revise', 'entities.context', 'entities.create', 'entities.get', "
    "'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', 'entities.identity_history', "
    "'entities.merge', 'entities.merge.preview', 'entities.names.add', 'entities.names.list', "
    "'entities.names.retire', 'entities.names.supersede', 'entities.observations.list', "
    "'entities.observe', 'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', 'entities.profile', "
    "'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', "
    "'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', 'entities.update', "
    "'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', 'goodnotes.notebooks.list', "
    "'goodnotes.pages.list', 'goodnotes.propose', 'goodnotes.pull', 'goodnotes.read', "
    "'goodnotes.runs.list', 'goodnotes.search', 'goodnotes.status', 'goodnotes.work', "
    "'gsqs.start', 'gsqs.status', 'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'relationship_memory.archive', 'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', 'relationship_memory.propose', "
    "'relationship_memory.restore', 'relationship_memory.revise', 'relationship_memory.search', "
    "'reports.begin_cycle', 'reports.commit', 'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', 'review.decide', "
    "'review.list', 'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.comments.create', "
    "'tasks.comments.list', 'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', "
    "'tasks.search', 'tasks.transition', 'tasks.update')"
)
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', 'canvas_workspace_read', "
    "'capture_authoring', 'capture_review', 'commitment_authoring', 'commitment_read', "
    "'constraint_authoring', 'constraint_read', 'constraint_sync_authoring', "
    "'constraint_sync_read', 'content_extraction', 'context_preference', 'context_preparation', "
    "'continuity_authoring', 'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', 'entity_read', "
    "'goodnotes_browse', 'goodnotes_content', 'goodnotes_correction', 'goodnotes_proposal', "
    "'goodnotes_pull', 'goodnotes_pull_observation', 'goodnotes_read', 'goodnotes_work', "
    "'gsqs_b0_execution', 'gsqs_b0_observation', 'knowledge_read', 'knowledge_search', "
    "'relationship_memory_authoring', 'relationship_memory_proposal', 'relationship_memory_read', "
    "'report_authoring', 'report_read', 'review_disposition', 'security_validation', "
    "'source_inspection', 'status_observation', 'task_authoring', 'task_read')"
)
#: Same set plus WP-MCP-PROJ-02 continuity.projects.read.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.create', 'capture.list', 'capture.read', 'capture.revise', 'capture.search', "
    "'commitments.close', 'commitments.create', 'commitments.history', 'commitments.list', "
    "'commitments.read', 'commitments.search', 'commitments.update', 'commitments.waiting_on', "
    "'constraint_categories.create', 'constraint_categories.deactivate', "
    "'constraint_categories.list', 'constraint_categories.reorder', "
    "'constraint_categories.update', 'constraint_sync.acknowledge', 'constraint_sync.apply', "
    "'constraint_sync.conflicts', 'constraint_sync.delta', 'constraint_sync.preview', "
    "'constraint_sync.resolve', 'constraint_sync.state', 'constraints.close', "
    "'constraints.close_follow_up', 'constraints.create', 'constraints.history', "
    "'constraints.list', 'constraints.overview', 'constraints.publish', 'constraints.read', "
    "'constraints.reopen', 'constraints.search', 'constraints.transition', 'constraints.update', "
    "'constraints.void', 'context.feedback', 'context.prepare', 'continuity.projects', "
    "'continuity.projects.create', 'continuity.projects.read', 'continuity.pulse', "
    "'continuity.situations', "
    "'continuity.situations.create', 'continuity.tasks.create', 'documents.archive', "
    "'documents.create', 'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'entities.addresses.add', 'entities.addresses.list', "
    "'entities.addresses.retire', 'entities.addresses.revise', 'entities.affiliations.create', "
    "'entities.affiliations.end', 'entities.affiliations.revise', 'entities.aliases.add', "
    "'entities.aliases.list', 'entities.aliases.retire', 'entities.aliases.supersede', "
    "'entities.archive', 'entities.assignments.create', 'entities.assignments.end', "
    "'entities.assignments.list', 'entities.assignments.revise', 'entities.communication.add', "
    "'entities.communication.list', 'entities.communication.retire', "
    "'entities.communication.revise', 'entities.context', 'entities.create', 'entities.get', "
    "'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', 'entities.identity_history', "
    "'entities.merge', 'entities.merge.preview', 'entities.names.add', 'entities.names.list', "
    "'entities.names.retire', 'entities.names.supersede', 'entities.observations.list', "
    "'entities.observe', 'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', 'entities.profile', "
    "'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', "
    "'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', 'entities.update', "
    "'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', 'goodnotes.notebooks.list', "
    "'goodnotes.pages.list', 'goodnotes.propose', 'goodnotes.pull', 'goodnotes.read', "
    "'goodnotes.runs.list', 'goodnotes.search', 'goodnotes.status', 'goodnotes.work', "
    "'gsqs.start', 'gsqs.status', 'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'relationship_memory.archive', 'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', 'relationship_memory.propose', "
    "'relationship_memory.restore', 'relationship_memory.revise', 'relationship_memory.search', "
    "'reports.begin_cycle', 'reports.commit', 'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', 'review.decide', "
    "'review.list', 'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.comments.create', "
    "'tasks.comments.list', 'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', "
    "'tasks.search', 'tasks.transition', 'tasks.update')"
)
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', 'canvas_workspace_read', "
    "'capture_authoring', 'capture_review', 'commitment_authoring', 'commitment_read', "
    "'constraint_authoring', 'constraint_read', 'constraint_sync_authoring', "
    "'constraint_sync_read', 'content_extraction', 'context_preference', 'context_preparation', "
    "'continuity_authoring', 'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', 'entity_read', "
    "'goodnotes_browse', 'goodnotes_content', 'goodnotes_correction', 'goodnotes_proposal', "
    "'goodnotes_pull', 'goodnotes_pull_observation', 'goodnotes_read', 'goodnotes_work', "
    "'gsqs_b0_execution', 'gsqs_b0_observation', 'knowledge_read', 'knowledge_search', "
    "'relationship_memory_authoring', 'relationship_memory_proposal', 'relationship_memory_read', "
    "'report_authoring', 'report_read', 'review_disposition', 'security_validation', "
    "'source_inspection', 'status_observation', 'task_authoring', 'task_read')"
)


def _restate_audit(capability: str, purpose: str) -> None:
    for name, expression in (("capability_is_known", capability), ("purpose_is_known", purpose)):
        op.drop_constraint(name, "audit_events", schema=SCHEMA, type_="check")
        op.create_check_constraint(name, "audit_events", expression, schema=SCHEMA)


def upgrade() -> None:
    _restate_audit(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)
    op.execute(
        f"CREATE INDEX {INDEX} ON {SCHEMA}.projects "
        "(principal_id, created_at DESC, project_id DESC)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.{INDEX}")
    _restate_audit(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
