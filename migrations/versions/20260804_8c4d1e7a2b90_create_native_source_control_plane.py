"""Create the provider-neutral native-source persistence and control plane.

Revision ID: 8c4d1e7a2b90
Revises: 7f2a9d6c4e18
Create Date: 2026-08-04

The SQL is frozen in this revision rather than derived from live domain enums.
It stores source-authoritative evidence, exact configuration and run receipts,
monotonic checkpoints, and simulation-only watcher evidence.  The live gate can
record denial but this revision creates no live activation writer or credential
path.
"""

from __future__ import annotations

from alembic import op

revision: str = "8c4d1e7a2b90"
down_revision: str | None = "7f2a9d6c4e18"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.sources DROP CONSTRAINT provider_kind_is_known;
        ALTER TABLE knowledge.sources ADD CONSTRAINT provider_kind_is_known
          CHECK (provider_kind IN ('apple_calendar', 'apple_contacts', 'apple_mail', 'fixture'));
        ALTER TABLE knowledge.source_objects DROP CONSTRAINT kind_is_known;
        ALTER TABLE knowledge.source_objects ADD CONSTRAINT kind_is_known
          CHECK (kind IN ('calendar_event', 'contact', 'container', 'file', 'mail_message'));

        CREATE TABLE knowledge.source_version_evidence (
          evidence_id text PRIMARY KEY CHECK (evidence_id ~ '^sevd_[A-Za-z0-9]{8,64}$'),
          version_id text NOT NULL REFERENCES knowledge.source_object_versions(version_id),
          evidence_kind text NOT NULL
            CHECK (evidence_kind IN ('calendar_event', 'contact', 'mail_message')),
          payload bytea NOT NULL,
          payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
          byte_count bigint NOT NULL CHECK (byte_count = octet_length(payload)),
          recorded_at timestamptz NOT NULL,
          CONSTRAINT source_version_evidence_is_idempotent
            UNIQUE (version_id, evidence_kind, payload_sha256)
        );
        CREATE TABLE knowledge.native_bridges (
          bridge_id text PRIMARY KEY CHECK (bridge_id ~ '^nbrg_[A-Za-z0-9]{8,64}$'),
          protocol_version text NOT NULL,
          label text NOT NULL,
          created_at timestamptz NOT NULL,
          CONSTRAINT a_native_bridge_identity_is_stable UNIQUE (protocol_version, label)
        );
        CREATE TABLE knowledge.native_bridge_observations (
          observation_id text PRIMARY KEY CHECK (observation_id ~ '^sobs_[A-Za-z0-9]{8,64}$'),
          bridge_id text NOT NULL REFERENCES knowledge.native_bridges(bridge_id),
          available boolean NOT NULL,
          protocol_version text NOT NULL,
          observed_at timestamptz NOT NULL
        );
        CREATE TABLE knowledge.native_source_accounts (
          account_id text PRIMARY KEY CHECK (account_id ~ '^nacct_[A-Za-z0-9]{8,64}$'),
          bridge_id text NOT NULL REFERENCES knowledge.native_bridges(bridge_id),
          source_id text NOT NULL REFERENCES knowledge.sources(source_id),
          source_kind text NOT NULL CHECK (source_kind IN ('calendar', 'contacts', 'mail')),
          label text NOT NULL,
          private_locator text NOT NULL,
          first_observed_at timestamptz NOT NULL,
          CONSTRAINT native_account_locator_is_issued_once
            UNIQUE (bridge_id, source_kind, private_locator)
        );
        CREATE TABLE knowledge.native_source_buckets (
          bucket_id text PRIMARY KEY CHECK (bucket_id ~ '^nbkt_[A-Za-z0-9]{8,64}$'),
          account_id text NOT NULL REFERENCES knowledge.native_source_accounts(account_id),
          parent_bucket_id text REFERENCES knowledge.native_source_buckets(bucket_id),
          source_kind text NOT NULL CHECK (source_kind IN ('calendar', 'contacts', 'mail')),
          label text NOT NULL,
          private_locator text NOT NULL,
          selectable boolean NOT NULL,
          first_observed_at timestamptz NOT NULL,
          CONSTRAINT a_native_bucket_cannot_parent_itself
            CHECK (parent_bucket_id IS NULL OR parent_bucket_id <> bucket_id),
          CONSTRAINT native_bucket_locator_is_issued_once UNIQUE (account_id, private_locator)
        );
        CREATE TABLE knowledge.native_discovery_snapshots (
          discovery_id text PRIMARY KEY CHECK (discovery_id ~ '^ndisc_[A-Za-z0-9]{8,64}$'),
          bridge_id text NOT NULL REFERENCES knowledge.native_bridges(bridge_id),
          snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
          observed_at timestamptz NOT NULL,
          CONSTRAINT native_discovery_snapshot_is_idempotent
            UNIQUE (bridge_id, snapshot_sha256)
        );
        CREATE TABLE knowledge.native_configuration_revisions (
          configuration_id text NOT NULL CHECK (configuration_id ~ '^ncfg_[A-Za-z0-9]{8,64}$'),
          revision integer NOT NULL CHECK (revision >= 1),
          bridge_id text NOT NULL REFERENCES knowledge.native_bridges(bridge_id),
          timezone_name text NOT NULL,
          start_date date NOT NULL,
          start_at timestamptz NOT NULL,
          cutoff_at timestamptz NOT NULL,
          calendar_horizon_at timestamptz NOT NULL,
          selection_sha256 text NOT NULL,
          created_at timestamptz NOT NULL,
          PRIMARY KEY (configuration_id, revision),
          CONSTRAINT native_configuration_range_is_ordered CHECK (start_at <= cutoff_at),
          CONSTRAINT native_calendar_horizon_is_ninety_days
            CHECK (calendar_horizon_at = cutoff_at + interval '90 days'),
          CONSTRAINT native_configuration_selection_digest_is_sha256
            CHECK (selection_sha256 ~ '^[0-9a-f]{64}$')
        );
        CREATE TABLE knowledge.native_configuration_buckets (
          configuration_id text NOT NULL,
          revision integer NOT NULL,
          bucket_id text NOT NULL REFERENCES knowledge.native_source_buckets(bucket_id),
          PRIMARY KEY (configuration_id, revision, bucket_id),
          FOREIGN KEY (configuration_id, revision)
            REFERENCES knowledge.native_configuration_revisions(configuration_id, revision)
        );
        CREATE TABLE knowledge.native_sync_runs (
          run_id text PRIMARY KEY CHECK (run_id ~ '^nrun_[A-Za-z0-9]{8,64}$'),
          configuration_id text NOT NULL,
          configuration_revision integer NOT NULL,
          run_kind text NOT NULL CHECK (run_kind IN ('backfill', 'baseline', 'reconciliation')),
          state text NOT NULL CHECK (state IN ('failed', 'partial', 'succeeded')),
          start_at timestamptz NOT NULL,
          cutoff_at timestamptz NOT NULL,
          calendar_horizon_at timestamptz NOT NULL,
          idempotency_key text NOT NULL,
          recorded_at timestamptz NOT NULL,
          FOREIGN KEY (configuration_id, configuration_revision)
            REFERENCES knowledge.native_configuration_revisions(configuration_id, revision),
          CONSTRAINT native_run_range_is_ordered CHECK (start_at <= cutoff_at),
          CONSTRAINT native_run_calendar_horizon_is_ninety_days
            CHECK (calendar_horizon_at = cutoff_at + interval '90 days'),
          CONSTRAINT native_sync_run_idempotency_is_scoped
            UNIQUE (configuration_id, configuration_revision, idempotency_key)
        );
        CREATE TABLE knowledge.native_bucket_runs (
          bucket_run_id text PRIMARY KEY CHECK (bucket_run_id ~ '^nbrun_[A-Za-z0-9]{8,64}$'),
          run_id text NOT NULL REFERENCES knowledge.native_sync_runs(run_id),
          bucket_id text NOT NULL REFERENCES knowledge.native_source_buckets(bucket_id),
          state text NOT NULL CHECK (state IN ('failed', 'partial', 'succeeded')),
          item_count bigint NOT NULL CHECK (item_count >= 0),
          recorded_at timestamptz NOT NULL,
          CONSTRAINT one_native_bucket_receipt_per_run UNIQUE (run_id, bucket_id)
        );
        CREATE TABLE knowledge.native_sync_jobs (
          job_id text PRIMARY KEY CHECK (job_id ~ '^njob_[A-Za-z0-9]{8,64}$'),
          configuration_id text NOT NULL,
          configuration_revision integer NOT NULL,
          bucket_id text NOT NULL REFERENCES knowledge.native_source_buckets(bucket_id),
          range_start timestamptz NOT NULL,
          range_end timestamptz NOT NULL,
          state text NOT NULL CHECK (state IN ('failed', 'queued', 'running', 'succeeded')),
          lease_owner text,
          lease_expires_at timestamptz,
          idempotency_key text NOT NULL,
          created_at timestamptz NOT NULL,
          updated_at timestamptz NOT NULL,
          FOREIGN KEY (configuration_id, configuration_revision)
            REFERENCES knowledge.native_configuration_revisions(configuration_id, revision),
          CONSTRAINT native_job_requires_selected_bucket
            FOREIGN KEY (configuration_id, configuration_revision, bucket_id)
            REFERENCES knowledge.native_configuration_buckets
              (configuration_id, revision, bucket_id),
          CONSTRAINT native_sync_job_range_is_ordered CHECK (range_start <= range_end),
          CONSTRAINT a_native_job_is_running_exactly_while_leased CHECK (
            (state = 'running') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
          ),
          CONSTRAINT native_sync_job_idempotency_is_scoped
            UNIQUE (configuration_id, configuration_revision, bucket_id, idempotency_key)
        );
        CREATE UNIQUE INDEX one_active_native_lease_per_bucket_range
          ON knowledge.native_sync_jobs (bucket_id, range_start, range_end)
          WHERE state = 'running';
        CREATE TABLE knowledge.native_checkpoints (
          checkpoint_id text PRIMARY KEY CHECK (checkpoint_id ~ '^ncp_[A-Za-z0-9]{8,64}$'),
          bucket_id text NOT NULL REFERENCES knowledge.native_source_buckets(bucket_id),
          sequence bigint NOT NULL CHECK (sequence >= 1),
          previous_checkpoint_id text UNIQUE REFERENCES knowledge.native_checkpoints(checkpoint_id),
          cursor_private text NOT NULL,
          cursor_digest text NOT NULL CHECK (cursor_digest ~ '^[0-9a-f]{64}$'),
          recorded_at timestamptz NOT NULL,
          CONSTRAINT native_checkpoint_predecessor_matches_sequence
            CHECK ((sequence = 1) = (previous_checkpoint_id IS NULL)),
          CONSTRAINT native_checkpoint_sequence_is_monotonic UNIQUE (bucket_id, sequence)
        );
        CREATE TABLE knowledge.source_observations (
          observation_id text PRIMARY KEY CHECK (observation_id ~ '^sobs_[A-Za-z0-9]{8,64}$'),
          source_object_id text NOT NULL REFERENCES knowledge.source_objects(source_object_id),
          version_id text NOT NULL REFERENCES knowledge.source_object_versions(version_id),
          bucket_id text NOT NULL REFERENCES knowledge.native_source_buckets(bucket_id),
          observed_at timestamptz NOT NULL,
          CONSTRAINT source_version_observation_is_idempotent UNIQUE (version_id, bucket_id)
        );
        CREATE TABLE knowledge.source_memberships (
          membership_id text PRIMARY KEY CHECK (membership_id ~ '^smem_[A-Za-z0-9]{8,64}$'),
          parent_bucket_id text NOT NULL REFERENCES knowledge.native_source_buckets(bucket_id),
          source_object_id text NOT NULL REFERENCES knowledge.source_objects(source_object_id),
          version_id text NOT NULL REFERENCES knowledge.source_object_versions(version_id),
          observed_at timestamptz NOT NULL,
          CONSTRAINT source_membership_version_is_idempotent
            UNIQUE (parent_bucket_id, version_id)
        );
        CREATE TABLE knowledge.native_watcher_simulations (
          simulation_id text NOT NULL CHECK (simulation_id ~ '^nsim_[A-Za-z0-9]{8,64}$'),
          sequence integer NOT NULL CHECK (sequence >= 1),
          bucket_id text NOT NULL REFERENCES knowledge.native_source_buckets(bucket_id),
          state text NOT NULL CHECK (state IN (
            'simulation_pending', 'simulating', 'simulation_complete', 'simulation_failed'
          )),
          recorded_at timestamptz NOT NULL,
          PRIMARY KEY (simulation_id, sequence)
        );
        CREATE TABLE knowledge.native_simulation_receipts (
          receipt_id text PRIMARY KEY CHECK (receipt_id ~ '^nsimr_[A-Za-z0-9]{8,64}$'),
          simulation_id text NOT NULL,
          simulation_sequence integer NOT NULL,
          checkpoint_id text NOT NULL REFERENCES knowledge.native_checkpoints(checkpoint_id),
          terminal_state text NOT NULL,
          recorded_at timestamptz NOT NULL,
          FOREIGN KEY (simulation_id, simulation_sequence)
            REFERENCES knowledge.native_watcher_simulations(simulation_id, sequence),
          CONSTRAINT native_simulation_receipt_state_is_terminal
            CHECK (terminal_state IN ('simulation_complete', 'simulation_failed')),
          CONSTRAINT one_receipt_per_native_simulation UNIQUE (simulation_id)
        );
        CREATE TABLE knowledge.native_live_activation_gates (
          gate_id text PRIMARY KEY CHECK (gate_id ~ '^nlg_[A-Za-z0-9]{8,64}$'),
          bucket_id text NOT NULL REFERENCES knowledge.native_source_buckets(bucket_id),
          state text NOT NULL CHECK (
            state IN ('attestation_required', 'blocked', 'not_authorized')
          ),
          reason_code text NOT NULL,
          recorded_at timestamptz NOT NULL,
          CONSTRAINT one_native_live_gate_per_bucket UNIQUE (bucket_id)
        );
        """
    )
    op.execute(
        """
        CREATE FUNCTION knowledge.reject_native_receipt_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'native control-plane receipts are append-only'
            USING ERRCODE = 'restrict_violation';
        END; $$;

        CREATE FUNCTION knowledge.native_checkpoint_follows_predecessor() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE prior_id text; prior_sequence bigint;
        BEGIN
          SELECT checkpoint_id, sequence INTO prior_id, prior_sequence
          FROM knowledge.native_checkpoints
          WHERE bucket_id = NEW.bucket_id
          ORDER BY sequence DESC LIMIT 1;
          IF prior_id IS NULL THEN
            IF NEW.sequence <> 1 OR NEW.previous_checkpoint_id IS NOT NULL THEN
              RAISE EXCEPTION 'first checkpoint must start the chain'
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
          ELSIF NEW.sequence <> prior_sequence + 1
             OR NEW.previous_checkpoint_id IS DISTINCT FROM prior_id THEN
            RAISE EXCEPTION 'checkpoint must extend the current chain'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_checkpoint_requires_current_predecessor
          BEFORE INSERT ON knowledge.native_checkpoints
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_checkpoint_follows_predecessor();

        CREATE FUNCTION knowledge.native_simulation_follows_closed_state_machine() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE prior_state text; prior_sequence integer;
        BEGIN
          SELECT state, sequence INTO prior_state, prior_sequence
          FROM knowledge.native_watcher_simulations
          WHERE simulation_id = NEW.simulation_id
          ORDER BY sequence DESC LIMIT 1;
          IF prior_state IS NULL THEN
            IF NEW.sequence <> 1 OR NEW.state <> 'simulation_pending' THEN
              RAISE EXCEPTION 'simulation must begin pending'
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
          ELSIF NEW.sequence <> prior_sequence + 1 OR NOT (
            (prior_state = 'simulation_pending' AND NEW.state = 'simulating') OR
            (prior_state = 'simulating' AND NEW.state IN (
              'simulation_complete', 'simulation_failed'
            ))
          ) THEN
            RAISE EXCEPTION 'simulation transition is not permitted'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_simulation_requires_closed_transition
          BEFORE INSERT ON knowledge.native_watcher_simulations
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_simulation_follows_closed_state_machine();

        CREATE FUNCTION knowledge.native_configuration_has_bucket() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          expected_digest text;
          actual_digest text;
          configuration_bridge text;
        BEGIN
          SELECT selection_sha256, bridge_id
            INTO expected_digest, configuration_bridge
          FROM knowledge.native_configuration_revisions
          WHERE configuration_id = NEW.configuration_id AND revision = NEW.revision;
          IF NOT EXISTS (
            SELECT 1 FROM knowledge.native_configuration_buckets b
            WHERE b.configuration_id = NEW.configuration_id AND b.revision = NEW.revision
          ) THEN
            RAISE EXCEPTION 'native configuration requires an exact nonempty bucket selection'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          SELECT encode(sha256(convert_to(
            string_agg(bucket_id, E'\n' ORDER BY bucket_id COLLATE "C"), 'UTF8'
          )), 'hex') INTO actual_digest
          FROM knowledge.native_configuration_buckets
          WHERE configuration_id = NEW.configuration_id AND revision = NEW.revision;
          IF actual_digest IS DISTINCT FROM expected_digest THEN
            RAISE EXCEPTION 'native configuration selection does not match its immutable seal'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM knowledge.native_configuration_buckets selected
            JOIN knowledge.native_source_buckets bucket
              ON bucket.bucket_id = selected.bucket_id
            JOIN knowledge.native_source_accounts account
              ON account.account_id = bucket.account_id
            WHERE selected.configuration_id = NEW.configuration_id
              AND selected.revision = NEW.revision
              AND (account.bridge_id <> configuration_bridge OR NOT bucket.selectable)
          ) THEN
            RAISE EXCEPTION 'native configuration selection is outside its bridge scope'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NULL;
        END; $$;
        CREATE CONSTRAINT TRIGGER native_configuration_requires_bucket
          AFTER INSERT ON knowledge.native_configuration_revisions
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_configuration_has_bucket();
        CREATE CONSTRAINT TRIGGER native_configuration_bucket_matches_seal
          AFTER INSERT ON knowledge.native_configuration_buckets
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_configuration_has_bucket();

        CREATE FUNCTION knowledge.native_source_binding_is_consistent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          version_object_id text;
          object_source_id text;
          bucket_source_id text;
          bucket_kind text;
        BEGIN
          SELECT version.source_object_id, object.source_id
            INTO version_object_id, object_source_id
          FROM knowledge.source_object_versions version
          JOIN knowledge.source_objects object
            ON object.source_object_id = version.source_object_id
          WHERE version.version_id = NEW.version_id;
          IF version_object_id IS DISTINCT FROM NEW.source_object_id THEN
            RAISE EXCEPTION 'source observation version does not name its object'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          IF TG_TABLE_NAME = 'source_memberships' THEN
            SELECT bucket.source_kind, account.source_id
              INTO bucket_kind, bucket_source_id
            FROM knowledge.native_source_buckets bucket
            JOIN knowledge.native_source_accounts account
              ON account.account_id = bucket.account_id
            WHERE bucket.bucket_id = NEW.parent_bucket_id;
            IF bucket_kind <> 'contacts' THEN
              RAISE EXCEPTION 'source membership requires a contacts container'
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
          ELSE
            SELECT account.source_id INTO bucket_source_id
            FROM knowledge.native_source_buckets bucket
            JOIN knowledge.native_source_accounts account
              ON account.account_id = bucket.account_id
            WHERE bucket.bucket_id = NEW.bucket_id;
          END IF;
          IF object_source_id IS DISTINCT FROM bucket_source_id THEN
            RAISE EXCEPTION 'source evidence is outside the selected account scope'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER source_observation_requires_matching_version
          BEFORE INSERT ON knowledge.source_observations
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_source_binding_is_consistent();
        CREATE TRIGGER source_membership_requires_matching_contact_version
          BEFORE INSERT ON knowledge.source_memberships
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_source_binding_is_consistent();

        CREATE FUNCTION knowledge.native_evidence_kind_matches_object() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE object_kind text;
        BEGIN
          SELECT object.kind INTO object_kind
          FROM knowledge.source_object_versions version
          JOIN knowledge.source_objects object
            ON object.source_object_id = version.source_object_id
          WHERE version.version_id = NEW.version_id;
          IF object_kind IS DISTINCT FROM NEW.evidence_kind THEN
            RAISE EXCEPTION 'source evidence kind does not match its authoritative object'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER source_evidence_requires_matching_object_kind
          BEFORE INSERT ON knowledge.source_version_evidence
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_evidence_kind_matches_object();

        CREATE FUNCTION knowledge.native_account_kind_matches_provider() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE provider_kind text;
        BEGIN
          IF TG_OP = 'UPDATE' AND (
            OLD.source_id IS DISTINCT FROM NEW.source_id
            OR OLD.source_kind IS DISTINCT FROM NEW.source_kind
          ) THEN
            RAISE EXCEPTION 'native account authority scope is immutable'
              USING ERRCODE = 'restrict_violation';
          END IF;
          SELECT source.provider_kind INTO provider_kind
          FROM knowledge.sources source WHERE source.source_id = NEW.source_id;
          IF provider_kind IS DISTINCT FROM 'apple_' || NEW.source_kind THEN
            RAISE EXCEPTION 'native account kind does not match its authoritative source'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_account_requires_matching_provider
          BEFORE INSERT OR UPDATE OF source_id, source_kind
          ON knowledge.native_source_accounts
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_account_kind_matches_provider();

        CREATE FUNCTION knowledge.native_bucket_scope_is_consistent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE account_kind text; parent_account_id text; parent_kind text;
        BEGIN
          IF TG_OP = 'UPDATE' AND (
            OLD.account_id IS DISTINCT FROM NEW.account_id
            OR OLD.parent_bucket_id IS DISTINCT FROM NEW.parent_bucket_id
            OR OLD.source_kind IS DISTINCT FROM NEW.source_kind
          ) THEN
            RAISE EXCEPTION 'native bucket authority scope is immutable'
              USING ERRCODE = 'restrict_violation';
          END IF;
          SELECT source_kind INTO account_kind
          FROM knowledge.native_source_accounts WHERE account_id = NEW.account_id;
          IF account_kind IS DISTINCT FROM NEW.source_kind THEN
            RAISE EXCEPTION 'native bucket kind does not match its account'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          IF NEW.parent_bucket_id IS NOT NULL THEN
            SELECT account_id, source_kind INTO parent_account_id, parent_kind
            FROM knowledge.native_source_buckets WHERE bucket_id = NEW.parent_bucket_id;
            IF parent_account_id IS DISTINCT FROM NEW.account_id
               OR parent_kind IS DISTINCT FROM NEW.source_kind THEN
              RAISE EXCEPTION 'native child bucket is outside its parent scope'
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_bucket_requires_account_and_parent_scope
          BEFORE INSERT OR UPDATE OF account_id, parent_bucket_id, source_kind
          ON knowledge.native_source_buckets
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_bucket_scope_is_consistent();

        CREATE FUNCTION knowledge.native_bucket_run_is_selected() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM knowledge.native_sync_runs run
            JOIN knowledge.native_configuration_buckets selected
              ON selected.configuration_id = run.configuration_id
             AND selected.revision = run.configuration_revision
             AND selected.bucket_id = NEW.bucket_id
            WHERE run.run_id = NEW.run_id
          ) THEN
            RAISE EXCEPTION 'native bucket run is outside its exact configuration selection'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_bucket_run_requires_selected_bucket
          BEFORE INSERT ON knowledge.native_bucket_runs
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_bucket_run_is_selected();

        CREATE FUNCTION knowledge.native_simulation_receipt_is_consistent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE simulation_state text; simulation_bucket text; checkpoint_bucket text;
        BEGIN
          SELECT state, bucket_id INTO simulation_state, simulation_bucket
          FROM knowledge.native_watcher_simulations
          WHERE simulation_id = NEW.simulation_id AND sequence = NEW.simulation_sequence;
          SELECT bucket_id INTO checkpoint_bucket
          FROM knowledge.native_checkpoints WHERE checkpoint_id = NEW.checkpoint_id;
          IF simulation_state IS DISTINCT FROM NEW.terminal_state THEN
            RAISE EXCEPTION 'simulation receipt state contradicts its simulation'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          IF simulation_bucket IS DISTINCT FROM checkpoint_bucket THEN
            RAISE EXCEPTION 'simulation receipt checkpoint is outside its bucket'
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER native_simulation_receipt_requires_exact_evidence
          BEFORE INSERT ON knowledge.native_simulation_receipts
          FOR EACH ROW EXECUTE FUNCTION knowledge.native_simulation_receipt_is_consistent();

        DO $$
        DECLARE table_name text;
        BEGIN
          FOREACH table_name IN ARRAY ARRAY[
            'source_version_evidence', 'native_bridge_observations',
            'native_discovery_snapshots', 'native_configuration_revisions',
            'native_configuration_buckets', 'native_sync_runs', 'native_bucket_runs',
            'native_checkpoints', 'source_observations', 'source_memberships',
            'native_watcher_simulations', 'native_simulation_receipts',
            'native_live_activation_gates'
          ] LOOP
            EXECUTE format(
              'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON knowledge.%I '
              'FOR EACH ROW EXECUTE FUNCTION knowledge.reject_native_receipt_mutation()',
              table_name || '_is_append_only', table_name
            );
          END LOOP;
        END; $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE knowledge.native_live_activation_gates;
        DROP TABLE knowledge.native_simulation_receipts;
        DROP TABLE knowledge.native_watcher_simulations;
        DROP TABLE knowledge.source_memberships;
        DROP TABLE knowledge.source_observations;
        DROP TABLE knowledge.native_checkpoints;
        DROP TABLE knowledge.native_sync_jobs;
        DROP TABLE knowledge.native_bucket_runs;
        DROP TABLE knowledge.native_sync_runs;
        DROP TABLE knowledge.native_configuration_buckets;
        DROP TABLE knowledge.native_configuration_revisions;
        DROP TABLE knowledge.native_discovery_snapshots;
        DROP TABLE knowledge.native_source_buckets;
        DROP TABLE knowledge.native_source_accounts;
        DROP TABLE knowledge.native_bridge_observations;
        DROP TABLE knowledge.native_bridges;
        DROP TABLE knowledge.source_version_evidence;
        DROP FUNCTION knowledge.native_configuration_has_bucket();
        DROP FUNCTION knowledge.native_simulation_receipt_is_consistent();
        DROP FUNCTION knowledge.native_bucket_run_is_selected();
        DROP FUNCTION knowledge.native_bucket_scope_is_consistent();
        DROP FUNCTION knowledge.native_account_kind_matches_provider();
        DROP FUNCTION knowledge.native_evidence_kind_matches_object();
        DROP FUNCTION knowledge.native_source_binding_is_consistent();
        DROP FUNCTION knowledge.native_simulation_follows_closed_state_machine();
        DROP FUNCTION knowledge.native_checkpoint_follows_predecessor();
        DROP FUNCTION knowledge.reject_native_receipt_mutation();

        ALTER TABLE knowledge.sources DROP CONSTRAINT provider_kind_is_known;
        ALTER TABLE knowledge.sources ADD CONSTRAINT provider_kind_is_known
          CHECK (provider_kind IN ('fixture'));
        ALTER TABLE knowledge.source_objects DROP CONSTRAINT kind_is_known;
        ALTER TABLE knowledge.source_objects ADD CONSTRAINT kind_is_known
          CHECK (kind IN ('container', 'file'));
        """
    )
