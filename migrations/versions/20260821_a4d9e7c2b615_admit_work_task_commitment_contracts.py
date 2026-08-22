"""Admit the bounded WP-FE-03 Task and Commitment persistence contracts.

Revision ID: a4d9e7c2b615
Revises: e9b2c4d7a150
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "a4d9e7c2b615"
down_revision: str | tuple[str, ...] | None = "e9b2c4d7a150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.list', 'commitments.read', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', 'documents.revise', "
    "'entities.context', 'entities.get', 'entities.relationships', "
    "'entities.resolve', 'entities.search', 'entities.unresolved_mentions', "
    "'goodnotes.content', 'goodnotes.propose', 'goodnotes.work', "
    "'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'reports.begin_cycle', 'reports.commit', "
    "'reports.latest', 'reports.list', 'reports.read', 'reports.record_run_state', "
    "'reports.resolve_set', 'reports.search', 'review.decide', 'review.list', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.history', 'commitments.list', "
    "'commitments.read', 'commitments.search', 'commitments.update', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', 'documents.revise', "
    "'entities.context', 'entities.get', 'entities.relationships', "
    "'entities.resolve', 'entities.search', 'entities.unresolved_mentions', "
    "'goodnotes.content', 'goodnotes.propose', 'goodnotes.work', "
    "'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'reports.begin_cycle', 'reports.commit', "
    "'reports.latest', 'reports.list', 'reports.read', 'reports.record_run_state', "
    "'reports.resolve_set', 'reports.search', 'review.decide', 'review.list', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)


def _restate_capabilities(expression: str) -> None:
    op.execute('ALTER TABLE knowledge.audit_events DROP CONSTRAINT "capability_is_known"')
    op.execute(
        'ALTER TABLE knowledge.audit_events ADD CONSTRAINT "capability_is_known" '
        f"CHECK ({expression})"
    )


def upgrade() -> None:
    _restate_capabilities(_CAPABILITIES_AT_THIS_REVISION)
    op.execute("ALTER TABLE knowledge.task_history ADD COLUMN request_digest text")
    op.execute("ALTER TABLE knowledge.task_history ADD COLUMN bulk_operation_id text")
    op.execute(
        "ALTER TABLE knowledge.task_history ADD CONSTRAINT "
        "a_task_history_request_digest_is_sha256 CHECK "
        "(request_digest IS NULL OR request_digest ~ '^[0-9a-f]{64}$')"
    )
    op.execute(
        "ALTER TABLE knowledge.task_history ADD CONSTRAINT "
        "a_task_history_bulk_operation_is_opaque CHECK "
        "(bulk_operation_id IS NULL OR bulk_operation_id ~ '^bulk_[A-Za-z0-9]{8,64}$')"
    )
    op.execute("ALTER TABLE knowledge.commitment_history ADD COLUMN request_digest text")
    op.execute(
        "ALTER TABLE knowledge.commitment_history ADD CONSTRAINT "
        "a_commitment_history_request_digest_is_sha256 CHECK "
        "(request_digest IS NULL OR request_digest ~ '^[0-9a-f]{64}$')"
    )
    op.execute("ALTER TABLE knowledge.task_history DROP CONSTRAINT a_task_history_action_is_known")
    op.execute(
        "ALTER TABLE knowledge.task_history ADD CONSTRAINT a_task_history_action_is_known "
        "CHECK (action IN ('create','update','update_title','update_description',"
        "'transition_lifecycle','set_priority','schedule','defer','archive','unarchive',"
        "'set_recurrence','cancel_recurrence','link_commitment','set_role'))"
    )
    op.execute(
        "ALTER TABLE knowledge.commitment_history DROP CONSTRAINT "
        "a_commitment_history_action_is_known"
    )
    op.execute(
        "ALTER TABLE knowledge.commitment_history ADD CONSTRAINT "
        "a_commitment_history_action_is_known CHECK (action IN ('create','update','close'))"
    )
    op.execute(
        "ALTER TABLE knowledge.commitments ADD CONSTRAINT "
        "commitments_principal_commitment_is_unique UNIQUE (principal_id, commitment_id)"
    )
    op.execute("ALTER TABLE knowledge.tasks DROP CONSTRAINT tasks_commitment_id_fkey")
    op.execute(
        "ALTER TABLE knowledge.tasks ADD CONSTRAINT tasks_commitment_is_same_principal "
        "FOREIGN KEY (principal_id, commitment_id) REFERENCES "
        "knowledge.commitments (principal_id, commitment_id)"
    )
    op.execute(
        "CREATE INDEX tasks_work_view_order ON knowledge.tasks "
        "(principal_id, lifecycle_state, archived_at, due_at, scheduled_at, task_id)"
    )
    op.execute(
        "CREATE INDEX commitments_work_view_order ON knowledge.commitments "
        "(principal_id, state, direction, due_at, commitment_id)"
    )
    op.execute(
        "CREATE TABLE knowledge.task_bulk_operations ("
        "bulk_operation_id text PRIMARY KEY CHECK "
        "(bulk_operation_id ~ '^bulk_[A-Za-z0-9]{8,64}$'), "
        "principal_id text NOT NULL CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'), "
        "preview_idempotency_key text NOT NULL CHECK "
        "(preview_idempotency_key ~ '^[A-Za-z0-9_-]{8,128}$'), "
        "request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'), "
        "previewed_at timestamptz NOT NULL, expires_at timestamptz NOT NULL, "
        "preview_affected integer NOT NULL, preview_no_op integer NOT NULL, "
        "confirmed_at timestamptz, confirm_idempotency_key text, "
        "affected integer, no_op integer, rejected integer, "
        "history_ids jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "CONSTRAINT a_task_bulk_preview_expires_later CHECK (expires_at > previewed_at), "
        "CONSTRAINT task_bulk_preview_counts_are_non_negative CHECK "
        "(preview_affected >= 0 AND preview_no_op >= 0), "
        "CONSTRAINT task_bulk_preview_size_is_bounded CHECK "
        "(preview_affected + preview_no_op BETWEEN 1 AND 100), "
        "CONSTRAINT a_task_bulk_confirm_key_is_bounded CHECK "
        "(confirm_idempotency_key IS NULL OR "
        "confirm_idempotency_key ~ '^[A-Za-z0-9_-]{8,128}$'), "
        "CONSTRAINT a_task_bulk_confirmation_key_is_paired CHECK "
        "((confirmed_at IS NULL) = (confirm_idempotency_key IS NULL)), "
        "CONSTRAINT a_task_bulk_result_is_paired CHECK "
        "((confirmed_at IS NULL AND affected IS NULL AND no_op IS NULL AND "
        "rejected IS NULL AND jsonb_array_length(history_ids) = 0) OR "
        "(confirmed_at IS NOT NULL AND affected IS NOT NULL AND no_op IS NOT NULL AND "
        "rejected IS NOT NULL)), "
        "CONSTRAINT task_bulk_confirmation_matches_preview CHECK "
        "(confirmed_at IS NULL OR (affected = preview_affected AND "
        "no_op = preview_no_op AND rejected = 0 AND "
        "jsonb_array_length(history_ids) = preview_affected + preview_no_op)), "
        "CONSTRAINT one_task_bulk_preview_key_per_principal UNIQUE "
        "(principal_id, preview_idempotency_key), "
        "CONSTRAINT one_task_bulk_confirm_key_per_principal UNIQUE "
        "(principal_id, confirm_idempotency_key))"
    )
    op.execute(
        "CREATE INDEX task_bulk_operations_by_principal ON "
        "knowledge.task_bulk_operations (principal_id, bulk_operation_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE knowledge.task_bulk_operations")
    op.execute("DROP INDEX knowledge.commitments_work_view_order")
    op.execute("DROP INDEX knowledge.tasks_work_view_order")
    op.execute("ALTER TABLE knowledge.tasks DROP CONSTRAINT tasks_commitment_is_same_principal")
    op.execute(
        "ALTER TABLE knowledge.tasks ADD CONSTRAINT tasks_commitment_id_fkey "
        "FOREIGN KEY (commitment_id) REFERENCES knowledge.commitments (commitment_id)"
    )
    op.execute(
        "ALTER TABLE knowledge.commitments DROP CONSTRAINT "
        "commitments_principal_commitment_is_unique"
    )
    op.execute(
        "ALTER TABLE knowledge.commitment_history DROP CONSTRAINT "
        "a_commitment_history_action_is_known"
    )
    op.execute(
        "ALTER TABLE knowledge.commitment_history ADD CONSTRAINT "
        "a_commitment_history_action_is_known CHECK (action IN ('close','create'))"
    )
    op.execute("ALTER TABLE knowledge.task_history DROP CONSTRAINT a_task_history_action_is_known")
    op.execute(
        "ALTER TABLE knowledge.task_history ADD CONSTRAINT a_task_history_action_is_known "
        "CHECK (action IN ('archive','cancel_recurrence','create','defer','link_commitment',"
        "'schedule','set_priority','set_recurrence','set_role','transition_lifecycle',"
        "'unarchive','update_description','update_title'))"
    )
    op.execute(
        "ALTER TABLE knowledge.commitment_history DROP CONSTRAINT "
        "a_commitment_history_request_digest_is_sha256"
    )
    op.execute("ALTER TABLE knowledge.commitment_history DROP COLUMN request_digest")
    op.execute(
        "ALTER TABLE knowledge.task_history DROP CONSTRAINT a_task_history_request_digest_is_sha256"
    )
    op.execute(
        "ALTER TABLE knowledge.task_history DROP CONSTRAINT a_task_history_bulk_operation_is_opaque"
    )
    op.execute("ALTER TABLE knowledge.task_history DROP COLUMN bulk_operation_id")
    op.execute("ALTER TABLE knowledge.task_history DROP COLUMN request_digest")
    _restate_capabilities(_CAPABILITIES_BEFORE_THIS_REVISION)
