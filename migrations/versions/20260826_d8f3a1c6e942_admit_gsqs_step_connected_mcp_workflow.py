"""Admit the connected-MCP GSQS B0 `gsqs.step` capability.

Revision ID: d8f3a1c6e942
Revises: c4b0a1d9e827
Create Date: 2026-08-26

One capability name (`gsqs.step`). Purposes are unchanged
(`gsqs_b0_execution`, `gsqs_b0_observation`). ChatLLM drives inference
through production `my-pa` MCP; this name is the case lease/submit step
beside `gsqs.start` / `gsqs.status`.

**No table is created or altered here.** This revision widens one closed-set
CHECK constraint on `knowledge.audit_events` and restates the unchanged
purpose set (`D-69`).

The literals below are written out and frozen at this revision rather than
derived from the domain enums. `downgrade` restores `c4b0a1d9e827`'s
vocabulary exactly.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "d8f3a1c6e942"
down_revision: str | None = "c4b0a1d9e827"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.history', 'commitments.list', "
    "'commitments.read', 'commitments.search', 'commitments.update', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', "
    "'entities.archive', 'entities.assignments.create', "
    "'entities.assignments.end', 'entities.assignments.list', "
    "'entities.assignments.revise', 'entities.context', 'entities.create', "
    "'entities.get', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.observations.list', 'entities.observe', "
    "'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', "
    "'entities.resolve', 'entities.restore', 'entities.search', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'goodnotes.content', 'goodnotes.propose', "
    "'goodnotes.work', 'gsqs.start', 'gsqs.status', 'gsqs.step', "
    "'knowledge.coverage', "
    "'knowledge.read', 'knowledge.reveal', 'knowledge.search', "
    "'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'relationship_memory.archive', 'relationship_memory.create', "
    "'relationship_memory.get', 'relationship_memory.history', "
    "'relationship_memory.list', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', "
    "'reports.begin_cycle', 'reports.commit', 'reports.latest', "
    "'reports.list', 'reports.read', 'reports.record_run_state', "
    "'reports.resolve_set', 'reports.search', 'review.decide', 'review.list', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', "
    "'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', "
    "'tasks.search', 'tasks.transition', 'tasks.update')"
)

_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.history', 'commitments.list', "
    "'commitments.read', 'commitments.search', 'commitments.update', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', "
    "'entities.archive', 'entities.assignments.create', "
    "'entities.assignments.end', 'entities.assignments.list', "
    "'entities.assignments.revise', 'entities.context', 'entities.create', "
    "'entities.get', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.observations.list', 'entities.observe', "
    "'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', "
    "'entities.resolve', 'entities.restore', 'entities.search', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'goodnotes.content', 'goodnotes.propose', "
    "'goodnotes.work', 'gsqs.start', 'gsqs.status', 'knowledge.coverage', "
    "'knowledge.read', 'knowledge.reveal', 'knowledge.search', "
    "'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'relationship_memory.archive', 'relationship_memory.create', "
    "'relationship_memory.get', 'relationship_memory.history', "
    "'relationship_memory.list', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', "
    "'reports.begin_cycle', 'reports.commit', 'reports.latest', "
    "'reports.list', 'reports.read', 'reports.record_run_state', "
    "'reports.resolve_set', 'reports.search', 'review.decide', 'review.list', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', "
    "'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', "
    "'tasks.search', 'tasks.transition', 'tasks.update')"
)

_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_observation_ingest', 'entity_read', 'goodnotes_content', "
    "'goodnotes_proposal', 'goodnotes_work', 'gsqs_b0_execution', "
    "'gsqs_b0_observation', 'knowledge_read', 'knowledge_search', "
    "'relationship_memory_authoring', 'relationship_memory_read', "
    "'report_authoring', 'report_read', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation', "
    "'task_authoring', 'task_read')"
)

_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_observation_ingest', 'entity_read', 'goodnotes_content', "
    "'goodnotes_proposal', 'goodnotes_work', 'gsqs_b0_execution', "
    "'gsqs_b0_observation', 'knowledge_read', 'knowledge_search', "
    "'relationship_memory_authoring', 'relationship_memory_read', "
    "'report_authoring', 'report_read', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation', "
    "'task_authoring', 'task_read')"
)


def _restate(capability: str, purpose: str) -> None:
    """Replace both closed-set constraints on `audit_events` in one transaction."""
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
