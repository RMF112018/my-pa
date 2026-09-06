"""Persist immutable GoodNotes client lease policy and client-scoped retry keys.

Revision ID: e8f2a6c9d104
Revises: d4e8b1c7a902
"""

from alembic import op

revision = "e8f2a6c9d104"
down_revision = "d4e8b1c7a902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE knowledge.goodnotes_pull_sessions
          ADD COLUMN lease_seconds integer NOT NULL DEFAULT 900,
          ADD CONSTRAINT goodnotes_pull_session_lease_is_bounded
            CHECK (lease_seconds BETWEEN 60 AND 86400);
        ALTER TABLE knowledge.goodnotes_pull_assignments
          DROP CONSTRAINT one_goodnotes_pull_work_attempt,
          ADD CONSTRAINT one_goodnotes_pull_work_attempt UNIQUE
            (principal_id, client_id, run_id, page_version_id, content_sha256, attempt);
        ALTER TABLE knowledge.goodnotes_pull_completions
          DROP CONSTRAINT one_goodnotes_pull_completion_key,
          ADD CONSTRAINT one_goodnotes_pull_completion_key UNIQUE
            (principal_id, client_id, idempotency_key);
    """)


def downgrade() -> None:
    op.execute("""
        LOCK TABLE knowledge.goodnotes_pull_sessions,
          knowledge.goodnotes_pull_assignments, knowledge.goodnotes_pull_completions
          IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM knowledge.goodnotes_pull_assignments
            GROUP BY principal_id, run_id, page_version_id, content_sha256, attempt
            HAVING count(*) > 1)
          OR EXISTS (SELECT 1 FROM knowledge.goodnotes_pull_completions
            GROUP BY principal_id, idempotency_key HAVING count(*) > 1)
          OR EXISTS (SELECT 1 FROM knowledge.goodnotes_pull_sessions WHERE lease_seconds <> 900)
          THEN RAISE EXCEPTION 'GoodNotes client history cannot fit the previous schema';
          END IF;
        END $$;
        ALTER TABLE knowledge.goodnotes_pull_assignments
          DROP CONSTRAINT one_goodnotes_pull_work_attempt,
          ADD CONSTRAINT one_goodnotes_pull_work_attempt UNIQUE
            (principal_id, run_id, page_version_id, content_sha256, attempt);
        ALTER TABLE knowledge.goodnotes_pull_completions
          DROP CONSTRAINT one_goodnotes_pull_completion_key,
          ADD CONSTRAINT one_goodnotes_pull_completion_key UNIQUE (principal_id, idempotency_key);
        ALTER TABLE knowledge.goodnotes_pull_sessions
          DROP CONSTRAINT goodnotes_pull_session_lease_is_bounded,
          DROP COLUMN lease_seconds;
    """)
