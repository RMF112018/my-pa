"""Complete RI split recovery, origin bindings, and re-enrichment work.

Revision ID: 8e1c4a7b2d90
Revises: 3d07af4dc513
"""

# ruff: noqa: S608 -- every interpolated identifier is the fixed repository schema.

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Final

from alembic import context, op
from sqlalchemy import text

revision: str = "8e1c4a7b2d90"
down_revision: str | None = "3d07af4dc513"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "knowledge"

# Frozen here rather than imported from the live enum: a historical migration
# must keep the vocabulary it admitted. The prior value is the exact
# `b64e29a0f7c1` capability constraint; this revision adds only identity history
# and the two halves of governed split.
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
    "'entities.identity_history', 'entities.merge', 'entities.merge.preview', "
    "'entities.observations.list', 'entities.observe', "
    "'entities.proposals.create', 'entities.relationships', "
    "'entities.relationships.create', 'entities.relationships.end', "
    "'entities.relationships.revise', 'entities.resolve', 'entities.restore', "
    "'entities.search', 'entities.split', 'entities.split.preview', "
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
    "'relationship_memory.list', 'relationship_memory.propose', "
    "'relationship_memory.restore', 'relationship_memory.revise', "
    "'relationship_memory.search', 'reports.begin_cycle', 'reports.commit', "
    "'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
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
    "'entities.merge', 'entities.merge.preview', 'entities.observations.list', "
    "'entities.observe', 'entities.proposals.create', 'entities.relationships', "
    "'entities.relationships.create', 'entities.relationships.end', "
    "'entities.relationships.revise', 'entities.resolve', 'entities.restore', "
    "'entities.search', 'entities.unresolved_mentions', "
    "'entities.unresolved_mentions.resolve', 'entities.update', "
    "'goodnotes.content', 'goodnotes.propose', 'goodnotes.work', "
    "'gsqs.start', 'gsqs.status', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', "
    "'relationship_memory.archive', 'relationship_memory.create', "
    "'relationship_memory.get', 'relationship_memory.history', "
    "'relationship_memory.list', 'relationship_memory.propose', "
    "'relationship_memory.restore', 'relationship_memory.revise', "
    "'relationship_memory.search', 'reports.begin_cycle', 'reports.commit', "
    "'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)


def _restate_capabilities(expression: str) -> None:
    op.execute(f'ALTER TABLE {SCHEMA}.audit_events DROP CONSTRAINT "capability_is_known"')
    op.execute(
        f'ALTER TABLE {SCHEMA}.audit_events ADD CONSTRAINT "capability_is_known" '
        f"CHECK ({expression})"
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    return hashlib.sha256(encoded).hexdigest()


def _settle_completed_merges() -> None:
    bind = op.get_bind()
    operations = bind.execute(
        text(
            f"SELECT identity_operation_id FROM {SCHEMA}.entity_identity_operations "
            "WHERE operation_type = 'merge' AND state = 'completed' "
            "AND effect_count IS NULL ORDER BY identity_operation_id"
        )
    ).scalars()
    for operation_id in operations:
        rows = (
            bind.execute(
                text(
                    f"SELECT sequence, record_family, record_id, effect_kind, before_state, "
                    f"after_state, before_sha256, after_sha256 "
                    f"FROM {SCHEMA}.entity_identity_effects "
                    "WHERE identity_operation_id = :operation_id ORDER BY sequence"
                ),
                {"operation_id": operation_id},
            )
            .mappings()
            .all()
        )
        if not rows or [int(row["sequence"]) for row in rows] != list(range(1, len(rows) + 1)):
            raise RuntimeError("a completed merge must have one contiguous effect ledger")
        value: list[Mapping[str, object]] = [
            {
                "sequence": int(row["sequence"]),
                "family": str(row["record_family"]),
                "record_id": str(row["record_id"]),
                "kind": str(row["effect_kind"]),
                "before_state": row["before_state"],
                "after_state": row["after_state"],
                "before_sha256": str(row["before_sha256"]),
                "after_sha256": str(row["after_sha256"]),
            }
            for row in rows
        ]
        bind.execute(
            text(
                f"UPDATE {SCHEMA}.entity_identity_operations "
                "SET effect_count = :count, effects_digest = :digest "
                "WHERE identity_operation_id = :operation_id"
            ),
            {"count": len(rows), "digest": _digest(value), "operation_id": operation_id},
        )


def upgrade() -> None:
    _restate_capabilities(_CAPABILITIES_AT_THIS_REVISION)
    op.execute(
        f"""  # noqa: S608 -- fixed repository schema constant
        ALTER TABLE {SCHEMA}.relationship_memories
          ADD COLUMN origin_subject_entity_id text;
        UPDATE {SCHEMA}.relationship_memories
           SET origin_subject_entity_id = subject_entity_id;
        ALTER TABLE {SCHEMA}.relationship_memories
          ALTER COLUMN origin_subject_entity_id SET NOT NULL,
          ADD CONSTRAINT origin_subject_entity_id_is_an_opaque_identifier
            CHECK (origin_subject_entity_id ~ '^ent_[A-Za-z0-9]{{8,64}}$');

        ALTER TABLE {SCHEMA}.relationship_memory_proposals
          ADD COLUMN origin_subject_entity_id text;
        UPDATE {SCHEMA}.relationship_memory_proposals
           SET origin_subject_entity_id = subject_entity_id;
        ALTER TABLE {SCHEMA}.relationship_memory_proposals
          ALTER COLUMN origin_subject_entity_id SET NOT NULL,
          ADD CONSTRAINT proposal_origin_subject_is_an_opaque_identifier
            CHECK (origin_subject_entity_id ~ '^ent_[A-Za-z0-9]{{8,64}}$');

        ALTER TABLE {SCHEMA}.relationship_memory_context_links
          ADD COLUMN origin_subject_entity_id text;
        UPDATE {SCHEMA}.relationship_memory_context_links
           SET origin_subject_entity_id = target_id WHERE target_type = 'entity';
        ALTER TABLE {SCHEMA}.relationship_memory_context_links
          ADD CONSTRAINT an_entity_memory_context_link_retains_its_origin_subject
            CHECK ((target_type = 'entity') = (origin_subject_entity_id IS NOT NULL));

        ALTER TABLE {SCHEMA}.entity_identity_previews
          ADD COLUMN source_identity_operation_id text,
          DROP CONSTRAINT a_preview_operation_type_is_known,
          ADD CONSTRAINT a_preview_operation_type_is_known
            CHECK (operation_type IN ('merge','split')),
          ADD CONSTRAINT a_split_preview_names_exactly_one_source_operation
            CHECK ((operation_type = 'split') =
                   (source_identity_operation_id IS NOT NULL));

        ALTER TABLE {SCHEMA}.entity_identity_operations
          ADD COLUMN source_identity_operation_id text,
          ADD COLUMN effect_count integer,
          ADD COLUMN effects_digest text,
          DROP CONSTRAINT an_identity_operation_type_is_known,
          ADD CONSTRAINT an_identity_operation_type_is_known
            CHECK (operation_type IN ('merge','split')),
          ADD CONSTRAINT a_split_operation_names_exactly_one_source_merge
            CHECK ((operation_type = 'split') =
                   (source_identity_operation_id IS NOT NULL)),
          ADD CONSTRAINT an_identity_operation_settles_count_and_digest_together
            CHECK ((effect_count IS NULL) = (effects_digest IS NULL)),
          ADD CONSTRAINT an_identity_operation_settles_at_least_one_effect
            CHECK (effect_count IS NULL OR effect_count >= 1),
          ADD CONSTRAINT an_identity_operation_effect_digest_is_sha256
            CHECK (effects_digest IS NULL OR effects_digest ~ '^[0-9a-f]{{64}}$'),
          ADD CONSTRAINT a_split_names_a_source_operation_of_its_principal
            FOREIGN KEY (source_identity_operation_id, principal_id)
            REFERENCES {SCHEMA}.entity_identity_operations
              (identity_operation_id, principal_id)
            DEFERRABLE INITIALLY DEFERRED;

        ALTER TABLE {SCHEMA}.entity_identity_effects
          DROP CONSTRAINT an_identity_effect_family_is_known,
          ADD CONSTRAINT an_identity_effect_family_is_known CHECK (
            record_family IN ('entity','alias','identifier','assignment','relationship',
              'observation','proposal','review_case','relationship_memory',
              'memory_proposal','memory_context_link','derived_context')
          );
        """
    )
    if context.is_offline_mode():
        # Historical settlement uses the application's canonical-JSON digest,
        # not PostgreSQL's JSONB text representation. An offline script cannot
        # read those ledgers to compute it faithfully, so applying one must fail
        # closed. Normal online Alembic execution performs the bounded backfill.
        op.execute(
            "DO $$ BEGIN RAISE EXCEPTION "
            "'8e1c4a7b2d90 requires online Alembic execution for identity-effect settlement'; "
            "END $$"
        )
    else:
        _settle_completed_merges()
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_identity_operations
          ADD CONSTRAINT a_completed_identity_operation_has_settled_effects CHECK (
            state <> 'completed' OR
            (effect_count IS NOT NULL AND effects_digest IS NOT NULL)
          );
        CREATE UNIQUE INDEX one_completed_split_per_source_merge
          ON {SCHEMA}.entity_identity_operations
            (principal_id, source_identity_operation_id)
          WHERE operation_type = 'split' AND state = 'completed';

        CREATE FUNCTION {SCHEMA}.relationship_memory_origin_is_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.origin_subject_entity_id IS DISTINCT FROM OLD.origin_subject_entity_id THEN
            RAISE EXCEPTION 'relationship memory origin subject is immutable';
          END IF;
          RETURN NEW;
        END;
        $$;
        CREATE TRIGGER relationship_memory_origin_stays_fixed
          BEFORE UPDATE ON {SCHEMA}.relationship_memories
          FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.relationship_memory_origin_is_immutable();
        CREATE TRIGGER relationship_memory_proposal_origin_stays_fixed
          BEFORE UPDATE ON {SCHEMA}.relationship_memory_proposals
          FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.relationship_memory_origin_is_immutable();
        CREATE TRIGGER relationship_memory_context_origin_stays_fixed
          BEFORE UPDATE ON {SCHEMA}.relationship_memory_context_links
          FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.relationship_memory_origin_is_immutable();

        CREATE TABLE {SCHEMA}.entity_reenrichment_work (
          work_id text PRIMARY KEY CHECK (work_id ~ '^erwk_[0-9a-f]{{24}}$'),
          principal_id text NOT NULL CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          trigger text NOT NULL CHECK (trigger IN
            ('corrected_identity','new_alias','project_mapping_change',
             'role_or_organization_change','source_version_change',
             'model_or_rule_version_change',
             'accepted_quick_capture_correction','contradiction_resolution','policy_change')),
          cause_record_id text NOT NULL,
          binding_sha256 text NOT NULL CHECK (binding_sha256 ~ '^[0-9a-f]{{64}}$'),
          input_versions jsonb NOT NULL CHECK
            (jsonb_typeof(input_versions) = 'array'
             AND jsonb_array_length(input_versions) BETWEEN 0 AND 100),
          producer_versions jsonb NOT NULL CHECK
            (jsonb_typeof(producer_versions) = 'array'
             AND jsonb_array_length(producer_versions) BETWEEN 0 AND 100),
          policy_version text NOT NULL,
          state text NOT NULL CHECK (state IN ('queued','running','succeeded','stale','failed')),
          attempt_count integer NOT NULL DEFAULT 0,
          max_attempts integer NOT NULL DEFAULT 3,
          lease_owner text,
          lease_expires_at timestamptz,
          next_attempt_at timestamptz NOT NULL,
          stale_reasons text[],
          last_error_code text,
          created_at timestamptz NOT NULL,
          updated_at timestamptz NOT NULL,
          completed_at timestamptz,
          CONSTRAINT one_entity_reenrichment_binding UNIQUE (principal_id,binding_sha256),
          CONSTRAINT reenrichment_work_is_identified_within_principal
            UNIQUE (work_id,principal_id),
          CONSTRAINT reenrichment_attempts_are_bounded CHECK
            (attempt_count BETWEEN 0 AND max_attempts AND max_attempts BETWEEN 1 AND 10),
          CONSTRAINT running_reenrichment_has_a_complete_lease CHECK
            ((state = 'running') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
          CONSTRAINT terminal_reenrichment_records_completion CHECK
            ((state IN ('succeeded','stale','failed')) = (completed_at IS NOT NULL)),
          CONSTRAINT stale_reenrichment_states_why CHECK
            ((state = 'stale') = (coalesce(cardinality(stale_reasons),0) > 0))
        );
        CREATE INDEX entity_reenrichment_ready ON {SCHEMA}.entity_reenrichment_work
          (state,next_attempt_at,created_at);
        CREATE TABLE {SCHEMA}.entity_reenrichment_subjects (
          work_id text NOT NULL,
          principal_id text NOT NULL,
          sequence integer NOT NULL CHECK (sequence BETWEEN 1 AND 100),
          subject_kind text NOT NULL CHECK (subject_kind IN
            ('principal','entity','alias','assignment','relationship','source_object',
             'source_version','capture','capture_version','proposal','review_decision',
             'identity_operation')),
          subject_id text NOT NULL,
          subject_version text NOT NULL,
          CONSTRAINT one_reenrichment_subject_position PRIMARY KEY (work_id,sequence),
          CONSTRAINT a_reenrichment_subject_belongs_to_its_principal_work
            FOREIGN KEY (work_id,principal_id)
            REFERENCES {SCHEMA}.entity_reenrichment_work (work_id,principal_id)
            ON DELETE CASCADE
        );
        CREATE TABLE {SCHEMA}.entity_reenrichment_version_watermarks (
          principal_id text NOT NULL CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          namespace text NOT NULL,
          binding_key text NOT NULL,
          version text NOT NULL,
          updated_at timestamptz NOT NULL,
          CONSTRAINT one_reenrichment_version_watermark
            PRIMARY KEY (principal_id,namespace,binding_key),
          CONSTRAINT reenrichment_watermark_names_are_safe_tokens CHECK
            (namespace ~ '^[a-z][a-z0-9_]{{0,63}}$' AND
             binding_key ~ '^[a-z][a-z0-9_]{{0,63}}$')
        );
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DROP TABLE {SCHEMA}.entity_reenrichment_version_watermarks;
        DROP TABLE {SCHEMA}.entity_reenrichment_subjects;
        DROP TABLE {SCHEMA}.entity_reenrichment_work;
        DROP TRIGGER relationship_memory_context_origin_stays_fixed
          ON {SCHEMA}.relationship_memory_context_links;
        DROP TRIGGER relationship_memory_proposal_origin_stays_fixed
          ON {SCHEMA}.relationship_memory_proposals;
        DROP TRIGGER relationship_memory_origin_stays_fixed
          ON {SCHEMA}.relationship_memories;
        DROP FUNCTION {SCHEMA}.relationship_memory_origin_is_immutable();
        DROP INDEX {SCHEMA}.one_completed_split_per_source_merge;
        ALTER TABLE {SCHEMA}.entity_identity_effects
          DROP CONSTRAINT an_identity_effect_family_is_known,
          ADD CONSTRAINT an_identity_effect_family_is_known CHECK (
            record_family IN ('entity','alias','identifier','assignment','relationship',
              'observation','proposal','review_case','derived_context')
          );
        ALTER TABLE {SCHEMA}.entity_identity_operations
          DROP CONSTRAINT a_completed_identity_operation_has_settled_effects,
          DROP CONSTRAINT a_split_names_a_source_operation_of_its_principal,
          DROP CONSTRAINT an_identity_operation_effect_digest_is_sha256,
          DROP CONSTRAINT an_identity_operation_settles_at_least_one_effect,
          DROP CONSTRAINT an_identity_operation_settles_count_and_digest_together,
          DROP CONSTRAINT a_split_operation_names_exactly_one_source_merge,
          DROP CONSTRAINT an_identity_operation_type_is_known,
          DROP COLUMN effects_digest,
          DROP COLUMN effect_count,
          DROP COLUMN source_identity_operation_id,
          ADD CONSTRAINT an_identity_operation_type_is_known CHECK (operation_type = 'merge');
        ALTER TABLE {SCHEMA}.entity_identity_previews
          DROP CONSTRAINT a_split_preview_names_exactly_one_source_operation,
          DROP CONSTRAINT a_preview_operation_type_is_known,
          DROP COLUMN source_identity_operation_id,
          ADD CONSTRAINT a_preview_operation_type_is_known CHECK (operation_type = 'merge');
        ALTER TABLE {SCHEMA}.relationship_memory_context_links
          DROP CONSTRAINT an_entity_memory_context_link_retains_its_origin_subject,
          DROP COLUMN origin_subject_entity_id;
        ALTER TABLE {SCHEMA}.relationship_memory_proposals
          DROP CONSTRAINT proposal_origin_subject_is_an_opaque_identifier,
          DROP COLUMN origin_subject_entity_id;
        ALTER TABLE {SCHEMA}.relationship_memories
          DROP CONSTRAINT origin_subject_entity_id_is_an_opaque_identifier,
          DROP COLUMN origin_subject_entity_id;
        """
    )
    _restate_capabilities(_CAPABILITIES_BEFORE_THIS_REVISION)
