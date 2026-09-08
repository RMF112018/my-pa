"""Add the bounded, provider-neutral Constraint synchronization backend.

Revision ID: b8e4d6f20a11
Revises: f7a2c9d51e64
Create Date: 2026-09-08
"""
# ruff: noqa: E501, S608 -- interpolated identifiers are fixed repository schema names.

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8e4d6f20a11"
down_revision: str | None = "f7a2c9d51e64"
branch_labels: str | None = None
depends_on: str | None = None
SCHEMA: Final = "knowledge"
_RESOLUTION_IMMUTABILITY_FUNCTION: Final = "constraint_sync_resolution_history_stays_written"
_RESOLUTION_IMMUTABILITY_TRIGGER: Final = "constraint_sync_resolution_history_is_append_only"

# Frozen copies of f7a2c9d51e64's AT literals. Never derive migration vocabulary
# from live domain enums: downgrade must continue to describe its predecessor.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', 'capture.create', 'capture.list', 'capture.read', 'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', 'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', 'commitments.update', 'commitments.waiting_on', 'constraint_categories.create', 'constraint_categories.deactivate', 'constraint_categories.list', 'constraint_categories.reorder', 'constraint_categories.update', 'constraints.close', 'constraints.close_follow_up', 'constraints.create', 'constraints.history', 'constraints.list', 'constraints.overview', 'constraints.publish', 'constraints.read', 'constraints.reopen', 'constraints.search', 'constraints.transition', 'constraints.update', 'constraints.void', 'context.feedback', 'context.prepare', 'continuity.projects', 'continuity.projects.create', 'continuity.pulse', 'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', 'documents.archive', 'documents.create', 'documents.list', 'documents.read', 'documents.restore', 'documents.revise', 'entities.addresses.add', 'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', 'entities.affiliations.create', 'entities.affiliations.end', 'entities.affiliations.revise', 'entities.aliases.add', 'entities.aliases.list', 'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', 'entities.assignments.create', 'entities.assignments.end', 'entities.assignments.list', 'entities.assignments.revise', 'entities.communication.add', 'entities.communication.list', 'entities.communication.retire', 'entities.communication.revise', 'entities.context', 'entities.create', 'entities.get', 'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', 'entities.identifiers.retire', 'entities.identifiers.supersede', 'entities.identity_history', 'entities.merge', 'entities.merge.preview', 'entities.names.add', 'entities.names.list', 'entities.names.retire', 'entities.names.supersede', 'entities.observations.list', 'entities.observe', 'entities.participations.create', 'entities.participations.end', 'entities.participations.list', 'entities.participations.revise', 'entities.profile', 'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', 'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', 'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', 'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', 'entities.update', 'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', 'goodnotes.notebooks.list', 'goodnotes.pages.list', 'goodnotes.propose', 'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', 'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', 'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', 'native_sources.configure', 'native_sources.disable', 'native_sources.discover', 'native_sources.pause', 'native_sources.preflight', 'native_sources.reconcile', 'native_sources.resume', 'native_sources.retry', 'native_sources.status', 'native_sources.sync', 'relationship_memory.archive', 'relationship_memory.create', 'relationship_memory.get', 'relationship_memory.history', 'relationship_memory.list', 'relationship_memory.propose', 'relationship_memory.restore', 'relationship_memory.revise', 'relationship_memory.search', 'reports.begin_cycle', 'reports.commit', 'reports.latest', 'reports.list', 'reports.read', 'reports.record_run_state', 'reports.resolve_set', 'reports.search', 'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', 'tasks.transition', 'tasks.update')"
_PURPOSES_BEFORE_THIS_REVISION: Final = "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', 'canvas_workspace_read', 'capture_authoring', 'capture_review', 'commitment_authoring', 'commitment_read', 'constraint_authoring', 'constraint_read', 'content_extraction', 'context_preference', 'context_preparation', 'continuity_authoring', 'document_authoring', 'document_read', 'entity_authoring', 'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', 'entity_read', 'goodnotes_browse', 'goodnotes_content', 'goodnotes_correction', 'goodnotes_proposal', 'goodnotes_pull', 'goodnotes_pull_observation', 'goodnotes_read', 'goodnotes_work', 'gsqs_b0_execution', 'gsqs_b0_observation', 'knowledge_read', 'knowledge_search', 'relationship_memory_authoring', 'relationship_memory_proposal', 'relationship_memory_read', 'report_authoring', 'report_read', 'review_disposition', 'security_validation', 'source_inspection', 'status_observation', 'task_authoring', 'task_read')"
_CAPABILITIES_AT_THIS_REVISION: Final = "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', 'capture.create', 'capture.list', 'capture.read', 'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', 'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', 'commitments.update', 'commitments.waiting_on', 'constraint_categories.create', 'constraint_categories.deactivate', 'constraint_categories.list', 'constraint_categories.reorder', 'constraint_categories.update', 'constraint_sync.acknowledge', 'constraint_sync.apply', 'constraint_sync.conflicts', 'constraint_sync.delta', 'constraint_sync.preview', 'constraint_sync.resolve', 'constraint_sync.state', 'constraints.close', 'constraints.close_follow_up', 'constraints.create', 'constraints.history', 'constraints.list', 'constraints.overview', 'constraints.publish', 'constraints.read', 'constraints.reopen', 'constraints.search', 'constraints.transition', 'constraints.update', 'constraints.void', 'context.feedback', 'context.prepare', 'continuity.projects', 'continuity.projects.create', 'continuity.pulse', 'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', 'documents.archive', 'documents.create', 'documents.list', 'documents.read', 'documents.restore', 'documents.revise', 'entities.addresses.add', 'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', 'entities.affiliations.create', 'entities.affiliations.end', 'entities.affiliations.revise', 'entities.aliases.add', 'entities.aliases.list', 'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', 'entities.assignments.create', 'entities.assignments.end', 'entities.assignments.list', 'entities.assignments.revise', 'entities.communication.add', 'entities.communication.list', 'entities.communication.retire', 'entities.communication.revise', 'entities.context', 'entities.create', 'entities.get', 'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', 'entities.identifiers.retire', 'entities.identifiers.supersede', 'entities.identity_history', 'entities.merge', 'entities.merge.preview', 'entities.names.add', 'entities.names.list', 'entities.names.retire', 'entities.names.supersede', 'entities.observations.list', 'entities.observe', 'entities.participations.create', 'entities.participations.end', 'entities.participations.list', 'entities.participations.revise', 'entities.profile', 'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', 'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', 'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', 'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', 'entities.update', 'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', 'goodnotes.notebooks.list', 'goodnotes.pages.list', 'goodnotes.propose', 'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', 'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', 'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', 'native_sources.configure', 'native_sources.disable', 'native_sources.discover', 'native_sources.pause', 'native_sources.preflight', 'native_sources.reconcile', 'native_sources.resume', 'native_sources.retry', 'native_sources.status', 'native_sources.sync', 'relationship_memory.archive', 'relationship_memory.create', 'relationship_memory.get', 'relationship_memory.history', 'relationship_memory.list', 'relationship_memory.propose', 'relationship_memory.restore', 'relationship_memory.revise', 'relationship_memory.search', 'reports.begin_cycle', 'reports.commit', 'reports.latest', 'reports.list', 'reports.read', 'reports.record_run_state', 'reports.resolve_set', 'reports.search', 'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', 'tasks.transition', 'tasks.update')"
_PURPOSES_AT_THIS_REVISION: Final = "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', 'canvas_workspace_read', 'capture_authoring', 'capture_review', 'commitment_authoring', 'commitment_read', 'constraint_authoring', 'constraint_read', 'constraint_sync_authoring', 'constraint_sync_read', 'content_extraction', 'context_preference', 'context_preparation', 'continuity_authoring', 'document_authoring', 'document_read', 'entity_authoring', 'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', 'entity_read', 'goodnotes_browse', 'goodnotes_content', 'goodnotes_correction', 'goodnotes_proposal', 'goodnotes_pull', 'goodnotes_pull_observation', 'goodnotes_read', 'goodnotes_work', 'gsqs_b0_execution', 'gsqs_b0_observation', 'knowledge_read', 'knowledge_search', 'relationship_memory_authoring', 'relationship_memory_proposal', 'relationship_memory_read', 'report_authoring', 'report_read', 'review_disposition', 'security_validation', 'source_inspection', 'status_observation', 'task_authoring', 'task_read')"

_SYNC_STATES: Final = (
    "never_synced",
    "in_sync",
    "db_export_pending",
    "external_import_pending",
    "conflict",
    "workbook_unavailable",
    "schema_unsupported",
    "partial",
    "verification_pending",
    "verification_failed",
)


def _restate_audit(capability: str, purpose: str) -> None:
    for name, expression in (("capability_is_known", capability), ("purpose_is_known", purpose)):
        op.drop_constraint(name, "audit_events", schema=SCHEMA, type_="check")
        op.create_check_constraint(name, "audit_events", expression, schema=SCHEMA)


def upgrade() -> None:
    op.add_column("constraint_sync_targets", sa.Column("last_run_id", sa.Text()), schema=SCHEMA)
    op.create_check_constraint(
        "a_sync_target_last_run_is_an_opaque_identifier",
        "constraint_sync_targets",
        "last_run_id IS NULL OR last_run_id ~ '^csyr_[A-Za-z0-9]{8,64}$'",
        schema=SCHEMA,
    )
    for column in (
        sa.Column("sync_state", sa.Text()),
        sa.Column("lease_token", sa.Text()),
        sa.Column("preview_lease_until", sa.DateTime(timezone=True)),
        sa.Column("failure_kind", sa.Text()),
        sa.Column("preview_idempotency_key", sa.Text()),
        sa.Column("preview_request_digest", sa.Text()),
        sa.Column("apply_idempotency_key", sa.Text()),
        sa.Column("apply_request_digest", sa.Text()),
        sa.Column("apply_canonical_digest", sa.Text()),
        sa.Column("apply_sync_state", sa.Text()),
        sa.Column("acknowledge_idempotency_key", sa.Text()),
        sa.Column("acknowledge_request_digest", sa.Text()),
    ):
        op.add_column("constraint_sync_runs", column, schema=SCHEMA)
    op.execute(
        """UPDATE knowledge.constraint_sync_runs
        SET sync_state = CASE state
            WHEN 'acknowledged' THEN 'in_sync'
            WHEN 'applied' THEN 'verification_pending'
            WHEN 'failed' THEN 'verification_failed'
            ELSE 'never_synced' END,
            lease_token = repeat('0', 64),
            preview_lease_until = started_at,
            preview_idempotency_key = 'legacy__' || sync_run_id,
            preview_request_digest = repeat('0', 64),
            apply_sync_state = CASE WHEN state = 'applied'
                THEN 'verification_pending' ELSE NULL END"""
    )
    for name in (
        "sync_state",
        "lease_token",
        "preview_lease_until",
        "preview_idempotency_key",
        "preview_request_digest",
    ):
        op.alter_column("constraint_sync_runs", name, nullable=False, schema=SCHEMA)
    op.create_check_constraint(
        "a_constraint_sync_state_is_known",
        "constraint_sync_runs",
        "sync_state IN (" + ", ".join(repr(value) for value in _SYNC_STATES) + ")",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "a_sync_run_lease_token_is_sha256",
        "constraint_sync_runs",
        "lease_token ~ '^[0-9a-f]{64}$'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "a_sync_run_failure_kind_is_known",
        "constraint_sync_runs",
        "failure_kind IS NULL OR failure_kind IN "
        "('workbook_unavailable', 'schema_unsupported', 'verification_failed')",
        schema=SCHEMA,
    )
    for stem in ("preview", "apply", "acknowledge"):
        op.create_check_constraint(
            f"a_sync_run_{stem}_idempotency_key_is_valid",
            "constraint_sync_runs",
            f"{stem}_idempotency_key IS NULL OR "
            f"{stem}_idempotency_key ~ '^[A-Za-z0-9_-]{{8,128}}$'",
            schema=SCHEMA,
        )
        op.create_check_constraint(
            f"a_sync_run_{stem}_request_digest_is_sha256",
            "constraint_sync_runs",
            f"{stem}_request_digest IS NULL OR {stem}_request_digest ~ '^[0-9a-f]{{64}}$'",
            schema=SCHEMA,
        )
    op.create_check_constraint(
        "a_sync_run_apply_binding_is_complete",
        "constraint_sync_runs",
        "(apply_idempotency_key IS NULL) = (apply_request_digest IS NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "a_sync_run_apply_canonical_digest_is_sha256",
        "constraint_sync_runs",
        "apply_canonical_digest IS NULL OR apply_canonical_digest ~ '^[0-9a-f]{64}$'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "a_sync_run_apply_sync_state_is_known",
        "constraint_sync_runs",
        "apply_sync_state IS NULL OR apply_sync_state IN ('partial', 'verification_pending')",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "a_sync_run_acknowledge_binding_is_complete",
        "constraint_sync_runs",
        "(acknowledge_idempotency_key IS NULL) = (acknowledge_request_digest IS NULL)",
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "constraint_sync_targets_scope_is_unique",
        "constraint_sync_targets",
        ["principal_id", "project_id", "sync_target_id"],
        schema=SCHEMA,
    )
    op.drop_constraint(
        "a_sync_run_belongs_to_a_target_of_its_principal",
        "constraint_sync_runs",
        schema=SCHEMA,
        type_="foreignkey",
    )
    # The target is authoritative for the Project scope of its historical runs.
    # The predecessor constrained principal+target but left the duplicated
    # project_id unconstrained, so repair that denormalized value before making
    # the full scope relationship enforceable.
    op.execute(
        f"""
        UPDATE {SCHEMA}.constraint_sync_runs AS run
        SET project_id = target.project_id
        FROM {SCHEMA}.constraint_sync_targets AS target
        WHERE target.principal_id = run.principal_id
          AND target.sync_target_id = run.sync_target_id
          AND run.project_id <> target.project_id
        """
    )
    op.create_foreign_key(
        "a_sync_run_belongs_to_a_target_of_its_principal",
        "constraint_sync_runs",
        "constraint_sync_targets",
        ["principal_id", "project_id", "sync_target_id"],
        ["principal_id", "project_id", "sync_target_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.create_unique_constraint(
        "constraint_sync_runs_scope_is_unique",
        "constraint_sync_runs",
        ["principal_id", "project_id", "sync_target_id", "sync_run_id"],
        schema=SCHEMA,
    )
    op.create_table(
        "constraint_sync_legacy_unbound_conflicts",
        sa.Column("sync_conflict_id", sa.Text(), primary_key=True),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("sync_target_id", sa.Text(), nullable=False),
        sa.Column("constraint_id", sa.Text()),
        sa.Column("sync_run_id", sa.Text(), nullable=False),
        sa.Column("conflict_kind", sa.Text(), nullable=False),
        sa.Column("field_names", postgresql.JSONB, nullable=False),
        sa.Column("baseline_revision_id", sa.Text()),
        sa.Column("db_version", sa.Integer()),
        sa.Column("provider_version", sa.Text()),
        sa.Column("external_candidate", postgresql.JSONB),
        sa.Column("external_candidate_digest", sa.Text()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_history_id", sa.Text()),
        sa.Column(
            "legacy_scope_disposition",
            sa.Text(),
            nullable=False,
            server_default="legacy_unbound",
        ),
        sa.CheckConstraint(
            "legacy_scope_disposition = 'legacy_unbound'",
            name="legacy_sync_conflict_is_explicitly_unbound",
        ),
        schema=SCHEMA,
    )
    # Predecessor target pointers named only principal+run.  A pointer into a
    # sibling target is not authoritative history for this target, so clear it
    # rather than allowing it to block or mutate the sibling run.
    op.execute(
        f"""
        UPDATE {SCHEMA}.constraint_sync_targets AS target
        SET active_run_id = NULL, active_run_lease_until = NULL
        WHERE active_run_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {SCHEMA}.constraint_sync_runs AS run
              WHERE run.principal_id = target.principal_id
                AND run.project_id = target.project_id
                AND run.sync_target_id = target.sync_target_id
                AND run.sync_run_id = target.active_run_id
          )
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.constraint_sync_targets AS target
        SET last_verified_sync_run_id = NULL
        WHERE last_verified_sync_run_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {SCHEMA}.constraint_sync_runs AS run
              WHERE run.principal_id = target.principal_id
                AND run.project_id = target.project_id
                AND run.sync_target_id = target.sync_target_id
                AND run.sync_run_id = target.last_verified_sync_run_id
          )
        """
    )
    for name in (
        "a_sync_target_names_an_active_run_of_its_principal",
        "a_sync_target_names_a_verified_run_of_its_principal",
    ):
        op.drop_constraint(name, "constraint_sync_targets", schema=SCHEMA, type_="foreignkey")
    for name, pointer_column in (
        ("a_sync_target_names_an_active_run_of_its_principal", "active_run_id"),
        (
            "a_sync_target_names_a_verified_run_of_its_principal",
            "last_verified_sync_run_id",
        ),
        ("a_sync_target_names_its_last_run_of_its_principal", "last_run_id"),
    ):
        op.create_foreign_key(
            name,
            "constraint_sync_targets",
            "constraint_sync_runs",
            ["principal_id", "project_id", "sync_target_id", pointer_column],
            ["principal_id", "project_id", "sync_target_id", "sync_run_id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            deferrable=True,
            initially="DEFERRED",
        )
    op.create_unique_constraint(
        "constraint_sync_runs_principal_preview_key_is_unique",
        "constraint_sync_runs",
        ["principal_id", "preview_idempotency_key"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.constraint_sync_targets AS target
        SET last_run_id = COALESCE(
            (
                SELECT active_run.sync_run_id
                FROM {SCHEMA}.constraint_sync_runs AS active_run
                WHERE active_run.principal_id = target.principal_id
                  AND active_run.project_id = target.project_id
                  AND active_run.sync_target_id = target.sync_target_id
                  AND active_run.sync_run_id = target.active_run_id
            ),
            (
                SELECT verified_run.sync_run_id
                FROM {SCHEMA}.constraint_sync_runs AS verified_run
                WHERE verified_run.principal_id = target.principal_id
                  AND verified_run.project_id = target.project_id
                  AND verified_run.sync_target_id = target.sync_target_id
                  AND verified_run.sync_run_id = target.last_verified_sync_run_id
            )
        )
        """
    )
    # A predecessor-valid conflict could name one target and an unrelated run.
    # Preserve that historical statement byte-for-byte in a table no runtime
    # repository reads, while making the disposition explicit and preventing it
    # from acting as cross-target authority under the strengthened model.  It is
    # deliberately moved before resolution-history backfill: a resolved legacy
    # row keeps its original chst_ receipt and must not gain a synthetic csyrh_
    # outcome merely because the schema was upgraded.
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.constraint_sync_legacy_unbound_conflicts (
            sync_conflict_id, principal_id, project_id, sync_target_id,
            constraint_id, sync_run_id, conflict_kind, field_names,
            baseline_revision_id, db_version, provider_version,
            external_candidate, external_candidate_digest, state, created_at,
            resolved_at, resolution_history_id, legacy_scope_disposition
        )
        SELECT conflict.sync_conflict_id, conflict.principal_id,
            conflict.project_id, conflict.sync_target_id, conflict.constraint_id,
            conflict.sync_run_id, conflict.conflict_kind, conflict.field_names,
            conflict.baseline_revision_id, conflict.db_version,
            conflict.provider_version, conflict.external_candidate,
            conflict.external_candidate_digest, conflict.state,
            conflict.created_at, conflict.resolved_at,
            conflict.resolution_history_id, 'legacy_unbound'
        FROM {SCHEMA}.constraint_sync_conflicts AS conflict
        WHERE NOT EXISTS (
            SELECT 1 FROM {SCHEMA}.constraint_sync_runs AS run
            WHERE run.principal_id = conflict.principal_id
              AND run.project_id = conflict.project_id
              AND run.sync_target_id = conflict.sync_target_id
              AND run.sync_run_id = conflict.sync_run_id
        )
        """
    )
    op.execute(
        f"""
        DELETE FROM {SCHEMA}.constraint_sync_conflicts AS conflict
        USING {SCHEMA}.constraint_sync_legacy_unbound_conflicts AS legacy
        WHERE legacy.sync_conflict_id = conflict.sync_conflict_id
        """
    )
    op.drop_constraint(
        "a_sync_conflict_names_a_run_of_its_principal",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "a_sync_conflict_names_a_run_of_its_principal",
        "constraint_sync_conflicts",
        "constraint_sync_runs",
        ["principal_id", "project_id", "sync_target_id", "sync_run_id"],
        ["principal_id", "project_id", "sync_target_id", "sync_run_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.drop_constraint(
        "a_constraint_sync_conflict_kind_is_known",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "a_constraint_sync_conflict_kind_is_known",
        "constraint_sync_conflicts",
        "conflict_kind IN ('both_changed', 'deleted_in_canonical', 'deleted_in_external', "
        "'identity', 'lifecycle', 'new_in_external')",
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "constraint_sync_conflicts_principal_conflict_is_unique",
        "constraint_sync_conflicts",
        ["principal_id", "sync_conflict_id"],
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "constraint_sync_conflicts_scope_is_unique",
        "constraint_sync_conflicts",
        ["principal_id", "project_id", "sync_conflict_id"],
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "constraint_sync_conflicts_run_scope_is_unique",
        "constraint_sync_conflicts",
        ["principal_id", "project_id", "sync_target_id", "sync_run_id", "sync_conflict_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "constraint_sync_run_items",
        sa.Column("sync_run_id", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("sync_target_id", sa.Text(), nullable=False),
        sa.Column("external_row_key", sa.Text(), nullable=False),
        sa.Column("constraint_id", sa.Text()),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("expected_constraint_version", sa.Integer()),
        sa.Column("baseline_revision_id", sa.Text()),
        sa.Column("external_candidate", postgresql.JSONB),
        sa.Column("external_candidate_digest", sa.Text()),
        sa.Column("field_names", postgresql.JSONB, nullable=False),
        sa.Column("response_summary", postgresql.JSONB, nullable=False),
        sa.Column("applied_constraint_version", sa.Integer()),
        sa.Column("applied_revision_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "sync_run_id", "external_row_key", name="one_sync_item_per_run_row"
        ),
        sa.CheckConstraint(
            "sync_run_id ~ '^csyr_[A-Za-z0-9]{8,64}$'",
            name="sync_run_id_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'",
            name="principal_id_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "project_id ~ '^prj_[A-Za-z0-9]{8,64}$'",
            name="project_id_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "sync_target_id ~ '^csyt_[A-Za-z0-9]{8,64}$'",
            name="sync_target_id_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "length(trim(external_row_key)) BETWEEN 1 AND 256 AND external_row_key !~ '\\s'",
            name="a_sync_item_row_identity_is_bounded",
        ),
        sa.CheckConstraint(
            "action IN ('conflict', 'export_canonical', 'import_external', 'merge', 'no_op')",
            name="a_sync_item_action_is_known",
        ),
        sa.CheckConstraint(
            "constraint_id IS NULL OR constraint_id ~ '^cst_[A-Za-z0-9]{8,64}$'",
            name="a_sync_item_constraint_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "expected_constraint_version IS NULL OR expected_constraint_version >= 1",
            name="a_sync_item_expected_version_is_positive",
        ),
        sa.CheckConstraint(
            "external_candidate IS NULL OR (jsonb_typeof(external_candidate) = 'object' AND pg_column_size(external_candidate) <= 8192)",
            name="a_sync_item_candidate_is_bounded",
        ),
        sa.CheckConstraint(
            "external_candidate_digest IS NULL OR external_candidate_digest ~ '^[0-9a-f]{64}$'",
            name="a_sync_item_candidate_digest_is_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(field_names) = 'array' AND jsonb_array_length(field_names) <= 11",
            name="a_sync_item_field_names_are_bounded",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(response_summary) = 'object' AND pg_column_size(response_summary) <= 8192",
            name="a_sync_item_response_summary_is_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id", "project_id", "sync_target_id", "sync_run_id"],
            [
                f"{SCHEMA}.constraint_sync_runs.principal_id",
                f"{SCHEMA}.constraint_sync_runs.project_id",
                f"{SCHEMA}.constraint_sync_runs.sync_target_id",
                f"{SCHEMA}.constraint_sync_runs.sync_run_id",
            ],
            name="a_sync_item_belongs_to_its_principals_run",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "constraint_sync_run_items_by_principal_target",
        "constraint_sync_run_items",
        ["principal_id", "sync_target_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "constraint_sync_resolution_history",
        sa.Column("resolution_history_id", sa.Text(), primary_key=True),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("sync_target_id", sa.Text(), nullable=False),
        sa.Column("sync_conflict_id", sa.Text(), nullable=False),
        sa.Column("sync_run_id", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("expected_constraint_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_digest", sa.Text(), nullable=False),
        sa.Column("constraint_history_id", sa.Text()),
        sa.Column("constraint_version", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "resolution_history_id ~ '^csyrh_[A-Za-z0-9]{8,64}$'",
            name="resolution_history_id_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'",
            name="principal_id_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "project_id ~ '^prj_[A-Za-z0-9]{8,64}$'",
            name="project_id_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "sync_target_id ~ '^csyt_[A-Za-z0-9]{8,64}$'",
            name="sync_target_id_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "sync_conflict_id ~ '^csyc_[A-Za-z0-9]{8,64}$'",
            name="sync_conflict_id_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "sync_run_id ~ '^csyr_[A-Za-z0-9]{8,64}$'",
            name="sync_run_id_is_an_opaque_identifier",
        ),
        sa.CheckConstraint(
            "resolution IN ('accept_external', 'keep_canonical', 'manual_patch', 'reopen', "
            "'legacy_migrated')",
            name="a_sync_resolution_is_known",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9_-]{8,128}$'",
            name="a_sync_resolution_idempotency_key_is_valid",
        ),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'", name="a_sync_resolution_request_digest_is_sha256"
        ),
        sa.CheckConstraint(
            "constraint_version IS NULL OR constraint_version >= 1",
            name="a_sync_resolution_constraint_version_is_positive",
        ),
        sa.UniqueConstraint(
            "principal_id", "idempotency_key", name="one_sync_resolution_per_principal_key"
        ),
        sa.UniqueConstraint(
            "principal_id",
            "resolution_history_id",
            name="constraint_sync_resolutions_principal_id_is_unique",
        ),
        sa.ForeignKeyConstraint(
            [
                "principal_id",
                "project_id",
                "sync_target_id",
                "sync_run_id",
                "sync_conflict_id",
            ],
            [
                f"{SCHEMA}.constraint_sync_conflicts.principal_id",
                f"{SCHEMA}.constraint_sync_conflicts.project_id",
                f"{SCHEMA}.constraint_sync_conflicts.sync_target_id",
                f"{SCHEMA}.constraint_sync_conflicts.sync_run_id",
                f"{SCHEMA}.constraint_sync_conflicts.sync_conflict_id",
            ],
            name="a_sync_resolution_names_its_principals_conflict",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id", "project_id", "sync_target_id", "sync_run_id"],
            [
                f"{SCHEMA}.constraint_sync_runs.principal_id",
                f"{SCHEMA}.constraint_sync_runs.project_id",
                f"{SCHEMA}.constraint_sync_runs.sync_target_id",
                f"{SCHEMA}.constraint_sync_runs.sync_run_id",
            ],
            name="a_sync_resolution_names_its_principals_run",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "constraint_sync_resolutions_by_principal_conflict",
        "constraint_sync_resolution_history",
        ["principal_id", "sync_conflict_id", "created_at"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.constraint_sync_resolution_history (
            resolution_history_id, principal_id, project_id, sync_target_id,
            sync_conflict_id, sync_run_id, resolution, expected_constraint_version,
            idempotency_key, request_digest, constraint_history_id,
            constraint_version, created_at
        )
        SELECT 'csyrh_' || md5(sync_conflict_id), principal_id, project_id,
            sync_target_id, sync_conflict_id, sync_run_id, 'legacy_migrated',
            COALESCE(db_version, 1),
            'migrated_' || md5(sync_conflict_id),
            md5(sync_conflict_id) || md5(sync_conflict_id), resolution_history_id,
            db_version, COALESCE(resolved_at, created_at)
        FROM {SCHEMA}.constraint_sync_conflicts
        WHERE state = 'resolved' AND resolution_history_id IS NOT NULL
        """
    )
    op.drop_constraint(
        "a_sync_conflict_names_a_receipt_of_its_principal",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "a_sync_conflict_resolution_is_an_opaque_identifier",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="check",
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.constraint_sync_conflicts
        SET resolution_history_id = 'csyrh_' || md5(sync_conflict_id)
        WHERE state = 'resolved' AND resolution_history_id IS NOT NULL
        """
    )
    op.create_check_constraint(
        "a_sync_conflict_resolution_is_an_opaque_identifier",
        "constraint_sync_conflicts",
        "resolution_history_id IS NULL OR resolution_history_id ~ '^csyrh_[A-Za-z0-9]{8,64}$'",
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "a_sync_conflict_names_a_resolution_of_its_principal",
        "constraint_sync_conflicts",
        "constraint_sync_resolution_history",
        ["principal_id", "resolution_history_id"],
        ["principal_id", "resolution_history_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        deferrable=True,
        initially="DEFERRED",
    )
    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_RESOLUTION_IMMUTABILITY_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION '%.% is append only; % is refused', "
        "TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )
    op.execute(
        f"CREATE TRIGGER {_RESOLUTION_IMMUTABILITY_TRIGGER} BEFORE UPDATE OR DELETE "
        f"ON {SCHEMA}.constraint_sync_resolution_history FOR EACH ROW "
        f"EXECUTE FUNCTION {SCHEMA}.{_RESOLUTION_IMMUTABILITY_FUNCTION}()"
    )
    _restate_audit(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)


def downgrade() -> None:
    _restate_audit(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
    op.drop_constraint(
        "a_sync_conflict_names_a_resolution_of_its_principal",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "a_sync_conflict_resolution_is_an_opaque_identifier",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="check",
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.constraint_sync_conflicts AS conflict
        SET resolution_history_id = resolution.constraint_history_id,
            state = CASE WHEN resolution.constraint_history_id IS NULL
                THEN 'superseded' ELSE conflict.state END,
            resolved_at = CASE WHEN resolution.constraint_history_id IS NULL
                THEN NULL ELSE conflict.resolved_at END
        FROM {SCHEMA}.constraint_sync_resolution_history AS resolution
        WHERE resolution.principal_id = conflict.principal_id
          AND resolution.resolution_history_id = conflict.resolution_history_id
        """
    )
    op.create_check_constraint(
        "a_sync_conflict_resolution_is_an_opaque_identifier",
        "constraint_sync_conflicts",
        "resolution_history_id IS NULL OR resolution_history_id ~ '^chst_[A-Za-z0-9]{8,64}$'",
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "a_sync_conflict_names_a_receipt_of_its_principal",
        "constraint_sync_conflicts",
        "project_constraint_history",
        ["principal_id", "resolution_history_id"],
        ["principal_id", "history_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.drop_index(
        "constraint_sync_resolutions_by_principal_conflict",
        table_name="constraint_sync_resolution_history",
        schema=SCHEMA,
    )
    op.execute(
        f"DROP TRIGGER {_RESOLUTION_IMMUTABILITY_TRIGGER} "
        f"ON {SCHEMA}.constraint_sync_resolution_history"
    )
    op.drop_table("constraint_sync_resolution_history", schema=SCHEMA)
    op.execute(f"DROP FUNCTION {SCHEMA}.{_RESOLUTION_IMMUTABILITY_FUNCTION}()")
    op.drop_constraint(
        "constraint_sync_conflicts_run_scope_is_unique",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "constraint_sync_conflicts_principal_conflict_is_unique",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "constraint_sync_conflicts_scope_is_unique",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_index(
        "constraint_sync_run_items_by_principal_target",
        table_name="constraint_sync_run_items",
        schema=SCHEMA,
    )
    op.drop_table("constraint_sync_run_items", schema=SCHEMA)
    op.execute(
        f"""
        UPDATE {SCHEMA}.constraint_sync_conflicts
        SET state = 'superseded', resolved_at = NULL, resolution_history_id = NULL
        WHERE conflict_kind IN ('identity', 'lifecycle') AND state = 'open'
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.constraint_sync_conflicts
        SET conflict_kind = 'both_changed'
        WHERE conflict_kind IN ('identity', 'lifecycle')
        """
    )
    op.drop_constraint(
        "a_constraint_sync_conflict_kind_is_known",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "a_constraint_sync_conflict_kind_is_known",
        "constraint_sync_conflicts",
        "conflict_kind IN ('both_changed', 'deleted_in_canonical', 'deleted_in_external', 'new_in_external')",
        schema=SCHEMA,
    )
    for name in (
        "a_sync_run_acknowledge_binding_is_complete",
        "a_sync_run_apply_binding_is_complete",
        "a_sync_run_apply_canonical_digest_is_sha256",
        "a_sync_run_apply_sync_state_is_known",
        "a_sync_run_acknowledge_request_digest_is_sha256",
        "a_sync_run_acknowledge_idempotency_key_is_valid",
        "a_sync_run_apply_request_digest_is_sha256",
        "a_sync_run_apply_idempotency_key_is_valid",
        "a_sync_run_preview_request_digest_is_sha256",
        "a_sync_run_preview_idempotency_key_is_valid",
        "a_sync_run_failure_kind_is_known",
        "a_sync_run_lease_token_is_sha256",
        "a_constraint_sync_state_is_known",
    ):
        op.drop_constraint(name, "constraint_sync_runs", schema=SCHEMA, type_="check")
    op.drop_constraint(
        "a_sync_conflict_names_a_run_of_its_principal",
        "constraint_sync_conflicts",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "a_sync_conflict_names_a_run_of_its_principal",
        "constraint_sync_conflicts",
        "constraint_sync_runs",
        ["principal_id", "sync_run_id"],
        ["principal_id", "sync_run_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.constraint_sync_conflicts (
            sync_conflict_id, principal_id, project_id, sync_target_id,
            constraint_id, sync_run_id, conflict_kind, field_names,
            baseline_revision_id, db_version, provider_version,
            external_candidate, external_candidate_digest, state, created_at,
            resolved_at, resolution_history_id
        )
        SELECT sync_conflict_id, principal_id, project_id, sync_target_id,
            constraint_id, sync_run_id, conflict_kind, field_names,
            baseline_revision_id, db_version, provider_version,
            external_candidate, external_candidate_digest, state, created_at,
            resolved_at, resolution_history_id
        FROM {SCHEMA}.constraint_sync_legacy_unbound_conflicts
        """
    )
    op.drop_table("constraint_sync_legacy_unbound_conflicts", schema=SCHEMA)
    op.drop_constraint(
        "constraint_sync_runs_principal_preview_key_is_unique",
        "constraint_sync_runs",
        schema=SCHEMA,
        type_="unique",
    )
    for name in (
        "a_sync_target_names_an_active_run_of_its_principal",
        "a_sync_target_names_a_verified_run_of_its_principal",
        "a_sync_target_names_its_last_run_of_its_principal",
    ):
        op.drop_constraint(name, "constraint_sync_targets", schema=SCHEMA, type_="foreignkey")
    for name, pointer_column in (
        ("a_sync_target_names_an_active_run_of_its_principal", "active_run_id"),
        (
            "a_sync_target_names_a_verified_run_of_its_principal",
            "last_verified_sync_run_id",
        ),
    ):
        op.create_foreign_key(
            name,
            "constraint_sync_targets",
            "constraint_sync_runs",
            ["principal_id", pointer_column],
            ["principal_id", "sync_run_id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            deferrable=True,
            initially="DEFERRED",
        )
    op.drop_constraint(
        "constraint_sync_runs_scope_is_unique",
        "constraint_sync_runs",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "a_sync_run_belongs_to_a_target_of_its_principal",
        "constraint_sync_runs",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "a_sync_run_belongs_to_a_target_of_its_principal",
        "constraint_sync_runs",
        "constraint_sync_targets",
        ["principal_id", "sync_target_id"],
        ["principal_id", "sync_target_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.drop_constraint(
        "constraint_sync_targets_scope_is_unique",
        "constraint_sync_targets",
        schema=SCHEMA,
        type_="unique",
    )
    for name in (
        "acknowledge_request_digest",
        "acknowledge_idempotency_key",
        "apply_request_digest",
        "apply_idempotency_key",
        "apply_canonical_digest",
        "apply_sync_state",
        "preview_request_digest",
        "preview_idempotency_key",
        "failure_kind",
        "lease_token",
        "preview_lease_until",
        "sync_state",
    ):
        op.drop_column("constraint_sync_runs", name, schema=SCHEMA)
    op.drop_constraint(
        "a_sync_target_last_run_is_an_opaque_identifier",
        "constraint_sync_targets",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_column("constraint_sync_targets", "last_run_id", schema=SCHEMA)
