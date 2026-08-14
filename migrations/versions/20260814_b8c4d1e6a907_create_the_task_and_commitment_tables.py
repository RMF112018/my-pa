"""create the task and commitment tables

Revision ID: b8c4d1e6a907
Revises: 9d5e2f7b4c61
Create Date: 2026-08-14

Adds the first canonical Task/Commitment store on this lineage and widens
audit_events.capability_is_known and purpose_is_known with frozen literals.
Downgrade drops the tables and restores the prior audit vocabulary exactly.
"""

from __future__ import annotations

from alembic import op

revision: str = "b8c4d1e6a907"
down_revision: str | None = "9d5e2f7b4c61"
branch_labels: str | None = None
depends_on: str | None = None

_HEAD_CAPABILITIES = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.create', "
    "'commitments.list', 'knowledge.read', 'knowledge.search', "
    "'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status', 'tasks.attention', "
    "'tasks.bulk', 'tasks.create', 'tasks.history', 'tasks.list', 'tasks.preview', "
    "'tasks.read', 'tasks.search', 'tasks.transition', 'tasks.update', "
    "'tasks.waiting_on')"
)

_PRIOR_CAPABILITIES = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'knowledge.read', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status')"
)

_HEAD_PURPOSES = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'knowledge_read', 'knowledge_search', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation', 'task_authoring', 'task_review')"
)

_PRIOR_PURPOSES = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'knowledge_read', 'knowledge_search', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation')"
)


def _replace(name: str, expression: str) -> None:
    op.execute(f'ALTER TABLE knowledge.audit_events DROP CONSTRAINT "{name}"')
    op.execute(
        f'ALTER TABLE knowledge.audit_events ADD CONSTRAINT "{name}" CHECK ({expression})'
    )


def upgrade() -> None:
    _replace("capability_is_known", _HEAD_CAPABILITIES)
    _replace("purpose_is_known", _HEAD_PURPOSES)
    op.execute(
        """
        CREATE TABLE knowledge.task_recurrences (
          recurrence_id text PRIMARY KEY
            CHECK (recurrence_id ~ '^trcur_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          frequency text NOT NULL
            CONSTRAINT task_recurrence_frequency_is_known
            CHECK (frequency IN (
              'daily', 'weekdays', 'weekly', 'selected_weekdays', 'monthly'
            )),
          timezone text NOT NULL,
          interval integer NOT NULL DEFAULT 1
            CONSTRAINT task_recurrence_interval_is_positive CHECK (interval >= 1),
          weekdays integer[] NOT NULL DEFAULT '{}',
          start_date date,
          start_at timestamptz,
          series_title text NOT NULL DEFAULT '',
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT task_recurrence_start_is_date_xor_instant
            CHECK ((start_date IS NULL) <> (start_at IS NULL)),
          CONSTRAINT task_recurrence_is_principal_local
            UNIQUE (principal_id, recurrence_id)
        );
        CREATE INDEX task_recurrences_by_principal
          ON knowledge.task_recurrences (principal_id);

        CREATE TABLE knowledge.tasks (
          task_id text PRIMARY KEY
            CHECK (task_id ~ '^tsk_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          title text NOT NULL
            CONSTRAINT task_title_is_bounded CHECK (char_length(title) BETWEEN 1 AND 256),
          description text
            CONSTRAINT task_description_is_bounded
            CHECK (description IS NULL OR char_length(description) <= 8000),
          state text NOT NULL
            CONSTRAINT task_state_is_known
            CHECK (state IN (
              'open', 'in_progress', 'waiting', 'blocked', 'completed', 'cancelled'
            )),
          task_role text NOT NULL
            CONSTRAINT task_role_is_known
            CHECK (task_role IN ('action', 'follow_up', 'review', 'prepare')),
          priority text NOT NULL DEFAULT 'p3'
            CONSTRAINT task_priority_is_known
            CHECK (priority IN ('p1', 'p2', 'p3', 'p4')),
          evidence_state text NOT NULL
            CONSTRAINT task_evidence_state_is_known
            CHECK (evidence_state IN ('accepted', 'proposed')),
          acceptance_kind text NOT NULL
            CONSTRAINT task_acceptance_kind_is_known
            CHECK (acceptance_kind IN ('direct_principal', 'review', 'none')),
          accepted_by_review_decision_id text,
          origin_evidence_ref text,
          due_date date,
          due_at timestamptz,
          due_timezone text,
          scheduled_date date,
          scheduled_at timestamptz,
          deferred_until timestamptz,
          archived_at timestamptz,
          current_version integer NOT NULL DEFAULT 1
            CONSTRAINT task_version_starts_at_one CHECK (current_version >= 1),
          recurrence_id text,
          occurrence_key text,
          project_id text
            CONSTRAINT task_project_id_has_prefix
            CHECK (project_id IS NULL OR project_id ~ '^prj_[A-Za-z0-9]{8,64}$'),
          situation_id text
            CONSTRAINT task_situation_id_has_prefix
            CHECK (situation_id IS NULL OR situation_id ~ '^sit_[A-Za-z0-9]{8,64}$'),
          person_id text
            CONSTRAINT task_person_id_has_prefix
            CHECK (person_id IS NULL OR person_id ~ '^per_[A-Za-z0-9]{8,64}$'),
          opened_at timestamptz NOT NULL,
          closed_at timestamptz,
          closure_evidence_ref text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT task_due_is_date_xor_instant
            CHECK ((due_date IS NULL) OR (due_at IS NULL)),
          CONSTRAINT task_schedule_is_date_xor_instant
            CHECK ((scheduled_date IS NULL) OR (scheduled_at IS NULL)),
          CONSTRAINT task_occurrence_names_its_series
            CHECK ((recurrence_id IS NULL) = (occurrence_key IS NULL)),
          CONSTRAINT task_terminal_state_records_closed_at
            CHECK ((state IN ('completed', 'cancelled')) = (closed_at IS NOT NULL)),
          CONSTRAINT task_recurrence_is_principal_local
            FOREIGN KEY (principal_id, recurrence_id)
            REFERENCES knowledge.task_recurrences (principal_id, recurrence_id),
          CONSTRAINT task_occurrence_key_is_unique
            UNIQUE (principal_id, recurrence_id, occurrence_key)
        );
        CREATE INDEX tasks_by_principal ON knowledge.tasks (principal_id);
        CREATE UNIQUE INDEX one_actionable_occurrence_per_recurrence
          ON knowledge.tasks (principal_id, recurrence_id)
          WHERE recurrence_id IS NOT NULL AND state NOT IN ('completed', 'cancelled');

        CREATE TABLE knowledge.task_revisions (
          revision_id text PRIMARY KEY
            CHECK (revision_id ~ '^trev_[A-Za-z0-9]{8,64}$'),
          task_id text NOT NULL
            CHECK (task_id ~ '^tsk_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          version integer NOT NULL,
          origin text NOT NULL
            CONSTRAINT task_revision_origin_is_known
            CHECK (origin IN (
              'principal_direct', 'review_promotion', 'system_recurrence'
            )),
          state text NOT NULL
            CONSTRAINT task_revision_state_is_known
            CHECK (state IN (
              'open', 'in_progress', 'waiting', 'blocked', 'completed', 'cancelled'
            )),
          priority text NOT NULL
            CONSTRAINT task_revision_priority_is_known
            CHECK (priority IN ('p1', 'p2', 'p3', 'p4')),
          title text NOT NULL,
          prior_revision_id text,
          recorded_at timestamptz NOT NULL,
          CONSTRAINT task_revision_version_is_unique
            UNIQUE (principal_id, task_id, version)
        );
        CREATE INDEX task_revisions_by_task
          ON knowledge.task_revisions (principal_id, task_id);

        CREATE TABLE knowledge.task_context_links (
          link_id text PRIMARY KEY
            CHECK (link_id ~ '^tlnk_[A-Za-z0-9]{8,64}$'),
          task_id text NOT NULL
            CHECK (task_id ~ '^tsk_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          kind text NOT NULL
            CONSTRAINT task_context_link_kind_is_known
            CHECK (kind IN (
              'person', 'project', 'situation', 'commitment', 'capture',
              'proposal', 'review_decision', 'source_evidence', 'meeting'
            )),
          target_id text NOT NULL,
          CONSTRAINT task_context_link_is_unique
            UNIQUE (principal_id, task_id, kind, target_id)
        );

        CREATE TABLE knowledge.task_idempotency (
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          idempotency_key text NOT NULL
            CONSTRAINT task_idempotency_key_is_bounded
            CHECK (char_length(idempotency_key) BETWEEN 8 AND 128),
          request_hash text NOT NULL
            CONSTRAINT task_idempotency_hash_is_sha256
            CHECK (request_hash ~ '^[0-9a-f]{64}$'),
          result_json text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (principal_id, idempotency_key)
        );

        CREATE TABLE knowledge.task_bulk_previews (
          preview_id text PRIMARY KEY
            CHECK (preview_id ~ '^tbprv_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          operation text NOT NULL,
          operation_hash text NOT NULL
            CONSTRAINT task_preview_hash_is_sha256
            CHECK (operation_hash ~ '^[0-9a-f]{64}$'),
          targets_json text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE knowledge.commitments (
          commitment_id text PRIMARY KEY
            CHECK (commitment_id ~ '^cmt_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          counterparty_person_id text NOT NULL
            CHECK (counterparty_person_id ~ '^per_[A-Za-z0-9]{8,64}$'),
          direction text NOT NULL
            CONSTRAINT commitment_direction_is_known
            CHECK (direction IN ('owed_by_principal', 'owed_to_principal')),
          summary text NOT NULL
            CONSTRAINT commitment_summary_is_bounded
            CHECK (char_length(summary) BETWEEN 1 AND 512),
          state text NOT NULL
            CONSTRAINT commitment_state_is_known
            CHECK (state IN ('open', 'closed')),
          evidence_state text NOT NULL
            CONSTRAINT commitment_evidence_state_is_known
            CHECK (evidence_state IN ('accepted', 'proposed')),
          origin_evidence_ref text,
          due_date date,
          due_at timestamptz,
          due_timezone text,
          current_version integer NOT NULL DEFAULT 1,
          opened_at timestamptz NOT NULL,
          closed_at timestamptz,
          closure_evidence_ref text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT commitment_due_is_date_xor_instant
            CHECK ((due_date IS NULL) OR (due_at IS NULL)),
          CONSTRAINT commitment_closed_state_records_closed_at
            CHECK ((state = 'closed') = (closed_at IS NOT NULL))
        );
        CREATE INDEX commitments_by_principal ON knowledge.commitments (principal_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE knowledge.commitments;
        DROP TABLE knowledge.task_bulk_previews;
        DROP TABLE knowledge.task_idempotency;
        DROP TABLE knowledge.task_context_links;
        DROP TABLE knowledge.task_revisions;
        DROP TABLE knowledge.tasks;
        DROP TABLE knowledge.task_recurrences;
        """
    )
    _replace("capability_is_known", _PRIOR_CAPABILITIES)
    _replace("purpose_is_known", _PRIOR_PURPOSES)
