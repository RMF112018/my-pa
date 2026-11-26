"""Project-report reads: the read vocabulary (WP4P-S4).

Revision ID: 3b3373d8268e
Revises: fa18ef3d9bc0
Create Date: 2026-11-25

The one additive revision of the project-report reads WP4P, on the sole head
`fa18ef3d9bc0` (WP4P-W1 design report section 3; Manager ruling D1). Vocabulary
only: no table, column, index, view, trigger, `GRANT`, `REVOKE` or backfill.
In order it:

1. sets `lock_timeout` to 10 s for this revision's transaction only
   (`SET LOCAL`), so a lock that cannot be taken aborts the whole revision with
   `55P03` and leaves the database at `fa18ef3d9bc0`; then takes `ACCESS EXCLUSIVE`
   on `audit_events`, the only table it alters;
2. restates `audit_events.capability_is_known` (the `_restate` precedent: `DROP
   CONSTRAINT` then `ADD CONSTRAINT ... CHECK`, `ACCESS EXCLUSIVE` held to
   commit) with the frozen sorted set of 327 names: the 322 `fa18ef3d9bc0`
   left plus exactly `project_reports.catalog`, `project_reports.compare`,
   `project_reports.coverage`, `project_reports.query` and
   `project_reports.record_history`;
3. restates `purpose_is_known` with 74: the 73 `fa18ef3d9bc0` left plus
   exactly `project_reports_read`.

Every set is a frozen literal and this revision imports nothing from the live
domain. The domain declares the names in the same change (WP4P-S4).

`downgrade` locks the same table `ACCESS EXCLUSIVE` and refuses with
`restrict_violation`, deleting nothing, while any audit event names a new
capability or the new purpose (the `61fafdfd2986` precedent: refuse rather than
delete audit history). Otherwise it restores the byte copies of the previous
two CHECKs.

Applying this revision to a persistent, shared or production database requires
separate operator authority; nothing here grants it.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "3b3373d8268e"
down_revision: str | None = "fa18ef3d9bc0"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_LOCK_TIMEOUT: Final = "SET LOCAL lock_timeout = '10s'"
_LOCK_TABLES: Final = "LOCK TABLE knowledge.audit_events IN ACCESS EXCLUSIVE MODE"

# ---- the audit vocabulary, frozen ---------------------------------------------------

#: Byte copy of `fa18ef3d9bc0`'s AT set (322 names), the latest prior restatement
#: of `capability_is_known`.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.archive', 'capture.create', 'capture.list', 'capture.read', 'capture.restore', "
    "'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', "
    "'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', "
    "'commitments.update', 'commitments.v2.list', 'commitments.v2.read', "
    "'commitments.v2.search', 'commitments.v2.waiting_on', 'commitments.waiting_on', "
    "'communications.coverage', 'communications.read', 'communications.search', "
    "'constraint_categories.create', 'constraint_categories.deactivate', "
    "'constraint_categories.list', 'constraint_categories.reorder', "
    "'constraint_categories.update', 'constraint_sync.acknowledge', 'constraint_sync.apply', "
    "'constraint_sync.conflicts', 'constraint_sync.delta', 'constraint_sync.preview', "
    "'constraint_sync.resolve', 'constraint_sync.state', 'constraints.close', "
    "'constraints.close_follow_up', 'constraints.create', 'constraints.create_published', "
    "'constraints.history', 'constraints.list', 'constraints.overview', "
    "'constraints.portfolio_list', 'constraints.portfolio_overview', "
    "'constraints.portfolio_search', 'constraints.publish', 'constraints.read', "
    "'constraints.reopen', 'constraints.search', 'constraints.transition', "
    "'constraints.update', 'constraints.void', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.close', 'continuity.projects.create', "
    "'continuity.projects.read', 'continuity.projects.update', 'continuity.pulse', "
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
    "'entities.communication.revise', 'entities.context', 'entities.create', 'entities.get', "
    "'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.identity_history', 'entities.merge', 'entities.merge.preview', "
    "'entities.names.add', 'entities.names.list', 'entities.names.retire', "
    "'entities.names.supersede', 'entities.observations.list', 'entities.observe', "
    "'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', 'entities.profile', "
    "'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', "
    "'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'files.copy', 'files.download.begin', 'files.history', 'files.list', "
    "'files.mkdir', 'files.move', 'files.preview', 'files.rename', 'files.restore', "
    "'files.search', 'files.stat', 'files.trash', 'files.upload.abort', "
    "'files.upload.begin', 'files.upload.finalize', 'files.workspaces.list', "
    "'files.write_text', 'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', "
    "'goodnotes.notebooks.list', 'goodnotes.pages.list', 'goodnotes.propose', "
    "'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', "
    "'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', 'issues.close', "
    "'issues.closure_readiness', 'issues.create', 'issues.handoffs.correct', "
    "'issues.handoffs.list', 'issues.handoffs.record', 'issues.history', 'issues.list', "
    "'issues.memberships.add', 'issues.memberships.confirm', 'issues.memberships.correct', "
    "'issues.memberships.end', 'issues.project_links.add', 'issues.project_links.confirm', "
    "'issues.project_links.end', 'issues.read', 'issues.reopen', 'issues.timeline', "
    "'issues.update', 'issues.work.create_commitment', 'issues.work.create_task', "
    "'knowledge.assertions.create', 'knowledge.assertions.history', "
    "'knowledge.assertions.list', 'knowledge.assertions.read', "
    "'knowledge.assertions.reveal', 'knowledge.assertions.search', "
    "'knowledge.assertions.submit', 'knowledge.coverage', 'knowledge.discovery.checkpoint', "
    "'knowledge.read', 'knowledge.reveal', 'knowledge.search', 'meetings.create', "
    "'meetings.list', 'meetings.notes.read_version', 'meetings.notes.versions', "
    "'meetings.provider.bind', 'meetings.provider.reconcile', 'meetings.provider.review', "
    "'meetings.read', 'meetings.search', 'meetings.series.update', 'meetings.update', "
    "'native_sources.backfill', 'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', 'programs.members.resolve', "
    "'programs.overview', 'project_controls.configure', 'project_controls.status', "
    "'record_events.list', 'record_events.provenance', 'records.associations.assert', "
    "'records.associations.confirm', 'records.associations.contest', "
    "'records.associations.correct', 'records.associations.end', "
    "'records.associations.history', 'records.associations.reinstate', "
    "'records.backfill.plan', 'records.backfill.report', 'records.lineage', "
    "'records.lineage.related', 'relationship_memory.archive', 'relationship_memory.create', "
    "'relationship_memory.get', 'relationship_memory.history', 'relationship_memory.list', "
    "'relationship_memory.propose', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', 'reports.archive', "
    "'reports.begin_cycle', 'reports.commit', 'reports.delete', 'reports.history', "
    "'reports.hold.place', 'reports.hold.release', 'reports.latest', 'reports.list', "
    "'reports.manifest', 'reports.publish', 'reports.read', 'reports.record_run_state', "
    "'reports.resolve_set', 'reports.restore', 'reports.retention.get', "
    "'reports.retention.set', 'reports.search', 'reports.transfer.abort', "
    "'reports.transfer.append', 'reports.transfer.begin', 'reports.transfer.finalize', "
    "'reports.transfer.read_chunk', 'reports.types.create', 'reports.types.list', "
    "'reports.update', 'review.decide', 'review.list', 'schedule_activities.history', "
    "'schedule_activities.list', 'schedule_baselines.approve', 'schedule_baselines.compare', "
    "'schedule_baselines.governing', 'schedule_baselines.list', "
    "'schedule_baselines.propose', 'schedule_baselines.read', 'schedule_baselines.reject', "
    "'schedule_baselines.revoke', 'schedule_baselines.set_governing', "
    "'schedule_baselines.withdraw', 'schedule_changes.list', 'schedule_cpm_runs.activities', "
    "'schedule_cpm_runs.create', 'schedule_cpm_runs.read', 'schedule_p6_activities.list', "
    "'schedule_p6_calendars.list', 'schedule_p6_field_values.list', "
    "'schedule_p6_fields.available', 'schedule_p6_fields.set_captured', "
    "'schedule_p6_relationships.list', 'schedule_publications.import', "
    "'schedule_publications.import_p6', 'schedule_publications.list', "
    "'schedule_publications.read', 'schedule_scenario_outputs.list', "
    "'schedule_scenario_outputs.read', 'schedule_scenario_outputs.record', "
    "'schedule_scenario_versions.activities', 'schedule_scenario_versions.changes', "
    "'schedule_scenario_versions.create', 'schedule_scenario_versions.read', "
    "'schedule_scenario_versions.relationships', 'schedule_scenarios.create', "
    "'schedule_scenarios.list', 'schedule_scenarios.read', 'schedule_series.current', "
    "'schedule_series.list', 'schedule_series.match_decisions', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.comments.create', "
    "'tasks.comments.list', 'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', "
    "'tasks.search', 'tasks.transition', 'tasks.update')"
)

#: The same set plus exactly the five `project_reports.*` read names -- 327
#: names, sorted.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.archive', 'capture.create', 'capture.list', 'capture.read', 'capture.restore', "
    "'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', "
    "'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', "
    "'commitments.update', 'commitments.v2.list', 'commitments.v2.read', "
    "'commitments.v2.search', 'commitments.v2.waiting_on', 'commitments.waiting_on', "
    "'communications.coverage', 'communications.read', 'communications.search', "
    "'constraint_categories.create', 'constraint_categories.deactivate', "
    "'constraint_categories.list', 'constraint_categories.reorder', "
    "'constraint_categories.update', 'constraint_sync.acknowledge', 'constraint_sync.apply', "
    "'constraint_sync.conflicts', 'constraint_sync.delta', 'constraint_sync.preview', "
    "'constraint_sync.resolve', 'constraint_sync.state', 'constraints.close', "
    "'constraints.close_follow_up', 'constraints.create', 'constraints.create_published', "
    "'constraints.history', 'constraints.list', 'constraints.overview', "
    "'constraints.portfolio_list', 'constraints.portfolio_overview', "
    "'constraints.portfolio_search', 'constraints.publish', 'constraints.read', "
    "'constraints.reopen', 'constraints.search', 'constraints.transition', "
    "'constraints.update', 'constraints.void', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.close', 'continuity.projects.create', "
    "'continuity.projects.read', 'continuity.projects.update', 'continuity.pulse', "
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
    "'entities.communication.revise', 'entities.context', 'entities.create', 'entities.get', "
    "'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.identity_history', 'entities.merge', 'entities.merge.preview', "
    "'entities.names.add', 'entities.names.list', 'entities.names.retire', "
    "'entities.names.supersede', 'entities.observations.list', 'entities.observe', "
    "'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', 'entities.profile', "
    "'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', "
    "'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'files.copy', 'files.download.begin', 'files.history', 'files.list', "
    "'files.mkdir', 'files.move', 'files.preview', 'files.rename', 'files.restore', "
    "'files.search', 'files.stat', 'files.trash', 'files.upload.abort', "
    "'files.upload.begin', 'files.upload.finalize', 'files.workspaces.list', "
    "'files.write_text', 'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', "
    "'goodnotes.notebooks.list', 'goodnotes.pages.list', 'goodnotes.propose', "
    "'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', "
    "'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', 'issues.close', "
    "'issues.closure_readiness', 'issues.create', 'issues.handoffs.correct', "
    "'issues.handoffs.list', 'issues.handoffs.record', 'issues.history', 'issues.list', "
    "'issues.memberships.add', 'issues.memberships.confirm', 'issues.memberships.correct', "
    "'issues.memberships.end', 'issues.project_links.add', 'issues.project_links.confirm', "
    "'issues.project_links.end', 'issues.read', 'issues.reopen', 'issues.timeline', "
    "'issues.update', 'issues.work.create_commitment', 'issues.work.create_task', "
    "'knowledge.assertions.create', 'knowledge.assertions.history', "
    "'knowledge.assertions.list', 'knowledge.assertions.read', "
    "'knowledge.assertions.reveal', 'knowledge.assertions.search', "
    "'knowledge.assertions.submit', 'knowledge.coverage', 'knowledge.discovery.checkpoint', "
    "'knowledge.read', 'knowledge.reveal', 'knowledge.search', 'meetings.create', "
    "'meetings.list', 'meetings.notes.read_version', 'meetings.notes.versions', "
    "'meetings.provider.bind', 'meetings.provider.reconcile', 'meetings.provider.review', "
    "'meetings.read', 'meetings.search', 'meetings.series.update', 'meetings.update', "
    "'native_sources.backfill', 'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', 'programs.members.resolve', "
    "'programs.overview', 'project_controls.configure', 'project_controls.status', "
    "'project_reports.catalog', 'project_reports.compare', 'project_reports.coverage', "
    "'project_reports.query', 'project_reports.record_history', 'record_events.list', "
    "'record_events.provenance', 'records.associations.assert', "
    "'records.associations.confirm', 'records.associations.contest', "
    "'records.associations.correct', 'records.associations.end', "
    "'records.associations.history', 'records.associations.reinstate', "
    "'records.backfill.plan', 'records.backfill.report', 'records.lineage', "
    "'records.lineage.related', 'relationship_memory.archive', 'relationship_memory.create', "
    "'relationship_memory.get', 'relationship_memory.history', 'relationship_memory.list', "
    "'relationship_memory.propose', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', 'reports.archive', "
    "'reports.begin_cycle', 'reports.commit', 'reports.delete', 'reports.history', "
    "'reports.hold.place', 'reports.hold.release', 'reports.latest', 'reports.list', "
    "'reports.manifest', 'reports.publish', 'reports.read', 'reports.record_run_state', "
    "'reports.resolve_set', 'reports.restore', 'reports.retention.get', "
    "'reports.retention.set', 'reports.search', 'reports.transfer.abort', "
    "'reports.transfer.append', 'reports.transfer.begin', 'reports.transfer.finalize', "
    "'reports.transfer.read_chunk', 'reports.types.create', 'reports.types.list', "
    "'reports.update', 'review.decide', 'review.list', 'schedule_activities.history', "
    "'schedule_activities.list', 'schedule_baselines.approve', 'schedule_baselines.compare', "
    "'schedule_baselines.governing', 'schedule_baselines.list', "
    "'schedule_baselines.propose', 'schedule_baselines.read', 'schedule_baselines.reject', "
    "'schedule_baselines.revoke', 'schedule_baselines.set_governing', "
    "'schedule_baselines.withdraw', 'schedule_changes.list', 'schedule_cpm_runs.activities', "
    "'schedule_cpm_runs.create', 'schedule_cpm_runs.read', 'schedule_p6_activities.list', "
    "'schedule_p6_calendars.list', 'schedule_p6_field_values.list', "
    "'schedule_p6_fields.available', 'schedule_p6_fields.set_captured', "
    "'schedule_p6_relationships.list', 'schedule_publications.import', "
    "'schedule_publications.import_p6', 'schedule_publications.list', "
    "'schedule_publications.read', 'schedule_scenario_outputs.list', "
    "'schedule_scenario_outputs.read', 'schedule_scenario_outputs.record', "
    "'schedule_scenario_versions.activities', 'schedule_scenario_versions.changes', "
    "'schedule_scenario_versions.create', 'schedule_scenario_versions.read', "
    "'schedule_scenario_versions.relationships', 'schedule_scenarios.create', "
    "'schedule_scenarios.list', 'schedule_scenarios.read', 'schedule_series.current', "
    "'schedule_series.list', 'schedule_series.match_decisions', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.comments.create', "
    "'tasks.comments.list', 'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', "
    "'tasks.search', 'tasks.transition', 'tasks.update')"
)

#: Byte copy of `fa18ef3d9bc0`'s purpose AT set (73 purposes), the latest prior
#: restatement of `purpose_is_known`.
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', "
    "'canvas_workspace_read', 'capture_authoring', 'capture_review', 'commitment_authoring', "
    "'commitment_read', 'communications_read', 'constraint_authoring', 'constraint_read', "
    "'constraint_sync_authoring', 'constraint_sync_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', "
    "'entity_read', 'file_workspace_authoring', 'file_workspace_read', 'goodnotes_browse', "
    "'goodnotes_content', 'goodnotes_correction', 'goodnotes_proposal', 'goodnotes_pull', "
    "'goodnotes_pull_observation', 'goodnotes_read', 'goodnotes_work', 'gsqs_b0_execution', "
    "'gsqs_b0_observation', 'issue_authoring', 'issue_read', 'issue_work_authoring', "
    "'knowledge_assertion_authoring', 'knowledge_assertion_observation', "
    "'knowledge_assertion_read', 'knowledge_read', 'knowledge_search', 'lineage_backfill', "
    "'meeting_authoring', 'meeting_note_history_read', 'meeting_read', "
    "'program_reporting_read', 'record_event_provenance_read', 'record_event_read', "
    "'record_lineage_authoring', 'record_lineage_read', 'relationship_memory_authoring', "
    "'relationship_memory_proposal', 'relationship_memory_read', 'report_authoring', "
    "'report_hold', 'report_lifecycle', 'report_read', 'report_retention', "
    "'review_disposition', 'schedule_analysis_authoring', 'schedule_analysis_read', "
    "'schedule_baseline_approval', 'schedule_import', 'schedule_p6_configuration', "
    "'schedule_p6_import', 'schedule_read', 'security_validation', 'source_inspection', "
    "'status_observation', 'task_authoring', 'task_read')"
)

#: The same set plus exactly `project_reports_read` -- 74 purposes, sorted.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', "
    "'canvas_workspace_read', 'capture_authoring', 'capture_review', 'commitment_authoring', "
    "'commitment_read', 'communications_read', 'constraint_authoring', 'constraint_read', "
    "'constraint_sync_authoring', 'constraint_sync_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', "
    "'entity_read', 'file_workspace_authoring', 'file_workspace_read', 'goodnotes_browse', "
    "'goodnotes_content', 'goodnotes_correction', 'goodnotes_proposal', 'goodnotes_pull', "
    "'goodnotes_pull_observation', 'goodnotes_read', 'goodnotes_work', 'gsqs_b0_execution', "
    "'gsqs_b0_observation', 'issue_authoring', 'issue_read', 'issue_work_authoring', "
    "'knowledge_assertion_authoring', 'knowledge_assertion_observation', "
    "'knowledge_assertion_read', 'knowledge_read', 'knowledge_search', 'lineage_backfill', "
    "'meeting_authoring', 'meeting_note_history_read', 'meeting_read', "
    "'program_reporting_read', 'project_reports_read', 'record_event_provenance_read', "
    "'record_event_read', 'record_lineage_authoring', 'record_lineage_read', "
    "'relationship_memory_authoring', 'relationship_memory_proposal', "
    "'relationship_memory_read', 'report_authoring', 'report_hold', 'report_lifecycle', "
    "'report_read', 'report_retention', 'review_disposition', 'schedule_analysis_authoring', "
    "'schedule_analysis_read', 'schedule_baseline_approval', 'schedule_import', "
    "'schedule_p6_configuration', 'schedule_p6_import', 'schedule_read', "
    "'security_validation', 'source_inspection', 'status_observation', 'task_authoring', "
    "'task_read')"
)

#: The names this revision admits to the audit vocabulary.
_NEW_CAPABILITIES: Final = (
    "project_reports.catalog",
    "project_reports.compare",
    "project_reports.coverage",
    "project_reports.query",
    "project_reports.record_history",
)
_NEW_PURPOSES: Final = ("project_reports_read",)

# ---- downgrade -------------------------------------------------------------------

#: `downgrade` refuses while any audit event names what `fa18ef3d9bc0` cannot hold,
#: rather than deleting audit history to make the downgrade pass (the
#: `61fafdfd2986` precedent).
_REFUSE_DOWNGRADE: Final = """
    DO $$
    BEGIN
      IF EXISTS (
           SELECT 1 FROM knowledge.audit_events
            WHERE capability IN ('project_reports.catalog', 'project_reports.compare',
                                 'project_reports.coverage', 'project_reports.query',
                                 'project_reports.record_history')
               OR purpose IN ('project_reports_read')) THEN
        RAISE EXCEPTION 'project-report read audit exists; refusing to downgrade 3b3373d8268e'
          USING ERRCODE = 'restrict_violation';
      END IF;
    END $$
    """


def _restate(table: str, name: str, expression: str) -> None:
    op.drop_constraint(name, table, schema=SCHEMA, type_="check")
    op.create_check_constraint(name, table, expression, schema=SCHEMA)


def upgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_LOCK_TABLES)
    _restate("audit_events", "capability_is_known", _CAPABILITIES_AT_THIS_REVISION)
    _restate("audit_events", "purpose_is_known", _PURPOSES_AT_THIS_REVISION)


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_LOCK_TABLES)
    op.execute(_REFUSE_DOWNGRADE)
    _restate("audit_events", "purpose_is_known", _PURPOSES_BEFORE_THIS_REVISION)
    _restate("audit_events", "capability_is_known", _CAPABILITIES_BEFORE_THIS_REVISION)
