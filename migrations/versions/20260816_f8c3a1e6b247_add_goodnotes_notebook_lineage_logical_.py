"""Add additive GoodNotes notebook lineage, logical pages, and run ledger.

Revision ID: f8c3a1e6b247
Revises: d4a8c1e7b930
Created: 2026-08-16

Additive knowledge-schema DDL. Existing ordinal `goodnotes_pages` identity
(`source_object_id` + `page_number`) is unchanged. Path is history, not notebook
identity; page number is position, not logical-page identity. Snapshots and
positions are immutable. Closed-set CHECK literals are frozen here (`D-69`).
DDL is written out rather than imported from persistence modules (`D-48`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f8c3a1e6b247"
down_revision: str | tuple[str, ...] | None = "d4a8c1e7b930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE knowledge.goodnotes_notebooks (
          principal_id varchar(72) NOT NULL,
          notebook_id varchar(36) NOT NULL
            CHECK (notebook_id ~ '^gnnb_[a-f0-9]{24}$'),
          source_root_id varchar(128) NOT NULL
            CHECK (
              char_length(source_root_id) BETWEEN 1 AND 128
              AND position('/' in source_root_id) = 0
            ),
          label varchar(200)
            CHECK (label IS NULL OR char_length(label) BETWEEN 1 AND 200),
          identity_status varchar(16) NOT NULL
            CHECK (identity_status IN ('ACTIVE', 'AMBIGUOUS', 'RETIRED')),
          created_at timestamptz NOT NULL,
          last_observed_at timestamptz NOT NULL,
          CONSTRAINT goodnotes_notebooks_pkey PRIMARY KEY (principal_id, notebook_id),
          CONSTRAINT goodnotes_notebook_observed_after_creation
            CHECK (last_observed_at >= created_at)
        );

        CREATE TABLE knowledge.goodnotes_ingestion_runs (
          principal_id varchar(72) NOT NULL,
          run_id varchar(36) NOT NULL
            CHECK (run_id ~ '^gnrun_[a-f0-9]{24}$'),
          source_root_id varchar(128) NOT NULL
            CHECK (
              char_length(source_root_id) BETWEEN 1 AND 128
              AND position('/' in source_root_id) = 0
            ),
          trigger_type varchar(16) NOT NULL
            CHECK (trigger_type IN ('MANUAL', 'SCHEDULED', 'REPLAY')),
          request_id varchar(200) NOT NULL
            CHECK (char_length(request_id) BETWEEN 1 AND 200),
          idempotency_key varchar(200) NOT NULL
            CHECK (char_length(idempotency_key) BETWEEN 1 AND 200),
          request_fingerprint varchar(64) NOT NULL
            CHECK (request_fingerprint ~ '^[a-f0-9]{64}$'),
          started_at timestamptz NOT NULL,
          ended_at timestamptz,
          status varchar(16) NOT NULL
            CHECK (status IN (
              'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'BUSY', 'REPLAYED'
            )),
          lease_owner varchar(200)
            CHECK (
              lease_owner IS NULL OR char_length(lease_owner) BETWEEN 1 AND 200
            ),
          lease_expires_at timestamptz,
          snapshot_count integer NOT NULL DEFAULT 0
            CHECK (snapshot_count >= 0),
          page_count integer NOT NULL DEFAULT 0
            CHECK (page_count >= 0),
          new_logical_page_count integer NOT NULL DEFAULT 0
            CHECK (new_logical_page_count >= 0),
          changed_page_count integer NOT NULL DEFAULT 0
            CHECK (changed_page_count >= 0),
          ambiguous_page_count integer NOT NULL DEFAULT 0
            CHECK (ambiguous_page_count >= 0),
          error_code varchar(64)
            CHECK (error_code IS NULL OR char_length(error_code) BETWEEN 1 AND 64),
          error_class varchar(64)
            CHECK (error_class IS NULL OR char_length(error_class) BETWEEN 1 AND 64),
          CONSTRAINT goodnotes_ingestion_runs_pkey PRIMARY KEY (principal_id, run_id),
          CONSTRAINT one_goodnotes_ingestion_request UNIQUE (principal_id, request_id),
          CONSTRAINT goodnotes_ingestion_ended_after_start
            CHECK (ended_at IS NULL OR ended_at >= started_at)
        );

        CREATE TABLE knowledge.goodnotes_notebook_paths (
          principal_id varchar(72) NOT NULL,
          notebook_id varchar(36) NOT NULL,
          path varchar(1024) NOT NULL
            CHECK (char_length(path) BETWEEN 1 AND 1024),
          first_seen_at timestamptz NOT NULL,
          last_seen_at timestamptz NOT NULL,
          first_snapshot_id varchar(36)
            CHECK (
              first_snapshot_id IS NULL
              OR first_snapshot_id ~ '^gnsnap_[a-f0-9]{24}$'
            ),
          last_snapshot_id varchar(36)
            CHECK (
              last_snapshot_id IS NULL
              OR last_snapshot_id ~ '^gnsnap_[a-f0-9]{24}$'
            ),
          is_current boolean NOT NULL,
          CONSTRAINT goodnotes_notebook_paths_pkey
            PRIMARY KEY (principal_id, notebook_id, path),
          CONSTRAINT goodnotes_notebook_path_seen_order
            CHECK (last_seen_at >= first_seen_at),
          CONSTRAINT goodnotes_notebook_paths_notebook_fk
            FOREIGN KEY (principal_id, notebook_id)
            REFERENCES knowledge.goodnotes_notebooks (principal_id, notebook_id)
            ON DELETE RESTRICT
        );
        CREATE UNIQUE INDEX one_current_goodnotes_notebook_path
          ON knowledge.goodnotes_notebook_paths (principal_id, notebook_id)
          WHERE is_current;

        CREATE TABLE knowledge.goodnotes_source_snapshots (
          principal_id varchar(72) NOT NULL,
          snapshot_id varchar(36) NOT NULL
            CHECK (snapshot_id ~ '^gnsnap_[a-f0-9]{24}$'),
          notebook_id varchar(36) NOT NULL,
          source_object_id varchar(72) NOT NULL,
          observed_path varchar(1024) NOT NULL
            CHECK (char_length(observed_path) BETWEEN 1 AND 1024),
          raw_sha256 varchar(64) NOT NULL
            CHECK (raw_sha256 ~ '^[a-f0-9]{64}$'),
          size_bytes bigint NOT NULL
            CHECK (size_bytes > 0),
          mtime_ns bigint
            CHECK (mtime_ns IS NULL OR mtime_ns >= 0),
          page_count integer NOT NULL
            CHECK (page_count >= 0),
          observed_at timestamptz NOT NULL,
          settled_at timestamptz NOT NULL,
          run_id varchar(36) NOT NULL,
          CONSTRAINT goodnotes_source_snapshots_pkey
            PRIMARY KEY (principal_id, snapshot_id),
          CONSTRAINT one_goodnotes_snapshot_per_notebook_bytes
            UNIQUE (principal_id, notebook_id, raw_sha256),
          CONSTRAINT goodnotes_snapshot_settled_after_observation
            CHECK (settled_at >= observed_at),
          CONSTRAINT goodnotes_source_snapshots_notebook_fk
            FOREIGN KEY (principal_id, notebook_id)
            REFERENCES knowledge.goodnotes_notebooks (principal_id, notebook_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_source_snapshots_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES knowledge.goodnotes_ingestion_runs (principal_id, run_id)
            ON DELETE RESTRICT
        );

        CREATE TABLE knowledge.goodnotes_logical_pages (
          principal_id varchar(72) NOT NULL,
          logical_page_id varchar(36) NOT NULL
            CHECK (logical_page_id ~ '^gnlp_[a-f0-9]{24}$'),
          notebook_id varchar(36) NOT NULL,
          created_at timestamptz NOT NULL,
          last_seen_at timestamptz NOT NULL,
          identity_status varchar(16) NOT NULL
            CHECK (identity_status IN ('ACTIVE', 'AMBIGUOUS', 'RETIRED')),
          CONSTRAINT goodnotes_logical_pages_pkey
            PRIMARY KEY (principal_id, logical_page_id),
          CONSTRAINT goodnotes_logical_page_seen_after_creation
            CHECK (last_seen_at >= created_at),
          CONSTRAINT goodnotes_logical_pages_notebook_fk
            FOREIGN KEY (principal_id, notebook_id)
            REFERENCES knowledge.goodnotes_notebooks (principal_id, notebook_id)
            ON DELETE RESTRICT
        );

        CREATE TABLE knowledge.goodnotes_page_positions (
          principal_id varchar(72) NOT NULL,
          snapshot_id varchar(36) NOT NULL,
          page_number integer NOT NULL
            CHECK (page_number >= 1),
          logical_page_id varchar(36) NOT NULL,
          page_version_id varchar(30)
            CHECK (
              page_version_id IS NULL
              OR page_version_id ~ '^gnver_[a-f0-9]{24}$'
            ),
          match_method varchar(40) NOT NULL
            CHECK (match_method IN (
              'EXACT_NORMALIZED_RENDER',
              'EXACT_CANONICAL_RENDER',
              'STRONG_VISUAL_FINGERPRINT',
              'PERCEPTUAL_STRUCTURAL',
              'SEQUENCE_TIEBREAK',
              'ORDINAL_WEAK',
              'UNRESOLVED'
            )),
          match_confidence double precision
            CHECK (
              match_confidence IS NULL
              OR (match_confidence >= 0 AND match_confidence <= 1)
            ),
          prior_page_version_id varchar(30)
            CHECK (
              prior_page_version_id IS NULL
              OR prior_page_version_id ~ '^gnver_[a-f0-9]{24}$'
            ),
          created_at timestamptz NOT NULL,
          CONSTRAINT goodnotes_page_positions_pkey
            PRIMARY KEY (principal_id, snapshot_id, page_number),
          CONSTRAINT goodnotes_page_positions_snapshot_fk
            FOREIGN KEY (principal_id, snapshot_id)
            REFERENCES knowledge.goodnotes_source_snapshots (principal_id, snapshot_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_page_positions_logical_page_fk
            FOREIGN KEY (principal_id, logical_page_id)
            REFERENCES knowledge.goodnotes_logical_pages (principal_id, logical_page_id)
            ON DELETE RESTRICT
        );

        ALTER TABLE knowledge.goodnotes_page_versions
          ADD COLUMN logical_page_id varchar(36),
          ADD COLUMN normalized_render_sha256 varchar(64),
          ADD COLUMN perceptual_hash varchar(128),
          ADD COLUMN render_width integer,
          ADD COLUMN render_height integer,
          ADD COLUMN renderer_name varchar(100),
          ADD COLUMN renderer_version varchar(100),
          ADD COLUMN render_profile_version varchar(100);

        ALTER TABLE knowledge.goodnotes_page_versions
          ADD CONSTRAINT goodnotes_version_logical_page_id_shape
            CHECK (
              logical_page_id IS NULL
              OR logical_page_id ~ '^gnlp_[a-f0-9]{24}$'
            ),
          ADD CONSTRAINT goodnotes_version_normalized_render_sha256_shape
            CHECK (
              normalized_render_sha256 IS NULL
              OR normalized_render_sha256 ~ '^[a-f0-9]{64}$'
            ),
          ADD CONSTRAINT goodnotes_version_perceptual_hash_is_bounded
            CHECK (
              perceptual_hash IS NULL
              OR char_length(perceptual_hash) BETWEEN 1 AND 128
            ),
          ADD CONSTRAINT goodnotes_version_render_width_is_positive
            CHECK (render_width IS NULL OR render_width > 0),
          ADD CONSTRAINT goodnotes_version_render_height_is_positive
            CHECK (render_height IS NULL OR render_height > 0);

        CREATE TRIGGER goodnotes_source_snapshots_are_immutable
          BEFORE UPDATE OR DELETE ON knowledge.goodnotes_source_snapshots
          FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written();

        CREATE TRIGGER goodnotes_page_positions_are_immutable
          BEFORE UPDATE OR DELETE ON knowledge.goodnotes_page_positions
          FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS goodnotes_page_positions_are_immutable
          ON knowledge.goodnotes_page_positions;
        DROP TRIGGER IF EXISTS goodnotes_source_snapshots_are_immutable
          ON knowledge.goodnotes_source_snapshots;
        DROP TABLE IF EXISTS knowledge.goodnotes_page_positions;
        DROP TABLE IF EXISTS knowledge.goodnotes_logical_pages;
        DROP TABLE IF EXISTS knowledge.goodnotes_source_snapshots;
        DROP TABLE IF EXISTS knowledge.goodnotes_notebook_paths;
        DROP TABLE IF EXISTS knowledge.goodnotes_ingestion_runs;
        DROP TABLE IF EXISTS knowledge.goodnotes_notebooks;
        ALTER TABLE knowledge.goodnotes_page_versions
          DROP COLUMN IF EXISTS render_profile_version,
          DROP COLUMN IF EXISTS renderer_version,
          DROP COLUMN IF EXISTS renderer_name,
          DROP COLUMN IF EXISTS render_height,
          DROP COLUMN IF EXISTS render_width,
          DROP COLUMN IF EXISTS perceptual_hash,
          DROP COLUMN IF EXISTS normalized_render_sha256,
          DROP COLUMN IF EXISTS logical_page_id;
        """
    )
