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

        ALTER TABLE knowledge.native_admission_authorities
          ADD COLUMN checkpoint_job_id text
            REFERENCES knowledge.native_sync_jobs(job_id),
          ADD COLUMN checkpoint_run_id text
            REFERENCES knowledge.native_sync_runs(run_id),
          ADD COLUMN checkpoint_cursor_private text,
          ADD COLUMN checkpoint_cursor_digest text,
          ADD COLUMN checkpoint_terminal boolean,
          ADD COLUMN checkpoint_item_count integer,
          ADD CONSTRAINT native_authority_checkpoint_binding_is_complete CHECK (
            (checkpoint_job_id IS NULL AND checkpoint_run_id IS NULL
              AND checkpoint_cursor_private IS NULL AND checkpoint_cursor_digest IS NULL
              AND checkpoint_terminal IS NULL AND checkpoint_item_count IS NULL)
            OR
            (checkpoint_job_id IS NOT NULL AND checkpoint_run_id IS NOT NULL
              AND checkpoint_cursor_private IS NOT NULL
              AND checkpoint_cursor_digest IS NOT NULL
              AND checkpoint_terminal IS NOT NULL AND checkpoint_item_count IS NOT NULL)
          ),
          ADD CONSTRAINT native_authority_checkpoint_cursor_is_bounded
            CHECK (checkpoint_cursor_private IS NULL
              OR length(checkpoint_cursor_private) BETWEEN 1 AND 512),
          ADD CONSTRAINT native_authority_checkpoint_digest_is_sha256
            CHECK (checkpoint_cursor_digest IS NULL
              OR checkpoint_cursor_digest ~ '^[0-9a-f]{64}$'),
          ADD CONSTRAINT native_authority_checkpoint_terminal_matches_cursor CHECK (
            checkpoint_terminal IS NULL
            OR (checkpoint_terminal
              AND checkpoint_cursor_private = '__my_pa_native_baseline_complete__')
            OR (NOT checkpoint_terminal
              AND checkpoint_cursor_private <> '__my_pa_native_baseline_complete__')
          ),
          ADD CONSTRAINT native_authority_checkpoint_count_is_page_bounded
            CHECK (checkpoint_item_count IS NULL OR checkpoint_item_count BETWEEN 0 AND 100);

        CREATE FUNCTION knowledge.native_authority_consumption_is_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.consumed_at IS NOT NULL THEN
            RAISE EXCEPTION 'consumed native admission authority is immutable'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          IF NEW.authority_id IS DISTINCT FROM OLD.authority_id
             OR NEW.audit_id IS DISTINCT FROM OLD.audit_id
             OR NEW.configuration_id IS DISTINCT FROM OLD.configuration_id
             OR NEW.configuration_revision IS DISTINCT FROM OLD.configuration_revision
             OR NEW.bridge_id IS DISTINCT FROM OLD.bridge_id
             OR NEW.bucket_id IS DISTINCT FROM OLD.bucket_id
             OR NEW.source_id IS DISTINCT FROM OLD.source_id
             OR NEW.host_instance_id IS DISTINCT FROM OLD.host_instance_id
             OR NEW.envelope_id IS DISTINCT FROM OLD.envelope_id
             OR NEW.request_id IS DISTINCT FROM OLD.request_id
             OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
             OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
             OR NEW.consumed_at IS NULL
             OR NEW.admission_sha256 IS NULL THEN
            RAISE EXCEPTION 'native admission authority permits only one exact consumption'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_authority_allows_one_exact_consumption
          BEFORE UPDATE ON knowledge.native_admission_authorities
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_authority_consumption_is_immutable();

        ALTER TABLE knowledge.native_checkpoints
          ADD COLUMN job_id text REFERENCES knowledge.native_sync_jobs(job_id),
          ADD COLUMN admission_authority_id text
            REFERENCES knowledge.native_admission_authorities(authority_id),
          ADD COLUMN terminal boolean NOT NULL DEFAULT false,
          ADD COLUMN item_count integer NOT NULL DEFAULT 0 CHECK (item_count >= 0),
          ADD CONSTRAINT one_checkpoint_per_native_admission UNIQUE (admission_authority_id),
          ADD CONSTRAINT native_checkpoint_item_count_is_page_bounded
            CHECK (item_count BETWEEN 0 AND 100);
        ALTER TABLE knowledge.native_checkpoints
          ALTER COLUMN terminal DROP DEFAULT,
          ALTER COLUMN item_count DROP DEFAULT;

        CREATE FUNCTION knowledge.native_run_snapshot_is_exact() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          configured_bridge text;
          configured_start timestamptz;
          prior_start timestamptz;
          expected_kind text;
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
          IF EXISTS (
            SELECT 1 FROM knowledge.native_sync_runs
            WHERE configuration_id = NEW.configuration_id
              AND configuration_revision = NEW.configuration_revision
              AND idempotency_key = NEW.idempotency_key
          ) THEN
            RETURN NEW;
          END IF;
          SELECT start_at INTO prior_start
          FROM knowledge.native_configuration_revisions
          WHERE configuration_id = NEW.configuration_id
            AND revision = NEW.configuration_revision - 1;
          expected_kind := CASE
            WHEN prior_start IS NOT NULL AND configured_start < prior_start THEN 'backfill'
            ELSE 'baseline'
          END;
          IF NEW.run_kind IN ('baseline', 'backfill')
             AND NEW.run_kind IS DISTINCT FROM expected_kind THEN
            RAISE EXCEPTION 'native baseline run kind contradicts its immutable start history'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_run_requires_exact_frozen_inputs
          BEFORE INSERT ON knowledge.native_sync_runs
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_run_snapshot_is_exact();

        CREATE FUNCTION knowledge.native_job_matches_frozen_run() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          run_configuration text;
          run_revision integer;
          run_kind text;
          run_start timestamptz;
          run_cutoff timestamptz;
          run_horizon timestamptz;
          prior_start timestamptz;
          bucket_kind text;
          expected_end timestamptz;
        BEGIN
          IF TG_OP = 'UPDATE' AND (
            NEW.run_id IS DISTINCT FROM OLD.run_id
            OR NEW.configuration_id IS DISTINCT FROM OLD.configuration_id
            OR NEW.configuration_revision IS DISTINCT FROM OLD.configuration_revision
            OR NEW.bucket_id IS DISTINCT FROM OLD.bucket_id
            OR NEW.range_start IS DISTINCT FROM OLD.range_start
            OR NEW.range_end IS DISTINCT FROM OLD.range_end
            OR NEW.read_mode IS DISTINCT FROM OLD.read_mode
          ) THEN
            RAISE EXCEPTION 'native job frozen scope is immutable'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          IF NEW.run_id IS NULL THEN
            IF TG_OP = 'UPDATE' AND OLD.run_id IS NULL THEN
              RETURN NEW;
            END IF;
            RAISE EXCEPTION 'new native job requires an exact frozen run'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          SELECT configuration_id, configuration_revision, native_sync_runs.run_kind,
                 start_at, cutoff_at, calendar_horizon_at
            INTO run_configuration, run_revision, run_kind,
                 run_start, run_cutoff, run_horizon
          FROM knowledge.native_sync_runs WHERE run_id = NEW.run_id;
          SELECT source_kind INTO bucket_kind
          FROM knowledge.native_source_buckets WHERE bucket_id = NEW.bucket_id;
          IF run_configuration IS DISTINCT FROM NEW.configuration_id
             OR run_revision IS DISTINCT FROM NEW.configuration_revision THEN
            RAISE EXCEPTION 'native job is outside its frozen run'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          IF run_kind NOT IN ('baseline', 'backfill') THEN
            RAISE EXCEPTION 'native baseline job requires a baseline or backfill run'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          IF (bucket_kind = 'contacts') <> (NEW.read_mode = 'current_inventory') THEN
            RAISE EXCEPTION 'native job read mode contradicts its source kind'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          IF bucket_kind = 'contacts' THEN
            IF NEW.range_start IS DISTINCT FROM run_cutoff
               OR NEW.range_end IS DISTINCT FROM run_cutoff THEN
              RAISE EXCEPTION 'native contacts job is outside its frozen inventory sentinel'
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
          ELSE
            expected_end := CASE
              WHEN bucket_kind = 'calendar' THEN run_horizon
              ELSE run_cutoff
            END;
            IF run_kind = 'backfill' THEN
              SELECT start_at INTO prior_start
              FROM knowledge.native_configuration_revisions
              WHERE configuration_id = run_configuration
                AND revision = run_revision - 1;
              IF prior_start IS NULL OR run_start >= prior_start THEN
                RAISE EXCEPTION 'native backfill run lacks an earlier-start delta'
                  USING ERRCODE = 'integrity_constraint_violation';
              END IF;
              expected_end := prior_start - interval '1 millisecond';
            END IF;
            IF NEW.range_start IS DISTINCT FROM run_start
               OR NEW.range_end IS DISTINCT FROM expected_end THEN
              RAISE EXCEPTION 'native job range is outside its exact frozen run window'
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_job_requires_exact_frozen_run
          BEFORE INSERT OR UPDATE ON knowledge.native_sync_jobs
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_job_matches_frozen_run();

        CREATE FUNCTION knowledge.native_checkpoint_follows_admission() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          job_bucket text;
          job_run text;
          job_configuration text;
          job_revision integer;
          authority_bucket text;
          authority_run text;
          authority_job text;
          authority_configuration text;
          authority_revision integer;
          authority_cursor text;
          authority_digest text;
          authority_terminal boolean;
          authority_count integer;
          consumed timestamptz;
        BEGIN
          IF NEW.job_id IS NULL OR NEW.admission_authority_id IS NULL THEN
            RAISE EXCEPTION 'new native checkpoint requires an admitted page binding'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          SELECT bucket_id, run_id, configuration_id, configuration_revision
            INTO job_bucket, job_run, job_configuration, job_revision
          FROM knowledge.native_sync_jobs WHERE job_id = NEW.job_id;
          SELECT bucket_id, consumed_at, checkpoint_run_id, checkpoint_job_id,
                 configuration_id, configuration_revision,
                 checkpoint_cursor_private, checkpoint_cursor_digest,
                 checkpoint_terminal, checkpoint_item_count
            INTO authority_bucket, consumed, authority_run, authority_job,
                 authority_configuration, authority_revision,
                 authority_cursor, authority_digest,
                 authority_terminal, authority_count
          FROM knowledge.native_admission_authorities
          WHERE authority_id = NEW.admission_authority_id;
          IF job_bucket IS DISTINCT FROM NEW.bucket_id
             OR authority_bucket IS DISTINCT FROM NEW.bucket_id
             OR job_run IS DISTINCT FROM authority_run
             OR NEW.job_id IS DISTINCT FROM authority_job
             OR job_configuration IS DISTINCT FROM authority_configuration
             OR job_revision IS DISTINCT FROM authority_revision
             OR NEW.cursor_private IS DISTINCT FROM authority_cursor
             OR NEW.cursor_digest IS DISTINCT FROM authority_digest
             OR NEW.terminal IS DISTINCT FROM authority_terminal
             OR NEW.item_count IS DISTINCT FROM authority_count
             OR consumed IS NULL THEN
            RAISE EXCEPTION 'native checkpoint requires its exact admitted page and frozen job'
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
        DROP TRIGGER native_authority_allows_one_exact_consumption
          ON knowledge.native_admission_authorities;
        DROP FUNCTION knowledge.native_authority_consumption_is_immutable();

        ALTER TABLE knowledge.native_checkpoints
          DROP CONSTRAINT one_checkpoint_per_native_admission,
          DROP CONSTRAINT native_checkpoint_item_count_is_page_bounded,
          DROP COLUMN item_count,
          DROP COLUMN terminal,
          DROP COLUMN admission_authority_id,
          DROP COLUMN job_id;
        ALTER TABLE knowledge.native_admission_authorities
          DROP CONSTRAINT native_authority_checkpoint_count_is_page_bounded,
          DROP CONSTRAINT native_authority_checkpoint_terminal_matches_cursor,
          DROP CONSTRAINT native_authority_checkpoint_digest_is_sha256,
          DROP CONSTRAINT native_authority_checkpoint_cursor_is_bounded,
          DROP CONSTRAINT native_authority_checkpoint_binding_is_complete,
          DROP COLUMN checkpoint_item_count,
          DROP COLUMN checkpoint_terminal,
          DROP COLUMN checkpoint_cursor_digest,
          DROP COLUMN checkpoint_cursor_private,
          DROP COLUMN checkpoint_run_id,
          DROP COLUMN checkpoint_job_id;
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
