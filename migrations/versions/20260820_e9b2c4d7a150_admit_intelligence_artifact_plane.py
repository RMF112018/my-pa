"""Admit reports.* capabilities and create the Intelligence Artifact plane.

Revision ID: e9b2c4d7a150
Revises: f3a8c1d7e592
Create Date: 2026-08-20

WP-RPT-00 through WP-RPT-04. Forward ALTER admits eight `reports.*` capabilities
and the `report_authoring`/`report_read` purposes, then creates Principal-
partitioned cycle, producer-run, immutable-artifact, receipt, pipeline-
dependency, and external-provenance tables. DDL is written out rather than
imported from `tables.py` (`D-48`, `D-69`). Closed-set literals are frozen at
this revision. No production grant, live report ingestion, or shared-database
mutation is authorized by this revision existing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "e9b2c4d7a150"
down_revision: str | tuple[str, ...] | None = "f3a8c1d7e592"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA: Final = "knowledge"

_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.list', 'commitments.read', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'entities.context', 'entities.get', "
    "'entities.relationships', 'entities.resolve', 'entities.search', "
    "'entities.unresolved_mentions', 'goodnotes.content', 'goodnotes.propose', "
    "'goodnotes.work', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'reports.begin_cycle', 'reports.commit', "
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
    "'commitments.create', 'commitments.list', 'commitments.read', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'entities.context', 'entities.get', "
    "'entities.relationships', 'entities.resolve', 'entities.search', "
    "'entities.unresolved_mentions', 'goodnotes.content', 'goodnotes.propose', "
    "'goodnotes.work', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_read', 'goodnotes_content', "
    "'goodnotes_proposal', 'goodnotes_work', 'knowledge_read', "
    "'knowledge_search', 'report_authoring', 'report_read', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation', 'task_authoring', 'task_read')"
)
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_read', 'goodnotes_content', "
    "'goodnotes_proposal', 'goodnotes_work', 'knowledge_read', "
    "'knowledge_search', 'review_disposition', 'security_validation', "
    "'source_inspection', 'status_observation', 'task_authoring', 'task_read')"
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
    _restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.intelligence_cycle_runs (
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          cycle_run_id text NOT NULL
            CHECK (cycle_run_id ~ '^micr_[A-Za-z0-9]{{8,64}}$'),
          cycle_id text NOT NULL
            CHECK (cycle_id = 'morning_intelligence'),
          business_date date NOT NULL,
          state text NOT NULL
            CHECK (state IN ('open', 'running', 'complete', 'failed', 'cancelled')),
          version integer NOT NULL
            CHECK (version >= 1),
          automation_platform text
            CHECK (
              automation_platform IS NULL
              OR length(automation_platform) BETWEEN 1 AND 64
            ),
          external_root_run_id text
            CHECK (
              external_root_run_id IS NULL
              OR length(external_root_run_id) BETWEEN 1 AND 128
            ),
          created_at timestamptz NOT NULL,
          started_at timestamptz,
          finished_at timestamptz,
          CONSTRAINT intelligence_cycle_runs_pkey
            PRIMARY KEY (principal_id, cycle_run_id)
        );

        CREATE UNIQUE INDEX intelligence_cycle_external_root_is_unique
          ON {SCHEMA}.intelligence_cycle_runs (
            principal_id, automation_platform, external_root_run_id
          )
          WHERE external_root_run_id IS NOT NULL;

        CREATE INDEX intelligence_cycle_runs_by_date
          ON {SCHEMA}.intelligence_cycle_runs (principal_id, cycle_id, business_date DESC);

        CREATE TABLE {SCHEMA}.intelligence_producer_runs (
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          run_id text NOT NULL
            CHECK (run_id ~ '^rrun_[A-Za-z0-9]{{8,64}}$'),
          cycle_run_id text NOT NULL
            CHECK (cycle_run_id ~ '^micr_[A-Za-z0-9]{{8,64}}$'),
          focus_area_id text
            CHECK (
              focus_area_id IS NULL
              OR focus_area_id IN (
                'risk_deadline_exception', 'decision_approval',
                'communications', 'project_program_pulse',
                'watchlist_dependency', 'action_commitment'
              )
            ),
          stage text NOT NULL
            CHECK (stage IN (
              'collector', 'researcher', 'synthesizer', 'reporter', 'morning_brief'
            )),
          artifact_kind text NOT NULL
            CHECK (artifact_kind IN (
              'collector_candidates', 'research_context', 'synthesis_package',
              'focus_report', 'morning_brief'
            )),
          source_lane text
            CHECK (
              source_lane IS NULL
              OR source_lane IN (
                'sharepoint', 'onedrive', 'my_pa', 'outlook', 'teams'
              )
            ),
          producer_task_id text NOT NULL
            CHECK (length(producer_task_id) BETWEEN 1 AND 128),
          producer_task_name text NOT NULL
            CHECK (length(producer_task_name) BETWEEN 1 AND 256),
          automation_platform text NOT NULL
            CHECK (length(automation_platform) BETWEEN 1 AND 64),
          automation_run_id text
            CHECK (
              automation_run_id IS NULL
              OR length(automation_run_id) BETWEEN 1 AND 128
            ),
          report_date date NOT NULL,
          coverage_start timestamptz,
          coverage_end timestamptz,
          state text NOT NULL
            CHECK (state IN (
              'scheduled', 'running', 'succeeded', 'partial', 'failed', 'cancelled'
            )),
          version integer NOT NULL
            CHECK (version >= 1),
          failure_code text
            CHECK (
              failure_code IS NULL
              OR length(failure_code) BETWEEN 1 AND 64
            ),
          failure_summary text
            CHECK (
              failure_summary IS NULL
              OR length(failure_summary) BETWEEN 1 AND 256
            ),
          created_at timestamptz NOT NULL,
          started_at timestamptz,
          finished_at timestamptz,
          CONSTRAINT intelligence_producer_runs_pkey
            PRIMARY KEY (principal_id, run_id),
          CONSTRAINT intelligence_producer_runs_cycle_fk
            FOREIGN KEY (principal_id, cycle_run_id)
            REFERENCES {SCHEMA}.intelligence_cycle_runs (principal_id, cycle_run_id)
            ON DELETE RESTRICT,
          CONSTRAINT intelligence_run_stage_kind_match CHECK (
            (stage = 'collector' AND artifact_kind = 'collector_candidates')
            OR (stage = 'researcher' AND artifact_kind = 'research_context')
            OR (stage = 'synthesizer' AND artifact_kind = 'synthesis_package')
            OR (stage = 'reporter' AND artifact_kind = 'focus_report')
            OR (stage = 'morning_brief' AND artifact_kind = 'morning_brief')
          ),
          CONSTRAINT intelligence_run_focus_and_lane_match CHECK (
            (
              stage = 'morning_brief'
              AND focus_area_id IS NULL
              AND source_lane IS NULL
            )
            OR (
              stage = 'researcher'
              AND focus_area_id IS NOT NULL
              AND source_lane IS NOT NULL
            )
            OR (
              stage IN ('collector', 'synthesizer', 'reporter')
              AND focus_area_id IS NOT NULL
              AND source_lane IS NULL
            )
          )
        );

        CREATE UNIQUE INDEX intelligence_producer_external_run_is_unique
          ON {SCHEMA}.intelligence_producer_runs (
            principal_id, automation_platform, producer_task_id, automation_run_id
          )
          WHERE automation_run_id IS NOT NULL;

        CREATE INDEX intelligence_producer_runs_by_cycle
          ON {SCHEMA}.intelligence_producer_runs (
            principal_id, cycle_run_id, stage, focus_area_id, source_lane
          );

        CREATE TABLE {SCHEMA}.intelligence_artifacts (
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          artifact_id text NOT NULL
            CHECK (artifact_id ~ '^rpt_[A-Za-z0-9]{{8,64}}$'),
          cycle_run_id text NOT NULL
            CHECK (cycle_run_id ~ '^micr_[A-Za-z0-9]{{8,64}}$'),
          producer_run_id text NOT NULL
            CHECK (producer_run_id ~ '^rrun_[A-Za-z0-9]{{8,64}}$'),
          focus_area_id text
            CHECK (
              focus_area_id IS NULL
              OR focus_area_id IN (
                'risk_deadline_exception', 'decision_approval',
                'communications', 'project_program_pulse',
                'watchlist_dependency', 'action_commitment'
              )
            ),
          stage text NOT NULL
            CHECK (stage IN (
              'collector', 'researcher', 'synthesizer', 'reporter', 'morning_brief'
            )),
          artifact_kind text NOT NULL
            CHECK (artifact_kind IN (
              'collector_candidates', 'research_context', 'synthesis_package',
              'focus_report', 'morning_brief'
            )),
          source_lane text
            CHECK (
              source_lane IS NULL
              OR source_lane IN (
                'sharepoint', 'onedrive', 'my_pa', 'outlook', 'teams'
              )
            ),
          report_date date NOT NULL,
          title text NOT NULL
            CHECK (length(title) BETWEEN 1 AND 256),
          body_markdown text NOT NULL,
          structured_content jsonb
            CHECK (
              structured_content IS NULL
              OR jsonb_typeof(structured_content) = 'object'
            ),
          content_sha256 text NOT NULL
            CHECK (content_sha256 ~ '^[0-9a-f]{{64}}$'),
          content_bytes integer NOT NULL
            CHECK (content_bytes >= 0 AND content_bytes <= 2097152),
          artifact_state text NOT NULL
            CHECK (artifact_state IN ('partial', 'final', 'superseded', 'rejected')),
          completeness text
            CHECK (
              completeness IS NULL
              OR length(completeness) BETWEEN 1 AND 32
            ),
          schema_version text NOT NULL
            CHECK (length(schema_version) BETWEEN 1 AND 32),
          producer_prompt_version text
            CHECK (
              producer_prompt_version IS NULL
              OR length(producer_prompt_version) BETWEEN 1 AND 64
            ),
          generated_at timestamptz NOT NULL,
          committed_at timestamptz NOT NULL,
          version integer NOT NULL
            CHECK (version >= 1),
          is_current boolean NOT NULL,
          supersedes_artifact_id text
            CHECK (
              supersedes_artifact_id IS NULL
              OR supersedes_artifact_id ~ '^rpt_[A-Za-z0-9]{{8,64}}$'
            ),
          evaluation_metric_id text
            CHECK (
              evaluation_metric_id IS NULL
              OR length(evaluation_metric_id) BETWEEN 1 AND 64
            ),
          evaluation_metric_version text
            CHECK (
              evaluation_metric_version IS NULL
              OR length(evaluation_metric_version) BETWEEN 1 AND 32
            ),
          evaluation_score text
            CHECK (
              evaluation_score IS NULL
              OR length(evaluation_score) BETWEEN 1 AND 32
            ),
          evaluation_state text
            CHECK (
              evaluation_state IS NULL
              OR length(evaluation_state) BETWEEN 1 AND 32
            ),
          search_document tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(title, '')), 'A')
            || setweight(to_tsvector('english', coalesce(body_markdown, '')), 'B')
          ) STORED,
          CONSTRAINT intelligence_artifacts_pkey
            PRIMARY KEY (principal_id, artifact_id),
          CONSTRAINT intelligence_artifacts_cycle_fk
            FOREIGN KEY (principal_id, cycle_run_id)
            REFERENCES {SCHEMA}.intelligence_cycle_runs (principal_id, cycle_run_id)
            ON DELETE RESTRICT,
          CONSTRAINT intelligence_artifacts_run_fk
            FOREIGN KEY (principal_id, producer_run_id)
            REFERENCES {SCHEMA}.intelligence_producer_runs (principal_id, run_id)
            ON DELETE RESTRICT,
          CONSTRAINT intelligence_artifacts_supersedes_fk
            FOREIGN KEY (principal_id, supersedes_artifact_id)
            REFERENCES {SCHEMA}.intelligence_artifacts (principal_id, artifact_id)
            ON DELETE RESTRICT,
          CONSTRAINT intelligence_artifact_no_self_supersession CHECK (
            supersedes_artifact_id IS NULL
            OR supersedes_artifact_id <> artifact_id
          ),
          CONSTRAINT intelligence_artifact_stage_kind_match CHECK (
            (stage = 'collector' AND artifact_kind = 'collector_candidates')
            OR (stage = 'researcher' AND artifact_kind = 'research_context')
            OR (stage = 'synthesizer' AND artifact_kind = 'synthesis_package')
            OR (stage = 'reporter' AND artifact_kind = 'focus_report')
            OR (stage = 'morning_brief' AND artifact_kind = 'morning_brief')
          ),
          CONSTRAINT intelligence_artifact_focus_and_lane_match CHECK (
            (
              stage = 'morning_brief'
              AND focus_area_id IS NULL
              AND source_lane IS NULL
            )
            OR (
              stage = 'researcher'
              AND focus_area_id IS NOT NULL
              AND source_lane IS NOT NULL
            )
            OR (
              stage IN ('collector', 'synthesizer', 'reporter')
              AND focus_area_id IS NOT NULL
              AND source_lane IS NULL
            )
          )
        );

        CREATE UNIQUE INDEX intelligence_artifact_current_head
          ON {SCHEMA}.intelligence_artifacts (
            principal_id,
            cycle_run_id,
            stage,
            coalesce(focus_area_id, ''),
            coalesce(source_lane, '')
          )
          WHERE is_current;

        CREATE INDEX intelligence_artifacts_by_cycle_stage
          ON {SCHEMA}.intelligence_artifacts (
            principal_id, cycle_run_id, stage, focus_area_id, source_lane,
            report_date DESC, committed_at DESC
          );

        CREATE INDEX intelligence_artifacts_search_document
          ON {SCHEMA}.intelligence_artifacts USING gin (search_document);

        CREATE TABLE {SCHEMA}.intelligence_commit_receipts (
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          receipt_id text NOT NULL
            CHECK (receipt_id ~ '^rrc_[A-Za-z0-9]{{8,64}}$'),
          idempotency_key text NOT NULL
            CHECK (length(idempotency_key) BETWEEN 1 AND 128),
          mutation_kind text NOT NULL
            CHECK (mutation_kind IN ('cycle_begin', 'artifact_commit', 'run_state')),
          fingerprint_sha256 text NOT NULL
            CHECK (fingerprint_sha256 ~ '^[0-9a-f]{{64}}$'),
          cycle_run_id text NOT NULL
            CHECK (cycle_run_id ~ '^micr_[A-Za-z0-9]{{8,64}}$'),
          producer_run_id text
            CHECK (
              producer_run_id IS NULL
              OR producer_run_id ~ '^rrun_[A-Za-z0-9]{{8,64}}$'
            ),
          artifact_id text
            CHECK (
              artifact_id IS NULL
              OR artifact_id ~ '^rpt_[A-Za-z0-9]{{8,64}}$'
            ),
          content_sha256 text
            CHECK (
              content_sha256 IS NULL
              OR content_sha256 ~ '^[0-9a-f]{{64}}$'
            ),
          content_bytes integer
            CHECK (content_bytes IS NULL OR content_bytes >= 0),
          created_at timestamptz NOT NULL,
          CONSTRAINT intelligence_commit_receipts_pkey
            PRIMARY KEY (principal_id, receipt_id),
          CONSTRAINT one_intelligence_key_per_principal
            UNIQUE (principal_id, idempotency_key),
          CONSTRAINT intelligence_receipts_cycle_fk
            FOREIGN KEY (principal_id, cycle_run_id)
            REFERENCES {SCHEMA}.intelligence_cycle_runs (principal_id, cycle_run_id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT intelligence_receipts_run_fk
            FOREIGN KEY (principal_id, producer_run_id)
            REFERENCES {SCHEMA}.intelligence_producer_runs (principal_id, run_id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT intelligence_receipts_artifact_fk
            FOREIGN KEY (principal_id, artifact_id)
            REFERENCES {SCHEMA}.intelligence_artifacts (principal_id, artifact_id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED
        );

        CREATE TABLE {SCHEMA}.intelligence_pipeline_dependencies (
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          downstream_artifact_id text NOT NULL
            CHECK (downstream_artifact_id ~ '^rpt_[A-Za-z0-9]{{8,64}}$'),
          upstream_artifact_id text NOT NULL
            CHECK (upstream_artifact_id ~ '^rpt_[A-Za-z0-9]{{8,64}}$'),
          dependency_role text NOT NULL
            CHECK (length(dependency_role) BETWEEN 1 AND 64),
          required boolean NOT NULL,
          expected_stage text
            CHECK (
              expected_stage IS NULL
              OR expected_stage IN (
                'collector', 'researcher', 'synthesizer', 'reporter', 'morning_brief'
              )
            ),
          expected_focus_area_id text
            CHECK (
              expected_focus_area_id IS NULL
              OR expected_focus_area_id IN (
                'risk_deadline_exception', 'decision_approval',
                'communications', 'project_program_pulse',
                'watchlist_dependency', 'action_commitment'
              )
            ),
          expected_source_lane text
            CHECK (
              expected_source_lane IS NULL
              OR expected_source_lane IN (
                'sharepoint', 'onedrive', 'my_pa', 'outlook', 'teams'
              )
            ),
          CONSTRAINT intelligence_pipeline_dependencies_pkey
            PRIMARY KEY (principal_id, downstream_artifact_id, upstream_artifact_id),
          CONSTRAINT intelligence_dependency_no_self CHECK (
            downstream_artifact_id <> upstream_artifact_id
          ),
          CONSTRAINT intelligence_dependency_downstream_fk
            FOREIGN KEY (principal_id, downstream_artifact_id)
            REFERENCES {SCHEMA}.intelligence_artifacts (principal_id, artifact_id)
            ON DELETE RESTRICT,
          CONSTRAINT intelligence_dependency_upstream_fk
            FOREIGN KEY (principal_id, upstream_artifact_id)
            REFERENCES {SCHEMA}.intelligence_artifacts (principal_id, artifact_id)
            ON DELETE RESTRICT
        );

        CREATE TABLE {SCHEMA}.intelligence_provenance_refs (
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          artifact_id text NOT NULL
            CHECK (artifact_id ~ '^rpt_[A-Za-z0-9]{{8,64}}$'),
          position integer NOT NULL
            CHECK (position >= 1),
          source_system text NOT NULL
            CHECK (length(source_system) BETWEEN 1 AND 64),
          source_ref text NOT NULL
            CHECK (length(source_ref) BETWEEN 1 AND 256),
          relation text NOT NULL
            CHECK (relation IN ('supports', 'contradicts', 'context', 'derived_from')),
          source_url text
            CHECK (
              source_url IS NULL
              OR (
                length(source_url) BETWEEN 1 AND 512
                AND source_url ~ '^(https|http)://'
              )
            ),
          observed_at timestamptz,
          retrieved_at timestamptz,
          evidence_subject_id text
            CHECK (
              evidence_subject_id IS NULL
              OR evidence_subject_id ~ '^[a-z]+_[A-Za-z0-9]{{8,64}}$'
            ),
          CONSTRAINT intelligence_provenance_refs_pkey
            PRIMARY KEY (principal_id, artifact_id, position),
          CONSTRAINT intelligence_provenance_artifact_fk
            FOREIGN KEY (principal_id, artifact_id)
            REFERENCES {SCHEMA}.intelligence_artifacts (principal_id, artifact_id)
            ON DELETE RESTRICT
        );

        CREATE FUNCTION {SCHEMA}.intelligence_artifacts_protect_body()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'intelligence artifacts are never deleted';
          END IF;
          IF NEW.body_markdown IS DISTINCT FROM OLD.body_markdown
             OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
             OR NEW.content_bytes IS DISTINCT FROM OLD.content_bytes
             OR NEW.title IS DISTINCT FROM OLD.title
             OR NEW.structured_content IS DISTINCT FROM OLD.structured_content
             OR NEW.principal_id IS DISTINCT FROM OLD.principal_id
             OR NEW.artifact_id IS DISTINCT FROM OLD.artifact_id
             OR NEW.cycle_run_id IS DISTINCT FROM OLD.cycle_run_id
             OR NEW.producer_run_id IS DISTINCT FROM OLD.producer_run_id
             OR NEW.stage IS DISTINCT FROM OLD.stage
             OR NEW.artifact_kind IS DISTINCT FROM OLD.artifact_kind THEN
            RAISE EXCEPTION 'intelligence artifact body and identity are immutable';
          END IF;
          RETURN NEW;
        END;
        $$;

        CREATE TRIGGER intelligence_artifacts_protect_body
          BEFORE UPDATE OR DELETE ON {SCHEMA}.intelligence_artifacts
          FOR EACH ROW
          EXECUTE FUNCTION {SCHEMA}.intelligence_artifacts_protect_body();

        CREATE FUNCTION {SCHEMA}.intelligence_lineage_is_append_only()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RAISE EXCEPTION 'intelligence lineage rows are append-only';
        END;
        $$;

        CREATE TRIGGER intelligence_pipeline_dependencies_are_append_only
          BEFORE UPDATE OR DELETE ON {SCHEMA}.intelligence_pipeline_dependencies
          FOR EACH ROW
          EXECUTE FUNCTION {SCHEMA}.intelligence_lineage_is_append_only();

        CREATE TRIGGER intelligence_provenance_refs_are_append_only
          BEFORE UPDATE OR DELETE ON {SCHEMA}.intelligence_provenance_refs
          FOR EACH ROW
          EXECUTE FUNCTION {SCHEMA}.intelligence_lineage_is_append_only();

        CREATE TRIGGER intelligence_commit_receipts_are_append_only
          BEFORE UPDATE OR DELETE ON {SCHEMA}.intelligence_commit_receipts
          FOR EACH ROW
          EXECUTE FUNCTION {SCHEMA}.intelligence_lineage_is_append_only();
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DROP TRIGGER IF EXISTS intelligence_commit_receipts_are_append_only
          ON {SCHEMA}.intelligence_commit_receipts;
        DROP TRIGGER IF EXISTS intelligence_provenance_refs_are_append_only
          ON {SCHEMA}.intelligence_provenance_refs;
        DROP TRIGGER IF EXISTS intelligence_pipeline_dependencies_are_append_only
          ON {SCHEMA}.intelligence_pipeline_dependencies;
        DROP TRIGGER IF EXISTS intelligence_artifacts_protect_body
          ON {SCHEMA}.intelligence_artifacts;
        DROP FUNCTION IF EXISTS {SCHEMA}.intelligence_lineage_is_append_only();
        DROP FUNCTION IF EXISTS {SCHEMA}.intelligence_artifacts_protect_body();
        DROP TABLE IF EXISTS {SCHEMA}.intelligence_provenance_refs;
        DROP TABLE IF EXISTS {SCHEMA}.intelligence_pipeline_dependencies;
        DROP TABLE IF EXISTS {SCHEMA}.intelligence_commit_receipts;
        DROP TABLE IF EXISTS {SCHEMA}.intelligence_artifacts;
        DROP TABLE IF EXISTS {SCHEMA}.intelligence_producer_runs;
        DROP TABLE IF EXISTS {SCHEMA}.intelligence_cycle_runs;
        """
    )
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
