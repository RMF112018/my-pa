"""Freeze WP-12E baseline inputs and bind checkpoints to admitted pages.

Revision ID: a7c3e8d1f642
Revises: 9d5e2f7b4c61
"""

from __future__ import annotations

from alembic import op

revision: str = "a7c3e8d1f642"
down_revision: str | None = "9d5e2f7b4c61"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.native_sync_runs
          ADD COLUMN bridge_id text,
          ADD COLUMN adapter_identity text;
        ALTER TABLE knowledge.native_sync_runs
          DISABLE TRIGGER native_sync_runs_is_append_only;
        UPDATE knowledge.native_sync_runs run
        SET bridge_id = configuration.bridge_id,
            adapter_identity = 'legacy-protocol-v1'
        FROM knowledge.native_configuration_revisions configuration
        WHERE configuration.configuration_id = run.configuration_id
          AND configuration.revision = run.configuration_revision;
        ALTER TABLE knowledge.native_sync_runs
          ENABLE TRIGGER native_sync_runs_is_append_only;
        ALTER TABLE knowledge.native_sync_runs
          ALTER COLUMN bridge_id SET NOT NULL,
          ALTER COLUMN adapter_identity SET NOT NULL,
          ADD CONSTRAINT native_sync_runs_bridge_id_fkey
            FOREIGN KEY (bridge_id) REFERENCES knowledge.native_bridges(bridge_id),
          ADD CONSTRAINT native_run_adapter_identity_is_bounded
            CHECK (adapter_identity ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$');

        ALTER TABLE knowledge.native_sync_runs
          DROP CONSTRAINT native_sync_runs_state_check,
          ADD CONSTRAINT native_run_state_is_known
            CHECK (state IN ('failed', 'partial', 'running', 'succeeded'));

        ALTER TABLE knowledge.native_sync_jobs
          ADD COLUMN run_id text REFERENCES knowledge.native_sync_runs(run_id),
          ADD COLUMN read_mode text NOT NULL DEFAULT 'bounded_time',
          ADD CONSTRAINT native_sync_job_read_mode_is_known
            CHECK (read_mode IN ('bounded_time', 'current_inventory'));
        ALTER TABLE knowledge.native_sync_jobs ALTER COLUMN read_mode DROP DEFAULT;

        ALTER TABLE knowledge.native_checkpoints
          ADD COLUMN job_id text REFERENCES knowledge.native_sync_jobs(job_id),
          ADD COLUMN admission_authority_id text
            REFERENCES knowledge.native_admission_authorities(authority_id),
          ADD COLUMN terminal boolean NOT NULL DEFAULT false,
          ADD COLUMN item_count integer NOT NULL DEFAULT 0 CHECK (item_count >= 0),
          ADD CONSTRAINT one_checkpoint_per_native_admission UNIQUE (admission_authority_id);
        ALTER TABLE knowledge.native_checkpoints
          ALTER COLUMN terminal DROP DEFAULT,
          ALTER COLUMN item_count DROP DEFAULT;

        CREATE FUNCTION knowledge.native_run_snapshot_is_exact() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE configured_bridge text; configured_start timestamptz;
        BEGIN
          SELECT bridge_id, start_at INTO configured_bridge, configured_start
          FROM knowledge.native_configuration_revisions
          WHERE configuration_id = NEW.configuration_id
            AND revision = NEW.configuration_revision;
          IF configured_bridge IS DISTINCT FROM NEW.bridge_id
             OR configured_start IS DISTINCT FROM NEW.start_at THEN
            RAISE EXCEPTION 'native run does not freeze its exact configuration inputs'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_run_requires_exact_frozen_inputs
          BEFORE INSERT ON knowledge.native_sync_runs
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_run_snapshot_is_exact();

        CREATE FUNCTION knowledge.native_job_matches_frozen_run() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE run_configuration text; run_revision integer; bucket_kind text;
        BEGIN
          IF NEW.run_id IS NULL THEN
            RAISE EXCEPTION 'new native job requires an exact frozen run'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          SELECT configuration_id, configuration_revision
            INTO run_configuration, run_revision
          FROM knowledge.native_sync_runs WHERE run_id = NEW.run_id;
          SELECT source_kind INTO bucket_kind
          FROM knowledge.native_source_buckets WHERE bucket_id = NEW.bucket_id;
          IF run_configuration IS DISTINCT FROM NEW.configuration_id
             OR run_revision IS DISTINCT FROM NEW.configuration_revision THEN
            RAISE EXCEPTION 'native job is outside its frozen run'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          IF (bucket_kind = 'contacts') <> (NEW.read_mode = 'current_inventory') THEN
            RAISE EXCEPTION 'native job read mode contradicts its source kind'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_job_requires_exact_frozen_run
          BEFORE INSERT OR UPDATE ON knowledge.native_sync_jobs
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_job_matches_frozen_run();

        CREATE FUNCTION knowledge.native_checkpoint_follows_admission() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE job_bucket text; authority_bucket text; consumed timestamptz;
        BEGIN
          IF NEW.job_id IS NULL OR NEW.admission_authority_id IS NULL THEN
            RAISE EXCEPTION 'new native checkpoint requires an admitted page binding'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          SELECT bucket_id INTO job_bucket
          FROM knowledge.native_sync_jobs WHERE job_id = NEW.job_id;
          SELECT bucket_id, consumed_at INTO authority_bucket, consumed
          FROM knowledge.native_admission_authorities
          WHERE authority_id = NEW.admission_authority_id;
          IF job_bucket IS DISTINCT FROM NEW.bucket_id
             OR authority_bucket IS DISTINCT FROM NEW.bucket_id
             OR consumed IS NULL THEN
            RAISE EXCEPTION 'native checkpoint requires an admitted page in its exact job bucket'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_checkpoint_requires_admitted_page
          BEFORE INSERT ON knowledge.native_checkpoints
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_checkpoint_follows_admission();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER native_checkpoint_requires_admitted_page ON knowledge.native_checkpoints;
        DROP FUNCTION knowledge.native_checkpoint_follows_admission();
        DROP TRIGGER native_job_requires_exact_frozen_run ON knowledge.native_sync_jobs;
        DROP FUNCTION knowledge.native_job_matches_frozen_run();
        DROP TRIGGER native_run_requires_exact_frozen_inputs ON knowledge.native_sync_runs;
        DROP FUNCTION knowledge.native_run_snapshot_is_exact();

        ALTER TABLE knowledge.native_checkpoints
          DROP CONSTRAINT one_checkpoint_per_native_admission,
          DROP COLUMN item_count,
          DROP COLUMN terminal,
          DROP COLUMN admission_authority_id,
          DROP COLUMN job_id;
        ALTER TABLE knowledge.native_sync_jobs
          DROP CONSTRAINT native_sync_job_read_mode_is_known,
          DROP COLUMN read_mode,
          DROP COLUMN run_id;
        ALTER TABLE knowledge.native_sync_runs
          DROP CONSTRAINT native_run_state_is_known,
          ADD CONSTRAINT native_sync_runs_state_check
            CHECK (state IN ('failed', 'partial', 'succeeded')),
          DROP CONSTRAINT native_run_adapter_identity_is_bounded,
          DROP CONSTRAINT native_sync_runs_bridge_id_fkey,
          DROP COLUMN adapter_identity,
          DROP COLUMN bridge_id;
        """
    )
