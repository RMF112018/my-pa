"""Add bounded retry scheduling, terminal dead letters, and worker liveness.

Revision ID: b4e8d2c7a613
Revises: 91d7b3e5a204
Created: 2026-08-12 06:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b4e8d2c7a613"
down_revision: str | None = "91d7b3e5a204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.jobs
          ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT now(),
          ADD COLUMN dead_lettered_at timestamptz;
        UPDATE knowledge.jobs SET dead_lettered_at = updated_at WHERE state = 'failed';
        ALTER TABLE knowledge.jobs ADD CONSTRAINT a_failed_job_is_dead_lettered
          CHECK ((state = 'failed') = (dead_lettered_at IS NOT NULL));
        DROP INDEX knowledge.jobs_by_principal_claim_order;
        CREATE INDEX jobs_by_principal_claim_order
          ON knowledge.jobs (principal_id, state, next_attempt_at, created_at);

        ALTER TABLE knowledge.capture_jobs
          ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT now(),
          ADD COLUMN dead_lettered_at timestamptz;
        UPDATE knowledge.capture_jobs SET dead_lettered_at = updated_at WHERE state = 'failed';
        ALTER TABLE knowledge.capture_jobs ADD CONSTRAINT a_failed_capture_job_is_dead_lettered
          CHECK ((state = 'failed') = (dead_lettered_at IS NOT NULL));
        DROP INDEX knowledge.capture_jobs_by_principal_claim_order;
        CREATE INDEX capture_jobs_by_principal_claim_order
          ON knowledge.capture_jobs (principal_id, state, next_attempt_at, created_at);

        CREATE TABLE knowledge.worker_heartbeats (
          worker_owner text
            CHECK (worker_owner ~ '^[A-Za-z0-9_-]{4,64}$'),
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          plane text NOT NULL CHECK (plane IN ('capture', 'enrollment')),
          started_at timestamptz NOT NULL DEFAULT now(),
          heartbeat_at timestamptz NOT NULL DEFAULT now(),
          stopped_at timestamptz,
          PRIMARY KEY (worker_owner, principal_id)
        );
        CREATE INDEX worker_heartbeats_by_principal_plane
          ON knowledge.worker_heartbeats (principal_id, plane, heartbeat_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE knowledge.worker_heartbeats;

        DROP INDEX knowledge.capture_jobs_by_principal_claim_order;
        CREATE INDEX capture_jobs_by_principal_claim_order
          ON knowledge.capture_jobs (principal_id, state, created_at);
        ALTER TABLE knowledge.capture_jobs
          DROP CONSTRAINT a_failed_capture_job_is_dead_lettered,
          DROP COLUMN dead_lettered_at,
          DROP COLUMN next_attempt_at;

        DROP INDEX knowledge.jobs_by_principal_claim_order;
        CREATE INDEX jobs_by_principal_claim_order
          ON knowledge.jobs (principal_id, state, created_at);
        ALTER TABLE knowledge.jobs
          DROP CONSTRAINT a_failed_job_is_dead_lettered,
          DROP COLUMN dead_lettered_at,
          DROP COLUMN next_attempt_at;
        """
    )
