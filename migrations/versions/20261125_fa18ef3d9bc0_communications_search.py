"""Communications search: rederive markers, identifier kinds and the read vocabulary (WP4-S1).

Revision ID: fa18ef3d9bc0
Revises: 0d4e247d03cb
Create Date: 2026-11-25

The one additive revision of communications intelligence WP4, on the sole head
`0d4e247d03cb` (Manager rulings D6, D7, D10, R2, R3, R4, R5 and R17; design
report section 2.1 without the prune, which ruling R4 defers). In order it:

1. sets `lock_timeout` to 10 s for this revision's transaction only
   (`SET LOCAL`), so a lock that cannot be taken aborts the whole revision with
   `55P03` and leaves the database at `0d4e247d03cb`; then takes every lock the
   revision needs up front, in one fixed order (the downgrade's order):
   `ACCESS EXCLUSIVE` on `communication_messages`, `communication_identifiers`
   and `audit_events`, the three tables it alters;
2. adds two columns to `communication_messages`:
   * `source_unavailable BOOLEAN NOT NULL DEFAULT false` -- set by the WP4
     rederive when a message's source file is missing or its SHA-256 differs,
     cleared by a later successful rederive (R3);
   * `identifiers_version TEXT` (a token CHECK,
     `a_communication_identifiers_version_is_a_token`) -- the extractor version
     the message's identifier rows were last written under; NULL means never
     recorded, which covers every WP3a row (R2);
3. replaces the function of the named-mutable trigger
   `communication_messages_change_only_their_projection` (`CREATE OR REPLACE`,
   the trigger itself is unchanged) so both new columns are mutable. Without
   this the JSONB-minus rule of `52a829ef718a` keeps every added column
   immutable;
4. widens `a_communication_identifier_kind_is_known` on
   `communication_identifiers` with `cor` and `pco` (R5: change order requests
   and potential change orders are their own kinds), by dropping and re-adding
   the CHECK (a validating scan). The table stays append-only exactly as
   before: no DELETE is admitted and no setting is read (R4: no prune in WP4);
5. restates `audit_events.capability_is_known` (the `_restate` precedent: `DROP
   CONSTRAINT` then `ADD CONSTRAINT ... CHECK`, `ACCESS EXCLUSIVE` held to
   commit) with the frozen sorted set of 315 names: the 312 `61fafdfd2986`
   left plus exactly `communications.coverage`, `communications.read` and
   `communications.search`; and `purpose_is_known` with 71: the 70
   `640aaacc78e8` left plus exactly `communications_read` (D7). The names are
   admitted ahead of the domain, which declares them in WP4-S5.

Every bound is a frozen literal and this revision imports nothing from the live
domain. No trigram index (ruling D5 / M1), no `GRANT`, no `REVOKE`, no backfill.

`downgrade` locks the same three tables `ACCESS EXCLUSIVE` and refuses with
`restrict_violation`, deleting nothing, while any row holds what the previous
revision cannot hold or would silently lose: a message with
`source_unavailable` true or a recorded `identifiers_version`, an identifier of
kind `cor` or `pco`, or an audit event naming a new capability or the new
purpose (the `61fafdfd2986` precedent: refuse rather than delete evidence or
audit history). Otherwise it restores the byte copies of the previous audit
sets, kind CHECK and trigger function, then drops the two columns.

Applying this revision to a persistent, shared or production database requires
separate operator authority; nothing here grants it.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "fa18ef3d9bc0"
down_revision: str | None = "0d4e247d03cb"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_LOCK_TIMEOUT: Final = "SET LOCAL lock_timeout = '10s'"

#: Every lock the revision needs, taken first and in one fixed order (the
#: downgrade's), so no lock is upgraded or added after it began changing things.
_LOCK_TABLES: Final = (
    "LOCK TABLE knowledge.communication_messages, knowledge.communication_identifiers, "
    "knowledge.audit_events IN ACCESS EXCLUSIVE MODE"
)

# ---- step 2: the two message columns ---------------------------------------------

_MESSAGES: Final = "communication_messages"

#: `(column, DDL type)`, in the order they are added (and dropped in reverse).
_MESSAGE_COLUMNS: Final = (
    ("source_unavailable", "BOOLEAN NOT NULL DEFAULT false"),
    ("identifiers_version", "TEXT"),
)
_IDENTIFIERS_VERSION_CHECK: Final = "a_communication_identifiers_version_is_a_token"
_IDENTIFIERS_VERSION_EXPRESSION: Final = "identifiers_version ~ '^[a-z][a-z0-9_]{0,63}$'"

# ---- step 3: the named-mutable message guard --------------------------------------

_MESSAGE_FUNCTION: Final = "communication_messages_change_only_their_projection"

#: Byte copy of `52a829ef718a`'s `_MESSAGE_MUTABLE`.
_MUTABLE_BEFORE_THIS_REVISION: Final = (
    "search_text",
    "search_text_sha256",
    "search_text_version",
    "search_text_basis",
    "search_text_flags",
    "text_snapshot_id",
    "text_record_ordinal",
    "body_state",
    "body_sha256",
    "body_utf8_bytes",
    "content_type",
    "latest_snapshot_id",
    "identity_conflict",
    "participants_reconciled",
    "participants_disagreed",
    "search_document",
)
#: The same columns plus exactly the two this revision adds.
_MUTABLE_AT_THIS_REVISION: Final = (
    *_MUTABLE_BEFORE_THIS_REVISION,
    "source_unavailable",
    "identifiers_version",
)


def _message_guard(mutable: tuple[str, ...]) -> str:
    """The guard function, as `52a829ef718a`'s `_named_mutable` and `_only` render it.

    Rendered with `CREATE OR REPLACE`; the body between the dollar quotes is
    byte-identical to the original for `_MUTABLE_BEFORE_THIS_REVISION`, so the
    downgrade restores exactly what `52a829ef718a` created.
    """
    keys = ", ".join(f"'{name}'" for name in mutable)
    return f"""
    CREATE OR REPLACE FUNCTION {SCHEMA}.{_MESSAGE_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '{_MESSAGES} rows are never deleted'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF (to_jsonb(NEW) - ARRAY[{keys}]::text[])
         IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[{keys}]::text[]) THEN
        RAISE EXCEPTION '{_MESSAGES} changes only its named mutable columns'
          USING ERRCODE = 'restrict_violation';
      END IF;
      RETURN NEW;
    END; $$;
    """


# ---- step 4: the identifier kinds ---------------------------------------------------

_IDENTIFIERS: Final = "communication_identifiers"
_KIND_CHECK: Final = "a_communication_identifier_kind_is_known"
#: Byte copy of `52a829ef718a`'s kind set.
_KINDS_BEFORE_THIS_REVISION: Final = (
    "kind IN ('cb', 'co', 'fpl', 'gmp', 'rfi', 'spec', 'submittal')"
)
#: The same set plus exactly `cor` and `pco`, sorted.
_KINDS_AT_THIS_REVISION: Final = (
    "kind IN ('cb', 'co', 'cor', 'fpl', 'gmp', 'pco', 'rfi', 'spec', 'submittal')"
)

# ---- step 5: the audit vocabulary, frozen -------------------------------------------

#: Byte copy of `61fafdfd2986`'s AT set (312 names), the latest prior
#: restatement of `capability_is_known`.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.archive', 'capture.create', 'capture.list', 'capture.read', "
    "'capture.restore', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.history', 'commitments.list', 'commitments.read', "
    "'commitments.search', 'commitments.update', 'commitments.v2.list', "
    "'commitments.v2.read', 'commitments.v2.search', 'commitments.v2.waiting_on', "
    "'commitments.waiting_on', 'constraint_categories.create', "
    "'constraint_categories.deactivate', 'constraint_categories.list', "
    "'constraint_categories.reorder', 'constraint_categories.update', "
    "'constraint_sync.acknowledge', 'constraint_sync.apply', 'constraint_sync.conflicts', "
    "'constraint_sync.delta', 'constraint_sync.preview', 'constraint_sync.resolve', "
    "'constraint_sync.state', 'constraints.close', 'constraints.close_follow_up', "
    "'constraints.create', 'constraints.create_published', 'constraints.history', "
    "'constraints.list', 'constraints.overview', 'constraints.portfolio_list', "
    "'constraints.portfolio_overview', 'constraints.portfolio_search', "
    "'constraints.publish', 'constraints.read', 'constraints.reopen', "
    "'constraints.search', 'constraints.transition', 'constraints.update', "
    "'constraints.void', 'context.feedback', 'context.prepare', 'continuity.projects', "
    "'continuity.projects.close', 'continuity.projects.create', "
    "'continuity.projects.read', 'continuity.projects.update', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', "
    "'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', "
    "'entities.affiliations.create', 'entities.affiliations.end', "
    "'entities.affiliations.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', "
    "'entities.assignments.create', 'entities.assignments.end', "
    "'entities.assignments.list', 'entities.assignments.revise', "
    "'entities.communication.add', 'entities.communication.list', "
    "'entities.communication.retire', 'entities.communication.revise', "
    "'entities.context', 'entities.create', 'entities.get', 'entities.graph', "
    "'entities.identifiers.bind', 'entities.identifiers.list', "
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
    "'entities.update', 'files.copy', 'files.download.begin', 'files.history', "
    "'files.list', 'files.mkdir', 'files.move', 'files.preview', 'files.rename', "
    "'files.restore', 'files.search', 'files.stat', 'files.trash', 'files.upload.abort', "
    "'files.upload.begin', 'files.upload.finalize', 'files.workspaces.list', "
    "'files.write_text', 'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', "
    "'goodnotes.notebooks.list', 'goodnotes.pages.list', 'goodnotes.propose', "
    "'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', "
    "'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', 'issues.close', "
    "'issues.closure_readiness', 'issues.create', 'issues.handoffs.correct', "
    "'issues.handoffs.list', 'issues.handoffs.record', 'issues.history', 'issues.list', "
    "'issues.memberships.add', 'issues.memberships.confirm', "
    "'issues.memberships.correct', 'issues.memberships.end', 'issues.project_links.add', "
    "'issues.project_links.confirm', 'issues.project_links.end', 'issues.read', "
    "'issues.reopen', 'issues.timeline', 'issues.update', "
    "'issues.work.create_commitment', 'issues.work.create_task', "
    "'knowledge.assertions.create', 'knowledge.assertions.history', "
    "'knowledge.assertions.list', 'knowledge.assertions.read', "
    "'knowledge.assertions.reveal', 'knowledge.assertions.search', "
    "'knowledge.assertions.submit', 'knowledge.coverage', "
    "'knowledge.discovery.checkpoint', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'meetings.create', 'meetings.list', "
    "'meetings.notes.read_version', 'meetings.notes.versions', 'meetings.provider.bind', "
    "'meetings.provider.reconcile', 'meetings.provider.review', 'meetings.read', "
    "'meetings.search', 'meetings.series.update', 'meetings.update', "
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
    "'records.lineage.related', 'relationship_memory.archive', "
    "'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', "
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
    "'schedule_activities.list', 'schedule_baselines.approve', "
    "'schedule_baselines.compare', 'schedule_baselines.governing', "
    "'schedule_baselines.list', 'schedule_baselines.propose', 'schedule_baselines.read', "
    "'schedule_baselines.reject', 'schedule_baselines.revoke', "
    "'schedule_baselines.set_governing', 'schedule_baselines.withdraw', "
    "'schedule_changes.list', 'schedule_cpm_runs.activities', 'schedule_cpm_runs.create', "
    "'schedule_cpm_runs.read', 'schedule_publications.import', "
    "'schedule_publications.list', 'schedule_publications.read', "
    "'schedule_scenario_outputs.list', 'schedule_scenario_outputs.read', "
    "'schedule_scenario_outputs.record', 'schedule_scenario_versions.activities', "
    "'schedule_scenario_versions.changes', 'schedule_scenario_versions.create', "
    "'schedule_scenario_versions.read', 'schedule_scenario_versions.relationships', "
    "'schedule_scenarios.create', 'schedule_scenarios.list', 'schedule_scenarios.read', "
    "'schedule_series.current', 'schedule_series.list', "
    "'schedule_series.match_decisions', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status', 'tasks.bulk_confirm', "
    "'tasks.bulk_preview', 'tasks.comments.create', 'tasks.comments.list', "
    "'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)

#: The same set plus exactly the three `communications.*` read names -- 315
#: names, sorted.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.archive', 'capture.create', 'capture.list', 'capture.read', 'capture.restore', "
    "'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', "
    "'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', "
    "'commitments.update', 'commitments.v2.list', 'commitments.v2.read', 'commitments.v2.search', "
    "'commitments.v2.waiting_on', 'commitments.waiting_on', 'communications.coverage', "
    "'communications.read', 'communications.search', 'constraint_categories.create', "
    "'constraint_categories.deactivate', 'constraint_categories.list', "
    "'constraint_categories.reorder', 'constraint_categories.update', "
    "'constraint_sync.acknowledge', 'constraint_sync.apply', 'constraint_sync.conflicts', "
    "'constraint_sync.delta', 'constraint_sync.preview', 'constraint_sync.resolve', "
    "'constraint_sync.state', 'constraints.close', 'constraints.close_follow_up', "
    "'constraints.create', 'constraints.create_published', 'constraints.history', "
    "'constraints.list', 'constraints.overview', 'constraints.portfolio_list', "
    "'constraints.portfolio_overview', 'constraints.portfolio_search', 'constraints.publish', "
    "'constraints.read', 'constraints.reopen', 'constraints.search', 'constraints.transition', "
    "'constraints.update', 'constraints.void', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.close', 'continuity.projects.create', "
    "'continuity.projects.read', 'continuity.projects.update', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', 'entities.addresses.list', "
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
    "'files.copy', 'files.download.begin', 'files.history', 'files.list', 'files.mkdir', "
    "'files.move', 'files.preview', 'files.rename', 'files.restore', 'files.search', 'files.stat', "
    "'files.trash', 'files.upload.abort', 'files.upload.begin', 'files.upload.finalize', "
    "'files.workspaces.list', 'files.write_text', 'goodnotes.complete', 'goodnotes.content', "
    "'goodnotes.correct', 'goodnotes.notebooks.list', 'goodnotes.pages.list', 'goodnotes.propose', "
    "'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', "
    "'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', 'issues.close', "
    "'issues.closure_readiness', 'issues.create', 'issues.handoffs.correct', "
    "'issues.handoffs.list', 'issues.handoffs.record', 'issues.history', 'issues.list', "
    "'issues.memberships.add', 'issues.memberships.confirm', 'issues.memberships.correct', "
    "'issues.memberships.end', 'issues.project_links.add', 'issues.project_links.confirm', "
    "'issues.project_links.end', 'issues.read', 'issues.reopen', 'issues.timeline', "
    "'issues.update', 'issues.work.create_commitment', 'issues.work.create_task', "
    "'knowledge.assertions.create', 'knowledge.assertions.history', 'knowledge.assertions.list', "
    "'knowledge.assertions.read', 'knowledge.assertions.reveal', 'knowledge.assertions.search', "
    "'knowledge.assertions.submit', 'knowledge.coverage', 'knowledge.discovery.checkpoint', "
    "'knowledge.read', 'knowledge.reveal', 'knowledge.search', 'meetings.create', 'meetings.list', "
    "'meetings.notes.read_version', 'meetings.notes.versions', 'meetings.provider.bind', "
    "'meetings.provider.reconcile', 'meetings.provider.review', 'meetings.read', "
    "'meetings.search', 'meetings.series.update', 'meetings.update', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'programs.members.resolve', 'programs.overview', "
    "'project_controls.configure', 'project_controls.status', 'record_events.list', "
    "'record_events.provenance', 'records.associations.assert', 'records.associations.confirm', "
    "'records.associations.contest', 'records.associations.correct', 'records.associations.end', "
    "'records.associations.history', 'records.associations.reinstate', 'records.backfill.plan', "
    "'records.backfill.report', 'records.lineage', 'records.lineage.related', "
    "'relationship_memory.archive', 'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', 'relationship_memory.propose', "
    "'relationship_memory.restore', 'relationship_memory.revise', 'relationship_memory.search', "
    "'reports.archive', 'reports.begin_cycle', 'reports.commit', 'reports.delete', "
    "'reports.history', 'reports.hold.place', 'reports.hold.release', 'reports.latest', "
    "'reports.list', 'reports.manifest', 'reports.publish', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.restore', "
    "'reports.retention.get', 'reports.retention.set', 'reports.search', 'reports.transfer.abort', "
    "'reports.transfer.append', 'reports.transfer.begin', 'reports.transfer.finalize', "
    "'reports.transfer.read_chunk', 'reports.types.create', 'reports.types.list', "
    "'reports.update', 'review.decide', 'review.list', 'schedule_activities.history', "
    "'schedule_activities.list', 'schedule_baselines.approve', 'schedule_baselines.compare', "
    "'schedule_baselines.governing', 'schedule_baselines.list', 'schedule_baselines.propose', "
    "'schedule_baselines.read', 'schedule_baselines.reject', 'schedule_baselines.revoke', "
    "'schedule_baselines.set_governing', 'schedule_baselines.withdraw', 'schedule_changes.list', "
    "'schedule_cpm_runs.activities', 'schedule_cpm_runs.create', 'schedule_cpm_runs.read', "
    "'schedule_publications.import', 'schedule_publications.list', 'schedule_publications.read', "
    "'schedule_scenario_outputs.list', 'schedule_scenario_outputs.read', "
    "'schedule_scenario_outputs.record', 'schedule_scenario_versions.activities', "
    "'schedule_scenario_versions.changes', 'schedule_scenario_versions.create', "
    "'schedule_scenario_versions.read', 'schedule_scenario_versions.relationships', "
    "'schedule_scenarios.create', 'schedule_scenarios.list', 'schedule_scenarios.read', "
    "'schedule_series.current', 'schedule_series.list', 'schedule_series.match_decisions', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.comments.create', 'tasks.comments.list', "
    "'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)

#: Byte copy of `640aaacc78e8`'s purpose AT set (70 purposes), the latest prior
#: restatement of `purpose_is_known`.
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', "
    "'canvas_workspace_read', 'capture_authoring', 'capture_review', 'commitment_authoring', "
    "'commitment_read', 'constraint_authoring', 'constraint_read', "
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
    "'schedule_baseline_approval', 'schedule_import', 'schedule_read', "
    "'security_validation', 'source_inspection', 'status_observation', 'task_authoring', "
    "'task_read')"
)

#: The same set plus exactly `communications_read` -- 71 purposes, sorted.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', 'canvas_workspace_read', "
    "'capture_authoring', 'capture_review', 'commitment_authoring', 'commitment_read', "
    "'communications_read', 'constraint_authoring', 'constraint_read', "
    "'constraint_sync_authoring', 'constraint_sync_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', 'document_authoring', "
    "'document_read', 'entity_authoring', 'entity_identity_correction', "
    "'entity_observation_ingest', 'entity_proposal', 'entity_read', 'file_workspace_authoring', "
    "'file_workspace_read', 'goodnotes_browse', 'goodnotes_content', 'goodnotes_correction', "
    "'goodnotes_proposal', 'goodnotes_pull', 'goodnotes_pull_observation', 'goodnotes_read', "
    "'goodnotes_work', 'gsqs_b0_execution', 'gsqs_b0_observation', 'issue_authoring', "
    "'issue_read', 'issue_work_authoring', 'knowledge_assertion_authoring', "
    "'knowledge_assertion_observation', 'knowledge_assertion_read', 'knowledge_read', "
    "'knowledge_search', 'lineage_backfill', 'meeting_authoring', 'meeting_note_history_read', "
    "'meeting_read', 'program_reporting_read', 'record_event_provenance_read', "
    "'record_event_read', 'record_lineage_authoring', 'record_lineage_read', "
    "'relationship_memory_authoring', 'relationship_memory_proposal', 'relationship_memory_read', "
    "'report_authoring', 'report_hold', 'report_lifecycle', 'report_read', 'report_retention', "
    "'review_disposition', 'schedule_analysis_authoring', 'schedule_analysis_read', "
    "'schedule_baseline_approval', 'schedule_import', 'schedule_read', 'security_validation', "
    "'source_inspection', 'status_observation', 'task_authoring', 'task_read')"
)

#: The names this revision admits to the audit vocabulary.
_NEW_CAPABILITIES: Final = (
    "communications.coverage",
    "communications.read",
    "communications.search",
)
_NEW_PURPOSES: Final = ("communications_read",)

# ---- downgrade -------------------------------------------------------------------

#: `downgrade` refuses while any row holds what `0d4e247d03cb` cannot hold or
#: would silently lose, rather than deleting evidence or audit history to make
#: the downgrade pass (the `61fafdfd2986` precedent). Each clause alone suffices.
_REFUSE_DOWNGRADE: Final = """
    DO $$
    BEGIN
      IF EXISTS (
           SELECT 1 FROM knowledge.communication_messages
            WHERE source_unavailable OR identifiers_version IS NOT NULL) THEN
        RAISE EXCEPTION 'messages record rederive state; refusing to downgrade fa18ef3d9bc0'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF EXISTS (
           SELECT 1 FROM knowledge.communication_identifiers WHERE kind IN ('cor', 'pco')) THEN
        RAISE EXCEPTION 'cor or pco identifiers exist; refusing to downgrade fa18ef3d9bc0'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF EXISTS (
           SELECT 1 FROM knowledge.audit_events
            WHERE capability IN ('communications.coverage', 'communications.read',
                                 'communications.search')
               OR purpose IN ('communications_read')) THEN
        RAISE EXCEPTION 'communications audit history exists; refusing to downgrade fa18ef3d9bc0'
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
    for column, ddl in _MESSAGE_COLUMNS:
        op.execute(f"ALTER TABLE {SCHEMA}.{_MESSAGES} ADD COLUMN {column} {ddl}")
    op.create_check_constraint(
        _IDENTIFIERS_VERSION_CHECK, _MESSAGES, _IDENTIFIERS_VERSION_EXPRESSION, schema=SCHEMA
    )
    op.execute(_message_guard(_MUTABLE_AT_THIS_REVISION))
    _restate(_IDENTIFIERS, _KIND_CHECK, _KINDS_AT_THIS_REVISION)
    _restate("audit_events", "capability_is_known", _CAPABILITIES_AT_THIS_REVISION)
    _restate("audit_events", "purpose_is_known", _PURPOSES_AT_THIS_REVISION)


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_LOCK_TABLES)
    op.execute(_REFUSE_DOWNGRADE)
    _restate("audit_events", "purpose_is_known", _PURPOSES_BEFORE_THIS_REVISION)
    _restate("audit_events", "capability_is_known", _CAPABILITIES_BEFORE_THIS_REVISION)
    _restate(_IDENTIFIERS, _KIND_CHECK, _KINDS_BEFORE_THIS_REVISION)
    op.execute(_message_guard(_MUTABLE_BEFORE_THIS_REVISION))
    op.drop_constraint(_IDENTIFIERS_VERSION_CHECK, _MESSAGES, schema=SCHEMA, type_="check")
    for column, _ddl in reversed(_MESSAGE_COLUMNS):
        op.execute(f"ALTER TABLE {SCHEMA}.{_MESSAGES} DROP COLUMN {column} RESTRICT")
