"""Create insert-only context-run tables for disclosed evidence references.

Revision ID: 9b2d5f8c3e01
Revises: 8a1c4e7b2d90
Create Date: 2026-08-15

WP-KC-04. DDL is written out rather than imported from `tables.py` (`D-48`,
`D-69`). Closed-set literals are frozen at this revision. Rollback of
`context.prepare` is capability revoke (AC-KC-037); these tables have no
UPDATE/DELETE in the application port. The trigger makes that a server property
as well, matching `capture_versions`.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "9b2d5f8c3e01"
down_revision: str | None = "8a1c4e7b2d90"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"
_IMMUTABILITY_FUNCTION: Final = "context_runs_stay_as_written"
_RUN_TRIGGER: Final = "context_runs_are_append_only"
_ITEM_TRIGGER: Final = "context_run_items_are_append_only"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.context_runs (
          context_manifest_id text NOT NULL
            CHECK (context_manifest_id ~ '^ctxm_[A-Za-z0-9]{{8,64}}$'),
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          request_id text NOT NULL
            CHECK (length(request_id) BETWEEN 1 AND 128),
          correlation_id text NOT NULL
            CHECK (correlation_id ~ '^corr_[A-Za-z0-9]{{8,64}}$'),
          audit_id text
            CHECK (
              audit_id IS NULL OR audit_id ~ '^audit_[A-Za-z0-9]{{8,64}}$'
            ),
          transport text NOT NULL
            CHECK (transport IN ('local', 'remote_client')),
          purpose text NOT NULL
            CHECK (purpose = 'context_preparation'),
          query_fingerprint text NOT NULL
            CHECK (query_fingerprint ~ '^[0-9a-f]{{64}}$'),
          retrieval_mode text NOT NULL
            CHECK (retrieval_mode IN ('hybrid_semantic', 'lexical_structured')),
          ranking_version text NOT NULL
            CHECK (length(ranking_version) BETWEEN 1 AND 64),
          policy_version text NOT NULL
            CHECK (length(policy_version) BETWEEN 1 AND 64),
          generated_at timestamptz NOT NULL,
          total_items integer NOT NULL
            CHECK (total_items >= 0),
          total_bytes integer NOT NULL
            CHECK (total_bytes >= 0),
          duration_ms integer
            CHECK (duration_ms IS NULL OR duration_ms >= 0),
          outcome text NOT NULL
            CHECK (outcome = 'success'),
          truncated boolean NOT NULL,
          truncation_reason text
            CHECK (
              truncation_reason IS NULL
              OR (length(truncation_reason) BETWEEN 1 AND 64)
            ),
          CONSTRAINT context_runs_pkey PRIMARY KEY (context_manifest_id),
          CONSTRAINT context_run_truncation_reason_matches_flag CHECK (
            (truncated = false AND truncation_reason IS NULL)
            OR (truncated = true AND truncation_reason IS NOT NULL)
          )
        );

        CREATE INDEX context_runs_by_principal
          ON {SCHEMA}.context_runs (principal_id, generated_at);

        CREATE TABLE {SCHEMA}.context_run_items (
          context_manifest_id text NOT NULL
            CHECK (context_manifest_id ~ '^ctxm_[A-Za-z0-9]{{8,64}}$'),
          position integer NOT NULL
            CHECK (position >= 0),
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          reference_id text NOT NULL
            CHECK (length(reference_id) BETWEEN 1 AND 80),
          plane text NOT NULL
            CHECK (plane IN (
              'capture', 'continuity', 'knowledge', 'managed_document', 'relationship'
            )),
          authority_class text NOT NULL
            CHECK (authority_class IN (
              'enrolled_source', 'managed_document', 'product_owned_capture',
              'product_owned_continuity', 'product_owned_relationship'
            )),
          lifecycle text NOT NULL
            CHECK (lifecycle IN (
              'accepted', 'derived', 'proposed', 'source_evidence', 'user_authored'
            )),
          classification text NOT NULL
            CHECK (classification IN (
              'private_local', 'restricted_local', 'synthetic_test'
            )),
          excerpt_sha256 text NOT NULL
            CHECK (excerpt_sha256 ~ '^[0-9a-f]{{64}}$'),
          reason_codes text NOT NULL
            CHECK (length(reason_codes) <= 512),
          source_id text,
          source_object_id text,
          source_version_id text,
          knowledge_id text,
          capture_id text,
          capture_version_id text,
          product_id text,
          managed_document_id text,
          managed_document_version_id text,
          span_start integer,
          span_end integer,
          CONSTRAINT one_item_per_context_run_position
            PRIMARY KEY (context_manifest_id, position),
          CONSTRAINT context_run_items_belong_to_a_run
            FOREIGN KEY (context_manifest_id)
            REFERENCES {SCHEMA}.context_runs (context_manifest_id)
            ON DELETE CASCADE,
          CONSTRAINT context_run_item_span_has_both_ends CHECK (
            (span_start IS NULL) = (span_end IS NULL)
          )
        );

        CREATE INDEX context_run_items_by_principal
          ON {SCHEMA}.context_run_items (principal_id);
        """
    )
    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION '%.% is append only; % is refused', "
        "TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )
    op.execute(
        f"CREATE TRIGGER {_RUN_TRIGGER} "
        f"BEFORE UPDATE OR DELETE ON {SCHEMA}.context_runs "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()"
    )
    op.execute(
        f"CREATE TRIGGER {_ITEM_TRIGGER} "
        f"BEFORE UPDATE OR DELETE ON {SCHEMA}.context_run_items "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_ITEM_TRIGGER} ON {SCHEMA}.context_run_items")
    op.execute(f"DROP TRIGGER IF EXISTS {_RUN_TRIGGER} ON {SCHEMA}.context_runs")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.context_run_items")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.context_runs")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{_IMMUTABILITY_FUNCTION}()")
