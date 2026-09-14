"""Strengthen Run 01 Project ownership and admit settings history.

Revision ID: e6a4c2f91b73
Revises: c4f1a8e52d90
Create Date: 2026-09-14

R01-WP03 adds nullable Capture Project scope, makes the remaining Capture,
Task, settings, Category, and Constraint Project references same-Principal,
and creates the settings-specific append-only configuration history. Existing
rows are never repaired or backfilled: incompatible ownership refuses the
upgrade. The audit capability set widens by exactly six names while purposes
remain unchanged. Frozen BEFORE literals are byte copies of c4f1a8e52d90's AT
lists and are not derived from runtime enums.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "e6a4c2f91b73"
down_revision: str | None = "c4f1a8e52d90"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"
_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

#: Frozen byte-copy of c4f1a8e52d90's AT vocabulary (177 names).
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
    "'continuity.projects.close', 'continuity.projects.create', "
    "'continuity.projects.read', 'continuity.projects.update', 'continuity.pulse', "
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
#: Same set plus exactly the six Run 01 Project Controls names (183 names).
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
    "'constraints.close_follow_up', 'constraints.create', 'constraints.create_published', "
    "'constraints.history', 'constraints.list', 'constraints.overview', "
    "'constraints.portfolio_list', 'constraints.portfolio_overview', "
    "'constraints.portfolio_search', 'constraints.publish', 'constraints.read', "
    "'constraints.reopen', 'constraints.search', 'constraints.transition', 'constraints.update', "
    "'constraints.void', 'context.feedback', 'context.prepare', 'continuity.projects', "
    "'continuity.projects.close', 'continuity.projects.create', "
    "'continuity.projects.read', 'continuity.projects.update', 'continuity.pulse', "
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
    "'project_controls.configure', 'project_controls.status', "
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


def _refuse_cross_principal_project_references() -> None:
    tables = (
        "tasks",
        "constraint_project_settings",
        "constraint_categories",
        "project_constraints",
    )
    for table in tables:
        op.execute(
            f"""
            DO $$
            DECLARE offending_count integer;
            BEGIN
              SELECT count(*) INTO offending_count
              FROM {SCHEMA}.{table} AS owned
              LEFT JOIN {SCHEMA}.projects AS project
                ON project.project_id = owned.project_id
               AND project.principal_id = owned.principal_id
              WHERE owned.project_id IS NOT NULL AND project.project_id IS NULL;
              IF offending_count > 0 THEN
                RAISE EXCEPTION
                  'R01-WP03 refused: % {table} row(s) name a Project outside their Principal',
                  offending_count;
              END IF;
            END $$
            """  # noqa: S608
        )


def _strengthen_project_references() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.captures ADD COLUMN project_id text")
    op.execute(
        f"ALTER TABLE {SCHEMA}.captures ADD CONSTRAINT "
        "a_capture_project_is_an_opaque_identifier CHECK "
        f"(project_id IS NULL OR project_id ~ '^prj_{_IDENTIFIER_SUFFIX}$')"
    )
    op.create_foreign_key(
        "a_capture_names_a_project_in_its_principal",
        "captures",
        "projects",
        ["project_id", "owner_principal_id"],
        ["project_id", "principal_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.create_index(
        "captures_by_principal_project_created_at",
        "captures",
        ["owner_principal_id", "project_id", "created_at"],
        schema=SCHEMA,
    )

    replacements = (
        (
            "tasks",
            "tasks_project_id_fkey",
            "a_task_names_a_project_in_its_principal",
        ),
        (
            "constraint_project_settings",
            "constraint_project_settings_project_id_fkey",
            "constraint_settings_project_is_same_principal",
        ),
        (
            "constraint_categories",
            "constraint_categories_project_id_fkey",
            "constraint_categories_project_is_same_principal",
        ),
        (
            "project_constraints",
            "project_constraints_project_id_fkey",
            "project_constraints_project_is_same_principal",
        ),
    )
    for table, old_name, new_name in replacements:
        op.drop_constraint(old_name, table, schema=SCHEMA, type_="foreignkey")
        op.create_foreign_key(
            new_name,
            table,
            "projects",
            ["project_id", "principal_id"],
            ["project_id", "principal_id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
        )


def _create_settings_history() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.constraint_project_settings_history (
          history_id text PRIMARY KEY
            CONSTRAINT a_constraint_settings_history_id_is_an_opaque_identifier
            CHECK (history_id ~ '^cpsh_{_IDENTIFIER_SUFFIX}$'),
          principal_id text NOT NULL
            CONSTRAINT a_constraint_settings_history_principal_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          project_id text NOT NULL
            CONSTRAINT a_constraint_settings_history_project_is_an_opaque_identifier
            CHECK (project_id ~ '^prj_{_IDENTIFIER_SUFFIX}$'),
          action text NOT NULL
            CONSTRAINT a_constraint_settings_history_action_is_known
            CHECK (action = 'configure'),
          actor text NOT NULL
            CONSTRAINT a_constraint_settings_history_actor_is_known
            CHECK (actor IN ('assistant', 'principal', 'system')),
          outcome text NOT NULL
            CONSTRAINT a_constraint_settings_history_outcome_is_known
            CHECK (outcome IN ('applied', 'no_op', 'rejected')),
          before_settings_version integer
            CONSTRAINT a_constraint_settings_history_before_version_is_positive
            CHECK (before_settings_version IS NULL OR before_settings_version >= 1),
          after_settings_version integer
            CONSTRAINT a_constraint_settings_history_after_version_is_positive
            CHECK (after_settings_version IS NULL OR after_settings_version >= 1),
          resulting_timezone_name text
            CONSTRAINT a_constraint_settings_history_timezone_is_bounded
            CHECK (resulting_timezone_name IS NULL OR
              (length(trim(resulting_timezone_name)) BETWEEN 1 AND 64 AND
               resulting_timezone_name !~ '\\s')),
          resulting_settings_updated_at timestamptz,
          idempotency_key text NOT NULL
            CONSTRAINT a_constraint_settings_history_idempotency_key_is_bounded
            CHECK (idempotency_key ~ '^[A-Za-z0-9_-]{{8,128}}$'),
          request_digest text NOT NULL
            CONSTRAINT a_constraint_settings_history_request_digest_is_sha256
            CHECK (request_digest ~ '^[0-9a-f]{{64}}$'),
          client_context text
            CONSTRAINT a_constraint_settings_history_client_context_is_bounded
            CHECK (client_context IS NULL OR length(trim(client_context)) BETWEEN 1 AND 128),
          correlation_id text
            CONSTRAINT a_constraint_settings_history_correlation_is_an_opaque_identifier
            CHECK (correlation_id IS NULL OR correlation_id ~ '^corr_{_IDENTIFIER_SUFFIX}$'),
          failure_code text
            CONSTRAINT a_constraint_settings_history_failure_code_is_bounded
            CHECK (failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{{0,63}}$'),
          failure_detail text
            CONSTRAINT a_constraint_settings_history_failure_detail_is_bounded
            CHECK (failure_detail IS NULL OR length(trim(failure_detail)) BETWEEN 1 AND 256),
          occurred_at timestamptz NOT NULL,
          recorded_at timestamptz NOT NULL,
          CONSTRAINT an_applied_constraint_settings_change_advances_its_version
            CHECK (outcome <> 'applied' OR
              (after_settings_version IS NOT NULL AND
               after_settings_version = coalesce(before_settings_version, 0) + 1)),
          CONSTRAINT a_no_op_constraint_settings_change_preserves_its_version
            CHECK (outcome <> 'no_op' OR
              (before_settings_version IS NOT NULL AND
               after_settings_version IS NOT NULL AND
               after_settings_version = before_settings_version)),
          CONSTRAINT a_rejected_constraint_settings_change_writes_no_new_version
            CHECK (outcome <> 'rejected' OR
              after_settings_version IS NOT DISTINCT FROM before_settings_version),
          CONSTRAINT a_successful_constraint_settings_change_records_its_snapshot
            CHECK (
              (outcome IN ('applied', 'no_op')) = (resulting_timezone_name IS NOT NULL) AND
              (outcome IN ('applied', 'no_op')) =
                (resulting_settings_updated_at IS NOT NULL)),
          CONSTRAINT only_a_rejected_constraint_settings_change_records_failure
            CHECK ((outcome = 'rejected') = (failure_code IS NOT NULL)),
          CONSTRAINT failure_detail_belongs_only_to_a_rejected_settings_change
            CHECK (failure_detail IS NULL OR outcome = 'rejected'),
          CONSTRAINT settings_history_is_recorded_after_it_occurs
            CHECK (recorded_at >= occurred_at),
          CONSTRAINT constraint_settings_history_idempotency_is_unique_per_principal
            UNIQUE (principal_id, idempotency_key),
          CONSTRAINT a_constraint_settings_history_names_a_project_in_its_principal
            FOREIGN KEY (project_id, principal_id)
            REFERENCES {SCHEMA}.projects (project_id, principal_id)
        )
        """
    )
    op.execute(
        f"CREATE TRIGGER constraint_project_settings_history_are_immutable "
        f"BEFORE UPDATE OR DELETE ON {SCHEMA}.constraint_project_settings_history "
        "FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written()"
    )


def upgrade() -> None:
    _refuse_cross_principal_project_references()
    _strengthen_project_references()
    _restate_audit(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)
    _create_settings_history()


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.constraint_project_settings_history RESTRICT")
    _restate_audit(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
    replacements = (
        (
            "project_constraints",
            "project_constraints_project_is_same_principal",
            "project_constraints_project_id_fkey",
        ),
        (
            "constraint_categories",
            "constraint_categories_project_is_same_principal",
            "constraint_categories_project_id_fkey",
        ),
        (
            "constraint_project_settings",
            "constraint_settings_project_is_same_principal",
            "constraint_project_settings_project_id_fkey",
        ),
        ("tasks", "a_task_names_a_project_in_its_principal", "tasks_project_id_fkey"),
    )
    for table, composite_name, single_name in replacements:
        op.drop_constraint(composite_name, table, schema=SCHEMA, type_="foreignkey")
        op.create_foreign_key(
            single_name,
            table,
            "projects",
            ["project_id"],
            ["project_id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
        )
    op.drop_index("captures_by_principal_project_created_at", table_name="captures", schema=SCHEMA)
    op.drop_constraint(
        "a_capture_names_a_project_in_its_principal",
        "captures",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "a_capture_project_is_an_opaque_identifier", "captures", schema=SCHEMA, type_="check"
    )
    op.drop_column("captures", "project_id", schema=SCHEMA)
